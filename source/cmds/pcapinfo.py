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
# File Discovery
# ============================================================================

def find_pcap_files(sos_home):
    """
    Find all pcap/pcapng files in sosreport.
    Returns: list of (filepath, size_bytes) tuples
    """
    pcap_files = []

    # Primary location: sos_commands/networking/
    networking_dir = os.path.join(sos_home, "sos_commands", "networking")
    if os.path.isdir(networking_dir):
        for pattern in ['*.pcap', '*.pcapng', '*.cap']:
            for filepath in glob.glob(os.path.join(networking_dir, pattern)):
                if os.path.isfile(filepath):
                    size = os.path.getsize(filepath)
                    pcap_files.append((filepath, size))

    # Fallback: recursive search from sos_home
    for root, dirs, files in os.walk(sos_home):
        for filename in files:
            if filename.endswith(('.pcap', '.pcapng', '.cap')):
                filepath = os.path.join(root, filename)
                if os.path.isfile(filepath):
                    size = os.path.getsize(filepath)
                    # Avoid duplicates
                    if (filepath, size) not in pcap_files:
                        pcap_files.append((filepath, size))

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
    except:
        pass
    return False


# ============================================================================
# Pcap Analysis with tshark
# ============================================================================

def analyze_pcap_tshark(filepath, options):
    """
    Analyze pcap file using tshark.
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
        # Get basic statistics
        cmd = ['tshark', '-r', filepath, '-q', '-z', 'io,phs']
        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=30)

        # Parse protocol hierarchy
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

        # Get conversations if requested
        if options.conversations:
            cmd = ['tshark', '-r', filepath, '-q', '-z', 'conv,ip']
            output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=30)

            for line in output.splitlines():
                # Parse lines like: "10.0.0.1 <-> 10.0.0.2  123  45678  789"
                match = re.search(r'(\S+)\s+<->\s+(\S+)\s+(\d+)\s+(\d+)', line)
                if match:
                    result['conversations'].append({
                        'addr1': match.group(1),
                        'addr2': match.group(2),
                        'packets': int(match.group(3)),
                        'bytes': int(match.group(4))
                    })

        # Get time range
        cmd = ['tshark', '-r', filepath, '-q', '-z', 'io,stat,0']
        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=30)

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
        # Count packets
        cmd = ['tcpdump', '-r', filepath, '-nn', '-q']
        if options.proto:
            cmd.append(options.proto)

        output = subprocess.check_output(cmd, stderr=subprocess.PIPE, text=True, timeout=30)

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
    > pcapinfo -f FILE      # Analyze specific pcap file
    > pcapinfo -c           # Show conversation analysis
    > pcapinfo -p tcp       # Filter by protocol (with tshark)
    > pcapinfo -h           # Show this help message
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


def display_pcap_summary(filepath, analysis, no_pipe):
    """Display summary of pcap file analysis."""
    result_str = ""
    rel_path = filepath
    if 'sos_commands' in filepath:
        rel_path = filepath[filepath.find('sos_commands'):]

    result_str += screen.COLOR_TITLE + "=" * 70 + screen.COLOR_RESET + "\n"
    result_str += screen.COLOR_TITLE + f"Analysis: {rel_path}" + screen.COLOR_RESET + "\n"
    result_str += screen.COLOR_TITLE + "=" * 70 + screen.COLOR_RESET + "\n\n"

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

    # Conversations
    if analysis['conversations']:
        result_str += screen.COLOR_HEADER + "Top Conversations:" + screen.COLOR_RESET + "\n"
        result_str += f"{'Source':<20} {'Destination':<20} {'Packets':>12} {'Bytes':>15}\n"
        result_str += "-" * 70 + "\n"

        sorted_convs = sorted(analysis['conversations'], key=lambda x: x['bytes'], reverse=True)
        for conv in sorted_convs[:20]:  # Top 20 conversations
            result_str += f"{conv['addr1']:<20} {conv['addr2']:<20} "
            result_str += f"{conv['packets']:>12,} {format_size(conv['bytes']):>15}\n"
        result_str += "\n"

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

        if not verify_pcap_file(o.file):
            result_str += screen.COLOR_CRITICAL + f"ERROR: Not a valid pcap file: {o.file}\n" + screen.COLOR_RESET
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

    # Analyze each file
    for filepath, size in pcap_files:
        if is_cmd_stopped and is_cmd_stopped():
            break

        # Verify file is valid pcap
        if not verify_pcap_file(filepath):
            result_str += screen.COLOR_WARNING + f"WARNING: Skipping non-pcap file: {filepath}\n\n" + screen.COLOR_RESET
            continue

        # Large file warning
        if size > 100 * 1024 * 1024:  # 100 MB
            result_str += screen.COLOR_WARNING + f"WARNING: Large file ({format_size(size)}), "
            result_str += f"analysis may take time...\n" + screen.COLOR_RESET

        # Analyze based on available tool
        if tool_name == 'tshark':
            analysis = analyze_pcap_tshark(filepath, o)
        else:
            analysis = analyze_pcap_tcpdump(filepath, o)

        # Display results
        result_str += display_pcap_summary(filepath, analysis, no_pipe)

    return result_str
