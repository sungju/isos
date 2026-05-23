#!/usr/bin/env python

"""
Network analysis command for isos
Provides network interface and connection diagnostics
"""

from optparse import OptionParser
from io import StringIO
import os
import re
import glob

import screen
import ansicolor

# Global state for command interruption
is_cmd_stopped = None


def description():
    return "Network interface and connection analysis"


def add_command():
    return True


cmd_name = "netinfo"


def get_command_info():
    return {cmd_name: run_netinfo}


# ============================================================================
# Helper Functions - File Parsing
# ============================================================================

def get_interface_list(sos_home):
    """Returns list of network interfaces from ip address command"""
    interfaces = []
    path = sos_home + "/sos_commands/networking/ip_-d_address"

    try:
        with open(path) as f:
            for line in f:
                # Look for lines like: "2: ens192: <BROADCAST,MULTICAST,UP,LOWER_UP>"
                match = re.match(r'^\d+:\s+(\S+):', line)
                if match:
                    iface = match.group(1)
                    # Remove @NONE or @if suffixes
                    iface = re.sub(r'@.*$', '', iface)
                    if iface not in interfaces:
                        interfaces.append(iface)
    except:
        pass

    return interfaces


def parse_ip_address(sos_home):
    """
    Parse ip -d address output
    Returns dict: interface -> {state, mtu, mac, ips: [list]}
    """
    result = {}
    path = sos_home + "/sos_commands/networking/ip_-d_address"

    try:
        with open(path) as f:
            current_iface = None
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                # Interface line: "2: ens192: <BROADCAST,MULTICAST,UP,LOWER_UP>"
                match = re.match(r'^\d+:\s+(\S+):\s+<([^>]+)>', line)
                if match:
                    iface = match.group(1)
                    iface = re.sub(r'@.*$', '', iface)  # Remove @NONE
                    flags = match.group(2)

                    result[iface] = {
                        'state': 'UP' if 'UP' in flags else 'DOWN',
                        'mtu': 0,
                        'mac': '',
                        'ips': []
                    }
                    current_iface = iface

                    # Look for MTU on same line
                    mtu_match = re.search(r'mtu\s+(\d+)', line)
                    if mtu_match:
                        result[iface]['mtu'] = int(mtu_match.group(1))

                elif current_iface:
                    # MAC address line: "    link/ether 00:50:56:ae:26:6e"
                    if 'link/ether' in line or 'link/loopback' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            if 'link/ether' in line:
                                result[current_iface]['mac'] = parts[1]
                            else:
                                result[current_iface]['mac'] = 'loopback'

                    # IP address line: "    inet 10.163.4.10/24"
                    elif 'inet ' in line or 'inet6 ' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            ip_addr = parts[1]
                            result[current_iface]['ips'].append(ip_addr)
    except:
        pass

    return result


def parse_ip_link_stats(sos_home):
    """
    Parse ip -s -d link output for RX/TX statistics
    Returns dict: interface -> {rx_packets, tx_packets, rx_dropped, tx_dropped, rx_errors, tx_errors}
    """
    result = {}
    path = sos_home + "/sos_commands/networking/ip_-s_-d_link"

    try:
        with open(path) as f:
            current_iface = None
            line_num = 0

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                # Interface line
                match = re.match(r'^\d+:\s+(\S+):', line)
                if match:
                    iface = match.group(1)
                    iface = re.sub(r'@.*$', '', iface)
                    current_iface = iface
                    result[iface] = {
                        'rx_bytes': 0, 'rx_packets': 0, 'rx_errors': 0, 'rx_dropped': 0,
                        'tx_bytes': 0, 'tx_packets': 0, 'tx_errors': 0, 'tx_dropped': 0
                    }
                    line_num = 0

                elif current_iface:
                    line_num += 1
                    # RX line is typically 2 lines after interface
                    # Format: "    RX: bytes  packets  errors  dropped overrun mcast"
                    # Next:   "    8577720597 26427906 0       3370    0       0"
                    if 'RX:' in line and 'bytes' in line:
                        continue
                    elif line_num == 2 or (line_num > 1 and re.match(r'^\s+\d+', line)):
                        parts = line.split()
                        if len(parts) >= 4 and parts[0].isdigit():
                            if 'rx_packets' not in result[current_iface] or result[current_iface]['rx_packets'] == 0:
                                result[current_iface]['rx_bytes'] = int(parts[0])
                                result[current_iface]['rx_packets'] = int(parts[1])
                                result[current_iface]['rx_errors'] = int(parts[2])
                                result[current_iface]['rx_dropped'] = int(parts[3])

                    # TX line follows RX
                    if 'TX:' in line and 'bytes' in line:
                        continue
                    elif line_num == 4 or (line_num > 3 and re.match(r'^\s+\d+', line)):
                        parts = line.split()
                        if len(parts) >= 4 and parts[0].isdigit():
                            if 'tx_packets' not in result[current_iface] or result[current_iface]['tx_packets'] == 0:
                                result[current_iface]['tx_bytes'] = int(parts[0])
                                result[current_iface]['tx_packets'] = int(parts[1])
                                result[current_iface]['tx_errors'] = int(parts[2])
                                result[current_iface]['tx_dropped'] = int(parts[3])
    except:
        pass

    return result


def parse_ethtool_speed(sos_home, device):
    """
    Parse ethtool output for link speed
    Returns dict: {speed, duplex} or None
    """
    # Try multiple possible file patterns
    patterns = [
        sos_home + "/sos_commands/networking/ethtool_" + device,
        sos_home + "/sos_commands/networking/ethtool_-*_" + device
    ]

    for pattern in patterns:
        files = glob.glob(pattern)
        for path in files:
            if 'ethtool_-S' in path or 'ethtool_-i' in path:
                continue  # Skip statistics and driver info

            try:
                with open(path) as f:
                    speed = None
                    duplex = None

                    for line in f:
                        if 'Speed:' in line:
                            match = re.search(r'Speed:\s*(\d+)Mb/s', line)
                            if match:
                                speed = match.group(1)
                        elif 'Duplex:' in line:
                            match = re.search(r'Duplex:\s*(\S+)', line)
                            if match:
                                duplex = match.group(1)

                    if speed:
                        return {'speed': speed, 'duplex': duplex}
            except:
                pass

    return None


def parse_ss_summary(sos_home):
    """
    Parse ss -s output for connection summary
    Returns dict with connection counts
    """
    result = {
        'total': 0,
        'tcp_estab': 0,
        'tcp_listen': 0,
        'tcp_timewait': 0,
        'tcp_total': 0,
        'udp': 0
    }

    path = sos_home + "/sos_commands/networking/ss_-s"

    try:
        with open(path) as f:
            for line in f:
                # Total: 329 (kernel 0)
                if line.startswith('Total:'):
                    match = re.search(r'Total:\s*(\d+)', line)
                    if match:
                        result['total'] = int(match.group(1))

                # TCP:   85 (estab 24, closed 34, orphaned 0, synrecv 0, timewait 34/0), ports 0
                elif line.startswith('TCP:'):
                    # Total TCP
                    match = re.search(r'TCP:\s*(\d+)', line)
                    if match:
                        result['tcp_total'] = int(match.group(1))

                    # Established
                    match = re.search(r'estab\s+(\d+)', line)
                    if match:
                        result['tcp_estab'] = int(match.group(1))

                    # Timewait
                    match = re.search(r'timewait\s+(\d+)', line)
                    if match:
                        result['tcp_timewait'] = int(match.group(1))

                # Look for LISTEN separately (might be on different line)
                elif 'LISTEN' in line:
                    match = re.search(r'LISTEN\s+(\d+)', line)
                    if match:
                        result['tcp_listen'] = int(match.group(1))

                # UDP:   8 (old format) or UDP\t  8 (table format)
                elif line.startswith('UDP'):
                    # Try colon format first
                    match = re.search(r'UDP:\s*(\d+)', line)
                    if match:
                        result['udp'] = int(match.group(1))
                    else:
                        # Try table format
                        parts = line.split()
                        if len(parts) >= 2 and parts[0] == 'UDP':
                            try:
                                result['udp'] = int(parts[1])
                            except:
                                pass
    except:
        pass

    return result


def parse_default_route(sos_home):
    """
    Parse ip route output for default route
    Returns string with default route or empty string
    """
    path = sos_home + "/sos_commands/networking/ip_route_show_table_all"

    try:
        with open(path) as f:
            for line in f:
                if line.startswith('default'):
                    return line.strip()
    except:
        pass

    return ""


def parse_ethtool_driver(sos_home, device):
    """
    Parse ethtool -i output for driver information
    Returns dict with driver, version, firmware, bus_info
    """
    result = {'driver': 'N/A', 'version': 'N/A', 'firmware': 'N/A', 'bus_info': 'N/A'}
    path = sos_home + "/sos_commands/networking/ethtool_-i_" + device

    try:
        with open(path) as f:
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                if line.startswith('driver:'):
                    result['driver'] = line.split(':', 1)[1].strip()
                elif line.startswith('version:'):
                    result['version'] = line.split(':', 1)[1].strip()
                elif line.startswith('firmware-version:'):
                    fw = line.split(':', 1)[1].strip()
                    if fw:
                        result['firmware'] = fw
                elif line.startswith('bus-info:'):
                    result['bus_info'] = line.split(':', 1)[1].strip()
    except:
        pass

    return result


def parse_ethtool_ring(sos_home, device):
    """
    Parse ethtool -g output for ring buffer settings
    Returns dict with rx, tx ring sizes
    """
    result = {'rx': 'N/A', 'tx': 'N/A'}
    path = sos_home + "/sos_commands/networking/ethtool_-g_" + device

    try:
        with open(path) as f:
            in_current = False
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                if 'Current hardware settings:' in line:
                    in_current = True
                    continue

                if in_current:
                    if line.startswith('RX:'):
                        result['rx'] = line.split(':')[1].strip()
                    elif line.startswith('TX:'):
                        result['tx'] = line.split(':')[1].strip()
                        break  # We have what we need
    except:
        pass

    return result


def parse_ethtool_features(sos_home, device):
    """
    Parse ethtool -k output for key offload features
    Returns dict of feature names to on/off values
    """
    result = {}
    path = sos_home + "/sos_commands/networking/ethtool_-k_" + device

    # Key features to report
    interesting_features = [
        'rx-checksumming',
        'tx-checksumming',
        'scatter-gather',
        'tcp-segmentation-offload',
        'generic-segmentation-offload',
        'generic-receive-offload',
        'large-receive-offload'
    ]

    try:
        with open(path) as f:
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                for feature in interesting_features:
                    if line.startswith(feature + ':'):
                        # Parse "feature: on" or "feature: off [fixed]"
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            value = parts[1].strip().split()[0]  # Get "on" or "off"
                            result[feature] = value
                        break
    except:
        pass

    return result


def format_bytes(bytes_val):
    """Convert bytes to human-readable format"""
    if bytes_val == 0:
        return "0 B"

    units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
    unit_idx = 0
    val = float(bytes_val)

    while val >= 1024 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1

    if unit_idx == 0:
        return "%d %s" % (int(val), units[unit_idx])
    else:
        return "%.1f %s" % (val, units[unit_idx])


def format_number(num):
    """Format large numbers with K/M/G suffix"""
    if num == 0:
        return "0"

    if num >= 1000000000:
        return "%.1fG" % (num / 1000000000.0)
    elif num >= 1000000:
        return "%.1fM" % (num / 1000000.0)
    elif num >= 1000:
        return "%.1fK" % (num / 1000.0)
    else:
        return str(num)


# ============================================================================
# Display Functions
# ============================================================================

def show_summary(sos_home, no_pipe):
    """Display default network summary"""
    from table_formatter import TableFormatter

    result_str = ""

    # Parse all data sources
    ip_info = parse_ip_address(sos_home)
    stats_info = parse_ip_link_stats(sos_home)
    ss_info = parse_ss_summary(sos_home)
    default_route = parse_default_route(sos_home)

    # Create table with TableFormatter (new pattern)
    table = TableFormatter(no_pipe=no_pipe, show_header=True, padding=1)
    table.add_column("DEVICE", width=12, align='left', color='yellow')
    table.add_column("STATE", width=6, align='left', color='green')
    table.add_column("IP_ADDRESS", width=18, align='left', color='cyan')
    table.add_column("SPEED", width=12, align='left', color='blue')
    table.add_column("RX_PACKETS", width=12, align='left', color='lightcyan')
    table.add_column("TX_PACKETS", width=12, align='left', color='lightcyan')
    table.add_column("ERRORS", width=10, align='left', color='lightcyan')

    # Add data rows with conditional coloring
    for iface in sorted(ip_info.keys()):
        info = ip_info[iface]
        stats = stats_info.get(iface, {})

        # Get primary IP
        ip_addr = info['ips'][0] if info['ips'] else 'N/A'

        # Get speed
        ethtool_info = parse_ethtool_speed(sos_home, iface)
        if ethtool_info and ethtool_info['speed']:
            speed = ethtool_info['speed'] + "Mb/s"
        elif iface == 'lo':
            speed = "-"
        else:
            speed = "N/A"

        # Get stats
        rx_packets = format_number(stats.get('rx_packets', 0))
        tx_packets = format_number(stats.get('tx_packets', 0))

        rx_errors = stats.get('rx_errors', 0)
        tx_errors = stats.get('tx_errors', 0)
        rx_dropped = stats.get('rx_dropped', 0)
        tx_dropped = stats.get('tx_dropped', 0)

        errors = "%d/%d" % (rx_errors + rx_dropped, tx_errors + tx_dropped)

        # Build cell_colors dict for conditional coloring
        cell_colors = {}

        # Color STATE column RED if DOWN
        if info['state'] == 'DOWN':
            cell_colors[1] = 'red'  # Column index 1 is STATE

        # Color ERRORS column RED if non-zero
        if rx_errors + tx_errors + rx_dropped + tx_dropped > 0:
            cell_colors[6] = 'red'  # Column index 6 is ERRORS

        # Add row to table with conditional cell colors
        table.add_row(iface, info['state'], ip_addr, speed, rx_packets, tx_packets, errors,
                      cell_colors=cell_colors if cell_colors else None)

    # Format and display table
    formatted_table = table.format()
    if no_pipe:
        print(formatted_table)
    else:
        result_str += formatted_table + "\n"

    # Empty line
    if no_pipe:
        print("")
    else:
        result_str += "\n"

    # Display default route
    if default_route:
        route_header = "Default Route:"
        if no_pipe:
            print(screen.COLOR_TITLE + route_header + screen.COLOR_RESET)
            print("  " + default_route)
            print("")
        else:
            result_str += route_header + "\n"
            result_str += "  " + default_route + "\n\n"

    # Display connection summary
    if ss_info['total'] > 0:
        conn_header = "Connection Summary:"
        if no_pipe:
            print(screen.COLOR_TITLE + conn_header + screen.COLOR_RESET)
        else:
            result_str += conn_header + "\n"

        tcp_line = "  TCP:   %d (estab %d, listen %d, timewait %d)" % (
            ss_info['tcp_total'], ss_info['tcp_estab'],
            ss_info['tcp_listen'], ss_info['tcp_timewait']
        )
        udp_line = "  UDP:   %d" % ss_info['udp']
        total_line = "  Total: %d sockets" % ss_info['total']

        if no_pipe:
            print(tcp_line)
            print(udp_line)
            print(total_line)
        else:
            result_str += tcp_line + "\n"
            result_str += udp_line + "\n"
            result_str += total_line + "\n"

    return result_str


def show_interface_detail(sos_home, device, no_pipe):
    """Display detailed information for a specific interface"""
    result_str = ""

    # Parse all data sources
    ip_info = parse_ip_address(sos_home)
    stats_info = parse_ip_link_stats(sos_home)
    driver_info = parse_ethtool_driver(sos_home, device)
    ring_info = parse_ethtool_ring(sos_home, device)
    features_info = parse_ethtool_features(sos_home, device)
    ethtool_info = parse_ethtool_speed(sos_home, device)

    # Check if interface exists
    if device not in ip_info:
        error_msg = "Interface '%s' not found" % device
        if no_pipe:
            print(screen.COLOR_CRITICAL + error_msg + screen.COLOR_RESET)
        else:
            result_str += error_msg + "\n"
        return result_str

    info = ip_info[device]
    stats = stats_info.get(device, {})

    # Interface header
    header = "Interface: %s" % device
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
    else:
        result_str += header + "\n"

    # Basic information
    state_line = "  State: %s, MTU: %d" % (info['state'], info['mtu'])
    if no_pipe:
        print(state_line)
    else:
        result_str += state_line + "\n"

    # Hardware address
    if info['mac'] and info['mac'] != 'loopback':
        # Try to identify vendor
        vendor = ""
        if info['mac'].startswith('00:50:56'):
            vendor = " (VMware)"
        elif info['mac'].startswith('52:54:00'):
            vendor = " (KVM/QEMU)"

        hw_line = "  Hardware: %s%s" % (info['mac'], vendor)
        if no_pipe:
            print(hw_line)
        else:
            result_str += hw_line + "\n"

    # IP addresses
    if info['ips']:
        if len(info['ips']) == 1:
            ip_line = "  IP Address: %s" % info['ips'][0]
        else:
            ip_line = "  IP Addresses:"
            for ip_addr in info['ips']:
                ip_line += "\n    - %s" % ip_addr

        if no_pipe:
            print(ip_line)
        else:
            result_str += ip_line + "\n"

    # Speed and duplex
    if ethtool_info:
        speed_line = "  Speed: %sMb/s" % ethtool_info['speed']
        if ethtool_info.get('duplex'):
            speed_line += ", Duplex: %s" % ethtool_info['duplex']
        if no_pipe:
            print(speed_line)
        else:
            result_str += speed_line + "\n"

    # Driver information
    if driver_info['driver'] != 'N/A':
        driver_line = "  Driver: %s, Version: %s" % (driver_info['driver'], driver_info['version'])
        if no_pipe:
            print(driver_line)
        else:
            result_str += driver_line + "\n"

        if driver_info['bus_info'] != 'N/A':
            bus_line = "  Bus Info: %s" % driver_info['bus_info']
            if no_pipe:
                print(bus_line)
            else:
                result_str += bus_line + "\n"

    # Statistics section
    if stats:
        stats_header = "\n  Statistics:"
        if no_pipe:
            print(stats_header)
        else:
            result_str += stats_header + "\n"

        rx_bytes = format_bytes(stats.get('rx_bytes', 0))
        rx_packets = format_number(stats.get('rx_packets', 0))
        rx_dropped = stats.get('rx_dropped', 0)
        rx_errors = stats.get('rx_errors', 0)

        rx_line = "    RX: %s, %s packets, %d dropped, %d errors" % (
            rx_bytes, rx_packets, rx_dropped, rx_errors
        )
        if no_pipe:
            print(rx_line)
        else:
            result_str += rx_line + "\n"

        tx_bytes = format_bytes(stats.get('tx_bytes', 0))
        tx_packets = format_number(stats.get('tx_packets', 0))
        tx_dropped = stats.get('tx_dropped', 0)
        tx_errors = stats.get('tx_errors', 0)

        tx_line = "    TX: %s, %s packets, %d dropped, %d errors" % (
            tx_bytes, tx_packets, tx_dropped, tx_errors
        )
        if no_pipe:
            print(tx_line)
        else:
            result_str += tx_line + "\n"

    # Ring buffers
    if ring_info['rx'] != 'N/A':
        ring_header = "\n  Ring Buffers:"
        ring_line = "    RX: %s, TX: %s" % (ring_info['rx'], ring_info['tx'])
        if no_pipe:
            print(ring_header)
            print(ring_line)
        else:
            result_str += ring_header + "\n"
            result_str += ring_line + "\n"

    # Offload features
    if features_info:
        features_header = "\n  Offload Features:"
        if no_pipe:
            print(features_header)
        else:
            result_str += features_header + "\n"

        for feature, value in sorted(features_info.items()):
            # Make feature names more readable
            feature_name = feature.replace('-', ' ').title()
            feature_line = "    %s: %s" % (feature_name, value)
            if no_pipe:
                print(feature_line)
            else:
                result_str += feature_line + "\n"

    return result_str


def colorize_ip(ip_str, no_pipe):
    """Colorize an IP address"""
    if no_pipe:
        return screen.COLOR_HEADER + ip_str + screen.COLOR_RESET
    return ip_str


def colorize_gateway(gw_str, no_pipe):
    """Colorize a gateway IP"""
    if no_pipe:
        return screen.COLOR_SUCCESS + gw_str + screen.COLOR_RESET
    return gw_str


def colorize_device(dev_str, no_pipe):
    """Colorize a device name"""
    if no_pipe:
        return screen.COLOR_TITLE + dev_str + screen.COLOR_RESET
    return dev_str


def colorize_keyword(keyword, no_pipe, color=screen.COLOR_14):
    """Colorize a keyword"""
    if no_pipe:
        return ansicolor.get_color(color) + keyword + screen.COLOR_RESET
    return keyword


def parse_route_entry(route_line):
    """Parse a route entry into structured data"""
    parts = route_line.split()
    route_data = {
        'destination': '',
        'dest_type': '',  # For broadcast/local prefix
        'gateway': '',
        'device': '',
        'proto': '',
        'scope': '',
        'metric': '',
        'src': '',
        'raw': route_line
    }

    if not parts:
        return route_data

    # First part is destination
    # Special handling for "broadcast IP" and "local IP" format
    if parts[0] in ['broadcast', 'local'] and len(parts) > 1 and '.' in parts[1]:
        route_data['dest_type'] = parts[0]
        route_data['destination'] = parts[1]
        i = 2
    else:
        route_data['destination'] = parts[0]
        i = 1

    # Parse key-value pairs
    while i < len(parts):
        if parts[i] == 'via' and i + 1 < len(parts):
            route_data['gateway'] = parts[i + 1]
            i += 2
        elif parts[i] == 'dev' and i + 1 < len(parts):
            route_data['device'] = parts[i + 1]
            i += 2
        elif parts[i] == 'proto' and i + 1 < len(parts):
            route_data['proto'] = parts[i + 1]
            i += 2
        elif parts[i] == 'scope' and i + 1 < len(parts):
            route_data['scope'] = parts[i + 1]
            i += 2
        elif parts[i] == 'metric' and i + 1 < len(parts):
            route_data['metric'] = parts[i + 1]
            i += 2
        elif parts[i] == 'src' and i + 1 < len(parts):
            route_data['src'] = parts[i + 1]
            i += 2
        elif parts[i] == 'table':
            # Skip table keyword and its value
            i += 2
        else:
            i += 1

    return route_data


def explain_route(route_data):
    """Generate human-readable explanation of a route"""
    dest = route_data['destination']
    gateway = route_data['gateway']
    device = route_data['device']
    proto = route_data['proto']
    scope = route_data['scope']
    metric = route_data['metric']

    explanation = []

    # Destination explanation
    if dest == 'default':
        explanation.append("Default gateway (all internet traffic)")
    elif dest.startswith('broadcast') or dest.startswith('local'):
        explanation.append("Local system route")
    elif '/' in dest:
        explanation.append("Network route to %s" % dest)
    else:
        explanation.append("Route to %s" % dest)

    # Gateway explanation
    if gateway:
        explanation.append("via gateway %s" % gateway)
    elif device:
        explanation.append("directly connected on %s" % device)

    # Proto explanation
    if proto == 'kernel':
        explanation.append("[Auto-configured by kernel]")
    elif proto == 'static':
        explanation.append("[Manually configured]")
    elif proto == 'dhcp':
        explanation.append("[Obtained via DHCP]")
    elif proto == 'boot':
        explanation.append("[Configured at boot]")
    elif proto:
        explanation.append("[Protocol: %s]" % proto)

    # Scope explanation
    if scope == 'global':
        explanation.append("(Internet-routable)")
    elif scope == 'link':
        explanation.append("(Local network only)")
    elif scope == 'host':
        explanation.append("(This machine only)")

    # Metric explanation
    if metric:
        explanation.append("Priority: %s" % metric)

    return " ".join(explanation)


def format_route_colored(route_data, no_pipe, tree_prefix=""):
    """Format a route with colors"""
    dest = route_data['destination']
    dest_type = route_data.get('dest_type', '')
    gateway = route_data['gateway']
    device = route_data['device']
    proto = route_data['proto']
    scope = route_data['scope']
    metric = route_data['metric']
    src = route_data['src']

    # Build colorized output
    parts = []

    # Destination with type prefix
    if dest_type:
        # We have a prefix like "broadcast" or "local"
        parts.append(colorize_keyword(dest_type, no_pipe, screen.COLOR_8))
        parts.append(colorize_ip(dest, no_pipe))
    elif dest == 'default':
        parts.append(colorize_keyword("default", no_pipe, screen.COLOR_2))
    elif '/' in dest or '.' in dest:
        # This is an IP or network
        parts.append(colorize_ip(dest, no_pipe))
    else:
        parts.append(dest)

    # Gateway
    if gateway:
        parts.append("via")
        parts.append(colorize_gateway(gateway, no_pipe))

    # Device
    if device:
        parts.append("dev")
        parts.append(colorize_device(device, no_pipe))

    # Proto
    if proto:
        parts.append("proto")
        if proto == "static":
            parts.append(colorize_keyword(proto, no_pipe, screen.COLOR_3))
        elif proto == "kernel":
            parts.append(colorize_keyword(proto, no_pipe, screen.COLOR_14))
        elif proto == "dhcp":
            parts.append(colorize_keyword(proto, no_pipe, screen.COLOR_6))
        else:
            parts.append(proto)

    # Scope
    if scope:
        parts.append("scope")
        if scope == "global":
            parts.append(colorize_keyword(scope, no_pipe, screen.COLOR_2))
        elif scope == "link":
            parts.append(colorize_keyword(scope, no_pipe, screen.COLOR_6))
        elif scope == "host":
            parts.append(colorize_keyword(scope, no_pipe, screen.COLOR_8))
        else:
            parts.append(scope)

    # Source
    if src:
        parts.append("src")
        parts.append(colorize_ip(src, no_pipe))

    # Metric
    if metric:
        parts.append("metric")
        parts.append(colorize_keyword(metric, no_pipe, screen.COLOR_4))

    return tree_prefix + " ".join(parts)


def show_routes(sos_home, no_pipe, descriptive=False):
    """Display routing table information"""
    result_str = ""
    path = sos_home + "/sos_commands/networking/ip_route_show_table_all"

    # Header
    header = "Routing Table"
    if descriptive:
        header += " (Descriptive Mode)"

    if no_pipe:
        print(screen.COLOR_TITLE + "┏━━ " + header + " ━━" + screen.COLOR_RESET)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"

    # Read and categorize routes
    try:
        with open(path) as f:
            default_routes = []
            network_routes = []
            local_routes = []

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                line = line.strip()
                if not line:
                    continue

                # Categorize routes
                if 'table local' in line:
                    local_routes.append(line)
                elif line.startswith('default'):
                    default_routes.append(line)
                else:
                    network_routes.append(line)

            # Display default routes (most important)
            if default_routes:
                section_header = "┃"
                if no_pipe:
                    print(screen.COLOR_SUCCESS + section_header + screen.COLOR_RESET)
                    print(screen.COLOR_SUCCESS + "┣━━ Internet Gateway" + screen.COLOR_RESET)
                else:
                    result_str += "\n[Internet Gateway]\n"

                if descriptive:
                    desc_note = "┃   These routes determine how traffic to the internet is handled."
                    if no_pipe:
                        print(screen.COLOR_INFO + desc_note + screen.COLOR_RESET)
                    else:
                        result_str += "These routes determine how traffic to the internet is handled.\n"

                for idx, route in enumerate(default_routes):
                    route_data = parse_route_entry(route)
                    is_last = (idx == len(default_routes) - 1) and not network_routes and not local_routes

                    if is_last:
                        tree_char = "┃   └──"
                    else:
                        tree_char = "┃   ├──"

                    formatted_route = format_route_colored(route_data, no_pipe, tree_char)

                    if no_pipe:
                        print(formatted_route)
                    else:
                        result_str += " => " + route + "\n"

                    # Add explanation in descriptive mode
                    if descriptive:
                        if is_last:
                            explanation = "┃       " + explain_route(route_data)
                        else:
                            explanation = "┃   │   " + explain_route(route_data)

                        if no_pipe:
                            print(screen.COLOR_INFO + explanation + screen.COLOR_RESET)
                        else:
                            result_str += "    " + explain_route(route_data) + "\n"

            # Display network routes
            if network_routes:
                section_header = "┃"
                if no_pipe:
                    print(screen.COLOR_HEADER + section_header + screen.COLOR_RESET)
                    print(screen.COLOR_HEADER + "┣━━ Direct Networks" + screen.COLOR_RESET)
                else:
                    result_str += "\n[Direct Networks]\n"

                if descriptive:
                    desc_note = "┃   These are directly connected networks (no gateway needed)."
                    if no_pipe:
                        print(screen.COLOR_INFO + desc_note + screen.COLOR_RESET)
                    else:
                        result_str += "These are directly connected networks (no gateway needed).\n"

                for idx, route in enumerate(network_routes):
                    route_data = parse_route_entry(route)
                    is_last = (idx == len(network_routes) - 1) and not local_routes

                    if is_last:
                        tree_char = "┃   └──"
                    else:
                        tree_char = "┃   ├──"

                    formatted_route = format_route_colored(route_data, no_pipe, tree_char)

                    if no_pipe:
                        print(formatted_route)
                    else:
                        result_str += " -> " + route + "\n"

                    # Add explanation in descriptive mode
                    if descriptive:
                        if is_last:
                            explanation = "┃       " + explain_route(route_data)
                        else:
                            explanation = "┃   │   " + explain_route(route_data)

                        if no_pipe:
                            print(screen.COLOR_INFO + explanation + screen.COLOR_RESET)
                        else:
                            result_str += "    " + explain_route(route_data) + "\n"

            # Display local routes (collapsed by default)
            if local_routes:
                section_header = "┃"
                if no_pipe:
                    print(screen.COLOR_INFO + section_header + screen.COLOR_RESET)
                    print(screen.COLOR_INFO + "┗━━ Local Routes (" + str(len(local_routes)) + " entries)" + screen.COLOR_RESET)
                else:
                    result_str += "\n[Local Routes]\n"

                if descriptive:
                    desc_note = "    These routes handle local traffic (broadcasts, local IPs, loopback)."
                    if no_pipe:
                        print(screen.COLOR_INFO + desc_note + screen.COLOR_RESET)
                    else:
                        result_str += "These routes handle local traffic (broadcasts, local IPs, loopback).\n"

                    # In descriptive mode, show routes with tree
                    show_count = min(len(local_routes), 15)
                    for idx, route in enumerate(local_routes[:show_count]):
                        route_data = parse_route_entry(route)
                        is_last = (idx == show_count - 1) or (idx == len(local_routes) - 1)

                        if is_last:
                            tree_char = "    └──"
                        else:
                            tree_char = "    ├──"

                        formatted_route = format_route_colored(route_data, no_pipe, tree_char)

                        if no_pipe:
                            print(formatted_route)
                        else:
                            result_str += "    " + route + "\n"

                        # Add brief explanation
                        if is_last:
                            explanation = "        " + explain_route(route_data)
                        else:
                            explanation = "    │   " + explain_route(route_data)

                        if no_pipe:
                            print(screen.COLOR_INFO + explanation + screen.COLOR_RESET)
                        else:
                            result_str += "      " + explain_route(route_data) + "\n"

                    if len(local_routes) > show_count:
                        remaining = "    ... (%d more local routes)" % (len(local_routes) - show_count)
                        if no_pipe:
                            print(screen.COLOR_INFO + remaining + screen.COLOR_RESET)
                        else:
                            result_str += remaining + "\n"
                else:
                    # Non-descriptive mode - just show count
                    hint = "    Use -d to show details"
                    if no_pipe:
                        print(screen.COLOR_INFO + hint + screen.COLOR_RESET)

            # Add legend in descriptive mode
            if descriptive and no_pipe:
                print("")
                legend = "┏━━ Legend ━━"
                print(screen.COLOR_TITLE + legend + screen.COLOR_RESET)
                print("┃  " + colorize_keyword("proto static", no_pipe, screen.COLOR_3) + "  = Manually configured by administrator")
                print("┃  " + colorize_keyword("proto kernel", no_pipe, screen.COLOR_14) + "  = Auto-configured by kernel when IP assigned")
                print("┃  " + colorize_keyword("proto dhcp", no_pipe, screen.COLOR_6) + "    = Obtained via DHCP")
                print("┃  " + colorize_keyword("scope global", no_pipe, screen.COLOR_2) + "  = Internet-routable addresses")
                print("┃  " + colorize_keyword("scope link", no_pipe, screen.COLOR_6) + "    = Local network only (LAN)")
                print("┃  " + colorize_keyword("scope host", no_pipe, screen.COLOR_8) + "    = This machine only (localhost)")
                print("┗  " + colorize_keyword("metric", no_pipe, screen.COLOR_4) + "        = Route priority (lower = higher priority)")

    except:
        error_msg = "Unable to read routing table"
        if no_pipe:
            print(error_msg)
        else:
            result_str += error_msg + "\n"

    return result_str


def show_connections(sos_home, no_pipe):
    """Display connection analysis"""
    result_str = ""
    path = sos_home + "/sos_commands/networking/ss_-peaonmi"

    # Header
    header = "Connection Analysis"
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
        print("=" * 80)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"

    # Parse connections
    tcp_states = {}
    udp_count = 0
    listening_ports = {}  # port -> (process, proto)

    try:
        with open(path) as f:
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                # Skip header and non-connection lines
                if line.startswith('Netid') or line.startswith('nl '):
                    continue

                parts = line.split()
                if len(parts) < 2:
                    continue

                proto = parts[0]
                state = parts[1] if len(parts) > 1 else ''

                # Count TCP states
                if proto == 'tcp':
                    tcp_states[state] = tcp_states.get(state, 0) + 1

                    # Parse listening ports
                    if state == 'LISTEN' and len(parts) >= 5:
                        local_addr = parts[4]
                        # Extract port from address
                        if ':' in local_addr:
                            port = local_addr.split(':')[-1]
                            # Extract process name from users field
                            process = ''
                            for part in parts:
                                if 'users:' in part or part.startswith('users:('):
                                    # Parse users:(("program",pid=1234,fd=5))
                                    match = re.search(r'\(\("([^"]+)"', part)
                                    if match:
                                        process = match.group(1)
                                    break
                            listening_ports[port] = (process, 'tcp')

                elif proto == 'udp':
                    udp_count += 1

        # Display TCP state breakdown
        if tcp_states:
            tcp_header = "\nTCP Connection States:"
            if no_pipe:
                print(screen.COLOR_HEADER + tcp_header + screen.COLOR_RESET)
                print("  " + "-" * 40)
            else:
                result_str += tcp_header + "\n"
                result_str += "  " + "-" * 40 + "\n"

            for state in sorted(tcp_states.keys()):
                count = tcp_states[state]
                if no_pipe:
                    # Context-based coloring: highlight important states
                    if state == 'ESTAB' or state == 'ESTABLISHED':
                        state_color = screen.COLOR_SUCCESS
                    elif state == 'LISTEN':
                        state_color = screen.COLOR_INFO
                    else:
                        state_color = screen.COLOR_IMPORTANT

                    colored_state = state_color + "%-15s" % state + screen.COLOR_RESET
                    colored_count = screen.COLOR_HIGHLIGHT + str(count) + screen.COLOR_RESET
                    state_line = "  %s %s" % (colored_state, colored_count)
                    print(state_line)
                else:
                    state_line = "  %-15s %d" % (state, count)
                    result_str += state_line + "\n"

        # Display UDP count
        if udp_count > 0:
            udp_line = "\nUDP Sockets: %d" % udp_count
            if no_pipe:
                print(screen.COLOR_HEADER + udp_line + screen.COLOR_RESET)
            else:
                result_str += udp_line + "\n"

        # Display top listening ports
        if listening_ports:
            listen_header = "\nListening Ports:"
            if no_pipe:
                print(screen.COLOR_HEADER + listen_header + screen.COLOR_RESET)
            else:
                result_str += listen_header + "\n"

            # Table header
            table_header = "  %-8s %-6s %s" % ("PORT", "PROTO", "PROCESS")
            if no_pipe:
                print(screen.COLOR_HEADER + table_header + screen.COLOR_RESET)
                print("  " + "-" * 60)
            else:
                result_str += table_header + "\n"
                result_str += "  " + "-" * 60 + "\n"

            # Sort by port number
            sorted_ports = sorted(listening_ports.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)

            # Show first 20
            for port, (process, proto) in sorted_ports[:20]:
                process_name = process if process else 'unknown'

                if no_pipe:
                    # Apply context-based coloring
                    colored_port = screen.COLOR_IMPORTANT + port + screen.COLOR_RESET
                    colored_proto = screen.COLOR_INFO + proto + screen.COLOR_RESET
                    colored_process = screen.COLOR_HIGHLIGHT + process_name + screen.COLOR_RESET
                    port_line = "  %-14s %-12s %s" % (colored_port, colored_proto, colored_process)
                    print(port_line)
                else:
                    port_line = "  %-8s %-6s %s" % (port, proto, process_name)
                    result_str += port_line + "\n"

            if len(sorted_ports) > 20:
                remaining = "  ... (%d more ports)" % (len(sorted_ports) - 20)
                if no_pipe:
                    print(screen.COLOR_INFO + remaining + screen.COLOR_RESET)
                else:
                    result_str += remaining + "\n"

    except:
        error_msg = "Unable to read connection details"
        if no_pipe:
            print(error_msg)
        else:
            result_str += error_msg + "\n"

    return result_str


def show_statistics(sos_home, no_pipe):
    """Display network protocol statistics"""
    result_str = ""
    path = sos_home + "/sos_commands/networking/netstat_-s"    # Header
    header = "Network Protocol Statistics"
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
        print("=" * 80)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"

    # Parse and display key statistics
    try:
        with open(path) as f:
            current_proto = None
            stats = {}

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                line = line.strip()
                if not line:
                    continue

                # Protocol headers
                if line.endswith(':') and not line.startswith(' '):
                    current_proto = line[:-1]
                    stats[current_proto] = []
                elif current_proto:
                    stats[current_proto].append(line)

            # Display statistics for key protocols
            for proto in ['Ip', 'Tcp', 'Udp', 'Icmp']:
                if proto in stats:
                    proto_header = "\n%s Statistics:" % proto
                    if no_pipe:
                        print(screen.COLOR_HEADER + proto_header + screen.COLOR_RESET)
                    else:
                        result_str += proto_header + "\n"

                    # Show interesting stats (errors, drops, retransmits)
                    interesting_keywords = ['error', 'drop', 'fail', 'retrans', 'reset', 'bad', 'invalid', 'discard']
                    normal_stats = []
                    error_stats = []

                    for stat in stats[proto]:
                        is_interesting = any(keyword in stat.lower() for keyword in interesting_keywords)
                        # Extract the number to check if it's non-zero
                        match = re.search(r'(\d+)', stat)
                        if match and int(match.group(1)) > 0:
                            if is_interesting:
                                error_stats.append(stat)
                            else:
                                normal_stats.append(stat)

                    # Show error stats in red
                    for stat in error_stats[:10]:  # Limit to 10
                        if no_pipe:
                            print(screen.COLOR_CRITICAL + "  " + stat + screen.COLOR_RESET)
                        else:
                            result_str += "  " + stat + "\n"

                    # Show normal stats
                    for stat in normal_stats[:5]:  # Limit to 5
                        if no_pipe:
                            print("  " + stat)
                        else:
                            result_str += "  " + stat + "\n"

    except:
        error_msg = "Unable to read protocol statistics"
        if no_pipe:
            print(error_msg)
        else:
            result_str += error_msg + "\n"

    return result_str


def show_networkmanager(sos_home, no_pipe):
    """Display NetworkManager information"""
    result_str = ""
    dev_path = sos_home + "/sos_commands/networkmanager/nmcli_dev"    # Header
    header = "NetworkManager Status"
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
        print("=" * 80)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"

    # Read device status
    try:
        with open(dev_path) as f:
            devices_header = "\nManaged Devices:"
            if no_pipe:
                print(screen.COLOR_HEADER + devices_header + screen.COLOR_RESET)
            else:
                result_str += devices_header + "\n"

            header_printed = False
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                line = line.strip()
                if not line:
                    continue

                # Print header with separator
                if line.startswith('DEVICE'):
                    if no_pipe:
                        print(screen.COLOR_INFO + "  " + line + screen.COLOR_RESET)
                        print("  " + "-" * 70)
                    else:
                        result_str += "  " + line + "\n"
                        result_str += "  " + "-" * 70 + "\n"
                    header_printed = True
                    continue

                # Apply column coloring to device lines
                if no_pipe:
                    colored_line = screen.get_colored_line("  " + line)
                    # Highlight connected state
                    if 'connected' in line and 'disconnected' not in line:
                        colored_line = colored_line.replace('connected', screen.COLOR_SUCCESS + 'connected' + screen.COLOR_RESET)
                    print(colored_line)
                else:
                    result_str += "  " + line + "\n"

    except:
        error_msg = "NetworkManager information not available"
        if no_pipe:
            print(error_msg)
        else:
            result_str += error_msg + "\n"

    # Try to read connection details
    con_path = sos_home + "/sos_commands/networkmanager/nmcli_con"
    try:
        with open(con_path) as f:
            connections_header = "\nConnections:"
            if no_pipe:
                print(screen.COLOR_HEADER + connections_header + screen.COLOR_RESET)
            else:
                result_str += connections_header + "\n"

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                line = line.strip()
                if not line or line.startswith('NAME'):
                    continue

                if no_pipe:
                    print("  " + line)
                else:
                    result_str += "  " + line + "\n"
    except:
        pass  # Connection info is optional

    return result_str


def show_arp(sos_home, no_pipe):
    """Display ARP table"""
    result_str = ""
    path = sos_home + "/proc/net/arp"

    # Header
    header = "ARP Table"
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
        print("=" * 80)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"
    try:
        with open(path) as f:
            entries = []
            header_line = None

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                line = line.strip()
                if not line:
                    continue

                # Skip header
                if line.startswith('IP address'):
                    header_line = line
                    continue

                # Parse ARP entry
                parts = line.split()
                if len(parts) >= 6:
                    ip_addr = parts[0]
                    hw_type = parts[1]
                    flags = parts[2]
                    mac_addr = parts[3]
                    device = parts[5]

                    # Decode flags (0x2 = complete, 0x4 = permanent)
                    flag_str = ""
                    if flags == '0x2':
                        flag_str = "COMPLETE"
                    elif flags == '0x6':
                        flag_str = "PERMANENT"
                    elif flags == '0x0':
                        flag_str = "INCOMPLETE"
                    else:
                        flag_str = flags

                    entries.append((ip_addr, mac_addr, flag_str, device))

            if entries:
                # Display table header
                table_header = "\n%-18s %-20s %-12s %s" % ("IP_ADDRESS", "MAC_ADDRESS", "STATE", "DEVICE")
                if no_pipe:
                    print(screen.COLOR_HEADER + table_header + screen.COLOR_RESET)
                    print("-" * 70)
                else:
                    result_str += table_header + "\n"
                    result_str += "-" * 70 + "\n"

                # Display entries
                for ip_addr, mac_addr, state, device in entries:
                    entry_line = "%-18s %-20s %-12s %s" % (ip_addr, mac_addr, state, device)
                    line_colored = screen.get_colored_line(entry_line)
                    if no_pipe:
                        print(line_colored)
                    else:
                        result_str += entry_line + "\n"

                # Summary
                summary = "\nTotal ARP entries: %d" % len(entries)
                if no_pipe:
                    print(summary)
                else:
                    result_str += summary + "\n"
            else:
                no_entries = "\nNo ARP entries found"
                if no_pipe:
                    print(no_entries)
                else:
                    result_str += no_entries + "\n"

    except:
        error_msg = "Unable to read ARP table"
        if no_pipe:
            print(error_msg)
        else:
            result_str += error_msg + "\n"

    return result_str


def show_neighbor(sos_home, no_pipe):
    """Display neighbor table (IPv4 and IPv6)"""
    result_str = ""
    path = sos_home + "/sos_commands/networking/ip_-s_-s_neigh_show"

    # Header
    header = "Neighbor Table (NDP/ARP)"
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
        print("=" * 80)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"
    try:
        with open(path) as f:
            entries = []

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                line = line.strip()
                if not line:
                    continue

                # Parse neighbor entry
                # Format: "10.163.4.3 dev ens192 lladdr 20:20:00:00:00:aa ref 1 used 537777/0/537776 probes 4 REACHABLE"
                parts = line.split()
                if len(parts) < 3:
                    continue

                ip_addr = parts[0]
                device = ""
                mac_addr = ""
                state = ""
                ref_count = ""

                # Parse key-value pairs
                i = 1
                while i < len(parts):
                    if parts[i] == 'dev' and i + 1 < len(parts):
                        device = parts[i + 1]
                        i += 2
                    elif parts[i] == 'lladdr' and i + 1 < len(parts):
                        mac_addr = parts[i + 1]
                        i += 2
                    elif parts[i] == 'ref' and i + 1 < len(parts):
                        ref_count = parts[i + 1]
                        i += 2
                    else:
                        # Last part is usually the state
                        if parts[i].isupper():
                            state = parts[i]
                        i += 1

                if ip_addr and device:
                    entries.append((ip_addr, mac_addr if mac_addr else "N/A", state if state else "UNKNOWN", device, ref_count))

            if entries:
                # Display table header
                table_header = "\n%-40s %-20s %-12s %-10s %s" % ("IP_ADDRESS", "MAC_ADDRESS", "STATE", "DEVICE", "REF")
                if no_pipe:
                    print(screen.COLOR_HEADER + table_header + screen.COLOR_RESET)
                    print("-" * 90)
                else:
                    result_str += table_header + "\n"
                    result_str += "-" * 90 + "\n"

                # Display entries with state-based coloring
                for ip_addr, mac_addr, state, device, ref_count in entries:
                    entry_line = "%-40s %-20s %-12s %-10s %s" % (ip_addr, mac_addr, state, device, ref_count)

                    if no_pipe:
                        # Color code based on state
                        if state == "REACHABLE":
                            print(screen.COLOR_SUCCESS + entry_line + screen.COLOR_RESET)
                        elif state == "STALE":
                            print(screen.COLOR_TITLE + entry_line + screen.COLOR_RESET)
                        elif state == "FAILED" or state == "INCOMPLETE":
                            print(screen.COLOR_CRITICAL + entry_line + screen.COLOR_RESET)
                        else:
                            print(entry_line)
                    else:
                        result_str += entry_line + "\n"

                # Summary
                summary = "\nTotal neighbor entries: %d" % len(entries)
                if no_pipe:
                    print(summary)
                else:
                    result_str += summary + "\n"

                # State breakdown
                states = {}
                for _, _, state, _, _ in entries:
                    states[state] = states.get(state, 0) + 1

                if states:
                    state_summary = "\nState breakdown:"
                    if no_pipe:
                        print(screen.COLOR_HEADER + state_summary + screen.COLOR_RESET)
                    else:
                        result_str += state_summary + "\n"

                    for state in sorted(states.keys()):
                        count = states[state]
                        state_line = "  %-12s %d" % (state, count)
                        if no_pipe:
                            print(state_line)
                        else:
                            result_str += state_line + "\n"

            else:
                no_entries = "\nNo neighbor entries found"
                if no_pipe:
                    print(no_entries)
                else:
                    result_str += no_entries + "\n"

    except:
        error_msg = "Unable to read neighbor table"
        if no_pipe:
            print(error_msg)
        else:
            result_str += error_msg + "\n"

    return result_str


def show_interface_list(sos_home, no_pipe):
    """Display simple interface list"""
    result_str = ""    # Header
    header = "Network Interfaces"
    if no_pipe:
        print(screen.COLOR_TITLE + header + screen.COLOR_RESET)
        print("=" * 80)
    else:
        result_str += header + "\n"
        result_str += "=" * 80 + "\n"

    # Get interface information
    ip_info = parse_ip_address(sos_home)
    stats_info = parse_ip_link_stats(sos_home)

    if ip_info:
        table_header = "\n%-12s %-8s %-18s %-15s %s" % ("INTERFACE", "STATE", "IP_ADDRESS", "MAC_ADDRESS", "MTU")
        if no_pipe:
            print(screen.COLOR_HEADER + table_header + screen.COLOR_RESET)
            print("-" * 70)
        else:
            result_str += table_header + "\n"
            result_str += "-" * 70 + "\n"

        for iface in sorted(ip_info.keys()):
            info = ip_info[iface]

            # Get primary IP
            ip_addr = info['ips'][0] if info['ips'] else 'N/A'

            # Format MAC
            mac = info['mac'] if info['mac'] and info['mac'] != 'loopback' else '-'

            # Format line
            iface_line = "%-12s %-8s %-18s %-15s %d" % (
                iface, info['state'], ip_addr, mac, info['mtu']
            )

            # Apply column coloring and state-specific coloring
            if no_pipe:
                colored_line = screen.get_colored_line(iface_line)
                # Override state color based on UP/DOWN
                if info['state'] == 'DOWN':
                    colored_line = colored_line.replace(info['state'], screen.COLOR_CRITICAL + info['state'] + screen.COLOR_SUCCESS)
                print(colored_line)
            else:
                result_str += iface_line + "\n"

        # Summary
        total = len(ip_info)
        up_count = sum(1 for info in ip_info.values() if info['state'] == 'UP')
        down_count = total - up_count

        summary = "\nTotal interfaces: %d (UP: %d, DOWN: %d)" % (total, up_count, down_count)
        if no_pipe:
            print(summary)
        else:
            result_str += summary + "\n"
    else:
        no_ifaces = "\nNo interfaces found"
        if no_pipe:
            print(no_ifaces)
        else:
            result_str += no_ifaces + "\n"

    return result_str


# ============================================================================
# Help and Main Entry Point
# ============================================================================

def print_interface_help_msg(no_pipe):
    msg = '''netinfo -i  --  Interface detail view

SYNOPSIS
    netinfo -i DEVICE

DESCRIPTION
    Shows detailed information for a specific network interface, including
    state, MTU, hardware address, IP addresses, link speed, driver info,
    RX/TX statistics, ring buffer sizes, and offload feature flags.
    Reads from sos_commands/networking/ip_-d_address, ip_-s_-d_link,
    and ethtool_* files.

OPTIONS
    -i DEVICE, --interface DEVICE
        Show detailed information for the named interface (e.g. ens192).

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo -i ens192
    example.com> netinfo -i lo
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_routes_help_msg(no_pipe):
    msg = '''netinfo -r  --  Routing table view

SYNOPSIS
    netinfo -r [-d]

DESCRIPTION
    Displays the routing table parsed from
    sos_commands/networking/ip_route_show_table_all.
    Routes are grouped into Internet Gateway, Direct Networks, and Local
    Routes sections with color-coded protocol and scope annotations.

OPTIONS
    -r, --routes
        Show routing table.

    -d, --descriptive
        Add human-readable explanation below each route entry and show
        a legend. Also expands the Local Routes section (up to 15 entries).

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo -r
    example.com> netinfo -r -d
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_connections_help_msg(no_pipe):
    msg = '''netinfo -c  --  Connection analysis view

SYNOPSIS
    netinfo -c

DESCRIPTION
    Analyzes TCP/UDP socket state from
    sos_commands/networking/ss_-peaonmi.
    Shows TCP connection state breakdown (ESTAB, LISTEN, TIME-WAIT, etc.),
    UDP socket count, and a table of listening ports with owning process names.

OPTIONS
    -c, --connections
        Show connection analysis.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo -c
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_stats_help_msg(no_pipe):
    msg = '''netinfo -s  --  Network protocol statistics view

SYNOPSIS
    netinfo -s

DESCRIPTION
    Displays key protocol statistics parsed from
    sos_commands/networking/netstat_-s.
    Shows error, drop, retransmit, and other notable counters for the
    IP, TCP, UDP, and ICMP protocol sections.

OPTIONS
    -s, --stats
        Show protocol statistics.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo -s
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_nm_help_msg(no_pipe):
    msg = '''netinfo -n  --  NetworkManager status view

SYNOPSIS
    netinfo -n

DESCRIPTION
    Shows NetworkManager device and connection status parsed from
    sos_commands/networkmanager/nmcli_dev and nmcli_con.
    Lists managed devices with their state and all configured connections.

OPTIONS
    -n, --nm
        Show NetworkManager status.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo -n
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_list_help_msg(no_pipe):
    msg = '''netinfo -l  --  Interface list view

SYNOPSIS
    netinfo -l

DESCRIPTION
    Displays a compact table of all network interfaces with state, primary
    IP address, MAC address, and MTU. Reads from
    sos_commands/networking/ip_-d_address and ip_-s_-d_link.
    Summarizes total, UP, and DOWN interface counts at the bottom.

OPTIONS
    -l, --list
        Show simple interface list.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo -l
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_arp_help_msg(no_pipe):
    msg = '''netinfo --arp  --  ARP table view

SYNOPSIS
    netinfo --arp

DESCRIPTION
    Displays the ARP table parsed from proc/net/arp.
    Shows IP address, MAC address, entry state (COMPLETE, PERMANENT,
    INCOMPLETE), and device for each entry.

OPTIONS
    --arp
        Show ARP table.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo --arp
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_neigh_help_msg(no_pipe):
    msg = '''netinfo --neigh  --  Neighbor table view

SYNOPSIS
    netinfo --neigh

DESCRIPTION
    Displays the IPv4/IPv6 neighbor (NDP/ARP) table parsed from
    sos_commands/networking/ip_-s_-s_neigh_show.
    Shows IP address, MAC address, state (REACHABLE, STALE, FAILED, etc.),
    device, and reference count, with a state breakdown summary.

OPTIONS
    --neigh
        Show neighbor table (NDP/ARP).

    -h, --help
        Show this help message.

EXAMPLES
    example.com> netinfo --neigh
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    """Print help message"""
    cmd_examples = '''
Examples:
    > netinfo              # Show network summary
    > netinfo -i ens192    # Show details for interface ens192
    > netinfo -r           # Show routing table
    > netinfo -r -d        # Show routing table with detailed explanations
    > netinfo -c           # Show connection analysis
    > netinfo -s           # Show protocol statistics
    > netinfo -n           # Show NetworkManager status
    > netinfo -l           # Show simple interface list
    > netinfo --arp        # Show ARP table
    > netinfo --neigh      # Show neighbor table (NDP/ARP)
    > netinfo -h           # Show this help message
'''

    if no_pipe == False:
        output = StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()
        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""


def run_netinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    """Main entry point for netinfo command"""
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    # Set up option parser
    usage = "Usage: netinfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  default=False,
                  help='Show this help message')
    op.add_option('-i', '--interface', dest='interface',
                  default=None, type='string',
                  help='Show detailed information for specific interface')
    op.add_option('-r', '--routes', dest='show_routes', action='store_true',
                  default=False,
                  help='Show routing table')
    op.add_option('-c', '--connections', dest='show_connections', action='store_true',
                  default=False,
                  help='Show connection analysis')
    op.add_option('-s', '--stats', dest='show_stats', action='store_true',
                  default=False,
                  help='Show protocol statistics')
    op.add_option('-n', '--nm', dest='show_nm', action='store_true',
                  default=False,
                  help='Show NetworkManager status')
    op.add_option('-l', '--list', dest='show_list', action='store_true',
                  default=False,
                  help='Show simple interface list')
    op.add_option('--arp', dest='show_arp', action='store_true',
                  default=False,
                  help='Show ARP table')
    op.add_option('--neigh', dest='show_neigh', action='store_true',
                  default=False,
                  help='Show neighbor table (NDP/ARP)')
    op.add_option('-d', '--descriptive', dest='descriptive', action='store_true',
                  default=False,
                  help='Show descriptive explanations (use with -r for routing)')

    # Parse options
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help:
        if o.interface:
            return print_interface_help_msg(no_pipe)
        elif o.show_routes:
            return print_routes_help_msg(no_pipe)
        elif o.show_connections:
            return print_connections_help_msg(no_pipe)
        elif o.show_stats:
            return print_stats_help_msg(no_pipe)
        elif o.show_nm:
            return print_nm_help_msg(no_pipe)
        elif o.show_list:
            return print_list_help_msg(no_pipe)
        elif o.show_arp:
            return print_arp_help_msg(no_pipe)
        elif o.show_neigh:
            return print_neigh_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)

    # Initialize screen module
    screen.init_data(no_pipe, 1, is_cmd_stopped_func)

    # Get sosreport home directory
    sos_home = env_vars["sos_home"]

    # Route to appropriate view
    if o.interface:
        return show_interface_detail(sos_home, o.interface, no_pipe)
    elif o.show_routes:
        return show_routes(sos_home, no_pipe, o.descriptive)
    elif o.show_connections:
        return show_connections(sos_home, no_pipe)
    elif o.show_stats:
        return show_statistics(sos_home, no_pipe)
    elif o.show_nm:
        return show_networkmanager(sos_home, no_pipe)
    elif o.show_list:
        return show_interface_list(sos_home, no_pipe)
    elif o.show_arp:
        return show_arp(sos_home, no_pipe)
    elif o.show_neigh:
        return show_neighbor(sos_home, no_pipe)
    else:
        # Display summary (default mode)
        return show_summary(sos_home, no_pipe)
