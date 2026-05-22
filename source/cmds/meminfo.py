import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import expanduser, isfile, isdir, join
import traceback
from itertools import chain
import re
from datetime import datetime
from collections import defaultdict
import shutil


from isos import run_shell_command, column_strings
import screen
from soshelpers import get_main

# Bar chart width constants
ITEM_BAR_WIDTH = 20   # Width for individual process/slab bars
TOTAL_BAR_WIDTH = 40  # Width for total usage bar (2x for emphasis)

def description():
    return "Shows memory related information"


def add_command():
    return True


cmd_name = "meminfo"
def get_command_info():
    return { cmd_name : run_meminfo }


def get_system_total_memory_kb():
    """
    Get system's total physical memory in KB from /proc/meminfo.

    Returns:
        int: Total memory in KB, or 0 if unable to determine
    """
    global sos_home
    try:
        with open(sos_home + "/proc/meminfo") as f:
            for line in f:
                if "MemTotal:" in line:
                    return int(line.split()[1])
    except:
        pass
    return 0


def get_terminal_width():
    """
    Get terminal width from prompt_toolkit/shutil.

    This function always queries the terminal fresh (no caching) to detect
    terminal resizes that happen during command execution.

    Returns:
        int: Terminal width in columns, or 80 if unable to determine
    """
    try:
        # Always get fresh terminal size (no caching) to catch resizes
        # shutil.get_terminal_size() makes a system call each time
        terminal_size = shutil.get_terminal_size()
        return terminal_size.columns
    except:
        # Fallback to 80 columns if unable to determine
        return 80


def get_optimal_max_widths(show_graph=False):
    """
    Calculate optimal maximum column widths based on terminal width.

    Args:
        show_graph: If True, account for graph column in calculations

    Returns:
        dict: Maximum widths for different column types
            - 'process_name': Max width for process names
            - 'slab_name': Max width for SLAB names
    """
    terminal_width = get_terminal_width()

    # Reserve space for other columns and padding
    # This matches separator_width formula: pname_width + 15 + 4 (+ 24 + 2 if graph)
    if show_graph:
        # With graph: Process_Name + Percent(24) + Usage(15) + padding(4+2)
        reserved_space = 24 + 15 + 4 + 2  # = 45
    else:
        # Without graph: Process_Name + Usage(15) + padding(4)
        reserved_space = 15 + 4  # = 19

    available_width = terminal_width - reserved_space

    # Set reasonable bounds
    # Process names: minimum 20, maximum based on available space (but cap at 100)
    process_max = max(20, min(100, available_width))

    # SLAB names: slightly smaller to account for additional columns
    if show_graph:
        # SLAB table has: NAME + Percent(24) + TOTAL(12) + OBJSIZE(8) + padding(8)
        # This matches separator_width formula: slab_width + 24 + 2 + 12 + 8 + 6 = slab_width + 52
        slab_reserved = 24 + 12 + 8 + 8
    else:
        # SLAB table has: NAME + TOTAL(12) + OBJSIZE(8) + padding(6)
        # This matches separator_width formula: slab_width + 12 + 8 + 6 = slab_width + 26
        slab_reserved = 12 + 8 + 6

    slab_available = terminal_width - slab_reserved
    slab_max = max(20, min(80, slab_available))

    return {
        'process_name': process_max,
        'slab_name': slab_max
    }


def truncate_middle(text, max_width):
    """
    Truncate text with ellipsis in the middle to preserve the end.

    This is useful for process names with full paths where the end
    contains the actual executable name.

    Args:
        text: String to truncate
        max_width: Maximum width including ellipsis

    Returns:
        Truncated string with '...' in the middle if needed

    Examples:
        truncate_middle("/usr/bin/very_long_process_name", 20)
        -> "/usr/bin/...s_name"
    """
    if len(text) <= max_width:
        return text

    if max_width < 4:
        return text[:max_width]

    # Reserve 3 characters for '...'
    available = max_width - 3
    # Split available space: slightly favor the end to preserve executable name
    left_chars = available // 2
    right_chars = available - left_chars

    return text[:left_chars] + "..." + text[-right_chars:]


def show_mem_balloon(op, no_pipe):
    result_str = ''
    page_size = get_main().page_size
    try:
        with open(sos_home + "/sys/kernel/debug/vmmemctl") as f:
            target = 0
            current = 0
            for line in f:
                words = line.split(":")
                if words[0] == "target" and words[1].endswith("pages"):
                    target = int(words[1].split()[0])
                elif words[0] == "current":
                    current = int(words[1].split()[0])


            result_str = result_str +\
                    screen.get_pipe_aware_line("VMware VM")
            result_str = result_str +\
                    screen.get_pipe_aware_line("Target  : %d pages (%s)" %\
                        (target, get_size_str(target * page_size)))
            result_str = result_str +\
                    screen.get_pipe_aware_line("Current : %d pages (%s)" %\
                        (current, get_size_str(current * page_size)))

            return result_str
    except:
        pass

    return result_str


def get_size_str(size):
    size_str = ""
    if size > (1024 * 1024 * 1024): # GiB
        size_str = "%.1f GiB" % (size / (1024*1024*1024))
    elif size > (1024 * 1024): # MiB
        size_str = "%.1f MiB" % (size / (1024*1024))
    elif size > (1024): # KiB
        size_str = "%.1f KiB" % (size / (1024))
    else:
        size_str = "%.0f B" % (size)

    return size_str


def get_memory_bar(percentage, width=20, no_pipe=True):
    """
    Generate ASCII bar chart for memory usage percentage with 4 gradual shading levels

    Args:
        percentage: Usage percentage (0-100)
        width: Total width of bar in characters
        no_pipe: Whether colors are enabled

    Returns:
        String representation of bar chart like: [████▓▒░░░░░] 45.2%
        Uses 4 shading characters:
        ░ (light)  - empty portion
        ▒ (medium) - 0-33% of fractional character
        ▓ (heavy)  - 33-66% of fractional character
        █ (full)   - fully filled characters
    """
    if percentage < 0:
        percentage = 0
    if percentage > 100:
        percentage = 100

    # Calculate exact filled width (as float to get fractional part)
    exact_filled = (percentage / 100.0) * width
    filled_count = int(exact_filled)
    fraction = exact_filled - filled_count

    # Shading characters for gradual fill
    empty_char = '░'   # Light shade for empty
    light_char = '▒'   # Medium shade for 0-33% fill
    medium_char = '▓'  # Heavy shade for 33-66% fill
    full_char = '█'    # Full block for 100% fill

    # Build the bar with gradual shading
    bar_chars = []

    # Add fully filled characters
    bar_chars.extend([full_char] * filled_count)

    # Add fractional character if there's remaining space
    if filled_count < width:
        if fraction >= 0.66:
            bar_chars.append(full_char)    # 66-100% shows as full (almost complete)
        elif fraction >= 0.33:
            bar_chars.append(medium_char)  # 33-66% shows as heavy shade
        elif fraction > 0:
            bar_chars.append(light_char)   # 1-33% shows as medium shade
        else:
            bar_chars.append(empty_char)   # Exactly 0 shows as empty

    # Fill remaining with empty characters
    remaining = width - len(bar_chars)
    bar_chars.extend([empty_char] * remaining)

    bar = '[' + ''.join(bar_chars) + ']'

    # Add color coding based on usage level
    if no_pipe:
        import ansicolor
        if percentage >= 90:
            color = ansicolor.get_color(ansicolor.RED)
        elif percentage >= 70:
            color = ansicolor.get_color(ansicolor.YELLOW)
        elif percentage >= 50:
            color = ansicolor.get_color(ansicolor.CYAN)
        else:
            color = ansicolor.get_color(ansicolor.GREEN)
        reset = ansicolor.get_color(ansicolor.RESET)
        bar = color + bar + reset

    return bar

def get_file_list(filename, checkdir=True):
    result_list = []

    file_list = glob.glob(filename)
    for file in file_list:
        if isdir(file) and checkdir:
            flist = get_file_list(file + "/*")
            result_list = result_list + flist
        else:
            result_list.append(file)

    return result_list


hugepages_size = 2 * 1024 * 1024

def show_oom_meminfo(op, no_pipe, meminfo_dict):
    from table_formatter import TableFormatter

    global hugepages_size

    result_str = ""
    page_size = get_main().page_size

    # Create table with TableFormatter
    table = TableFormatter(no_pipe=no_pipe, show_header=True, padding=1)
    table.add_column("Category", width=30, align='left', color='yellow')
    table.add_column("Size", width=15, align='right', color='red')

    sorted_meminfo_dict = sorted(meminfo_dict.items(),
                            key=operator.itemgetter(1), reverse=True)

    for i in range(0, len(sorted_meminfo_dict)):
        try:
            key = sorted_meminfo_dict[i][0]
            val = sorted_meminfo_dict[i][1]
            if key.startswith("hugepages_") and key != "hugepages_size":
                val = val * hugepages_size
            table.add_row(key, get_size_str(val))
        except Exception as e:
            print(e)
            pass

    # Format and output table
    formatted_table = table.format()
    if no_pipe:
        print("\n" + "#" * 46)
        print(formatted_table)
        print("~" * 46)
    else:
        result_str = "\n" + "#" * 46 + "\n"
        result_str += formatted_table + "\n"
        result_str += "~" * 46 + "\n"

    return result_str


def show_oom_slab_usage(op, no_pipe, slab_dict, total_usage):
    from table_formatter import TableFormatter

    # Get system's total memory for percentage calculation
    system_total_mem_kb = get_system_total_memory_kb()
    system_total_mem_bytes = system_total_mem_kb * 1024

    result_str = ""
    sorted_slab_dict = sorted(slab_dict.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = getattr(op, 'oom_top', 10)
    if (op.all):
        min_number = len(sorted_slab_dict) - 1

    print_count = min(len(sorted_slab_dict) - 1, min_number)

    # Create table with TableFormatter
    show_graph = getattr(op, 'graph', False)

    # Calculate optimal column width based on terminal width and longest SLAB name
    max_widths = get_optimal_max_widths(show_graph)
    max_slab_len = max(len(sorted_slab_dict[i][0]) for i in range(0, print_count)) if print_count > 0 else 20
    slab_width = max(20, min(max_widths['slab_name'], max_slab_len + 2))
    # Disable Rich when using graphs to avoid ANSI code conflicts
    use_rich = not show_graph
    table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
    table.add_column("SLAB_Name", width=slab_width, align='left', color='yellow')
    if show_graph:
        table.add_column("Usage_Percent", width=24, align='left', color='cyan')
    table.add_column("Usage", width=15, align='right', color='red')

    for i in range(0, print_count):
        pname = sorted_slab_dict[i][0]
        # Truncate SLAB name to fit column width
        if len(pname) > slab_width:
            pname = pname[:slab_width-3] + "..."
        mem_usage = sorted_slab_dict[i][1]
        if show_graph:
            # Calculate percentage based on system's total memory
            percentage = (mem_usage * 100.0 / system_total_mem_bytes) if system_total_mem_bytes > 0 else 0
            bar = get_memory_bar(percentage, width=ITEM_BAR_WIDTH, no_pipe=no_pipe)
            table.add_row(pname, bar, get_size_str(mem_usage))
        else:
            table.add_row(pname, get_size_str(mem_usage))

    # Format and output table
    formatted_table = table.format()
    # SLAB_Name(dynamic) + Usage(15) + padding
    separator_width = slab_width + 15 + 4
    if show_graph:
        separator_width += 24 + 2

    if no_pipe:
        # Split table into header and data rows
        table_lines = formatted_table.split('\n')
        print("=" * separator_width)
        if len(table_lines) > 0:
            print(table_lines[0])  # Print header
            print("-" * separator_width)  # Add separator line
            for line in table_lines[1:]:  # Print data rows
                if line.strip():  # Skip empty lines
                    print(line)
        if print_count < len(sorted_slab_dict) - 1:
            print("\t<...>")
        print("=" * separator_width)
        print("Total memory usage from SLABs = %s" % get_size_str(total_usage))
        # Show total usage bar graph
        if show_graph and system_total_mem_bytes > 0:
            total_percentage = (total_usage * 100.0 / system_total_mem_bytes)
            print("\tNotes) %.2f percent from total system memory(%s)" %
                  (total_percentage, get_size_str(system_total_mem_bytes)))
            bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
            print("\t       %s" % bar)
    else:
        # Split table into header and data rows for piped output
        table_lines = formatted_table.split('\n')
        result_str = "=" * separator_width + "\n"
        if len(table_lines) > 0:
            result_str += table_lines[0] + "\n"  # Header
            result_str += "-" * separator_width + "\n"  # Separator
            for line in table_lines[1:]:  # Data rows
                if line.strip():
                    result_str += line + "\n"
        if print_count < len(sorted_slab_dict) - 1:
            result_str += "\t<...>\n"
        result_str += "=" * separator_width + "\n"
        result_str += "Total memory usage from SLABs = %s\n" % get_size_str(total_usage)
        # Show total usage bar graph
        if show_graph and system_total_mem_bytes > 0:
            total_percentage = (total_usage * 100.0 / system_total_mem_bytes)
            result_str += "\tNotes) %.2f percent from total system memory(%s)\n" % \
                          (total_percentage, get_size_str(system_total_mem_bytes))
            bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
            result_str += "\t       %s\n" % bar

    return result_str


def show_oom_memory_usage(op, no_pipe, oom_dict, total_usage):
    from table_formatter import TableFormatter

    # Get system's total memory for percentage calculation
    system_total_mem_kb = get_system_total_memory_kb()
    system_total_mem_bytes = system_total_mem_kb * 1024

    result_str = ""
    sorted_oom_dict = sorted(oom_dict.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = getattr(op, 'oom_top', 10)
    if (op.all):
        min_number = len(sorted_oom_dict) - 1

    print_count = min(len(sorted_oom_dict) - 1, min_number)

    # Create table with TableFormatter
    show_graph = getattr(op, 'graph', False)

    # Calculate optimal column width based on terminal width and longest process name
    initial_terminal_width = get_terminal_width()
    max_widths = get_optimal_max_widths(show_graph)
    max_pname_len = max(len(sorted_oom_dict[i][0]) for i in range(0, print_count)) if print_count > 0 else 20
    pname_width = max(20, min(max_widths['process_name'], max_pname_len + 1))
    # Disable Rich when using graphs to avoid ANSI code conflicts
    use_rich = not show_graph
    table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
    table.add_column("Process_Name", width=pname_width, align='left', color='yellow')
    if show_graph:
        table.add_column("Usage_Percent", width=24, align='left', color='cyan')
    table.add_column("Usage", width=15, align='right', color='red')

    rows_added_since_check = 0
    for i in range(0, print_count):
        # Check for terminal resize every 10 rows (to avoid excessive system calls)
        if show_graph and i > 0 and rows_added_since_check >= 10:
            current_width = get_terminal_width()
            if abs(current_width - initial_terminal_width) > 5:
                # Terminal resized significantly - output current table and start new one
                # Format and output current table first
                formatted_table = table.format()
                separator_width = pname_width + 15 + 4
                if show_graph:
                    separator_width += 24 + 2

                if no_pipe:
                    table_lines = formatted_table.split('\n')
                    print("=" * separator_width)
                    if len(table_lines) > 0:
                        print(table_lines[0])
                        print("-" * separator_width)
                        for line in table_lines[1:]:
                            if line.strip():
                                print(line)
                    print("=" * separator_width)

                    # Print resize notice
                    print(colored("\n[Terminal resized - adjusting table width]\n", 'yellow'))

                # Recalculate widths and create new table
                initial_terminal_width = current_width
                max_widths = get_optimal_max_widths(show_graph)
                pname_width = max(20, min(max_widths['process_name'], max_pname_len + 1))

                table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
                table.add_column("Process_Name", width=pname_width, align='left', color='yellow')
                if show_graph:
                    table.add_column("Usage_Percent", width=24, align='left', color='cyan')
                table.add_column("Usage", width=15, align='right', color='red')

                rows_added_since_check = 0

        pname = sorted_oom_dict[i][0]
        # Truncate process name to fit column width
        pname = truncate_middle(pname, pname_width)
        mem_usage = sorted_oom_dict[i][1]
        if show_graph:
            # Calculate percentage based on system's total memory
            percentage = (mem_usage * 100.0 / system_total_mem_bytes) if system_total_mem_bytes > 0 else 0
            bar = get_memory_bar(percentage, width=ITEM_BAR_WIDTH, no_pipe=no_pipe)
            table.add_row(pname, bar, get_size_str(mem_usage))
        else:
            table.add_row(pname, get_size_str(mem_usage))

        rows_added_since_check += 1

    # Format and output table
    formatted_table = table.format()
    # Process_Name(dynamic) + Usage(15) + padding
    separator_width = pname_width + 15 + 4
    if show_graph:
        separator_width += 24 + 2

    if no_pipe:
        # Split table into header and data rows
        table_lines = formatted_table.split('\n')
        print("=" * separator_width)
        if len(table_lines) > 0:
            print(table_lines[0])  # Print header
            print("-" * separator_width)  # Add separator line
            for line in table_lines[1:]:  # Print data rows
                if line.strip():  # Skip empty lines
                    print(line)
        if print_count < len(sorted_oom_dict) - 1:
            print("\t<...>")
        print("=" * separator_width)
        print("Total memory usage from processes = %s" % get_size_str(total_usage))
        # Show total usage bar graph
        if show_graph and system_total_mem_bytes > 0:
            total_percentage = (total_usage * 100.0 / system_total_mem_bytes)
            print("\tNotes) %.2f percent from total system memory(%s)" %
                  (total_percentage, get_size_str(system_total_mem_bytes)))
            bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
            print("\t       %s" % bar)
    else:
        # Split table into header and data rows for piped output
        table_lines = formatted_table.split('\n')
        result_str = "=" * separator_width + "\n"
        if len(table_lines) > 0:
            result_str += table_lines[0] + "\n"  # Header
            result_str += "-" * separator_width + "\n"  # Separator
            for line in table_lines[1:]:  # Data rows
                if line.strip():
                    result_str += line + "\n"
        if print_count < len(sorted_oom_dict) - 1:
            result_str += "\t<...>\n"
        result_str += "=" * separator_width + "\n"
        result_str += "Total memory usage from processes = %s\n" % get_size_str(total_usage)
        # Show total usage bar graph
        if show_graph and system_total_mem_bytes > 0:
            total_percentage = (total_usage * 100.0 / system_total_mem_bytes)
            result_str += "\tNotes) %.2f percent from total system memory(%s)\n" % \
                          (total_percentage, get_size_str(system_total_mem_bytes))
            bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
            result_str += "\t       %s\n" % bar

    return result_str


def get_size(val):
    page_size = get_main().page_size

    size = 0
    if val.endswith("B"):
        size = int(val[:-2]) * 1024
    else:
        size = int(val.split('#')[0]) * page_size

    return size


def get_sos_relative_name(path):
    if path.startswith(sos_home):
        prompt_str, _ = get_main().get_home_path_str()
        path = prompt_str + path[len(sos_home):]

    return path


def build_process_filter_pattern(filter_str):
    """
    Build regex pattern from filter string.
    Supports:
    - Comma-separated: "java,python,VM" -> regex: (java|python|VM)
    - Direct regex: "java.*" -> regex: java.*

    Returns compiled regex pattern or None if invalid
    """
    if not filter_str:
        return None

    try:
        # Check if it contains commas (comma-separated list)
        if ',' in filter_str:
            # Split by comma and build OR pattern
            processes = [p.strip() for p in filter_str.split(',')]
            # Escape special regex characters in each process name
            processes = [re.escape(p) for p in processes if p]
            regex_str = '|'.join(processes)
            # Wrap in parentheses for clarity
            regex_str = '(' + regex_str + ')'
        else:
            # Treat as direct regex pattern
            regex_str = filter_str

        return re.compile(regex_str, re.IGNORECASE)
    except re.error:
        return None


def detect_oom_file_format(file_path):
    """Detect the log format of a file containing OOM events.

    Returns 'vmcore-dmesg' if lines start with [timestamp] pattern,
    'syslog' otherwise.
    """
    try:
        with open(file_path) as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                if re.match(r'^\[\s*\d+\.\d+\]', line):
                    return 'vmcore-dmesg'
                if 'kernel:' in line:
                    return 'syslog'
    except:
        pass
    return 'syslog'


def parse_oom_timestamp(line, format='syslog'):
    """Extract timestamp from log line.

    Returns a datetime for syslog format, or None for vmcore-dmesg
    (jiffies cannot be reliably converted to wall-clock time without
    boot time reference, so timestamp-based analysis is skipped).
    """
    try:
        if format == 'vmcore-dmesg':
            return None
        else:
            # Try standard syslog format: "Feb 22 10:15:30"
            match = re.match(r'(\w+\s+\d+\s+\d+:\d+:\d+)', line)
            if match:
                timestamp_str = match.group(1)
                # Add current year for parsing
                current_year = datetime.now().year
                timestamp = datetime.strptime(timestamp_str + " " + str(current_year), "%b %d %H:%M:%S %Y")
                return timestamp
    except:
        pass
    return None


def extract_invoker_process(line):
    """Extract the process name that invoked OOM killer"""
    try:
        # Pattern: "processname invoked oom-killer:"
        match = re.search(r'(\S+)\s+invoked oom-killer:', line)
        if match:
            return match.group(1)
    except:
        pass
    return "unknown"


def extract_stack_trace_info(line):
    """Extract function name and module from vmcore-dmesg stack trace line.

    Parses: [timestamp]  function_name+0xoffset/0xsize [module]
    Returns: (function_name, module) tuple, or (None, None) if no match.

    TODO: Integrate into show_oom_events when adding vmcore-dmesg detail view.
    Call on each oom_invoked line for vmcore-dmesg format to display annotated
    stack traces with resolved function names and modules.
    """
    try:
        match = re.search(r'\[[\d.]+\]\s+(\w+)\+0x[\da-f]+/0x[\da-f]+(?:\s+\[([^\]]+)\])?', line)
        if match:
            return (match.group(1), match.group(2))
    except:
        pass
    return (None, None)


def collect_oom_events(file_list, op):
    """Collect all OOM events with metadata for analysis"""
    oom_events = []
    page_size = get_main().page_size

    for file in file_list:
        if not isfile(file):
            continue

        file_format = detect_oom_file_format(file)

        try:
            with open(file) as f:
                oom_data = None
                oom_ps_started = False
                rss_index = -1
                pid_index = -1
                pname_index = -1

                trim_word = '] ' if file_format == 'vmcore-dmesg' else ' kernel: '
                if op.trim_word != "":
                    trim_word = op.trim_word

                for line in chain(f, [""]):
                    if op.trim_idx != 0:
                        try:
                            trim_word = line.split()[op.trim_idx + 1]
                        except:
                            pass
                    if trim_word not in line:
                        trim_word = '] '
                    trim_ends_idx = line.find(trim_word) + len(trim_word)

                    # Detect OOM event start
                    oom_start = "invoked oom-killer:" in line
                    if file_format == 'vmcore-dmesg' and not oom_start and oom_data is None:
                        oom_start = "Out of memory:" in line
                    if oom_start:
                        oom_data = {
                            'timestamp': parse_oom_timestamp(line, file_format),
                            'invoker': extract_invoker_process(line),
                            'file': file,
                            'line': line.strip(),
                            'processes': {},
                            'total_rss': 0,
                            'killed_process': None,
                            'killed_pid': None
                        }
                        continue

                    # Capture killed process
                    if oom_data and "Out of memory: Killed process" in line:
                        try:
                            match = re.search(r'Killed process (\d+) \(([^)]+)\)', line)
                            if match:
                                oom_data['killed_pid'] = match.group(1)
                                oom_data['killed_process'] = match.group(2)
                        except:
                            pass
                        continue

                    # Parse process table header
                    if oom_data and "uid" in line and "total_vm" in line:
                        oom_ps_started = True
                        line = line[trim_ends_idx:]
                        line = line.replace("[", "").replace("]", "")
                        words = line.split()
                        for i in range(0, len(words)):
                            if words[i] == "rss":
                                rss_index = i
                            elif words[i] == "pid":
                                pid_index = i
                            elif words[i] == "name":
                                pname_index = i
                        continue

                    # Parse process entries
                    if oom_ps_started and "[" not in line[trim_ends_idx:]:
                        # End of process table - save event
                        if oom_data:
                            oom_events.append(oom_data)
                            oom_data = None
                        oom_ps_started = False
                        rss_index = -1
                        pid_index = -1
                        pname_index = -1
                        continue

                    if oom_ps_started and oom_data:
                        line = line[trim_ends_idx:]
                        line = line.replace("[", "").replace("]", "")
                        words = line.split()
                        if len(words) <= pname_index:
                            continue
                        pid = words[pid_index]
                        pname = words[pname_index]
                        try:
                            rss = int(words[rss_index]) * page_size
                            oom_data['total_rss'] += rss
                            oom_data['processes'][pname] = oom_data['processes'].get(pname, 0) + rss
                        except:
                            pass

        except Exception as e:
            pass

    return oom_events


def show_oom_summary_dashboard(oom_events, no_pipe):
    """Display OOM summary dashboard"""
    from table_formatter import TableFormatter

    if not oom_events:
        return screen.get_pipe_aware_line("No OOM events found.\n")

    result_str = ""

    # Header
    if no_pipe:
        print("\n" + "=" * 80)
        print("OOM KILLER SUMMARY DASHBOARD".center(80))
        print("=" * 80)
    else:
        result_str += "\n" + "=" * 80 + "\n"
        result_str += "OOM KILLER SUMMARY DASHBOARD".center(80) + "\n"
        result_str += "=" * 80 + "\n"

    # Basic statistics
    total_events = len(oom_events)
    timestamps = [e['timestamp'] for e in oom_events if e['timestamp']]

    if timestamps:
        first_oom = min(timestamps)
        last_oom = max(timestamps)
        duration = (last_oom - first_oom).total_seconds() / 3600.0  # hours
        date_range = "%s to %s (%.1f hours)" % (
            first_oom.strftime("%b %d %H:%M"),
            last_oom.strftime("%b %d %H:%M"),
            duration
        )
    else:
        date_range = "Unknown"

    # Count invokers
    invoker_count = defaultdict(int)
    for event in oom_events:
        invoker_count[event['invoker']] += 1

    top_invokers = sorted(invoker_count.items(), key=lambda x: x[1], reverse=True)[:5]

    # Display basic stats
    stats_output = ""
    stats_output += "  Total OOM Events: %d\n" % total_events
    stats_output += "  Date Range: %s\n" % date_range
    stats_output += "\n"

    if no_pipe:
        print(stats_output)
    else:
        result_str += stats_output

    # Top invokers table
    table = TableFormatter(no_pipe=no_pipe, show_header=True, padding=1)
    table.add_column("TOP INVOKING PROCESSES", width=40, align='left', color='yellow')
    table.add_column("COUNT", width=10, align='right', color='red')
    table.add_column("PERCENTAGE", width=12, align='right', color='cyan')

    for invoker, count in top_invokers:
        percentage = (count * 100.0 / total_events)
        table.add_row(invoker, str(count), "%.1f%%" % percentage)

    formatted_table = table.format()
    if no_pipe:
        print(formatted_table)
        print("")
    else:
        result_str += formatted_table + "\n\n"

    return result_str


def analyze_oom_patterns(oom_events, no_pipe):
    """Analyze OOM patterns and detect issues"""
    result_str = ""

    if not oom_events:
        return result_str

    # Header
    if no_pipe:
        print("=" * 80)
        print("OOM PATTERN ANALYSIS".center(80))
        print("=" * 80)
    else:
        result_str += "=" * 80 + "\n"
        result_str += "OOM PATTERN ANALYSIS".center(80) + "\n"
        result_str += "=" * 80 + "\n"

    patterns = []

    # Detect OOM storms (multiple OOMs in short time)
    timestamps = sorted([e['timestamp'] for e in oom_events if e['timestamp']])
    if len(timestamps) >= 3:
        for i in range(len(timestamps) - 2):
            time_diff = (timestamps[i+2] - timestamps[i]).total_seconds() / 60.0  # minutes
            if time_diff < 5:  # 3 OOMs within 5 minutes
                patterns.append("⚠ OOM STORM: 3+ OOM events within 5 minutes detected around %s" %
                              timestamps[i].strftime("%b %d %H:%M"))
                break

    # Detect recurring invokers (same process repeatedly triggering OOM)
    invoker_count = defaultdict(int)
    for event in oom_events:
        invoker_count[event['invoker']] += 1

    for invoker, count in invoker_count.items():
        if count >= 5 and invoker != "unknown":
            percentage = (count * 100.0 / len(oom_events))
            patterns.append("⚠ RECURRING INVOKER: '%s' triggered OOM %d times (%.1f%%)" %
                          (invoker, count, percentage))

    # Detect potential memory leaks (same process killed multiple times)
    killed_count = defaultdict(int)
    for event in oom_events:
        if event['killed_process']:
            killed_count[event['killed_process']] += 1

    for process, count in killed_count.items():
        if count >= 3:
            patterns.append("⚠ POTENTIAL LEAK: '%s' was killed %d times by OOM killer" %
                          (process, count))

    # Display patterns
    if patterns:
        for pattern in patterns:
            if no_pipe:
                print("  " + pattern)
            else:
                result_str += "  " + pattern + "\n"
    else:
        msg = "  No concerning patterns detected."
        if no_pipe:
            print(msg)
        else:
            result_str += msg + "\n"

    if no_pipe:
        print("")
    else:
        result_str += "\n"

    return result_str


def show_oom_recommendations(oom_events, no_pipe):
    """Provide actionable recommendations based on OOM analysis"""
    result_str = ""

    if not oom_events:
        return result_str

    # Header
    if no_pipe:
        print("=" * 80)
        print("RECOMMENDATIONS".center(80))
        print("=" * 80)
    else:
        result_str += "=" * 80 + "\n"
        result_str += "RECOMMENDATIONS".center(80) + "\n"
        result_str += "=" * 80 + "\n"

    recommendations = []

    # Check if system has swap
    total_events = len(oom_events)
    if total_events >= 10:
        recommendations.append("1. CRITICAL: %d OOM events detected. System is severely memory constrained." % total_events)
        recommendations.append("   → Consider adding more physical RAM")
        recommendations.append("   → Enable or increase swap space size")

    # Check for recurring processes
    invoker_count = defaultdict(int)
    for event in oom_events:
        invoker_count[event['invoker']] += 1

    top_invoker = max(invoker_count.items(), key=lambda x: x[1]) if invoker_count else None
    if top_invoker and top_invoker[1] >= 5:
        recommendations.append("2. Process '%s' is frequently triggering OOM (%d times):" %
                             (top_invoker[0], top_invoker[1]))
        recommendations.append("   → Investigate memory usage of this process")
        recommendations.append("   → Check for memory leaks or excessive memory allocation")
        recommendations.append("   → Consider tuning application memory limits")

    # Check for killed processes
    killed_count = defaultdict(int)
    for event in oom_events:
        if event['killed_process']:
            killed_count[event['killed_process']] += 1

    if killed_count:
        top_killed = max(killed_count.items(), key=lambda x: x[1])
        if top_killed[1] >= 3:
            recommendations.append("3. Process '%s' was killed %d times by OOM killer:" %
                                 (top_killed[0], top_killed[1]))
            recommendations.append("   → This process may have a memory leak")
            recommendations.append("   → Review application logs for errors")
            recommendations.append("   → Consider memory profiling or heap dumps")

    # General recommendations
    if total_events >= 1:
        recommendations.append("4. General Actions:")
        recommendations.append("   → Review vm.overcommit_memory and vm.overcommit_ratio settings")
        recommendations.append("   → Check for runaway processes or memory-intensive workloads")
        recommendations.append("   → Monitor memory trends over time")
        recommendations.append("   → Consider implementing cgroup memory limits")

    # Display recommendations
    if recommendations:
        for rec in recommendations:
            if no_pipe:
                print("  " + rec)
            else:
                result_str += "  " + rec + "\n"

    if no_pipe:
        print("")
    else:
        result_str += "\n"

    return result_str


def show_oom_events(op, args, no_pipe):
    global hugepages_size

    result_str = ""
    file_list = []
    for file in args[1:]:
        file_list = file_list + get_file_list(file, True)

    if len(file_list) == 0:
        file_list = get_file_list(sos_home + "/var/log/messages*", False)
        file_list = file_list + \
                get_file_list(sos_home + "/sos_commands/logs/journalctl*", False)
        file_list = file_list + \
                get_file_list(sos_home + "/var/log/dmesg*", False)
        file_list = file_list + \
                get_file_list(sos_home + "/var/log/vmcore-dmesg.txt*", False)
        file_list = file_list + \
                get_file_list(sos_home + "/*vmcore-dmesg.txt*", False)

    # If summary mode is requested, collect all OOM events and show dashboard
    if op.oom_summary:
        oom_events = collect_oom_events(file_list, op)

        # Apply process filter if specified
        if op.process_filter:
            pattern = build_process_filter_pattern(op.process_filter)
            if pattern is None:
                result_str += screen.get_pipe_aware_line("Invalid filter pattern: %s\n" % op.process_filter)
                return result_str
            oom_events = [e for e in oom_events if pattern.search(e['invoker']) or
                         (e['killed_process'] and pattern.search(e['killed_process']))]

        # Apply count limit if specified
        if op.oom_count > 0 and len(oom_events) > op.oom_count:
            oom_events = oom_events[:op.oom_count]

        # Show summary dashboard
        result_str += show_oom_summary_dashboard(oom_events, no_pipe)

        # Show pattern analysis
        result_str += analyze_oom_patterns(oom_events, no_pipe)

        # Show recommendations
        result_str += show_oom_recommendations(oom_events, no_pipe)

        return result_str

    is_first_oom = True
    page_size = get_main().page_size
    oom_event_counter = 0
    process_filter_pattern = None
    if op.process_filter:
        process_filter_pattern = build_process_filter_pattern(op.process_filter)
        if process_filter_pattern is None:
            result_str = result_str + screen.get_pipe_aware_line("Invalid filter pattern: %s\n" % op.process_filter)
            return result_str

    for file in file_list:
        if not isfile(file):
            print("Not a file : '%s'" % (file))
            continue
        file_format = detect_oom_file_format(file)
        try:
            with open(file) as f:
                result_str = result_str +\
                        screen.get_pipe_aware_line("\nChecking file %s\n" % get_sos_relative_name(file))
                oom_invoked = False
                oom_meminfo = False
                oom_cgroup_stats = False
                oom_ps_started = False
                oom_slab_started = False
                rss_index = -1
                pid_index = -1
                pname_index = -1
                oom_dict = {}
                sname_index = -1
                stotal_index = -1
                slab_dict = {}
                meminfo_dict = {}
                cgroup_dict = {}
                total_usage = 0
                for line in chain(f, [""]):
                    trim_word = '] ' if file_format == 'vmcore-dmesg' else ' kernel: '
                    if op.trim_word != "":
                        trim_word = op.trim_word
                    if op.trim_idx != 0:
                        try:
                            trim_word = line.split()[op.trim_idx + 1]
                        except:
                            pass
                    if trim_word not in line:
                        trim_word = '] '
                    trim_ends_idx = line.find(trim_word) + len(trim_word)
                    oom_line_detected = "invoked oom-killer:" in line
                    if file_format == 'vmcore-dmesg' and not oom_line_detected and not oom_invoked:
                        oom_line_detected = "Out of memory:" in line
                    if oom_line_detected:
                        # Check if we've hit the count limit
                        if op.oom_count > 0 and oom_event_counter >= op.oom_count:
                            break

                        # Check process filter
                        if process_filter_pattern:
                            invoker = extract_invoker_process(line)
                            if not process_filter_pattern.search(invoker):
                                # Skip this OOM event - wrong process
                                continue

                        oom_invoked = True
                        oom_event_counter += 1
                        if not is_first_oom:
                            line = "\n\n" + line
                        result_str = result_str + \
                                screen.get_pipe_aware_line(line.rstrip())
                        is_first_oom = False
                        continue

                    if "Out of memory: Killed process" in line:
                        if not is_first_oom:
                            line = "\n" + line
                        result_str = result_str + \
                                screen.get_pipe_aware_line(line.rstrip())
                        continue

                    # For vmcore-dmesg format, display stack trace lines after OOM event
                    if oom_invoked and file_format == 'vmcore-dmesg':
                        # Match stack trace pattern: [timestamp]  function_name+0xoffset/0xsize [module]
                        # Skip if we've hit the process table or other known sections
                        if "uid" in line and "total_vm" in line:
                            # Process table started - don't display as stack trace
                            pass
                        elif "Mem-Info:" in line or "memory: usage" in line or "Memory cgroup stats" in line:
                            # Known section started - let normal handlers process it
                            pass
                        elif re.search(r'\[[\d.]+\]\s+\S+\+0x[\da-f]+/0x[\da-f]+', line):
                            # This is a stack trace line - display it
                            result_str = result_str + \
                                    screen.get_pipe_aware_line(line.rstrip())
                            continue
                        elif re.search(r'\[[\d.]+\]\s+(CPU:|Pid:|Call Trace:)', line):
                            # This is a stack trace context line - display it
                            result_str = result_str + \
                                    screen.get_pipe_aware_line(line.rstrip())
                            continue

                    if oom_invoked:
                        if "Mem-Info:" in line:
                            oom_meminfo = True
                            continue
                        elif "memory: usage" in line:
                            line = line[trim_ends_idx:]
                            cgroup_dict["memory"] = line
                            continue
                        elif "swap: usage" in line:
                            line = line[trim_ends_idx:]
                            cgroup_dict["swap"] = line
                            continue
                        elif "Memory cgroup stats for" in line:
                            line = line[line.find(" stats for ") + 11:-2]
                            cgroup_dict["cgroup"] = line
                            oom_cgroup_stats = True
                            continue


                    if oom_meminfo:
                        if " Node " not in line and "shmem:" in line:
                            line = line[trim_ends_idx:]
                            words = line.split()
                            for entry in words:
                                try:
                                    if ':' not in entry:
                                        continue
                                    key_val = entry.split(':')
                                    meminfo_dict[key_val[0]] = get_size(key_val[1])
                                except Exception as ie:
                                    print(ie)
                            continue
                        elif " Node " not in line and " hugepages_total" in line:
                            line = line[line.find("hugepages_total="):]
                            words = line.split()
                            for entry in words:
                                try:
                                    key_val = entry.split('=')
                                    if key_val[0] != "hugepages_size":
                                        size = int(key_val[1])
                                    else:
                                        size = get_size(key_val[1])
                                        hugepages_size = size
                                    meminfo_dict[key_val[0]] = size
                                except Exception as ie:
                                    print(ie)
                            continue
                        elif " total pagecache pages" in line:
                            line = line[trim_ends_idx:]
                            words = line.split()
                            try:
                                meminfo_dict["Pagecaches"] = get_size(words[0])
                            except:
                                pass
                        elif trim_word not in line or ("%sactive_anon" % trim_word) in line:
                            line = line[trim_ends_idx:]
                            try:
                                words = line.split()
                                for word in words:
                                    key_val = word.split(':')
                                    meminfo_dict[key_val[0]] = get_size(key_val[1])
                            except: # Ignore messed log
                                pass

                    if oom_cgroup_stats:
                        if trim_word not in line or ("%sanon" % trim_word) in line:
                            line = line[trim_ends_idx:]
                            words = line.split()
                            meminfo_dict[words[0]] = get_size(words[1])

                    if oom_invoked and "Unreclaimable slab info:" in line:
                        oom_slab_started = True
                        oom_meminfo = False
                        oom_cgroup_stats = False
                        line = f.readline() # read one more line to get title line
                        line = line[trim_ends_idx:]
                        words = line.split()
                        for i in range(0, len(words)):
                            if words[i] == "Name":
                                sname_index = i
                            elif words[i] == "Total":
                                stotal_index = i

                        continue

                    if oom_slab_started:
                        if "Tasks state (memory values in pages):" in line:
                            oom_slab_started = False
                            result_str = result_str +\
                                show_oom_slab_usage(op, no_pipe, slab_dict, total_usage) +\
                                screen.get_pipe_aware_line("")
                            slab_dict = {}
                            total_usage = 0
                            continue

                        line = line[trim_ends_idx:]
                        words = line.split()
                        stotal = 0
                        if len(words) <= sname_index:
                            continue
                        try:
                            stotal = int(words[stotal_index][:-2]) * 1024
                            total_usage = total_usage + stotal
                        except:
                            pass
                        sname = words[sname_index]
                        slab_dict[sname] = stotal


                    if oom_invoked and "uid" in line and "total_vm" in line:
                        oom_ps_started = True
                        oom_meminfo = False
                        oom_cgroup_stats = False
                        line = line[trim_ends_idx:]
                        line = line.replace("[", "")
                        line = line.replace("]", "")
                        words = line.split()
                        for i in range(0, len(words)):
                            if words[i] == "rss":
                                rss_index = i
                            elif words[i] == "pid":
                                pid_index = i
                            elif words[i] == "name":
                                pname_index = i

                        continue

                    if not oom_ps_started:
                        continue

                    if oom_ps_started and "[" not in line[trim_ends_idx:]: #end of oom_ps
                        if len(cgroup_dict) > 0:
                            result_str = result_str +\
                                    screen.get_pipe_aware_line("CGroup : " + cgroup_dict["cgroup"])
                            cgroup_dict.pop("cgroup")
                            for key in cgroup_dict:
                                result_str = result_str + \
                                        screen.get_pipe_aware_line("  " + cgroup_dict[key])

                        result_str = result_str +\
                                show_oom_memory_usage(op, no_pipe, oom_dict, total_usage)
                        if op.details:
                            result_str = result_str +\
                                    show_oom_meminfo(op, no_pipe, meminfo_dict)
                        oom_invoked = False
                        oom_meminfo = False
                        oom_cgroup_stats = False
                        oom_ps_started = False
                        rss_index = -1
                        pid_index = -1
                        pname_index = -1
                        oom_dict = {}
                        meminfo_dict = {}
                        cgroup_dict = {}
                        total_usage = 0
                        continue

                    line = line[trim_ends_idx:]
                    line = line.replace("[", "")
                    line = line.replace("]", "")
                    words = line.split()
                    if len(words) <= pname_index:
                        continue
                    pid = words[pid_index]
                    try:
                        rss = int(words[rss_index]) * page_size
                        total_usage = total_usage + rss
                    except:
                        pass
                    pname = words[pname_index]
                    if op.all:
                        pname = pname + (" (%s)" % pid)
                    if pname in oom_dict:
                        rss = rss + oom_dict[pname]
                    oom_dict[pname] = rss

        except Exception as e:
            print(e)
            traceback.print_stack()


    return result_str


def show_swap_usage(op, no_pipe):
    # Get system's total memory for percentage calculation
    system_total_mem_kb = get_system_total_memory_kb()

    result_str = ""
    swap_usage_dict = {}
    total_swap = 0
    try:
        pid_list = get_file_list(sos_home + "/proc/[0-9]*", checkdir=False)
        for path in pid_list:
            try:
                with open(path + "/status") as f:
                    swap_usage = 0
                    pid = os.path.basename(path)
                    pname = ""
                    for line in f:
                        if line.startswith("VmSwap:"):
                            words = line.split()
                            swap_usage = swap_usage + int(words[1])
                        elif line.startswith("Name:"):
                            pname = line.split()[1]

                    if swap_usage > 0:
                        if op.all:
                            pname = pname + (" (%s)" % pid)
                        total_swap = total_swap + swap_usage
                        if pname in swap_usage_dict:
                            swap_usage = swap_usage + swap_usage_dict[pname]
                        swap_usage_dict[pname] = swap_usage

            except Exception as ie:
                # Ignore the case that doesn't have status
                pass
    except Exception as e:
        print(e)
        return ""

    sorted_swap_usage = sorted(swap_usage_dict.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = 10
    if (op.all):
        min_number = len(sorted_swap_usage) - 1

    print_count = min(len(sorted_swap_usage) - 1, min_number)

    # Create table with TableFormatter
    from table_formatter import TableFormatter

    show_graph = getattr(op, 'graph', False)

    # Calculate optimal column width based on terminal width and longest process name
    max_widths = get_optimal_max_widths(show_graph)
    max_pname_len = max(len(sorted_swap_usage[i][0]) for i in range(0, print_count)) if print_count > 0 else 20
    pname_width = max(20, min(max_widths['process_name'], max_pname_len + 1))
    # Disable Rich when using graphs to avoid ANSI code conflicts
    use_rich = not show_graph
    table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
    table.add_column("NAME", width=pname_width, align='left', color='yellow')
    if show_graph:
        table.add_column("Usage_Percent", width=24, align='left', color='cyan')
    table.add_column("Usage", width=15, align='right', color='red')

    for i in range(0, print_count):
        pname = sorted_swap_usage[i][0]
        # Truncate process name to fit column width
        pname = truncate_middle(pname, pname_width)
        swap_size = sorted_swap_usage[i][1] * 1024
        if show_graph:
            # Calculate percentage based on system's total memory
            percentage = (sorted_swap_usage[i][1] * 100.0 / system_total_mem_kb) if system_total_mem_kb > 0 else 0
            bar = get_memory_bar(percentage, width=20, no_pipe=no_pipe)
            table.add_row(pname, bar, get_size_str(swap_size))
        else:
            table.add_row(pname, get_size_str(swap_size))

    # Format and output table
    formatted_table = table.format()
    # NAME(dynamic) + Usage(15) + padding
    separator_width = pname_width + 15 + 4
    if show_graph:
        separator_width += 24 + 2

    if no_pipe:
        # Split table into header and data rows
        table_lines = formatted_table.split('\n')
        print("=" * separator_width)
        if len(table_lines) > 0:
            print(table_lines[0])  # Print header
            print("-" * separator_width)  # Add separator line
            for line in table_lines[1:]:  # Print data rows
                if line.strip():  # Skip empty lines
                    print(line)
        if print_count < len(sorted_swap_usage) - 1:
            print("\t<...>")
        print("=" * separator_width)
        print("Total memory usage from swap = %s" % get_size_str(total_swap * 1024))
        print("Notes) The total can be bigger than actual usage due to the shared memory")
    else:
        # Split table into header and data rows for piped output
        table_lines = formatted_table.split('\n')
        result_str = "=" * separator_width + "\n"
        if len(table_lines) > 0:
            result_str += table_lines[0] + "\n"  # Header
            result_str += "-" * separator_width + "\n"  # Separator
            for line in table_lines[1:]:  # Data rows
                if line.strip():
                    result_str += line + "\n"
        if print_count < len(sorted_swap_usage) - 1:
            result_str += "\t<...>\n"
        result_str += "=" * separator_width + "\n"
        result_str += "Total memory usage from swap = %s\n" % get_size_str(total_swap * 1024)
        result_str += "Notes) The total can be bigger than actual usage due to the shared memory\n"

    return result_str


def show_slabtop(op, no_pipe):
    # Get system's total memory for percentage calculation
    system_total_mem_kb = get_system_total_memory_kb()

    result_str = ''
    slab_list = {}
    slab_objsize = {}
    total_slab = 0
    idx_pagesperslab = -1
    idx_num_slabs = -1
    idx_objsize = -1
    try:
        with open(sos_home + '/proc/slabinfo') as f:
            result_lines = f.readlines()
            result_lines[1] = result_lines[1].replace('# name', 'name')
            result_line = result_lines[1].split()
            for i in range(1, len(result_line)):
                if "<pagesperslab>" in result_line[i]:
                    idx_pagesperslab = i
                elif "<num_slabs>" in result_line[i]:
                    idx_num_slabs = i
                elif "<objsize>" in result_line[i]:
                    idx_objsize = i

            if idx_pagesperslab == -1 or idx_num_slabs == -1:
                print("Invalid file")
                return ""

            for i in range(2, len(result_lines)):
                result_line = result_lines[i].split()
                if len(result_line) < idx_num_slabs:
                    continue
                total_used = int(result_line[idx_pagesperslab]) *\
                             int(result_line[idx_num_slabs])
                slab_list[result_line[0]] = total_used
                total_slab = total_slab + total_used
                slab_objsize[result_line[0]] = int(result_line[idx_objsize])

    except Exception as e:
        print(e)
        return ''

    sorted_slabtop = sorted(slab_list.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = 10
    if (op.all):
        min_number = len(sorted_slabtop) - 1

    print_count = min(len(sorted_slabtop) - 1, min_number)

    # Create table with TableFormatter
    from table_formatter import TableFormatter

    show_graph = getattr(op, 'graph', False)

    # Calculate optimal column width based on terminal width and longest SLAB name
    initial_terminal_width = get_terminal_width()
    max_widths = get_optimal_max_widths(show_graph)
    max_slab_len = max(len(sorted_slabtop[i][0]) for i in range(0, print_count)) if print_count > 0 else 20
    slab_width = max(20, min(max_widths['slab_name'], max_slab_len + 1))
    # Disable Rich when using graphs to avoid ANSI code conflicts
    use_rich = not show_graph
    table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
    table.add_column("NAME", width=slab_width, align='left', color='yellow')
    if show_graph:
        table.add_column("Usage_Percent", width=24, align='left', color='cyan')
    table.add_column("TOTAL", width=12, align='right', color='red')
    table.add_column("OBJSIZE", width=8, align='right', color='blue')

    page_size = get_main().page_size
    rows_added_since_check = 0
    for i in range(0, print_count):
        # Check for terminal resize every 10 rows (to avoid excessive system calls)
        if show_graph and i > 0 and rows_added_since_check >= 10:
            current_width = get_terminal_width()
            if abs(current_width - initial_terminal_width) > 5:
                # Terminal resized significantly - output current table and start new one
                # Format and output current table first
                formatted_table = table.format()
                separator_width = slab_width + 12 + 8 + 6
                if show_graph:
                    separator_width += 24 + 2

                if no_pipe:
                    table_lines = formatted_table.split('\n')
                    print("=" * separator_width)
                    if len(table_lines) > 0:
                        print(table_lines[0])
                        print("-" * separator_width)
                        for line in table_lines[1:]:
                            if line.strip():
                                print(line)
                    print("=" * separator_width)

                    # Print resize notice
                    print(colored("\n[Terminal resized - adjusting table width]\n", 'yellow'))

                # Recalculate widths and create new table
                initial_terminal_width = current_width
                max_widths = get_optimal_max_widths(show_graph)
                slab_width = max(20, min(max_widths['slab_name'], max_slab_len + 1))

                table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
                table.add_column("NAME", width=slab_width, align='left', color='yellow')
                if show_graph:
                    table.add_column("Usage_Percent", width=24, align='left', color='cyan')
                table.add_column("TOTAL", width=12, align='right', color='red')
                table.add_column("OBJSIZE", width=8, align='right', color='blue')

                rows_added_since_check = 0

        slab_name = sorted_slabtop[i][0]
        # Truncate SLAB name to fit column width
        if len(slab_name) > slab_width:
            slab_name = slab_name[:slab_width-3] + "..."
        obj_size = slab_objsize[sorted_slabtop[i][0]]  # Use original name for lookup
        slab_pages = sorted_slabtop[i][1]
        if show_graph:
            # Calculate percentage based on system's total memory
            # Convert slab_pages to KB by multiplying by page_size/1024
            slab_kb = slab_pages * page_size // 1024
            percentage = (slab_kb * 100.0 / system_total_mem_kb) if system_total_mem_kb > 0 else 0
            bar = get_memory_bar(percentage, width=20, no_pipe=no_pipe)
            table.add_row(slab_name,
                         bar,
                         get_size_str(slab_pages * page_size),
                         str(obj_size))
        else:
            table.add_row(slab_name,
                         get_size_str(slab_pages * page_size),
                         str(obj_size))

        rows_added_since_check += 1

    # Format and output table
    formatted_table = table.format()
    # NAME(dynamic) + TOTAL(12) + OBJSIZE(8) + padding
    separator_width = slab_width + 12 + 8 + 6
    if show_graph:
        separator_width += 24 + 2

    if no_pipe:
        # Split table into header and data rows
        table_lines = formatted_table.split('\n')
        print("=" * separator_width)
        if len(table_lines) > 0:
            print(table_lines[0])  # Print header
            print("-" * separator_width)  # Add separator line
            for line in table_lines[1:]:  # Print data rows
                if line.strip():  # Skip empty lines
                    print(line)
        if print_count < len(sorted_slabtop) - 1:
            print("\t<...>")
        print("=" * separator_width)
        print("Total memory usage from SLAB = %s" % get_size_str(total_slab * page_size))

        # Show total usage percentage with bar graph
        if system_total_mem_kb > 0:
            slab_kb = total_slab * page_size // 1024
            total_percentage = (slab_kb * 100.0 / system_total_mem_kb)
            system_total_mem_bytes = system_total_mem_kb * 1024
            print("\tNotes) %.2f percent from total system memory(%s)" %
                  (total_percentage, get_size_str(system_total_mem_bytes)))
            if show_graph:
                bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
                print("\t       %s" % bar)
    else:
        # Split table into header and data rows for piped output
        table_lines = formatted_table.split('\n')
        result_str = "=" * separator_width + "\n"
        if len(table_lines) > 0:
            result_str += table_lines[0] + "\n"  # Header
            result_str += "-" * separator_width + "\n"  # Separator
            for line in table_lines[1:]:  # Data rows
                if line.strip():
                    result_str += line + "\n"
        if print_count < len(sorted_slabtop) - 1:
            result_str += "\t<...>\n"
        result_str += "=" * separator_width + "\n"
        result_str += "Total memory usage from SLAB = %s\n" % get_size_str(total_slab * page_size)

    return result_str


def show_ps_memusage(op, no_pipe):
    from table_formatter import TableFormatter
    import sys

    # Get system's total memory for percentage calculation
    system_total_mem_kb = get_system_total_memory_kb()

    result_str = ''
    mem_usage_dict = {}
    total_rss = 0

    # Check if ps file exists
    ps_file = sos_home + '/ps'
    if not isfile(ps_file):
        if no_pipe:
            print("ps file not found: %s" % ps_file)
        return ""

    try:
        with open(ps_file) as f:
            result_lines = f.readlines()

        if len(result_lines) < 2:
            if no_pipe:
                print("ps file is empty or has no data")
            return ""

        for i in range(1, len(result_lines)):
            result_line = result_lines[i].split()
            # Check length first before accessing elements
            if len(result_line) < 11:
                continue
            if result_line[5] == "-":
                continue
            pid = result_line[1]
            if op.all:
                pname = "%s (%s)" % (result_line[10], pid)
            else:
                pname = result_line[10]
            try:
                rss = int(result_line[5])
            except ValueError:
                continue
            total_rss = total_rss + rss
            if pname in mem_usage_dict:
                rss = mem_usage_dict[pname] + rss

            if rss != 0:
                mem_usage_dict[pname] = rss

    except Exception as e:
        print("Error reading ps file: %s" % str(e))
        return ""

    # Check if we have any data
    if not mem_usage_dict:
        if no_pipe:
            print("No valid process data found in ps file")
        return ""

    sorted_usage = sorted(mem_usage_dict.items(),
            key=operator.itemgetter(1), reverse=True)

    min_number = 10
    if (op.all):
        min_number = len(sorted_usage) - 1

    print_count = min(len(sorted_usage) - 1, min_number)

    if print_count <= 0:
        if no_pipe:
            print("No processes to display")
        return ""

    # Create table with TableFormatter
    show_graph = getattr(op, 'graph', False)

    # Calculate optimal column width based on terminal width and longest process name
    initial_terminal_width = get_terminal_width()
    max_widths = get_optimal_max_widths(show_graph)
    max_pname_len = max(len(sorted_usage[i][0]) for i in range(0, print_count))
    pname_width = max(20, min(max_widths['process_name'], max_pname_len + 1))
    # Disable Rich when using graphs to avoid ANSI code conflicts
    use_rich = not show_graph
    table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
    table.add_column("Process_Name", width=pname_width, align='left', color='yellow')
    if show_graph:
        table.add_column("Usage_Percent", width=24, align='left', color='cyan')
    table.add_column("RSS_Usage", width=15, align='right', color='red')

    rows_added_since_check = 0
    for i in range(0, print_count):
        # Check for terminal resize every 10 rows (to avoid excessive system calls)
        if show_graph and i > 0 and rows_added_since_check >= 10:
            current_width = get_terminal_width()
            if abs(current_width - initial_terminal_width) > 5:
                # Terminal resized significantly - output current table and start new one
                # Format and output current table first
                formatted_table = table.format()
                separator_width = pname_width + 15 + 4
                if show_graph:
                    separator_width += 24 + 2

                if no_pipe:
                    table_lines = formatted_table.split('\n')
                    print("=" * separator_width)
                    if len(table_lines) > 0:
                        print(table_lines[0])
                        print("-" * separator_width)
                        for line in table_lines[1:]:
                            if line.strip():
                                print(line)
                    print("=" * separator_width)

                    # Print resize notice
                    print(colored("\n[Terminal resized - adjusting table width]\n", 'yellow'))

                # Recalculate widths and create new table
                initial_terminal_width = current_width
                max_widths = get_optimal_max_widths(show_graph)
                pname_width = max(20, min(max_widths['process_name'], max_pname_len + 1))

                table = TableFormatter(no_pipe=no_pipe, use_rich=use_rich, show_header=True, padding=1)
                table.add_column("Process_Name", width=pname_width, align='left', color='yellow')
                if show_graph:
                    table.add_column("Usage_Percent", width=24, align='left', color='cyan')
                table.add_column("RSS_Usage", width=15, align='right', color='red')

                rows_added_since_check = 0

        pname = sorted_usage[i][0]
        # Truncate process name to fit column width
        pname = truncate_middle(pname, pname_width)
        rss_kb = sorted_usage[i][1]
        if show_graph:
            # Calculate percentage based on system's total memory
            percentage = (rss_kb * 100.0 / system_total_mem_kb) if system_total_mem_kb > 0 else 0
            bar = get_memory_bar(percentage, width=20, no_pipe=no_pipe)
            table.add_row(pname, bar, get_size_str(rss_kb * 1024))
        else:
            table.add_row(pname, get_size_str(rss_kb * 1024))

        rows_added_since_check += 1

    # Format and output table
    formatted_table = table.format()
    # Calculate separator width based on columns
    # Process_Name(dynamic) + Graph(24 if shown) + RSS_Usage(15) + padding between columns
    separator_width = pname_width + 15 + 4  # 4 = 2 spaces padding on each side
    if show_graph:
        separator_width += 24 + 2  # Graph column + padding

    if no_pipe:
        # Split table into header and data rows
        table_lines = formatted_table.split('\n')
        print("=" * separator_width)
        if len(table_lines) > 0:
            print(table_lines[0])  # Print header
            print("-" * separator_width)  # Add separator line
            for line in table_lines[1:]:  # Print data rows
                if line.strip():  # Skip empty lines
                    print(line)
        if print_count < len(sorted_usage) - 1:
            print("\t<...>")
        print("=" * separator_width)
        print("Total memory usage from user-space = %s" % get_size_str(total_rss * 1024))
        try:
            total_mem = 0
            with open(sos_home + "/proc/meminfo") as f:
                for line in f:
                    if "MemTotal:" in line:
                        total_mem = int(line.split()[1])
                        total_percentage = (total_rss * 100 / total_mem) if total_mem > 0 else 0
                        total_mem_bytes = total_mem * 1024
                        print("\tNotes) %.2f percent from total system memory(%s)" % \
                                (total_percentage, get_size_str(total_mem_bytes)))
                        if show_graph:
                            from ansicolor import get_color, CYAN, RESET
                            bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
                            print("\t       %s" % bar)
                        break
        except:
            pass
        sys.stdout.flush()
        result_str = ""
    else:
        # Split table into header and data rows for piped output
        table_lines = formatted_table.split('\n')
        result_str = "=" * separator_width + "\n"
        if len(table_lines) > 0:
            result_str += table_lines[0] + "\n"  # Header
            result_str += "-" * separator_width + "\n"  # Separator
            for line in table_lines[1:]:  # Data rows
                if line.strip():
                    result_str += line + "\n"
        if print_count < len(sorted_usage) - 1:
            result_str += "\t<...>\n"
        result_str += "=" * separator_width + "\n"
        result_str += "Total memory usage from user-space = %s\n" % get_size_str(total_rss * 1024)
        try:
            total_mem = 0
            with open(sos_home + "/proc/meminfo") as f:
                for line in f:
                    if "MemTotal:" in line:
                        total_mem = int(line.split()[1])
                        total_percentage = (total_rss * 100 / total_mem) if total_mem > 0 else 0
                        total_mem_bytes = total_mem * 1024
                        result_str += "\tNotes) %.2f percent from total system memory(%s)\n" % \
                                (total_percentage, get_size_str(total_mem_bytes))
                        if show_graph:
                            bar = get_memory_bar(total_percentage, width=TOTAL_BAR_WIDTH, no_pipe=no_pipe)
                            result_str += "\t       %s\n" % bar
                        break
        except:
            pass

    return result_str


def print_process_help_msg(no_pipe):
    msg = '''meminfo / meminfo -p  --  Process Memory Usage

SYNOPSIS
    meminfo [-p] [OPTIONS]

DESCRIPTION
    Shows per-process RSS (Resident Set Size) sorted by memory consumption,
    read from the sosreport's /ps file.  This is the default mode when no
    other sub-command flag is given.

OPTIONS
    -p, --process
        Enable process memory mode (default when no other flag is given).

    -a, --all
        Show all processes including those with PID appended to name.

    -g, --graph
        Add ASCII bar-chart column showing each process's share of total RAM.

    -d, --details
        Show additional detail per process.

    -h, --help
        Show this help message.

EXAMPLES
    # Default: top RSS consumers
    example.com> meminfo

    # All processes with bar charts
    example.com> meminfo -ag

    # Show details per process
    example.com> meminfo -pd
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_slab_help_msg(no_pipe):
    msg = '''meminfo -s  --  SLAB Memory Usage

SYNOPSIS
    meminfo -s [OPTIONS]

DESCRIPTION
    Shows kernel SLAB/SLUB memory usage per cache, parsed from
    /proc/slabinfo in the sosreport.  Equivalent to slabtop but
    reads from the captured snapshot rather than a live system.

OPTIONS
    -s, --slab
        Enable SLAB memory mode.

    -a, --all
        Show all SLAB caches, not just the top N.

    -g, --graph
        Add ASCII bar-chart column showing each cache's share of total RAM.

    -h, --help
        Show this help message.

EXAMPLES
    # Top SLAB consumers
    example.com> meminfo -s

    # All caches with bar charts
    example.com> meminfo -sag

    # Bar chart for top caches
    example.com> meminfo -sg
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_balloon_help_msg(no_pipe):
    msg = '''meminfo -b  --  Memory Balloon (VM)

SYNOPSIS
    meminfo -b

DESCRIPTION
    Shows VMware memory balloon information for virtual machine guests.
    Reads balloon target and current page counts from:

        sys/kernel/debug/vmmemctl

    This file is only present in sosreports collected from VMware guests
    with the vmware-tools / open-vm-tools balloon driver active.

OPTIONS
    -b, --balloon
        Enable balloon memory mode.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> meminfo -b
    VMware VM
    Target  : 131072 pages (512.0 MiB)
    Current : 98304 pages (384.0 MiB)
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_overall_help_msg(no_pipe):
    msg = '''meminfo --overall  --  Overall Memory Breakdown

SYNOPSIS
    meminfo --overall

DESCRIPTION
    Shows a full memory usage breakdown with ASCII bar graphs covering:

        MemTotal, MemFree, MemAvailable
        Buffers, Cached, SwapCached
        Active/Inactive (anon + file)
        Slab (reclaimable + unreclaimable)
        PageTables, Dirty, Writeback
        HugePages (if configured)

    Parsed from /proc/meminfo in the sosreport.

    Additionally, if OOM killer events are found in the logs
    (var/log/messages, sos_commands/logs/journalctl, var/log/dmesg),
    a summary of OOM activity is automatically appended.

OPTIONS
    --overall
        Enable overall memory breakdown mode.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> meminfo --overall
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_swap_help_msg(no_pipe):
    msg = '''meminfo -w  --  Swap Usage per Process

SYNOPSIS
    meminfo -w [OPTIONS]

DESCRIPTION
    Shows per-process swap usage sorted by VmSwap size, read from
    /proc/<pid>/status files captured in the sosreport.

OPTIONS
    -w, --swap
        Enable swap usage mode.

    -a, --all
        Show process name with PID appended (e.g. "java (1234)") instead
        of grouping all PIDs of the same name together.

    -g, --graph
        Add ASCII bar-chart column for each process's swap share.

    -h, --help
        Show this help message.

EXAMPLES
    # Per-process swap consumers
    example.com> meminfo -w

    # Show each PID individually with bar chart
    example.com> meminfo -wag
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_oom_help_msg(no_pipe):
    msg = '''meminfo -O  --  OOM Killer Event Analysis

SYNOPSIS
    meminfo -O [OPTIONS] [FILE ...]

DESCRIPTION
    Scans log files for OOM killer events and displays per-event memory usage
    breakdowns, sorted by process RSS at the time of the kill.

    If no FILE is given, the following paths are searched automatically
    (in order, inside the sosreport root):

        var/log/messages*
        sos_commands/logs/journalctl*
        var/log/dmesg*
        var/log/vmcore-dmesg.txt*
        *vmcore-dmesg.txt*   (top-level)

    Both syslog format and vmcore-dmesg (bracketed timestamp) format are
    auto-detected per file.

OPTIONS
    -O, --oom
        Enable OOM event analysis mode.

    --oom-summary
        Show a dashboard summarising all OOM events: total count, date range,
        top invoking processes, and pattern analysis.

    --oom-count N
        Display at most N OOM events (default: all).

    --oom-top N
        Show top N memory consumers per event (default: 10).

    --process-filter PATTERN
        Restrict output to events whose invoker or killed process matches
        PATTERN.  Accepts a plain name, comma-separated names, or a regex.

    -g, --graph
        Add ASCII bar-chart columns to the per-process memory table.

    -a, --all
        Show all processes, not just the top N.

    -h, --help
        Show this help message.

EXAMPLES
    # All OOM events from default log files
    example.com> meminfo -O

    # OOM events from a specific file
    example.com> meminfo -O /path/to/vmcore-dmesg.txt

    # Summary dashboard
    example.com> meminfo -O --oom-summary

    # Only java-related events, capped at 20
    example.com> meminfo -O --process-filter java --oom-count 20

    # Top 30 consumers per event with bar charts
    example.com> meminfo -O --oom-top 30 -g
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
    It shows memory usage from process / slab.

Examples)
    To see process memory usage with bar chart visualization:

    example.com> meminfo -g
    example.com> meminfo -ag

    To see oom events, you can specify log name or default file (/var/log/messages)
    will be used.

    example.com> meminfo -O
    Nov  9 01:12:50 example.com kernel: https-jsse-nio- invoked oom-killer: ...
    ==========================================================
    NAME                                               Usage
    ==========================================================
    java                                            11.2 GiB
    nft                                              1.3 GiB
    ...
        <...>
    ==========================================================
    Total memory usage from processes = 14.0 GiB

    To see OOM summary dashboard with pattern analysis:

    example.com> meminfo -O --oom-summary
    ================================================================================
                           OOM KILLER SUMMARY DASHBOARD
    ================================================================================
      Total OOM Events: 524
      Date Range: Feb 22 10:15 to Feb 24 14:30 (52.3 hours)

    TOP INVOKING PROCESSES                           COUNT  PERCENTAGE
    ========================================================================
    apache                                              178       34.0%
    java                                               145       27.7%
    ...

    To filter OOM events by process name (comma-separated for multiple):

    example.com> meminfo -O --process-filter "apache"
    example.com> meminfo -O --process-filter "java,python,VM"

    Advanced regex patterns also work:

    example.com> meminfo -O --process-filter "java.*"

    To limit the number of events shown:

    example.com> meminfo -O --oom-count 5
    example.com> meminfo -O --oom-summary --oom-count 100

    To control how many top memory consumers are shown per event:

    example.com> meminfo -O --oom-top 20

    vmcore-dmesg.txt format is also supported (kernel dmesg captured before crash):

    example.com> meminfo -O /path/to/vmcore-dmesg.txt
    Format: [342389.669262] process invoked oom-killer: ...
    The file is also auto-detected in the sosreport under var/log/vmcore-dmesg.txt.

    To show OOM events with bar chart visualization:

    example.com> meminfo -Og
    example.com> meminfo -Oag --oom-count 5

    To show SLAB memory usage with bar chart:

    example.com> meminfo -sg
    '''

    if no_pipe == False:
        output = StringIO.StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()

        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""

sos_home=""
is_cmd_stopped = None


def get_meminfo_dict():
    """
    Parse /proc/meminfo from sosreport into a dictionary.

    Returns:
        dict: Dictionary with meminfo keys and values in KB
    """
    global sos_home
    meminfo = {}

    try:
        with open(sos_home + "/proc/meminfo") as f:
            for line in f:
                if ':' in line:
                    parts = line.split(':')
                    key = parts[0].strip()
                    value_str = parts[1].strip().split()[0]
                    try:
                        meminfo[key] = int(value_str)
                    except:
                        pass
    except:
        pass

    return meminfo


def show_overall_memory(options, no_pipe):
    """
    Show overall memory usage breakdown with bar graphs
    Similar to pycrashext's meminfo --overall
    """
    global sos_home

    result_str = ""

    # Check if there are any OOM events in the log first
    # If found, automatically display OOM analysis (similar to pycrashext)
    try:
        file_list = get_file_list(sos_home + "/var/log/messages*", False)
        file_list = file_list + get_file_list(sos_home + "/sos_commands/logs/journalctl*", False)
        file_list = file_list + get_file_list(sos_home + "/var/log/dmesg*", False)

        # Count total OOM events across all files
        total_oom_events = 0
        files_with_oom = []
        for file in file_list:
            if not os.path.isfile(file):
                continue
            try:
                file_oom_count = 0
                with open(file) as f:
                    for line in f:
                        if "invoked oom-killer:" in line:
                            total_oom_events += 1
                            file_oom_count += 1
                if file_oom_count > 0:
                    files_with_oom.append((file, file_oom_count))
            except:
                pass

        if total_oom_events > 0:
            # Create a copy of options for OOM display
            import copy

            # Process each file that has OOM events, showing one event per file
            for file, count in files_with_oom:
                # Display separator for this file
                result_str += screen.get_pipe_aware_line("\n")
                result_str += screen.get_pipe_aware_line("=" * 80)
                if count > 1:
                    result_str += screen.get_pipe_aware_line("OOM EVENTS DETECTED in %s - %d events found,\n showing first one" %
                                                              (os.path.basename(file), count))
                else:
                    result_str += screen.get_pipe_aware_line("OOM EVENTS DETECTED in %s - Displaying OOM Analysis" %
                                                              os.path.basename(file))
                result_str += screen.get_pipe_aware_line("=" * 80)

                # Create options for this file with count=1
                file_options = copy.copy(options)
                file_options.graph = True
                file_options.oom_count = 1

                args_list = ['meminfo', file]
                result_str += show_oom_events(file_options, args_list, no_pipe)
                result_str += screen.get_pipe_aware_line("")
    except Exception as e:
        # Silently ignore errors in OOM detection to not break --overall display
        pass

    # Header
    result_str += screen.get_pipe_aware_line("\n" + "=" * 80)
    result_str += screen.get_pipe_aware_line("OVERALL MEMORY USAGE BREAKDOWN")
    result_str += screen.get_pipe_aware_line("=" * 80)

    # Parse /proc/meminfo
    meminfo = get_meminfo_dict()

    # Storage for memory categories
    mem_categories = {}

    # Get total memory
    total_mem_kb = meminfo.get('MemTotal', 0)

    if total_mem_kb == 0:
        result_str += screen.get_pipe_aware_line("\nError: Could not determine total system memory")
        return result_str

    # Extract memory categories from meminfo dict
    if 'MemFree' in meminfo and meminfo['MemFree'] > 0:
        mem_categories['Free'] = meminfo['MemFree']

    if 'Buffers' in meminfo and meminfo['Buffers'] > 0:
        mem_categories['Buffers'] = meminfo['Buffers']

    if 'Cached' in meminfo and meminfo['Cached'] > 0:
        mem_categories['Cached'] = meminfo['Cached']

    if 'Slab' in meminfo and meminfo['Slab'] > 0:
        mem_categories['Slab'] = meminfo['Slab']

    # Calculate HugePages total allocated (not just used)
    if 'HugePages_Total' in meminfo and 'Hugepagesize' in meminfo:
        huge_total = meminfo['HugePages_Total']
        huge_pagesize_kb = meminfo['Hugepagesize']
        if huge_total > 0:
            hugepages_total_kb = huge_total * huge_pagesize_kb
            if hugepages_total_kb > 0:
                mem_categories['HugePages'] = hugepages_total_kb

    # Get user-space memory usage from ps output
    user_space_kb = 0
    try:
        ps_file = sos_home + "/ps"
        if os.path.isfile(ps_file):
            with open(ps_file) as f:
                for line in f:
                    words = line.split()
                    if len(words) < 6:
                        continue

                    # Check if this looks like a ps output line (PID is numeric)
                    # In ps aux format: USER PID %CPU %MEM VSZ RSS ...
                    # PID is in column 1 (0-indexed)
                    if len(words) > 1 and not words[1].isdigit():
                        continue

                    try:
                        # RSS is in column 5 (0-indexed) in ps aux format
                        # Format: USER PID %CPU %MEM VSZ RSS ...
                        rss_kb = int(words[5])
                        user_space_kb += rss_kb
                    except (ValueError, IndexError):
                        continue
    except:
        pass

    # Store user-space in categories
    if user_space_kb > 0:
        mem_categories['User-Space'] = user_space_kb

    # Calculate kernel space (everything else)
    accounted_kb = sum(mem_categories.values())
    kernel_other_kb = total_mem_kb - accounted_kb

    if kernel_other_kb > 0:
        mem_categories['Kernel-Other'] = kernel_other_kb
    elif kernel_other_kb < 0:
        result_str += screen.get_pipe_aware_line("\nWarning: Memory accounting shows negative Kernel-Other")
        result_str += screen.get_pipe_aware_line("This may indicate shared memory among applications or parsing errors")

    # Sort categories by size (descending)
    sorted_categories = sorted(mem_categories.items(), key=lambda x: x[1], reverse=True)

    # Display header
    result_str += screen.get_pipe_aware_line("\nTotal System Memory: %s\n" % get_size_str(total_mem_kb * 1024))

    # Column headers
    header_format = "%-15s %11s %8s  %s"
    result_str += screen.get_pipe_aware_line(header_format % ("Category", "Size", "Percent", "Usage Bar"))
    result_str += screen.get_pipe_aware_line("-" * 80)

    # Display each category with bar graph
    for category, size_kb in sorted_categories:
        percentage = (size_kb * 100.0 / total_mem_kb) if total_mem_kb > 0 else 0
        size_str = get_size_str(size_kb * 1024)
        bar = get_memory_bar(percentage, TOTAL_BAR_WIDTH, no_pipe)

        line = "%-15s %11s %7.2f%%  %s" % (category, size_str, percentage, bar)
        result_str += screen.get_pipe_aware_line(line)

    result_str += screen.get_pipe_aware_line("-" * 80)

    # Summary
    result_str += screen.get_pipe_aware_line("\nMemory Accounting:")
    result_str += screen.get_pipe_aware_line("  Total Accounted: %s (%.2f%%)" %
          (get_size_str(accounted_kb * 1024),
           (accounted_kb * 100.0 / total_mem_kb) if total_mem_kb > 0 else 0))

    # Additional details
    result_str += screen.get_pipe_aware_line("\nKey Categories:")

    category_descriptions = {
        'User-Space': 'Application/process memory (RSS from all tasks)',
        'Slab': 'Kernel slab allocator cache',
        'HugePages': 'Huge pages allocated (total)',
        'Cached': 'Page cache (file-backed pages)',
        'Buffers': 'Buffer cache',
        'Free': 'Available free memory',
        'Kernel-Other': 'Kernel memory (page tables, stacks, vmalloc, etc.)'
    }

    for category, size_kb in sorted_categories:
        if category in category_descriptions:
            result_str += screen.get_pipe_aware_line("  %-15s : %s" % (category, category_descriptions[category]))

    # Show HugePages allocation vs actual usage breakdown
    if 'HugePages_Total' in meminfo and 'Hugepagesize' in meminfo:
        hp_total = meminfo.get('HugePages_Total', 0)
        hp_free = meminfo.get('HugePages_Free', 0)
        hp_rsvd = meminfo.get('HugePages_Rsvd', 0)
        hp_surp = meminfo.get('HugePages_Surp', 0)
        hp_size_kb = meminfo.get('Hugepagesize', 0)

        if hp_total > 0:
            hp_used = hp_total - hp_free

            # Calculate sizes in KB
            hp_total_kb = hp_total * hp_size_kb
            hp_used_kb = hp_used * hp_size_kb
            hp_free_kb = hp_free * hp_size_kb
            hp_rsvd_kb = hp_rsvd * hp_size_kb
            hp_surp_kb = hp_surp * hp_size_kb

            # Calculate percentages
            used_percent = (hp_used * 100.0 / hp_total) if hp_total > 0 else 0
            free_percent = (hp_free * 100.0 / hp_total) if hp_total > 0 else 0

            result_str += screen.get_pipe_aware_line("\n" + "=" * 80)
            result_str += screen.get_pipe_aware_line("HUGEPAGES ALLOCATION vs USAGE")
            result_str += screen.get_pipe_aware_line("=" * 80)

            # Bar graph showing used vs free
            bar_width = 60
            bar = get_memory_bar(used_percent, bar_width, no_pipe)

            result_str += screen.get_pipe_aware_line("\nUtilization:")
            result_str += screen.get_pipe_aware_line(bar)

            # Legend
            result_str += screen.get_pipe_aware_line("  █ Used: %s (%.2f%%)    ░ Free: %s (%.2f%%)" %
                (get_size_str(hp_used_kb * 1024), used_percent,
                 get_size_str(hp_free_kb * 1024), free_percent))

            # Total allocated
            result_str += screen.get_pipe_aware_line("  Total Allocated: %s (%d pages)" %
                (get_size_str(hp_total_kb * 1024), hp_total))

            # Page size info
            result_str += screen.get_pipe_aware_line("\nHugePage Size: %s" % get_size_str(hp_size_kb * 1024))

            # Reserved and Surplus (if any)
            if hp_rsvd > 0:
                result_str += screen.get_pipe_aware_line("Reserved: %d pages (%s)" %
                    (hp_rsvd, get_size_str(hp_rsvd_kb * 1024)))
            if hp_surp > 0:
                result_str += screen.get_pipe_aware_line("Surplus: %d pages (%s)" %
                    (hp_surp, get_size_str(hp_surp_kb * 1024)))

    result_str += screen.get_pipe_aware_line("\n" + "=" * 80)

    return result_str


def run_meminfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home

    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options] [file names]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-a', '--all', dest='all', action='store_true',
                  help='Show all entries')

    op.add_option('-b', '--balloon', dest='balloon', action='store_true',
                  help='Show memory balloon')

    op.add_option('-d', '--details', dest='details', action='store_true',
                  help='Show further details')

    op.add_option('-g', '--graph', dest='graph', action='store_true',
                  default=False,
                  help='Show bar chart for memory usage visualization')

    op.add_option('-O', '--oom', dest='oom', action='store_true',
                  help='Shows OOM events')

    op.add_option('--overall', dest='overall', action='store_true',
                  help='Show overall memory usage breakdown with bar graphs')

    op.add_option('--oom-summary', dest='oom_summary', action='store_true',
                  help='Show OOM summary dashboard with pattern analysis')

    op.add_option('--process-filter', dest='process_filter', default="",
                  action='store', type="string",
                  help='Filter OOM events by process name (comma-separated or regex)')

    op.add_option('--oom-count', dest='oom_count', default=0,
                  action='store', type="int",
                  help='Limit number of OOM events to display')

    op.add_option('--oom-top', dest='oom_top', default=10,
                  action='store', type="int",
                  help='Show top N memory consumers (default: 10)')

    op.add_option('-p', '--process', dest='process', action='store_true',
                  help='Shows process memory usage (default)')

    op.add_option('-s', '--slab', dest='slab', action='store_true',
                  help='Shows slabtop')

    op.add_option('-t', '--trim_word', dest='trim_word', default="",
            action='store', type="string",
            help="trim word to skip certain words in line")

    op.add_option('-T', '--trim_idx', dest='trim_idx', default=0,
            action='store', type="int",
            help="trim index to skip certain words in line")

    op.add_option("-w", "--swap", dest="swapshow", default=0,
                  action="store_true",
                  help="Show swap usage")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        if o.oom:
            return print_oom_help_msg(no_pipe)
        elif o.slab:
            return print_slab_help_msg(no_pipe)
        elif o.balloon:
            return print_balloon_help_msg(no_pipe)
        elif o.overall:
            return print_overall_help_msg(no_pipe)
        elif o.swapshow:
            return print_swap_help_msg(no_pipe)
        elif o.process:
            return print_process_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)
    
    result_str = ""
    sos_home = env_vars['sos_home']

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str = ""
    if o.overall:
        result_str = show_overall_memory(o, no_pipe)
    elif o.slab: # show slabtop
        result_str = show_slabtop(o, no_pipe)
    elif o.balloon:
        result_str = show_mem_balloon(o, no_pipe)
    elif o.oom:
        result_str = show_oom_events(o, args, no_pipe)
    elif o.swapshow:
        result_str = show_swap_usage(o, no_pipe)
    elif o.process:
        result_str = show_ps_memusage(o, no_pipe)
    else: # default: process list
        result_str = show_ps_memusage(o, no_pipe)

    return result_str
