"""
Cgroup Information Command

Displays cgroup (control groups) information from sosreports including:
- Cgroup version detection (v1, v2, hybrid)
- Memory usage and limits per cgroup
- CPU quotas and throttling
- OOM events and statistics
- Systemd cgroup hierarchy
"""

import sys
import os
from os.path import isfile, isdir, exists, join
from optparse import OptionParser
from io import StringIO
import re
from collections import defaultdict

import ansicolor
import screen
from cmd_helpers import (
    ColorManager, OutputBuilder, format_bytes,
    calculate_percentage, get_sos_file_path
)


def description():
    return "Shows cgroup (v1/v2) related information"


def add_command():
    return True


def get_command_info():
    return {"cginfo": run_cginfo}


# Constants
CGROUP_V2_MAX_LIMIT = 9223372036854771712
SIZE_1MB = 1048576


def detect_cgroup_version(sos_home):
    """
    Detect if system uses cgroup v1, v2, or hybrid.

    Args:
        sos_home: Root of sosreport

    Returns:
        String: "v1", "v2", "hybrid", or "unknown"
    """
    mounts_path = get_sos_file_path(sos_home, "proc", "mounts")

    has_cgroup_v1 = False
    has_cgroup_v2 = False

    try:
        with open(mounts_path, 'r') as f:
            for line in f:
                if "cgroup2" in line or "cgroup /sys/fs/cgroup cgroup2" in line:
                    has_cgroup_v2 = True
                elif "cgroup " in line and "/sys/fs/cgroup/" in line:
                    has_cgroup_v1 = True
    except (IOError, OSError):
        pass

    if has_cgroup_v2 and has_cgroup_v1:
        return "hybrid"
    elif has_cgroup_v2:
        return "v2"
    elif has_cgroup_v1:
        return "v1"
    else:
        return "unknown"


def get_cgroup_controllers(sos_home):
    """
    Get list of cgroup controllers from /proc/cgroups.

    Args:
        sos_home: Root of sosreport

    Returns:
        List of dicts with controller information
    """
    cgroups_path = get_sos_file_path(sos_home, "proc", "cgroups")
    controllers = []

    try:
        with open(cgroups_path, 'r') as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    controllers.append({
                        'name': parts[0],
                        'hierarchy': parts[1],
                        'num_cgroups': parts[2],
                        'enabled': parts[3] == '1'
                    })
    except (IOError, OSError):
        pass

    return controllers


def show_cgroup_version(sos_home, colors, output):
    """
    Show cgroup version and controllers.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    version = detect_cgroup_version(sos_home)

    output.add_colored_line("=== Cgroup Version ===", colors.cyan, colors.reset)
    output.add_line("Version: %s" % version.upper())

    # Show controllers
    controllers = get_cgroup_controllers(sos_home)
    if controllers:
        output.add_line("")
        output.add_colored_line("=== Controllers ===", colors.yellow, colors.reset)
        output.add_line("%-15s %-10s %-12s %s" %
                       ("Name", "Hierarchy", "Num CGroups", "Enabled"))
        output.add_line("-" * 50)

        for ctrl in controllers:
            if output.no_pipe:
                enabled_str = (colors.green + "Yes" + colors.reset if ctrl['enabled']
                             else colors.red + "No" + colors.reset)
            else:
                enabled_str = "Yes" if ctrl['enabled'] else "No"

            output.add_line("%-15s %-10s %-12s %s" % (
                ctrl['name'], ctrl['hierarchy'], ctrl['num_cgroups'], enabled_str))


def show_systemd_hierarchy(sos_home, colors, output):
    """
    Show systemd cgroup hierarchy.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    cgls_path = get_sos_file_path(sos_home, "sos_commands", "cgroups", "systemd-cgls")

    if not exists(cgls_path):
        output.add_line("systemd-cgls output not found")
        return

    output.add_colored_line("=== Systemd Cgroup Hierarchy ===", colors.cyan, colors.reset)
    output.add_line("")

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    try:
        with open(cgls_path, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    return

                line = screen.get_colored_line(line.rstrip())
                output.add_line(line)
    except (IOError, OSError):
        output.add_line("Error reading systemd-cgls output")


def get_memory_cgroups(sos_home):
    """
    Get memory usage for all cgroups.

    Args:
        sos_home: Root of sosreport

    Returns:
        List of dicts with path, usage, limit, percentage
    """
    memory_base = get_sos_file_path(sos_home, "sys", "fs", "cgroup", "memory")

    if not isdir(memory_base):
        return []

    cgroups = []

    # Walk through memory cgroup hierarchy
    for root, dirs, files in os.walk(memory_base):
        usage_file = join(root, "memory.usage_in_bytes")
        limit_file = join(root, "memory.limit_in_bytes")

        if exists(usage_file) and exists(limit_file):
            try:
                with open(usage_file, 'r') as f:
                    usage = int(f.read().strip())
                with open(limit_file, 'r') as f:
                    limit = int(f.read().strip())

                # Skip if usage is negligible (< 1MB)
                if usage < SIZE_1MB:
                    continue

                # Get relative path
                rel_path = root.replace(memory_base, "") or "/"

                # Calculate percentage
                percentage = calculate_percentage(usage, limit) if limit < CGROUP_V2_MAX_LIMIT else 0.0

                cgroups.append({
                    'path': rel_path,
                    'usage': usage,
                    'limit': limit,
                    'percentage': percentage
                })
            except (ValueError, IOError, OSError):
                pass

    return cgroups


def show_memory_cgroups(sos_home, colors, output, top_only=False):
    """
    Show memory usage for cgroups.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
        top_only: Show only top 20 consumers
    """
    cgroups = get_memory_cgroups(sos_home)

    if not cgroups:
        output.add_line("No memory cgroup information found")
        return

    # Sort by usage
    cgroups.sort(key=lambda x: x['usage'], reverse=True)

    if top_only:
        cgroups = cgroups[:20]

    output.add_colored_line("=== Memory Cgroup Usage ===", colors.cyan, colors.reset)
    output.add_line("")
    output.add_line("%-60s %12s %12s %8s" %
                   ("Path", "Usage", "Limit", "Percent"))
    output.add_line("-" * 95)

    for cg in cgroups:
        if is_cmd_stopped():
            break

        limit_str = ("unlimited" if cg['limit'] >= CGROUP_V2_MAX_LIMIT
                    else format_bytes(cg['limit']))
        percent_str = "%.1f%%" % cg['percentage'] if cg['percentage'] > 0 else "N/A"

        # Color code based on usage threshold
        if output.no_pipe:
            color = colors.get_threshold_color(cg['percentage'], critical=90, warning=70)
            if color:
                output.add_line("%-60s %12s %12s %s%8s%s" % (
                    cg['path'], format_bytes(cg['usage']), limit_str,
                    color, percent_str, colors.reset))
            else:
                output.add_line("%-60s %12s %12s %8s" % (
                    cg['path'], format_bytes(cg['usage']), limit_str, percent_str))
        else:
            output.add_line("%-60s %12s %12s %8s" % (
                cg['path'], format_bytes(cg['usage']), limit_str, percent_str))


def get_cpu_cgroups(sos_home):
    """
    Get CPU quota information for cgroups.

    Args:
        sos_home: Root of sosreport

    Returns:
        List of dicts with CPU quota information
    """
    cpu_base = get_sos_file_path(sos_home, "sys", "fs", "cgroup", "cpu,cpuacct")

    if not isdir(cpu_base):
        cpu_base = get_sos_file_path(sos_home, "sys", "fs", "cgroup", "cpu")

    if not isdir(cpu_base):
        return []

    cgroups = []

    for root, dirs, files in os.walk(cpu_base):
        quota_file = join(root, "cpu.cfs_quota_us")
        period_file = join(root, "cpu.cfs_period_us")

        if exists(quota_file) and exists(period_file):
            try:
                with open(quota_file, 'r') as f:
                    quota = int(f.read().strip())
                with open(period_file, 'r') as f:
                    period = int(f.read().strip())

                # Skip if no quota set
                if quota == -1:
                    continue

                rel_path = root.replace(cpu_base, "") or "/"
                cpu_cores = float(quota) / float(period)

                cgroups.append({
                    'path': rel_path,
                    'quota': quota,
                    'period': period,
                    'cores': cpu_cores
                })
            except (ValueError, IOError, OSError, ZeroDivisionError):
                pass

    return cgroups


def show_cpu_cgroups(sos_home, colors, output):
    """
    Show CPU quota information for cgroups.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    cgroups = get_cpu_cgroups(sos_home)

    if not cgroups:
        output.add_line("No CPU quotas found (all cgroups have unlimited CPU)")
        return

    output.add_colored_line("=== CPU Cgroup Quotas ===", colors.cyan, colors.reset)
    output.add_line("")
    output.add_line("%-60s %12s %12s %10s" %
                   ("Path", "Quota (us)", "Period (us)", "CPU Cores"))
    output.add_line("-" * 95)

    for cg in cgroups:
        if is_cmd_stopped():
            break

        output.add_line("%-60s %12d %12d %10.2f" % (
            cg['path'], cg['quota'], cg['period'], cg['cores']))


def show_oom_events(sos_home, colors, output):
    """
    Show OOM events from memory cgroups.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    memory_base = get_sos_file_path(sos_home, "sys", "fs", "cgroup", "memory")

    if not isdir(memory_base):
        output.add_line("Memory cgroup not found")
        return

    output.add_colored_line("=== OOM Events in Cgroups ===", colors.cyan, colors.reset)
    output.add_line("")
    output.add_line("%-60s %15s %12s" % ("Path", "Under OOM", "OOM Kills"))
    output.add_line("-" * 90)

    found_oom = False

    for root, dirs, files in os.walk(memory_base):
        if is_cmd_stopped():
            break

        oom_control = join(root, "memory.oom_control")

        if exists(oom_control):
            try:
                with open(oom_control, 'r') as f:
                    content = f.read()

                under_oom = "0"
                oom_kill = "0"

                for line in content.split('\n'):
                    if line.startswith("under_oom"):
                        under_oom = line.split()[1]
                    elif line.startswith("oom_kill "):
                        oom_kill = line.split()[1]

                # Only show if there were OOM events
                if oom_kill != "0" or under_oom != "0":
                    rel_path = root.replace(memory_base, "") or "/"

                    if output.no_pipe:
                        under_oom_str = (colors.red + under_oom + colors.reset
                                       if under_oom != "0" else under_oom)
                        oom_kill_str = (colors.yellow + oom_kill + colors.reset
                                      if oom_kill != "0" else oom_kill)
                    else:
                        under_oom_str = under_oom
                        oom_kill_str = oom_kill

                    output.add_line("%-60s %15s %12s" % (rel_path, under_oom_str, oom_kill_str))
                    found_oom = True

            except (IOError, OSError):
                pass

    if not found_oom:
        output.add_line("")
        output.add_line("No OOM events detected in any cgroup.")


def show_memory_stats(sos_home, cgroup_path, colors, output):
    """
    Show detailed memory statistics for a specific cgroup.

    Args:
        sos_home: Root of sosreport
        cgroup_path: Relative path to cgroup
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    if not cgroup_path.startswith("/"):
        cgroup_path = "/" + cgroup_path

    memory_stat = get_sos_file_path(sos_home, "sys", "fs", "cgroup", "memory",
                                    cgroup_path.lstrip('/'), "memory.stat")

    if not exists(memory_stat):
        output.add_line("Cgroup path not found: %s" % cgroup_path)
        return

    output.add_colored_line("=== Memory Statistics for %s ===" % cgroup_path,
                           colors.cyan, colors.reset)
    output.add_line("")

    try:
        with open(memory_stat, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    break

                parts = line.strip().split()
                if len(parts) == 2:
                    key, value = parts

                    # Format hierarchical stats with color
                    if output.no_pipe and (key.startswith("total_") or
                                          key.startswith("hierarchical_")):
                        formatted_key = colors.yellow + "%-35s" % key + colors.reset
                    else:
                        formatted_key = "%-35s" % key

                    # Format byte values
                    try:
                        val_int = int(value)
                        if val_int > 1024:
                            output.add_line("%s %15s (%s)" %
                                          (formatted_key, value, format_bytes(val_int)))
                        else:
                            output.add_line("%s %15s" % (formatted_key, value))
                    except ValueError:
                        output.add_line("%s %15s" % (formatted_key, value))

    except (IOError, OSError):
        output.add_line("Error reading memory statistics")


def print_list_help_msg(no_pipe):
    msg = '''cginfo -l  --  Systemd cgroup hierarchy view

SYNOPSIS
    cginfo -l

DESCRIPTION
    Displays the systemd cgroup hierarchy from the sosreport, reading
    sos_commands/cgroups/systemd-cgls output verbatim with color
    highlighting applied to the tree structure.

OPTIONS
    -l, --list
        Show systemd cgroup hierarchy.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -l
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_memory_help_msg(no_pipe):
    msg = '''cginfo -m  --  Memory cgroup usage view

SYNOPSIS
    cginfo -m

DESCRIPTION
    Shows memory usage for all cgroups that consume at least 1 MB,
    sorted by usage (highest first). Reads usage_in_bytes and
    limit_in_bytes from sys/fs/cgroup/memory/**/.
    Percentage column is color-coded: yellow >= 70%, red >= 90%.

OPTIONS
    -m, --memory
        Show memory usage for all cgroups.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -m
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_cpu_help_msg(no_pipe):
    msg = '''cginfo -c  --  CPU cgroup quota view

SYNOPSIS
    cginfo -c

DESCRIPTION
    Lists cgroups that have a CFS CPU quota set (cpu.cfs_quota_us != -1).
    Reads cpu.cfs_quota_us and cpu.cfs_period_us from
    sys/fs/cgroup/cpu,cpuacct/** (falls back to sys/fs/cgroup/cpu/**).
    The CPU Cores column shows quota/period as a fractional core count.

OPTIONS
    -c, --cpu
        Show CPU quotas for cgroups.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -c
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_oom_help_msg(no_pipe):
    msg = '''cginfo -o  --  OOM events view

SYNOPSIS
    cginfo -o

DESCRIPTION
    Scans memory.oom_control files under sys/fs/cgroup/memory/** and
    reports cgroups where under_oom or oom_kill is non-zero.
    Only cgroups with actual OOM activity are shown; a clean system will
    display "No OOM events detected."

OPTIONS
    -o, --oom
        Show OOM events in cgroups.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -o
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_top_help_msg(no_pipe):
    msg = '''cginfo -t  --  Top memory-consuming cgroups view

SYNOPSIS
    cginfo -t

DESCRIPTION
    Shows the top 20 memory-consuming cgroups sorted by current usage,
    skipping cgroups below 1 MB. This is a focused subset of -m output
    useful for quickly identifying the heaviest memory consumers.

OPTIONS
    -t, --top
        Show top memory-consuming cgroups.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -t
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_stats_help_msg(no_pipe):
    msg = '''cginfo -s  --  Detailed cgroup memory statistics view

SYNOPSIS
    cginfo -s PATH

DESCRIPTION
    Shows the full memory.stat file for a specific cgroup path.
    PATH is the relative cgroup path under sys/fs/cgroup/memory/
    (e.g. /system.slice/sshd.service).
    Byte values are shown with human-readable equivalents.
    Hierarchical and total_ keys are highlighted in yellow.

OPTIONS
    -s PATH, --stats PATH
        Show detailed statistics for the cgroup at PATH.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -s /system.slice/sshd.service
    example.com> cginfo -s /kubepods/pod-abc123
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_all_help_msg(no_pipe):
    msg = '''cginfo -a  --  Comprehensive cgroup information view

SYNOPSIS
    cginfo -a

DESCRIPTION
    Runs all cgroup analysis modes in sequence:
      1. Cgroup version and controllers (-v)
      2. Full memory cgroup usage (-m)
      3. CPU quota information (-c)
      4. OOM events (-o)
    Equivalent to running each mode individually but in a single output.

OPTIONS
    -a, --all
        Show all cgroup information.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> cginfo -a
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Shows cgroup (control groups) information from the sosreport.

Examples:
  cginfo           Show cgroup version and controllers (default)
  cginfo -l        Show systemd cgroup hierarchy (systemd-cgls output)
  cginfo -m        Show memory usage for all cgroups
  cginfo -c        Show CPU quotas for cgroups
  cginfo -o        Show OOM events in cgroups
  cginfo -t        Show top memory-consuming cgroups
  cginfo -s PATH   Show detailed statistics for specific cgroup
                   Example: cginfo -s /system.slice/sshd.service
  cginfo -a        Show all information (comprehensive)

Cgroup Info:
  - Cgroup v1: Traditional hierarchy with separate controllers
  - Cgroup v2: Unified hierarchy (modern systems)
  - Hybrid: Both v1 and v2 mounted
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


# Global state
is_cmd_stopped = None


def run_cginfo(input_str, env_vars, is_cmd_stopped_func,
               show_help=False, no_pipe=True):
    """
    Main entry point for cginfo command.

    Args:
        input_str: Command arguments
        env_vars: Environment variables dict
        is_cmd_stopped_func: Function to check if command should stop
        show_help: Show help message
        no_pipe: True if output goes to terminal

    Returns:
        Result string (empty if output went to terminal)
    """
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: cginfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-v', '--version', dest='show_version', action='store_true',
                  help='show cgroup version and controllers')
    op.add_option('-l', '--list', dest='show_list', action='store_true',
                  help='show systemd cgroup hierarchy')
    op.add_option('-m', '--memory', dest='show_memory', action='store_true',
                  help='show memory usage for all cgroups')
    op.add_option('-c', '--cpu', dest='show_cpu', action='store_true',
                  help='show CPU quotas for cgroups')
    op.add_option('-o', '--oom', dest='show_oom', action='store_true',
                  help='show OOM events in cgroups')
    op.add_option('-t', '--top', dest='show_top', action='store_true',
                  help='show top memory-consuming cgroups')
    op.add_option('-s', '--stats', dest='cgroup_path', type='string',
                  help='show detailed statistics for specific cgroup path')
    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all cgroup information')

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help:
        if o.show_all:
            return print_all_help_msg(no_pipe)
        elif o.show_list:
            return print_list_help_msg(no_pipe)
        elif o.show_memory:
            return print_memory_help_msg(no_pipe)
        elif o.show_cpu:
            return print_cpu_help_msg(no_pipe)
        elif o.show_oom:
            return print_oom_help_msg(no_pipe)
        elif o.show_top:
            return print_top_help_msg(no_pipe)
        elif o.cgroup_path:
            return print_stats_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)

    # Initialize helpers
    sos_home = env_vars["sos_home"]
    colors = ColorManager(no_pipe)
    output = OutputBuilder(no_pipe)

    # Execute requested operation
    try:
        if o.show_all:
            show_cgroup_version(sos_home, colors, output)
            output.add_line("")
            show_memory_cgroups(sos_home, colors, output, top_only=False)
            output.add_line("")
            show_cpu_cgroups(sos_home, colors, output)
            output.add_line("")
            show_oom_events(sos_home, colors, output)
        elif o.show_list:
            show_systemd_hierarchy(sos_home, colors, output)
        elif o.show_memory:
            show_memory_cgroups(sos_home, colors, output, top_only=False)
        elif o.show_cpu:
            show_cpu_cgroups(sos_home, colors, output)
        elif o.show_oom:
            show_oom_events(sos_home, colors, output)
        elif o.show_top:
            show_memory_cgroups(sos_home, colors, output, top_only=True)
        elif o.cgroup_path:
            show_memory_stats(sos_home, o.cgroup_path, colors, output)
        elif o.show_version:
            show_cgroup_version(sos_home, colors, output)
        else:
            # Default: show version and controllers
            show_cgroup_version(sos_home, colors, output)

    except Exception as e:
        output.add_line("Unexpected error: %s" % str(e))

    return output.get_result()
