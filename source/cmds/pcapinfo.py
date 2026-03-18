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
import ansicolor
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


def display_file_list(pcap_files, result):
    """Display list of pcap files found."""
    result.write(ansicolor.green("=" * 70) + "\n")
    result.write(ansicolor.green("PCAP Files Found") + "\n")
    result.write(ansicolor.green("=" * 70) + "\n\n")

    if not pcap_files:
        result.write("No pcap files found in sosreport.\n")
        return

    result.write(f"{'File':<50} {'Size':>15}\n")
    result.write("-" * 70 + "\n")

    total_size = 0
    for filepath, size in pcap_files:
        # Show relative path from sos_home
        rel_path = filepath
        if 'sos_commands' in filepath:
            rel_path = filepath[filepath.find('sos_commands'):]

        result.write(f"{rel_path:<50} {format_size(size):>15}\n")
        total_size += size

    result.write("-" * 70 + "\n")
    result.write(f"Total: {len(pcap_files)} file(s), {format_size(total_size)}\n\n")


def display_pcap_summary(filepath, analysis, result):
    """Display summary of pcap file analysis."""
    rel_path = filepath
    if 'sos_commands' in filepath:
        rel_path = filepath[filepath.find('sos_commands'):]

    result.write(ansicolor.green("=" * 70) + "\n")
    result.write(ansicolor.green(f"Analysis: {rel_path}") + "\n")
    result.write(ansicolor.green("=" * 70) + "\n\n")

    if analysis['errors']:
        for error in analysis['errors']:
            result.write(ansicolor.red(f"ERROR: {error}") + "\n")
        result.write("\n")
        return

    # Basic statistics
    result.write(f"Total Packets: {analysis['packet_count']:,}\n")
    if analysis['timespan']:
        result.write(f"Duration: {format_duration(analysis['timespan'])}\n")
    result.write("\n")

    # Protocol distribution
    if analysis['protocols']:
        result.write(ansicolor.cyan("Protocol Distribution:") + "\n")
        result.write(f"{'Protocol':<20} {'Packets':>15} {'Percentage':>15}\n")
        result.write("-" * 52 + "\n")

        sorted_protos = sorted(analysis['protocols'].items(), key=lambda x: x[1], reverse=True)
        for proto, count in sorted_protos[:10]:  # Top 10 protocols
            pct = (count / analysis['packet_count'] * 100) if analysis['packet_count'] > 0 else 0
            result.write(f"{proto:<20} {count:>15,} {pct:>14.1f}%\n")
        result.write("\n")

    # Conversations
    if analysis['conversations']:
        result.write(ansicolor.cyan("Top Conversations:") + "\n")
        result.write(f"{'Source':<20} {'Destination':<20} {'Packets':>12} {'Bytes':>15}\n")
        result.write("-" * 70 + "\n")

        sorted_convs = sorted(analysis['conversations'], key=lambda x: x['bytes'], reverse=True)
        for conv in sorted_convs[:20]:  # Top 20 conversations
            result.write(f"{conv['addr1']:<20} {conv['addr2']:<20} "
                        f"{conv['packets']:>12,} {format_size(conv['bytes']):>15}\n")
        result.write("\n")


# ============================================================================
# Main Command
# ============================================================================

def run_pcapinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    """Main entry point for pcapinfo command."""
    global sos_home, is_cmd_stopped

    # Set interruption callback
    is_cmd_stopped = is_cmd_stopped_func

    # Extract options from input string
    cmd_options = input_str.replace("pcapinfo", "").strip()

    # Parse options
    parser = OptionParser(usage="pcapinfo [options]")
    parser.add_option("-l", "--list", dest="list_only", action="store_true",
                     default=False, help="List pcap files only")
    parser.add_option("-f", "--file", dest="file", default="",
                     help="Analyze specific pcap file")
    parser.add_option("-p", "--proto", dest="proto", default="",
                     help="Filter by protocol (tcp, udp, icmp, etc.)")
    parser.add_option("-c", "--conversations", dest="conversations", action="store_true",
                     default=False, help="Show conversation analysis")
    parser.add_option("-s", "--summary", dest="summary", action="store_true",
                     default=True, help="Show summary statistics (default)")

    (options, args) = parser.parse_args(cmd_options.split()) if cmd_options else parser.parse_args([])

    # Initialize output
    result = screen.init_data(no_pipe)

    # Check for required tools
    tool_name, tool_path = find_pcap_tool()
    if not tool_name:
        result.write(ansicolor.red("ERROR: No pcap analysis tool found\n"))
        result.write("\nPlease install one of:\n")
        result.write("  - tshark (recommended): yum install wireshark-cli\n")
        result.write("  - tcpdump: yum install tcpdump\n\n")
        return screen.fini_data(result, no_pipe)

    result.write(f"Using tool: {tool_name}\n\n")

    # Find pcap files
    if options.file:
        # Specific file requested
        if not os.path.isfile(options.file):
            result.write(ansicolor.red(f"ERROR: File not found: {options.file}\n"))
            return screen.fini_data(result, no_pipe)

        if not verify_pcap_file(options.file):
            result.write(ansicolor.red(f"ERROR: Not a valid pcap file: {options.file}\n"))
            return screen.fini_data(result, no_pipe)

        pcap_files = [(options.file, os.path.getsize(options.file))]
    else:
        # Find all pcap files
        pcap_files = find_pcap_files(sos_home)

    # List mode
    if options.list_only:
        display_file_list(pcap_files, result)
        return screen.fini_data(result, no_pipe)

    # No files found
    if not pcap_files:
        result.write("No pcap files found in sosreport.\n")
        result.write("Use --file to specify a pcap file path.\n")
        return screen.fini_data(result, no_pipe)

    # Analyze each file
    for filepath, size in pcap_files:
        if is_cmd_stopped and is_cmd_stopped():
            break

        # Verify file is valid pcap
        if not verify_pcap_file(filepath):
            result.write(ansicolor.yellow(f"WARNING: Skipping non-pcap file: {filepath}\n\n"))
            continue

        # Large file warning
        if size > 100 * 1024 * 1024:  # 100 MB
            result.write(ansicolor.yellow(f"WARNING: Large file ({format_size(size)}), "
                                         "analysis may take time...\n"))

        # Analyze based on available tool
        if tool_name == 'tshark':
            analysis = analyze_pcap_tshark(filepath, options)
        else:
            analysis = analyze_pcap_tcpdump(filepath, options)

        # Display results
        display_pcap_summary(filepath, analysis, result)

    return screen.fini_data(result, no_pipe)
