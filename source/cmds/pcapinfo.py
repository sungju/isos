#!/usr/bin/env python

"""
Pcap analysis command for isos
Analyzes tcpdump/tshark packet capture files in sosreports
"""

from optparse import OptionParser
from io import StringIO
import os
import re
import glob
import subprocess
from collections import defaultdict
import shutil

import screen
from isos import run_shell_command
from table_formatter import TableFormatter
import ansicolor

# Global state for command interruption
is_cmd_stopped = None


def description():
    return "Analyze packet capture (pcap/pcapng) files"


def add_command():
    return True


cmd_name = "pcapinfo"


def get_command_info():
    return {cmd_name: run_pcapinfo}


# ============================================================================
# Tool Detection
# ============================================================================

def find_pcap_tool():
    """
    Detect available pcap analysis tool.
    Returns: ('tshark', path) or ('tcpdump', path) or (None, None)
    """
    # Prefer tshark (more features)
    tshark = shutil.which('tshark')
    if tshark:
        return ('tshark', tshark)

    # Fallback to tcpdump
    tcpdump = shutil.which('tcpdump')
    if tcpdump:
        return ('tcpdump', tcpdump)

    return (None, None)


# ============================================================================
# Timeout Calculation
# ============================================================================

def calculate_timeout(filepath, base_timeout=30, per_mb=0.5, max_timeout=600):
    """
    Calculate dynamic timeout based on file size.

    Args:
        filepath: Path to file
        base_timeout: Base timeout in seconds (default: 30)
        per_mb: Additional seconds per MB (default: 0.5)
        max_timeout: Maximum timeout in seconds (default: 600 = 10 minutes)

    Returns:
        Timeout in seconds
    """
    try:
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        timeout = base_timeout + (size_mb * per_mb)
        return min(timeout, max_timeout)
    except:
        return base_timeout


# ============================================================================
# File Discovery
# ============================================================================

def find_pcap_files(sos_home):
    """
    Find all pcap/pcapng files in sosreport.
    Returns: list of (filepath, size_bytes) tuples
    """
    pcap_files = []
    seen_paths = set()

    # Primary location: sos_commands/networking/
    networking_dir = os.path.join(sos_home, "sos_commands", "networking")
    if os.path.isdir(networking_dir):
        for pattern in ['*.pcap', '*.pcapng', '*.cap']:
            for filepath in glob.glob(os.path.join(networking_dir, pattern)):
                if os.path.isfile(filepath) and filepath not in seen_paths:
                    size = os.path.getsize(filepath)
                    pcap_files.append((filepath, size))
                    seen_paths.add(filepath)

    # Fallback: recursive search from sos_home
    for root, dirs, files in os.walk(sos_home):
        for filename in files:
            if filename.endswith(('.pcap', '.pcapng', '.cap')):
                filepath = os.path.join(root, filename)
                if os.path.isfile(filepath) and filepath not in seen_paths:
                    size = os.path.getsize(filepath)
                    pcap_files.append((filepath, size))
                    seen_paths.add(filepath)

    return sorted(pcap_files)


def verify_pcap_file(filepath):
    """
    Check if file is a valid pcap/pcapng file by magic bytes.
    Returns: True if valid, False otherwise
    """
    try:
        with open(filepath, 'rb') as f:
            magic = f.read(4)
            # pcap magic: 0xa1b2c3d4 (BE) or 0xd4c3b2a1 (LE)
            # pcapng magic: 0x0a0d0d0a
            if magic in [
                b'\xa1\xb2\xc3\xd4', b'\xd4\xc3\xb2\xa1',  # pcap
                b'\x0a\x0d\x0d\x0a'  # pcapng
            ]:
                return True
    except Exception:
        pass
    return False


def is_text_tcpdump(filepath):
    """
    Check if file is text-mode tcpdump output.
    Returns: True if text format, False otherwise
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Read first few lines
            for i in range(10):
                line = f.readline()
                if not line:
                    break
                # Look for typical tcpdump text format patterns
                # e.g., "12:34:56.789 IP 10.0.0.1.443 > 10.0.0.2.8080:"
                if re.search(r'\d{2}:\d{2}:\d{2}\.\d+.*IP\s+\d+\.\d+\.\d+\.\d+', line):
                    return True
                # Also check for packet number format: "1  12:34:56.789"
                if re.search(r'^\s*\d+\s+\d{2}:\d{2}:\d{2}\.\d+', line):
                    return True
    except Exception:
        pass
    return False


def get_packet_trace_tshark(filepath, options, stream_callback=None):
    """
    Get packet-by-packet trace using tshark.

    Args:
        filepath: Path to pcap file
        options: Command options
        stream_callback: Optional callback(line_type, data) for streaming output.
                        line_type is 'packet', data is packet dict.
                        When provided, packets are streamed immediately without accumulation.

    Returns: (list of packet dicts, error_msg or '')
             When stream_callback is provided, the list is empty (packets were streamed).
    """
    packets = []
    packet_count = 0

    try:
        # Calculate dynamic timeout based on file size
        timeout = calculate_timeout(filepath)

        # Build tshark command for packet listing
        cmd = ['tshark', '-r', filepath, '-n', '-t', 'ad']

        # Apply IP filter if specified
        if hasattr(options, 'ip') and options.ip:
            cmd.extend(['-Y', f'ip.addr=={options.ip}'])

        # Limit packet count
        if hasattr(options, 'limit') and options.limit:
            cmd.extend(['-c', str(options.limit)])

        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=timeout)

        for line in output.splitlines():
            if is_cmd_stopped and is_cmd_stopped():
                break

            # Parse tshark output format:
            # "1 2026-03-18 12:34:56.789 192.168.1.1 → 192.168.1.2 TCP 74 443 → 8080 [SYN]"
            parts = line.split(None, 6)
            if len(parts) >= 6:
                # Handle arrow format vs non-arrow format
                if parts[4] == '→':
                    # Arrow format: dst is parts[5], proto/info are in parts[6]
                    dst = parts[5]
                    if len(parts) > 6:
                        # parts[6] contains "TCP 74 443 → 8080 [SYN]"
                        # Split to extract protocol name and rest
                        rest = parts[6].split(None, 1)
                        proto = rest[0]  # "TCP", "UDP", "TLSv1.2", etc.
                        info = rest[1] if len(rest) > 1 else ''
                    else:
                        proto = ''
                        info = ''
                else:
                    # Non-arrow format: dst is parts[4], proto is parts[5]
                    dst = parts[4]
                    proto = parts[5] if len(parts) > 5 else ''
                    info = parts[6] if len(parts) > 6 else ''

                packet = {
                    'num': parts[0],
                    'timestamp': f"{parts[1]} {parts[2]}",
                    'src': parts[3],
                    'dst': dst,
                    'proto': proto,
                    'info': info
                }

                packet_count += 1
                if stream_callback:
                    stream_callback('packet', packet)
                else:
                    packets.append(packet)

    except subprocess.TimeoutExpired:
        return packets, 'Packet trace timeout - file too large, try -n to reduce packet count'
    except subprocess.CalledProcessError as e:
        return packets, f'tshark error: {e.stderr.strip() if e.stderr else str(e)}'
    except Exception as e:
        return packets, f'Trace error: {str(e)}'

    return packets, ''


def get_packet_trace_text(filepath, options):
    """
    Get packet-by-packet trace from text tcpdump file.
    Returns: list of packet dicts
    """
    packets = []
    packet_count = 0
    limit = options.limit if hasattr(options, 'limit') else 100

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                if packet_count >= limit:
                    break

                # Extract timestamp
                ts_match = re.search(r'(\d{2}:\d{2}:\d{2}\.\d+)', line)
                if not ts_match:
                    continue

                timestamp = ts_match.group(1)

                # Extract IP conversation: "IP src.port > dst.port" or "IP src > dst"
                ip_match = re.search(r'IP6?\s+(\d+\.\d+\.\d+\.\d+)(?:\.(\d+))?\s+>\s+(\d+\.\d+\.\d+\.\d+)(?:\.(\d+))?', line)
                if not ip_match:
                    # Try hostname format
                    ip_match = re.search(r'IP6?\s+([^\s:>]+?)(?:\.(\d+))?\s+>\s+([^\s:]+?)(?:\.(\d+))?:', line)

                if ip_match:
                    src_ip = ip_match.group(1)
                    src_port = ip_match.group(2) if ip_match.group(2) else ''
                    dst_ip = ip_match.group(3)
                    dst_port = ip_match.group(4) if ip_match.group(4) else ''

                    # Apply IP filter if specified
                    if hasattr(options, 'ip') and options.ip:
                        if options.ip not in [src_ip, dst_ip]:
                            continue

                    # Extract protocol and info
                    proto = 'IP'
                    if 'TCP' in line:
                        proto = 'TCP'
                    elif 'UDP' in line:
                        proto = 'UDP'
                    elif 'ICMP' in line:
                        proto = 'ICMP'

                    # Extract flags and length
                    info_parts = []
                    flags_match = re.search(r'Flags \[([^\]]+)\]', line)
                    if flags_match:
                        info_parts.append(f"[{flags_match.group(1)}]")

                    length_match = re.search(r'length\s+(\d+)', line)
                    if length_match:
                        info_parts.append(f"len={length_match.group(1)}")

                    # Build source and destination with ports
                    src = f"{src_ip}:{src_port}" if src_port else src_ip
                    dst = f"{dst_ip}:{dst_port}" if dst_port else dst_ip

                    packet_count += 1
                    packets.append({
                        'num': str(packet_count),
                        'timestamp': timestamp,
                        'src': src,
                        'dst': dst,
                        'proto': proto,
                        'info': ' '.join(info_parts)
                    })

    except Exception:
        pass

    return packets


def parse_text_tcpdump(filepath, options):
    """
    Parse text-mode tcpdump output and extract conversations.
    Returns: dict with analysis results
    """
    result = {
        'packet_count': 0,
        'protocols': defaultdict(int),
        'conversations': defaultdict(lambda: {'packets': 0, 'bytes': 0}),
        'timespan': None,
        'errors': []
    }

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            first_timestamp = None
            last_timestamp = None

            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break

                # Match typical tcpdump line:
                # "12:34:56.789012 IP 192.168.1.1.443 > 192.168.1.2.8080: Flags [P.], length 1234"
                # or "1  12:34:56.789012 IP 192.168.1.1 > 192.168.1.2: ICMP echo request"

                # Extract timestamp
                ts_match = re.search(r'(\d{2}):(\d{2}):(\d{2})\.(\d+)', line)
                if ts_match:
                    h, m, s, us = ts_match.groups()
                    timestamp = int(h) * 3600 + int(m) * 60 + int(s) + float('0.' + us)
                    if first_timestamp is None:
                        first_timestamp = timestamp
                    last_timestamp = timestamp

                # Extract IP conversation: "IP src.port > dst.port" or "IP src > dst"
                ip_match = re.search(r'IP6?\s+(\d+\.\d+\.\d+\.\d+)(?:\.\d+)?\s+>\s+(\d+\.\d+\.\d+\.\d+)', line)
                if not ip_match:
                    # Try IPv6 or hostname format
                    ip_match = re.search(r'IP6?\s+([^\s:>]+?)(?:\.\d+)?\s+>\s+([^\s:]+)', line)

                if ip_match:
                    src_ip = ip_match.group(1)
                    dst_ip = ip_match.group(2)

                    # Apply IP filter if specified
                    if hasattr(options, 'ip') and options.ip:
                        if options.ip not in [src_ip, dst_ip]:
                            continue

                    result['packet_count'] += 1

                    # Normalize conversation key (sort IPs)
                    conv_key = tuple(sorted([src_ip, dst_ip]))

                    result['conversations'][conv_key]['packets'] += 1

                    # Extract length/bytes
                    length_match = re.search(r'length\s+(\d+)', line)
                    if length_match:
                        result['conversations'][conv_key]['bytes'] += int(length_match.group(1))

                # Count protocols
                if 'IP ' in line or 'IP6 ' in line:
                    result['protocols']['IP'] += 1
                if 'TCP' in line:
                    result['protocols']['TCP'] += 1
                if 'UDP' in line:
                    result['protocols']['UDP'] += 1
                if 'ICMP' in line:
                    result['protocols']['ICMP'] += 1
                if 'ARP' in line:
                    result['protocols']['ARP'] += 1

            # Calculate timespan
            if first_timestamp and last_timestamp:
                result['timespan'] = last_timestamp - first_timestamp

    except Exception as e:
        result['errors'].append(f'Text parsing error: {str(e)}')

    # Convert conversations to list format
    conversations_list = []
    for (addr1, addr2), stats in result['conversations'].items():
        conversations_list.append({
            'addr1': addr1,
            'addr2': addr2,
            'packets': stats['packets'],
            'bytes': stats['bytes']
        })
    result['conversations'] = conversations_list

    return result


# ============================================================================
# Pcap Analysis with tshark
# ============================================================================

def analyze_pcap_tshark(filepath, options, stream_callback=None):
    """
    Analyze pcap file using tshark.

    Args:
        filepath: Path to pcap file
        options: Command options
        stream_callback: Optional callback(line_type, data) for streaming output
                        line_type can be: 'conversation', 'talker', 'protocol', 'error'

    Returns: dict with analysis results (minimal data if streaming)
    """
    result = {
        'packet_count': 0,
        'protocols': defaultdict(int),
        'conversations': [],
        'top_talkers': [],
        'timespan': None,
        'errors': [],
        'conversation_count': 0,
        'talker_count': 0
    }

    try:
        # Calculate dynamic timeout based on file size
        timeout = calculate_timeout(filepath)

        # Run conversation analysis FIRST so it streams immediately before other stats
        if options.conversations or (hasattr(options, 'ip') and options.ip):
            cmd = ['tshark', '-r', filepath, '-q', '-z', 'conv,ip']
            output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=timeout)

            for line in output.splitlines():
                # Parse lines like: "10.0.0.1 <-> 10.0.0.2  123  45678  789"
                match = re.search(r'(\S+)\s+<->\s+(\S+)\s+(\d+)\s+(\d+)', line)
                if match:
                    addr1 = match.group(1)
                    addr2 = match.group(2)

                    # Apply IP filter if specified
                    if hasattr(options, 'ip') and options.ip:
                        if options.ip not in [addr1, addr2]:
                            continue

                    conv_data = {
                        'addr1': addr1,
                        'addr2': addr2,
                        'packets': int(match.group(3)),
                        'bytes': int(match.group(4))
                    }

                    # Always stream via callback when provided, otherwise accumulate
                    if stream_callback:
                        stream_callback('conversation', conv_data)
                        result['conversation_count'] += 1
                    else:
                        result['conversations'].append(conv_data)

        # Get top talkers (endpoint statistics)
        cmd = ['tshark', '-r', filepath, '-q', '-z', 'endpoints,ip']
        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=timeout)

        in_endpoints = False
        for line in output.splitlines():
            if 'IPv4 Endpoints' in line:
                in_endpoints = True
                continue
            if in_endpoints and '=' * 10 in line:
                in_endpoints = False
                continue
            if in_endpoints and line.strip() and not line.strip().startswith('|') and not line.strip().startswith('Filter'):
                # Parse: "10.0.0.1   1234   567890   789   456789   445   111101"
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        talker_data = {
                            'address': parts[0],
                            'packets': int(parts[1]),
                            'bytes': int(parts[2])
                        }

                        # Stream output if callback provided, otherwise accumulate
                        if stream_callback:
                            stream_callback('talker', talker_data)
                            result['talker_count'] += 1
                        else:
                            result['top_talkers'].append(talker_data)
                    except (ValueError, IndexError):
                        pass

        # Collect protocol hierarchy statistics after conversations are streamed
        cmd = ['tshark', '-r', filepath, '-q', '-z', 'io,phs']
        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=timeout)

        in_hierarchy = False
        for line in output.splitlines():
            if 'Protocol Hierarchy Statistics' in line:
                in_hierarchy = True
                continue
            if in_hierarchy and line.strip():
                # Parse lines like: "eth       frames:1234 bytes:567890"
                match = re.search(r'(\S+)\s+frames:(\d+)', line)
                if match:
                    proto = match.group(1)
                    count = int(match.group(2))
                    result['protocols'][proto] = count
                    result['packet_count'] = max(result['packet_count'], count)

        # Get time range
        cmd = ['tshark', '-r', filepath, '-q', '-z', 'io,stat,0']
        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=timeout)

        for line in output.splitlines():
            # Parse duration from io,stat output
            match = re.search(r'Duration:\s+([\d.]+)\s+secs', line)
            if match:
                result['timespan'] = float(match.group(1))

    except subprocess.TimeoutExpired:
        result['errors'].append('Analysis timeout (file too large)')
    except subprocess.CalledProcessError as e:
        result['errors'].append(f'tshark error: {e.stderr.strip() if e.stderr else str(e)}')
    except Exception as e:
        result['errors'].append(f'Analysis error: {str(e)}')

    return result


def analyze_pcap_tcpdump(filepath, options):
    """
    Analyze pcap file using tcpdump (limited functionality).
    Returns: dict with analysis results
    """
    result = {
        'packet_count': 0,
        'protocols': defaultdict(int),
        'conversations': [],
        'top_talkers': [],
        'timespan': None,
        'errors': []
    }

    try:
        # Calculate dynamic timeout based on file size
        timeout = calculate_timeout(filepath)

        # Count packets
        cmd = ['tcpdump', '-r', filepath, '-nn', '-q']
        if options.proto:
            cmd.append(options.proto)

        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=timeout)

        lines = output.strip().splitlines()
        result['packet_count'] = len(lines)

        # Basic protocol detection from output
        for line in lines:
            if ' IP ' in line:
                result['protocols']['IP'] += 1
            if ' ARP ' in line:
                result['protocols']['ARP'] += 1
            if ' IP6 ' in line:
                result['protocols']['IPv6'] += 1

    except subprocess.TimeoutExpired:
        result['errors'].append('Analysis timeout (file too large)')
    except subprocess.CalledProcessError as e:
        result['errors'].append(f'tcpdump error: {e.stderr.strip() if e.stderr else str(e)}')
    except Exception as e:
        result['errors'].append(f'Analysis error: {str(e)}')

    return result


# ============================================================================
# Help Message
# ============================================================================

def print_help_msg(op, no_pipe):
    """Print help message"""
    cmd_examples = '''
Examples:
    > pcapinfo              # Analyze all pcap files in sosreport
    > pcapinfo -l           # List pcap files only
    > pcapinfo -f FILE      # Analyze specific pcap file (binary or text)
    > pcapinfo -c           # Show conversation analysis
    > pcapinfo -t           # Show packet-by-packet trace
    > pcapinfo -t -n 50     # Show first 50 packets
    > pcapinfo -i 10.0.0.1  # Show conversations with specific IP
    > pcapinfo -t -i 10.0.0.1  # Packet trace for specific IP only
    > pcapinfo -c -i 10.0.0.1  # Conversation analysis for specific IP
    > pcapinfo -p tcp       # Filter by protocol (with tshark)
    > pcapinfo -h           # Show this help message

Note:
    - Supports binary pcap/pcapng files and text-mode tcpdump output
    - Text format: reads tcpdump -nn output directly
    - IP filtering works with both binary and text files
    - Packet trace (-t) shows individual packets in conversation
    - Use -n to limit number of packets displayed (default: 100)
'''
    result_str = op.format_help() + cmd_examples
    return result_str


# ============================================================================
# Output Formatting
# ============================================================================

def format_size(bytes_val):
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} TB"


def format_duration(seconds):
    """Format seconds to human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def display_file_list(pcap_files, no_pipe):
    """Display list of pcap files found."""
    result_str = ""
    result_str += screen.COLOR_TITLE + "=" * 70 + screen.COLOR_RESET + "\n"
    result_str += screen.COLOR_TITLE + "PCAP Files Found" + screen.COLOR_RESET + "\n"
    result_str += screen.COLOR_TITLE + "=" * 70 + screen.COLOR_RESET + "\n\n"

    if not pcap_files:
        result_str += "No pcap files found in sosreport.\n"
        return result_str

    result_str += f"{'File':<50} {'Size':>15}\n"
    result_str += "-" * 70 + "\n"

    total_size = 0
    for filepath, size in pcap_files:
        # Show relative path from sos_home
        rel_path = filepath
        if 'sos_commands' in filepath:
            rel_path = filepath[filepath.find('sos_commands'):]

        result_str += f"{rel_path:<50} {format_size(size):>15}\n"
        total_size += size

    result_str += "-" * 70 + "\n"
    result_str += f"Total: {len(pcap_files)} file(s), {format_size(total_size)}\n\n"
    return result_str


def display_pcap_summary(filepath, analysis, no_pipe, options=None, is_streaming=False):
    """Display summary of pcap file analysis."""
    result_str = ""
    rel_path = filepath
    if 'sos_commands' in filepath:
        rel_path = filepath[filepath.find('sos_commands'):]

    result_str += screen.COLOR_TITLE + "=" * 70 + screen.COLOR_RESET + "\n"
    result_str += screen.COLOR_TITLE + f"Analysis: {rel_path}" + screen.COLOR_RESET + "\n"
    result_str += screen.COLOR_TITLE + "=" * 70 + screen.COLOR_RESET + "\n\n"

    # Show filter info if IP filtering is active
    if options and hasattr(options, 'ip') and options.ip:
        result_str += screen.COLOR_INFO + f"Filter: Showing conversations with IP {options.ip}\n" + screen.COLOR_RESET
        result_str += "\n"

    if analysis['errors']:
        for error in analysis['errors']:
            result_str += screen.COLOR_CRITICAL + f"ERROR: {error}" + screen.COLOR_RESET + "\n"
        result_str += "\n"
        return result_str

    # Basic statistics
    result_str += f"Total Packets: {analysis['packet_count']:,}\n"
    if analysis['timespan']:
        result_str += f"Duration: {format_duration(analysis['timespan'])}\n"
    result_str += "\n"

    # Protocol distribution
    if analysis['protocols']:
        result_str += screen.COLOR_HEADER + "Protocol Distribution:" + screen.COLOR_RESET + "\n"
        result_str += f"{'Protocol':<20} {'Packets':>15} {'Percentage':>15}\n"
        result_str += "-" * 52 + "\n"

        sorted_protos = sorted(analysis['protocols'].items(), key=lambda x: x[1], reverse=True)
        for proto, count in sorted_protos[:10]:  # Top 10 protocols
            pct = (count / analysis['packet_count'] * 100) if analysis['packet_count'] > 0 else 0
            result_str += f"{proto:<20} {count:>15,} {pct:>14.1f}%\n"
        result_str += "\n"

    # Top talkers (endpoint stats) - show count if streaming, otherwise show data
    if is_streaming and analysis.get('talker_count', 0) > 0:
        result_str += screen.COLOR_HEADER + f"Top Talkers (displayed above): {analysis['talker_count']:,} endpoints\n" + screen.COLOR_RESET
        result_str += "\n"
    elif analysis.get('top_talkers'):
        result_str += screen.COLOR_HEADER + "Top Talkers:" + screen.COLOR_RESET + "\n"
        result_str += f"{'Address':<20} {'Packets':>12} {'Bytes':>15}\n"
        result_str += "-" * 50 + "\n"

        sorted_talkers = sorted(analysis['top_talkers'], key=lambda x: x['bytes'], reverse=True)
        for talker in sorted_talkers[:10]:  # Top 10 endpoints
            result_str += f"{talker['address']:<20} {talker['packets']:>12,} {format_size(talker['bytes']):>15}\n"
        result_str += "\n"

    # Conversations - show count if streaming, otherwise show data
    if is_streaming and analysis.get('conversation_count', 0) > 0:
        result_str += screen.COLOR_HEADER + f"Conversations (displayed above): {analysis['conversation_count']:,} conversations\n" + screen.COLOR_RESET
        result_str += "\n"
    elif analysis['conversations']:
        result_str += screen.COLOR_HEADER + "Top Conversations:" + screen.COLOR_RESET + "\n"
        result_str += f"{'Source':<20} {'Destination':<20} {'Packets':>12} {'Bytes':>15}\n"
        result_str += "-" * 70 + "\n"

        sorted_convs = sorted(analysis['conversations'], key=lambda x: x['bytes'], reverse=True)
        for conv in sorted_convs[:20]:  # Top 20 conversations
            result_str += f"{conv['addr1']:<20} {conv['addr2']:<20} "
            result_str += f"{conv['packets']:>12,} {format_size(conv['bytes']):>15}\n"
        result_str += "\n"

    return result_str


def colorize_info(info_str, no_pipe):
    """
    Apply color highlighting to TCP flags and patterns in Info field.

    Args:
        info_str: Info field content
        no_pipe: True if outputting to terminal

    Returns:
        Colorized string with ANSI codes (or plain if piped)
    """
    if not no_pipe or not info_str:
        return info_str

    # Define flag color patterns
    flag_colors = [
        (r'\[SYN,\s*ACK\]', ansicolor.get_color(ansicolor.GREEN)),
        (r'\[SYN\]', ansicolor.get_color(ansicolor.LIGHTGREEN)),
        (r'\[FIN\]', ansicolor.get_color(ansicolor.LIGHTYELLOW)),
        (r'\[RST\]', ansicolor.get_color(ansicolor.LIGHTRED)),
        (r'\[PSH,\s*ACK\]', ansicolor.get_color(ansicolor.CYAN)),
        (r'\[ACK\]', ansicolor.get_color(ansicolor.DARKGRAY)),
        (r'\[S\.\]', ansicolor.get_color(ansicolor.GREEN)),
        (r'\[P\.\]', ansicolor.get_color(ansicolor.CYAN)),
        (r'\[\.?\]', ansicolor.get_color(ansicolor.DARKGRAY)),
        (r'Retransmission', ansicolor.get_color(ansicolor.LIGHTRED)),
    ]

    reset = ansicolor.get_color(ansicolor.RESET)
    result = info_str

    # Apply colors to matching patterns
    for pattern, color in flag_colors:
        result = re.sub(pattern, lambda m: f"{color}{m.group(0)}{reset}", result)

    return result


def display_packet_trace(packets, no_pipe):
    """Display packet-by-packet trace with color support using TableFormatter."""
    result_str = ""

    if not packets:
        result_str += "No packets found.\n\n"
        return result_str

    # Protocol color mapping
    PROTO_COLOR_MAP = {
        'TCP': 'cyan',
        'UDP': 'lightblue',
        'ICMP': 'yellow',
        'ARP': 'lightmagenta',
        'DNS': 'lightcyan',
        'HTTP': 'green',
        'HTTPS': 'green',
        'TLS': 'lightgreen',
        'SSL': 'lightgreen',
    }

    # Section header
    result_str += screen.COLOR_HEADER + "Packet Trace:" + screen.COLOR_RESET + "\n"

    # Detect terminal width
    try:
        term_size = shutil.get_terminal_size(fallback=(200, 24))
        term_width = term_size.columns
    except:
        term_width = 200

    # Calculate column widths based on terminal size
    # Default widths for wide terminals (>= 100 chars)
    col_num = 6
    col_timestamp = 26
    col_source = 17
    col_dest = 17
    col_proto = 8

    # Shrink columns for narrow terminals
    if term_width < 100:
        col_timestamp = 15  # Time-only, drop date
        col_num = 4
        col_proto = 6
        col_source = 15
        col_dest = 15

    # Calculate padding (5 columns = 5 separators in Rich, ~2 chars each)
    padding_estimate = 10

    # Calculate Info column width (flexible)
    fixed_width = col_num + col_timestamp + col_source + col_dest + col_proto + padding_estimate
    col_info = max(20, term_width - fixed_width)  # Minimum 20 chars for Info

    # Create table with dynamic widths
    table = TableFormatter(no_pipe=no_pipe, show_header=True, console_width=term_width)
    table.add_column("#", width=col_num, align='left', color='darkgray')
    table.add_column("Timestamp", width=col_timestamp, align='left', color='magenta')
    table.add_column("Source", width=col_source, align='left', color='lightgreen')
    table.add_column("Dest", width=col_dest, align='left', color='lightyellow')
    table.add_column("Proto", width=col_proto, align='left')  # Protocol-specific via cell_colors
    table.add_column("Info", width=col_info, align='left')  # Sub-colored via colorize_info()

    # Add packet rows
    for pkt in packets:
        # Truncate fields if too long (but not Info - let TableFormatter handle it)
        src = pkt['src'][:16] if len(pkt['src']) > 16 else pkt['src']
        dst = pkt['dst'][:16] if len(pkt['dst']) > 16 else pkt['dst']
        proto = pkt['proto']

        # Truncate timestamp for narrow terminals (show time only, drop date)
        if col_timestamp == 15:
            timestamp = pkt['timestamp'].split()[-1]  # Keep only time portion
        else:
            timestamp = pkt['timestamp']

        # Determine protocol color for Proto column (column index 4)
        proto_upper = proto.upper()
        proto_color = PROTO_COLOR_MAP.get(proto_upper, 'white')

        # TEMPORARY FIX: Disable Info field coloring to prevent ANSI bleeding
        # Rich library cannot safely truncate text with embedded raw ANSI codes
        # TODO: Convert colorize_info() to use Rich markup instead of raw ANSI
        colored_info = pkt['info']

        # Add row with protocol-specific coloring
        table.add_row(
            pkt['num'],
            timestamp,
            src,
            dst,
            proto,
            colored_info,
            cell_colors={4: proto_color}  # Color Proto column based on protocol
        )

    # Format table
    result_str += table.format() + "\n"
    result_str += f"Showing {len(packets)} packet(s)\n\n"

    return result_str


# ============================================================================
# Main Command
# ============================================================================

def run_pcapinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    """Main entry point for pcapinfo command."""
    global sos_home, is_cmd_stopped

    # Set interruption callback
    is_cmd_stopped = is_cmd_stopped_func

    # Parse options
    usage = "Usage: pcapinfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  default=False, help='Show this help message')
    op.add_option("-l", "--list", dest="list_only", action="store_true",
                  default=False, help="List pcap files only")
    op.add_option("-f", "--file", dest="file", default="",
                  help="Analyze specific pcap file")
    op.add_option("-p", "--proto", dest="proto", default="",
                  help="Filter by protocol (tcp, udp, icmp, etc.)")
    op.add_option("-c", "--conversations", dest="conversations", action="store_true",
                  default=False, help="Show conversation analysis")
    op.add_option("-i", "--ip", dest="ip", default="",
                  help="Filter conversations by specific IP address")
    op.add_option("-t", "--trace", dest="trace", action="store_true",
                  default=False, help="Show packet-by-packet trace of conversations")
    op.add_option("-n", "--limit", dest="limit", type="int", default=100,
                  help="Limit number of packets shown in trace (default: 100)")
    op.add_option("-s", "--summary", dest="summary", action="store_true",
                  default=True, help="Show summary statistics (default)")

    # Parse options with error handling
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help:
        return print_help_msg(op, no_pipe)

    # Initialize screen module
    screen.init_data(no_pipe, 1, is_cmd_stopped_func)

    # Get sosreport home directory
    sos_home = env_vars["sos_home"]

    # Initialize output string
    result_str = ""

    # Check for required tools
    tool_name, tool_path = find_pcap_tool()
    if not tool_name:
        result_str += screen.COLOR_CRITICAL + "ERROR: No pcap analysis tool found\n" + screen.COLOR_RESET
        result_str += "\nPlease install one of:\n"
        result_str += "  - tshark (recommended): yum install wireshark-cli\n"
        result_str += "  - tcpdump: yum install tcpdump\n\n"
        return result_str

    result_str += f"Using tool: {tool_name}\n\n"

    # Find pcap files
    if o.file:
        # Specific file requested
        if not os.path.isfile(o.file):
            result_str += screen.COLOR_CRITICAL + f"ERROR: File not found: {o.file}\n" + screen.COLOR_RESET
            return result_str

        if not verify_pcap_file(o.file) and not is_text_tcpdump(o.file):
            result_str += screen.COLOR_CRITICAL + f"ERROR: Not a valid pcap/tcpdump file: {o.file}\n" + screen.COLOR_RESET
            return result_str

        pcap_files = [(o.file, os.path.getsize(o.file))]
    else:
        # Find all pcap files
        pcap_files = find_pcap_files(sos_home)

    # List mode
    if o.list_only:
        result_str += display_file_list(pcap_files, no_pipe)
        return result_str

    # No files found
    if not pcap_files:
        result_str += "No pcap files found in sosreport.\n"
        result_str += "Use --file to specify a pcap file path.\n"
        return result_str

    # If IP filter specified, enable conversation display automatically
    if o.ip and not o.conversations:
        o.conversations = True

    # Analyze each file
    for filepath, size in pcap_files:
        if is_cmd_stopped and is_cmd_stopped():
            break

        # Check file type: binary pcap or text tcpdump
        is_binary_pcap = verify_pcap_file(filepath)
        is_text = is_text_tcpdump(filepath)

        if not is_binary_pcap and not is_text:
            result_str += screen.COLOR_WARNING + f"WARNING: Skipping unrecognized file format: {filepath}\n\n" + screen.COLOR_RESET
            continue

        # Large file warning and streaming mode detection
        is_large_file = size > 100 * 1024 * 1024  # 100 MB
        if is_large_file:
            result_str += screen.COLOR_WARNING + f"WARNING: Large file ({format_size(size)}), "
            result_str += f"using streaming mode to avoid memory issues...\n" + screen.COLOR_RESET

        # Always use streaming mode when conversation analysis is requested
        use_streaming = o.conversations or (hasattr(o, 'ip') and o.ip)

        if use_streaming:
            # Streaming mode: print conversations as they're parsed
            conv_header_printed = False
            talker_header_printed = False

            def stream_callback(line_type, data):
                nonlocal conv_header_printed, talker_header_printed, result_str

                if line_type == 'conversation':
                    if not conv_header_printed:
                        result_str += screen.COLOR_HEADER + "Conversations (streaming):" + screen.COLOR_RESET + "\n"
                        result_str += f"{'Source':<20} {'Destination':<20} {'Packets':>12} {'Bytes':>15}\n"
                        result_str += "-" * 70 + "\n"
                        print(result_str, end='')
                        result_str = ""
                        conv_header_printed = True

                    # Print conversation immediately
                    line = f"{data['addr1']:<20} {data['addr2']:<20} "
                    line += f"{data['packets']:>12,} {format_size(data['bytes']):>15}\n"
                    print(line, end='')

                elif line_type == 'talker':
                    if not talker_header_printed:
                        if conv_header_printed:
                            print()  # Separate from conversations
                        result_str += screen.COLOR_HEADER + "Top Talkers (streaming):" + screen.COLOR_RESET + "\n"
                        result_str += f"{'Address':<20} {'Packets':>12} {'Bytes':>15}\n"
                        result_str += "-" * 50 + "\n"
                        print(result_str, end='')
                        result_str = ""
                        talker_header_printed = True

                    # Print talker immediately
                    line = f"{data['address']:<20} {data['packets']:>12,} {format_size(data['bytes']):>15}\n"
                    print(line, end='')

            # Analyze with streaming callback
            if is_text:
                analysis = parse_text_tcpdump(filepath, o)
            elif tool_name == 'tshark':
                analysis = analyze_pcap_tshark(filepath, o, stream_callback=stream_callback)
            else:
                analysis = analyze_pcap_tcpdump(filepath, o)

            # Print summary at the end (after streamed conversations)
            if conv_header_printed or talker_header_printed:
                print()  # Separator
            result_str += display_pcap_summary(filepath, analysis, no_pipe, o, is_streaming=True)

        else:
            # Normal mode: accumulate all data then display
            if is_text:
                # Text-mode tcpdump output - parse directly
                analysis = parse_text_tcpdump(filepath, o)
            elif tool_name == 'tshark':
                # Binary pcap with tshark
                analysis = analyze_pcap_tshark(filepath, o)
            else:
                # Binary pcap with tcpdump
                analysis = analyze_pcap_tcpdump(filepath, o)

            # Display results
            result_str += display_pcap_summary(filepath, analysis, no_pipe, o)

        # Display packet trace if requested
        if o.trace:
            if is_text:
                # Get packet trace from text file
                packets = get_packet_trace_text(filepath, o)
                if packets:
                    result_str += display_packet_trace(packets, no_pipe)
            elif tool_name == 'tshark':
                # Streaming mode: print packets immediately as they're parsed
                packet_count = [0]

                # Flush accumulated output before streaming
                print(result_str, end='')
                result_str = ""

                # Print header immediately
                print(screen.COLOR_HEADER + "Packet Trace:" + screen.COLOR_RESET)
                print(f"{'#':<6} {'Timestamp':<26} {'Source':<17} {'Dest':<17} {'Proto':<8} Info")
                print("-" * 90)

                def packet_stream_callback(pkt):
                    packet_count[0] += 1
                    src = pkt['src'][:16] if len(pkt['src']) > 16 else pkt['src']
                    dst = pkt['dst'][:16] if len(pkt['dst']) > 16 else pkt['dst']
                    print(f"{pkt['num']:<6} {pkt['timestamp']:<26} {src:<17} {dst:<17} {pkt['proto']:<8} {pkt['info']}")

                _, trace_error = get_packet_trace_tshark(filepath, o, stream_callback=packet_stream_callback)

                if trace_error:
                    result_str += screen.COLOR_WARNING + f"WARNING: {trace_error}\n\n" + screen.COLOR_RESET

                result_str += f"\nShowing {packet_count[0]} packet(s)\n\n"
            else:
                # tcpdump doesn't support detailed packet listing easily
                result_str += screen.COLOR_WARNING + "Packet trace not available with tcpdump. Install tshark for packet trace support.\n\n" + screen.COLOR_RESET

    return result_str
