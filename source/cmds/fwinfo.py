#!/usr/bin/env python

from optparse import OptionParser
from io import StringIO
import os
import re
import glob

import screen
import ansicolor

is_cmd_stopped = None


def description():
    return "Firewall configuration analysis"


def add_command():
    return True


cmd_name = "fwinfo"


def get_command_info():
    return {cmd_name: run_fwinfo}


sos_home = ""


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except:
        return ""


def find_file(base_dir, pattern):
    matches = glob.glob(os.path.join(base_dir, pattern))
    if matches:
        return matches[0]
    return None


def detect_firewall(sos_home):
    has_firewalld = os.path.isdir(os.path.join(sos_home, "sos_commands/firewalld"))
    has_iptables = bool(glob.glob(os.path.join(sos_home,
                        "sos_commands/networking/iptables_-t_*")))
    has_nftables = bool(glob.glob(os.path.join(sos_home,
                        "sos_commands/networking/nft_*")))

    firewalld_running = False
    if has_firewalld:
        state_file = find_file(os.path.join(sos_home, "sos_commands/firewalld"),
                               "firewall-cmd_--state")
        if state_file:
            content = read_file(state_file).strip()
            if content == "running":
                firewalld_running = True

    return has_firewalld, has_iptables, has_nftables, firewalld_running


def show_summary(sos_home, no_pipe):
    result_str = ""
    has_firewalld, has_iptables, has_nftables, firewalld_running = \
        detect_firewall(sos_home)

    result_str += screen.get_pipe_aware_line(
        "%sFIREWALL SUMMARY%s" % (screen.COLOR_TITLE, screen.COLOR_RESET))
    result_str += screen.get_pipe_aware_line("=" * 70)
    result_str += screen.get_pipe_aware_line("")

    if has_firewalld:
        if firewalld_running:
            state_str = "%srunning%s" % (screen.COLOR_INFO, screen.COLOR_RESET)
        else:
            state_str = "%snot running%s" % (screen.COLOR_CRITICAL,
                                              screen.COLOR_RESET)
        result_str += screen.get_pipe_aware_line(
            "Active firewall: firewalld (%s)" % state_str)
    elif has_nftables:
        result_str += screen.get_pipe_aware_line("Active firewall: nftables")
    elif has_iptables:
        result_str += screen.get_pipe_aware_line("Active firewall: iptables")
    else:
        result_str += screen.get_pipe_aware_line(
            "%sNo firewall configuration found%s" % (
                screen.COLOR_WARNING, screen.COLOR_RESET))
        return result_str

    detected = []
    if has_firewalld:
        detected.append("firewalld")
    if has_iptables:
        detected.append("iptables")
    if has_nftables:
        detected.append("nftables")
    if len(detected) > 1:
        result_str += screen.get_pipe_aware_line(
            "Detected configurations: %s" % ", ".join(detected))

    result_str += screen.get_pipe_aware_line("")
    return result_str


def show_firewalld(sos_home, no_pipe):
    result_str = ""
    fw_dir = os.path.join(sos_home, "sos_commands/firewalld")
    if not os.path.isdir(fw_dir):
        result_str += screen.get_pipe_aware_line(
            "%sNo firewalld data found%s" % (
                screen.COLOR_WARNING, screen.COLOR_RESET))
        return result_str

    result_str += screen.get_pipe_aware_line(
        "%sFIREWALLD CONFIGURATION%s" % (screen.COLOR_TITLE, screen.COLOR_RESET))
    result_str += screen.get_pipe_aware_line("=" * 70)

    state_file = find_file(fw_dir, "firewall-cmd_--state")
    if state_file:
        state = read_file(state_file).strip()
        if state == "running":
            state_colored = "%s%s%s" % (screen.COLOR_INFO, state,
                                        screen.COLOR_RESET)
        else:
            state_colored = "%s%s%s" % (screen.COLOR_CRITICAL, state,
                                        screen.COLOR_RESET)
        result_str += screen.get_pipe_aware_line("State: %s" % state_colored)
    else:
        result_str += screen.get_pipe_aware_line("State: unknown")

    default_zone_file = find_file(fw_dir, "firewall-cmd_--get-default-zone")
    default_zone = ""
    if default_zone_file:
        default_zone = read_file(default_zone_file).strip()
        result_str += screen.get_pipe_aware_line(
            "Default zone: %s%s%s" % (screen.COLOR_IMPORTANT, default_zone,
                                       screen.COLOR_RESET))

    active_zones = {}
    active_zones_file = find_file(fw_dir, "firewall-cmd_--get-active-zones")
    if active_zones_file:
        content = read_file(active_zones_file)
        current_zone = None
        for line in content.splitlines():
            if is_cmd_stopped and is_cmd_stopped():
                break
            if not line.startswith(" ") and not line.startswith("\t") and line.strip():
                current_zone = line.strip()
                active_zones[current_zone] = []
            elif current_zone and "interfaces:" in line.lower():
                ifaces = line.split(":", 1)[1].strip()
                active_zones[current_zone] = ifaces.split()

    result_str += screen.get_pipe_aware_line("")

    zones_file = find_file(fw_dir, "firewall-cmd_--list-all-zones")
    if zones_file:
        content = read_file(zones_file)
        result_str += _parse_zones(content, active_zones, no_pipe)
    else:
        list_all_file = find_file(fw_dir, "firewall-cmd_--list-all")
        if list_all_file:
            content = read_file(list_all_file)
            result_str += _parse_zones(content, active_zones, no_pipe)

    return result_str


def _parse_zones(content, active_zones, no_pipe):
    result_str = ""
    current_zone = None
    zone_data = {}

    for line in content.splitlines():
        if is_cmd_stopped and is_cmd_stopped():
            break

        zone_match = re.match(r'^(\S+)(?:\s+\(active\))?\s*$', line)
        if zone_match and not line.startswith(" ") and not line.startswith("\t"):
            current_zone = zone_match.group(1)
            zone_data[current_zone] = {
                'active': "(active)" in line or current_zone in active_zones,
                'interfaces': [],
                'services': [],
                'ports': [],
                'rich_rules': [],
                'sources': [],
                'masquerade': False,
                'forward_ports': [],
            }
            continue

        if current_zone and current_zone in zone_data:
            stripped = line.strip()
            if stripped.startswith("interfaces:"):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    zone_data[current_zone]['interfaces'] = val.split()
            elif stripped.startswith("services:"):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    zone_data[current_zone]['services'] = val.split()
            elif stripped.startswith("ports:"):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    zone_data[current_zone]['ports'] = val.split()
            elif stripped.startswith("rich rules:"):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    zone_data[current_zone]['rich_rules'].append(val)
            elif stripped.startswith("rule "):
                zone_data[current_zone]['rich_rules'].append(stripped)
            elif stripped.startswith("sources:"):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    zone_data[current_zone]['sources'] = val.split()
            elif stripped.startswith("masquerade:"):
                val = stripped.split(":", 1)[1].strip()
                zone_data[current_zone]['masquerade'] = (val.lower() == "yes")
            elif stripped.startswith("forward-ports:"):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    zone_data[current_zone]['forward_ports'].append(val)

    for zone_name, data in zone_data.items():
        if is_cmd_stopped and is_cmd_stopped():
            break

        active_str = " (active)" if data['active'] else ""
        result_str += screen.get_pipe_aware_line(
            "%sZone: %s%s%s" % (screen.COLOR_TITLE, zone_name, active_str,
                                screen.COLOR_RESET))

        ifaces = " ".join(data['interfaces']) if data['interfaces'] else "(none)"
        result_str += screen.get_pipe_aware_line("  Interfaces: %s" % ifaces)

        services = " ".join(data['services']) if data['services'] else "(none)"
        result_str += screen.get_pipe_aware_line("  Services: %s" % services)

        if data['ports']:
            result_str += screen.get_pipe_aware_line(
                "  Ports: %s" % " ".join(data['ports']))

        if data['sources']:
            result_str += screen.get_pipe_aware_line(
                "  Sources: %s" % " ".join(data['sources']))

        if data['masquerade']:
            result_str += screen.get_pipe_aware_line(
                "  Masquerade: %syes%s" % (screen.COLOR_WARNING,
                                            screen.COLOR_RESET))

        if data['forward_ports']:
            result_str += screen.get_pipe_aware_line("  Forward Ports:")
            for fp in data['forward_ports']:
                result_str += screen.get_pipe_aware_line("    %s" % fp)

        if data['rich_rules']:
            result_str += screen.get_pipe_aware_line("  Rich Rules:")
            for rule in data['rich_rules']:
                result_str += screen.get_pipe_aware_line("    %s" % rule)

        result_str += screen.get_pipe_aware_line("")

    return result_str


def show_iptables(sos_home, no_pipe):
    result_str = ""
    net_dir = os.path.join(sos_home, "sos_commands/networking")

    tables = [
        ("filter", "iptables_-t_filter_-nvL"),
        ("nat", "iptables_-t_nat_-nvL"),
        ("mangle", "iptables_-t_mangle_-nvL"),
    ]

    found_any = False
    total_rules = 0

    result_str += screen.get_pipe_aware_line(
        "%sIPTABLES RULES%s" % (screen.COLOR_TITLE, screen.COLOR_RESET))
    result_str += screen.get_pipe_aware_line("=" * 70)

    for table_name, file_pattern in tables:
        if is_cmd_stopped and is_cmd_stopped():
            break

        table_file = find_file(net_dir, file_pattern)
        if not table_file:
            alt_files = glob.glob(os.path.join(net_dir,
                                  "iptables*%s*" % table_name))
            if alt_files:
                table_file = alt_files[0]

        if not table_file:
            continue

        found_any = True
        content = read_file(table_file)
        if not content.strip():
            continue

        result_str += screen.get_pipe_aware_line("")
        result_str += screen.get_pipe_aware_line(
            "%sTable: %s%s" % (screen.COLOR_HEADER, table_name,
                               screen.COLOR_RESET))
        result_str += screen.get_pipe_aware_line("-" * 40)

        chain_rules = {}
        current_chain = None

        for line in content.splitlines():
            if is_cmd_stopped and is_cmd_stopped():
                break

            chain_match = re.match(r'^Chain\s+(\S+)\s+\(policy\s+(\S+)', line)
            if chain_match:
                current_chain = chain_match.group(1)
                policy = chain_match.group(2)
                chain_rules[current_chain] = {'policy': policy, 'count': 0}

                if policy in ("DROP", "REJECT"):
                    policy_str = "%s%s%s" % (screen.COLOR_WARNING, policy,
                                             screen.COLOR_RESET)
                else:
                    policy_str = policy

                result_str += screen.get_pipe_aware_line(
                    "  Chain %s (policy %s)" % (current_chain, policy_str))
                continue

            chain_match2 = re.match(r'^Chain\s+(\S+)\s+\(', line)
            if chain_match2:
                current_chain = chain_match2.group(1)
                chain_rules[current_chain] = {'policy': '-', 'count': 0}
                result_str += screen.get_pipe_aware_line(
                    "  Chain %s" % current_chain)
                continue

            if current_chain and line.strip() and not line.strip().startswith("pkts"):
                parts = line.split()
                if len(parts) >= 3 and parts[0].replace("K", "").replace(
                        "M", "").replace("G", "").isdigit():
                    chain_rules[current_chain]['count'] += 1
                    total_rules += 1

                    target = parts[2] if len(parts) > 2 else ""
                    if target in ("DROP", "REJECT"):
                        result_str += screen.get_pipe_aware_line(
                            "    %s%s%s" % (screen.COLOR_WARNING,
                                            line.strip(), screen.COLOR_RESET))
                    else:
                        result_str += screen.get_pipe_aware_line(
                            "    %s" % line.strip())

        for chain_name, info in chain_rules.items():
            if info['count'] > 0:
                result_str += screen.get_pipe_aware_line(
                    "  %s: %d rules" % (chain_name, info['count']))

    saved_rules = os.path.join(sos_home, "etc/sysconfig/iptables")
    if os.path.exists(saved_rules):
        content = read_file(saved_rules)
        if content.strip():
            result_str += screen.get_pipe_aware_line("")
            result_str += screen.get_pipe_aware_line(
                "%sSaved rules: %s%s" % (screen.COLOR_HEADER,
                                          saved_rules, screen.COLOR_RESET))
            saved_count = sum(1 for line in content.splitlines()
                             if line.startswith("-A "))
            result_str += screen.get_pipe_aware_line(
                "  %d saved rules in /etc/sysconfig/iptables" % saved_count)

    if not found_any:
        result_str += screen.get_pipe_aware_line(
            "%sNo iptables data found%s" % (screen.COLOR_WARNING,
                                             screen.COLOR_RESET))
    else:
        result_str += screen.get_pipe_aware_line("")
        result_str += screen.get_pipe_aware_line(
            "Total active rules: %d" % total_rules)

    result_str += screen.get_pipe_aware_line("")
    return result_str


def show_nftables(sos_home, no_pipe):
    result_str = ""
    net_dir = os.path.join(sos_home, "sos_commands/networking")

    result_str += screen.get_pipe_aware_line(
        "%sNFTABLES RULES%s" % (screen.COLOR_TITLE, screen.COLOR_RESET))
    result_str += screen.get_pipe_aware_line("=" * 70)

    nft_file = find_file(net_dir, "nft_list_ruleset")
    if not nft_file:
        nft_files = glob.glob(os.path.join(net_dir, "nft_*"))
        if nft_files:
            nft_file = nft_files[0]

    if not nft_file:
        result_str += screen.get_pipe_aware_line(
            "%sNo nftables data found%s" % (screen.COLOR_WARNING,
                                             screen.COLOR_RESET))
        return result_str

    content = read_file(nft_file)
    if not content.strip():
        result_str += screen.get_pipe_aware_line(
            "%sNo nftables rules configured%s" % (screen.COLOR_WARNING,
                                                    screen.COLOR_RESET))
        return result_str

    result_str += screen.get_pipe_aware_line("")

    table_count = 0
    chain_count = 0
    rule_count = 0

    for line in content.splitlines():
        if is_cmd_stopped and is_cmd_stopped():
            break

        stripped = line.rstrip()

        if re.match(r'^table\s+', stripped):
            table_count += 1
            result_str += screen.get_pipe_aware_line(
                "%s%s%s" % (screen.COLOR_TITLE, stripped, screen.COLOR_RESET))
        elif re.match(r'\s+chain\s+', stripped):
            chain_count += 1
            result_str += screen.get_pipe_aware_line(
                "%s%s%s" % (screen.COLOR_HEADER, stripped, screen.COLOR_RESET))
        elif "drop" in stripped.lower() or "reject" in stripped.lower():
            rule_count += 1
            result_str += screen.get_pipe_aware_line(
                "%s%s%s" % (screen.COLOR_WARNING, stripped, screen.COLOR_RESET))
        else:
            if stripped.strip() and not stripped.strip() == "}" \
                    and not stripped.strip().startswith("#"):
                if re.match(r'\s+(type|policy|counter|meta|ip|tcp|udp|'
                           r'ct|iif|oif|accept|log|limit)\b', stripped):
                    rule_count += 1
            result_str += screen.get_pipe_aware_line(stripped)

    result_str += screen.get_pipe_aware_line("")
    result_str += screen.get_pipe_aware_line(
        "Summary: %d tables, %d chains" % (table_count, chain_count))
    result_str += screen.get_pipe_aware_line("")

    return result_str


def run_fwinfo(input_str, env_vars, is_cmd_stopped_func,
               show_help=False, no_pipe=True):
    global sos_home, is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func
    sos_home = env_vars['sos_home']

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    usage = """fwinfo -- Firewall configuration analysis

Examples:
    fwinfo             Auto-detect firewall and show summary
    fwinfo -f          Show firewalld configuration
    fwinfo -i          Show iptables rules
    fwinfo -n          Show nftables rules
    fwinfo -a          Show all firewall information"""

    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option("-f", "--firewalld", dest="firewalld", default=False,
                  action="store_true", help="Show firewalld configuration")
    op.add_option("-i", "--iptables", dest="iptables", default=False,
                  action="store_true", help="Show iptables rules")
    op.add_option("-n", "--nftables", dest="nftables", default=False,
                  action="store_true", help="Show nftables rules")
    op.add_option("-a", "--all", dest="show_all", default=False,
                  action="store_true", help="Show all firewall information")
    op.add_option("-h", "--help", dest="help", default=False,
                  action="store_true", help="Show help")

    o = input_str
    if type(input_str) is str:
        o = input_str.split()

    (options, args) = op.parse_args(o)

    if options.help or show_help:
        output = StringIO()
        op.print_help(output)
        return output.getvalue()

    result_str = ""

    if options.show_all:
        result_str += show_summary(sos_home, no_pipe)
        result_str += show_firewalld(sos_home, no_pipe)
        result_str += show_iptables(sos_home, no_pipe)
        result_str += show_nftables(sos_home, no_pipe)
        return result_str

    if options.firewalld:
        result_str += show_firewalld(sos_home, no_pipe)
        return result_str

    if options.iptables:
        result_str += show_iptables(sos_home, no_pipe)
        return result_str

    if options.nftables:
        result_str += show_nftables(sos_home, no_pipe)
        return result_str

    has_firewalld, has_iptables, has_nftables, firewalld_running = \
        detect_firewall(sos_home)

    result_str += show_summary(sos_home, no_pipe)

    if has_firewalld:
        result_str += show_firewalld(sos_home, no_pipe)
    elif has_nftables:
        result_str += show_nftables(sos_home, no_pipe)
    elif has_iptables:
        result_str += show_iptables(sos_home, no_pipe)

    return result_str
