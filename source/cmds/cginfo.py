import sys
import os
from os.path import isfile, isdir, exists, join
from optparse import OptionParser
from io import StringIO
import re
from collections import defaultdict

import ansicolor
import screen


def description():
    return "Shows cgroup (v1/v2) related information"


def add_command():
    return True


def get_command_info():
    return { "cginfo": run_cginfo }


def detect_cgroup_version(sos_home):
    """Detect if system uses cgroup v1, v2, or hybrid"""
    mounts_path = sos_home + "/proc/mounts"

    has_cgroup_v1 = False
    has_cgroup_v2 = False

    try:
        with open(mounts_path) as f:
            for line in f:
                if "cgroup2" in line or "cgroup /sys/fs/cgroup cgroup2" in line:
                    has_cgroup_v2 = True
                elif "cgroup " in line and "/sys/fs/cgroup/" in line:
                    has_cgroup_v1 = True
    except:
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
    """Get list of cgroup controllers from /proc/cgroups"""
    cgroups_path = sos_home + "/proc/cgroups"
    controllers = []

    try:
        with open(cgroups_path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    name = parts[0]
                    hierarchy = parts[1]
                    num_cgroups = parts[2]
                    enabled = parts[3]
                    controllers.append({
                        'name': name,
                        'hierarchy': hierarchy,
                        'num_cgroups': num_cgroups,
                        'enabled': enabled == '1'
                    })
    except:
        pass

    return controllers


def format_bytes(bytes_val):
    """Format bytes into human readable format"""
    try:
        bytes_val = int(bytes_val)
        if bytes_val >= 1099511627776:  # 1TB
            return "%.2f TB" % (bytes_val / 1099511627776.0)
        elif bytes_val >= 1073741824:  # 1GB
            return "%.2f GB" % (bytes_val / 1073741824.0)
        elif bytes_val >= 1048576:  # 1MB
            return "%.2f MB" % (bytes_val / 1048576.0)
        elif bytes_val >= 1024:  # 1KB
            return "%.2f KB" % (bytes_val / 1024.0)
        else:
            return "%d B" % bytes_val
    except:
        return "N/A"


def show_cgroup_version(sos_home, no_pipe):
    """Show cgroup version and controllers"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_GREEN = ansicolor.get_color(ansicolor.GREEN)
        COLOR_RED = ansicolor.get_color(ansicolor.RED)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_GREEN = COLOR_RED = COLOR_RESET = ""

    result_str = ""
    version = detect_cgroup_version(sos_home)

    result_str += COLOR_CYAN + "=== Cgroup Version ===" + COLOR_RESET + "\n"
    result_str += "Version: %s\n" % version.upper()

    # Show controllers
    controllers = get_cgroup_controllers(sos_home)
    if controllers:
        result_str += "\n" + COLOR_YELLOW + "=== Controllers ===" + COLOR_RESET + "\n"
        result_str += "%-15s %-10s %-12s %s\n" % ("Name", "Hierarchy", "Num CGroups", "Enabled")
        result_str += "-" * 50 + "\n"

        for ctrl in controllers:
            enabled_str = COLOR_GREEN + "Yes" + COLOR_RESET if ctrl['enabled'] else COLOR_RED + "No" + COLOR_RESET
            if no_pipe:
                result_str += "%-15s %-10s %-12s %s\n" % (
                    ctrl['name'], ctrl['hierarchy'], ctrl['num_cgroups'], enabled_str)
            else:
                result_str += "%-15s %-10s %-12s %s\n" % (
                    ctrl['name'], ctrl['hierarchy'], ctrl['num_cgroups'],
                    "Yes" if ctrl['enabled'] else "No")

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_systemd_hierarchy(sos_home, no_pipe):
    """Show systemd cgroup hierarchy"""
    cgls_path = sos_home + "/sos_commands/cgroups/systemd-cgls"

    if not exists(cgls_path):
        return "systemd-cgls output not found\n"

    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    result_str = COLOR_CYAN + "=== Systemd Cgroup Hierarchy ===" + COLOR_RESET + "\n\n"

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    try:
        with open(cgls_path) as f:
            for line in f:
                if is_cmd_stopped():
                    return result_str

                line = screen.get_colored_line(line.rstrip())
                if no_pipe:
                    print(line)
                else:
                    result_str += line + "\n"
    except:
        return "Error reading systemd-cgls output\n"

    if no_pipe:
        return ""
    else:
        return result_str


def get_memory_cgroups(sos_home):
    """Get memory usage for all cgroups"""
    memory_base = sos_home + "/sys/fs/cgroup/memory"

    if not isdir(memory_base):
        return []

    cgroups = []

    # Walk through memory cgroup hierarchy
    for root, dirs, files in os.walk(memory_base):
        usage_file = join(root, "memory.usage_in_bytes")
        limit_file = join(root, "memory.limit_in_bytes")

        if exists(usage_file) and exists(limit_file):
            try:
                with open(usage_file) as f:
                    usage = int(f.read().strip())
                with open(limit_file) as f:
                    limit = int(f.read().strip())

                # Skip if usage is negligible
                if usage < 1048576:  # Less than 1MB
                    continue

                # Get relative path
                rel_path = root.replace(memory_base, "") or "/"

                # Calculate percentage
                if limit < 9223372036854771712:  # Not max limit
                    percentage = (usage * 100.0) / limit
                else:
                    percentage = 0.0

                cgroups.append({
                    'path': rel_path,
                    'usage': usage,
                    'limit': limit,
                    'percentage': percentage
                })
            except:
                pass

    return cgroups


def show_memory_cgroups(sos_home, no_pipe, top_only=False):
    """Show memory usage for cgroups"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_RED = ansicolor.get_color(ansicolor.RED)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_RED = COLOR_RESET = ""

    cgroups = get_memory_cgroups(sos_home)

    if not cgroups:
        return "No memory cgroup information found\n"

    # Sort by usage
    cgroups.sort(key=lambda x: x['usage'], reverse=True)

    if top_only:
        cgroups = cgroups[:20]  # Top 20

    result_str = COLOR_CYAN + "=== Memory Cgroup Usage ===" + COLOR_RESET + "\n\n"
    result_str += "%-60s %12s %12s %8s\n" % ("Path", "Usage", "Limit", "Percent")
    result_str += "-" * 95 + "\n"

    for cg in cgroups:
        if is_cmd_stopped():
            break

        limit_str = format_bytes(cg['limit'])
        if cg['limit'] >= 9223372036854771712:
            limit_str = "unlimited"

        percent_str = "%.1f%%" % cg['percentage'] if cg['percentage'] > 0 else "N/A"

        # Color code based on usage
        if cg['percentage'] > 90:
            color = COLOR_RED
        elif cg['percentage'] > 70:
            color = COLOR_YELLOW
        else:
            color = ""

        if no_pipe and color:
            result_str += "%-60s %12s %12s %s%8s%s\n" % (
                cg['path'], format_bytes(cg['usage']), limit_str,
                color, percent_str, COLOR_RESET)
        else:
            result_str += "%-60s %12s %12s %8s\n" % (
                cg['path'], format_bytes(cg['usage']), limit_str, percent_str)

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def get_cpu_cgroups(sos_home):
    """Get CPU quota information for cgroups"""
    cpu_base = sos_home + "/sys/fs/cgroup/cpu,cpuacct"

    if not isdir(cpu_base):
        cpu_base = sos_home + "/sys/fs/cgroup/cpu"

    if not isdir(cpu_base):
        return []

    cgroups = []

    for root, dirs, files in os.walk(cpu_base):
        quota_file = join(root, "cpu.cfs_quota_us")
        period_file = join(root, "cpu.cfs_period_us")
        shares_file = join(root, "cpu.shares")

        if exists(quota_file) and exists(period_file):
            try:
                with open(quota_file) as f:
                    quota = int(f.read().strip())
                with open(period_file) as f:
                    period = int(f.read().strip())

                shares = None
                if exists(shares_file):
                    with open(shares_file) as f:
                        shares = int(f.read().strip())

                # Skip if no quota set
                if quota == -1:
                    continue

                rel_path = root.replace(cpu_base, "") or "/"

                # Calculate CPU cores
                cpu_cores = float(quota) / float(period)

                cgroups.append({
                    'path': rel_path,
                    'quota': quota,
                    'period': period,
                    'cores': cpu_cores,
                    'shares': shares
                })
            except:
                pass

    return cgroups


def show_cpu_cgroups(sos_home, no_pipe):
    """Show CPU quota information for cgroups"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    cgroups = get_cpu_cgroups(sos_home)

    if not cgroups:
        return "No CPU quotas found (all cgroups have unlimited CPU)\n"

    result_str = COLOR_CYAN + "=== CPU Cgroup Quotas ===" + COLOR_RESET + "\n\n"
    result_str += "%-60s %12s %12s %10s\n" % ("Path", "Quota (us)", "Period (us)", "CPU Cores")
    result_str += "-" * 95 + "\n"

    for cg in cgroups:
        if is_cmd_stopped():
            break

        result_str += "%-60s %12d %12d %10.2f\n" % (
            cg['path'], cg['quota'], cg['period'], cg['cores'])

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_oom_events(sos_home, no_pipe):
    """Show OOM events from memory cgroups"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RED = ansicolor.get_color(ansicolor.RED)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RED = COLOR_YELLOW = COLOR_RESET = ""

    memory_base = sos_home + "/sys/fs/cgroup/memory"

    if not isdir(memory_base):
        return "Memory cgroup not found\n"

    result_str = COLOR_CYAN + "=== OOM Events in Cgroups ===" + COLOR_RESET + "\n\n"
    result_str += "%-60s %15s %12s\n" % ("Path", "Under OOM", "OOM Kills")
    result_str += "-" * 90 + "\n"

    found_oom = False

    for root, dirs, files in os.walk(memory_base):
        oom_control = join(root, "memory.oom_control")

        if exists(oom_control):
            try:
                with open(oom_control) as f:
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

                    under_oom_str = under_oom
                    oom_kill_str = oom_kill

                    if no_pipe:
                        if under_oom != "0":
                            under_oom_str = COLOR_RED + under_oom + COLOR_RESET
                        if oom_kill != "0":
                            oom_kill_str = COLOR_YELLOW + oom_kill + COLOR_RESET

                    result_str += "%-60s %15s %12s\n" % (rel_path, under_oom_str, oom_kill_str)
                    found_oom = True
            except:
                pass

        if is_cmd_stopped():
            break

    if not found_oom:
        result_str += "\nNo OOM events detected in any cgroup.\n"

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_memory_stats(sos_home, cgroup_path, no_pipe):
    """Show detailed memory statistics for a specific cgroup"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_RESET = ""

    if not cgroup_path.startswith("/"):
        cgroup_path = "/" + cgroup_path

    memory_stat = sos_home + "/sys/fs/cgroup/memory" + cgroup_path + "/memory.stat"

    if not exists(memory_stat):
        return "Cgroup path not found: %s\n" % cgroup_path

    result_str = COLOR_CYAN + ("=== Memory Statistics for %s ===" % cgroup_path) + COLOR_RESET + "\n\n"

    try:
        with open(memory_stat) as f:
            for line in f:
                if is_cmd_stopped():
                    break

                parts = line.strip().split()
                if len(parts) == 2:
                    key, value = parts

                    # Format hierarchical stats differently
                    if key.startswith("total_") or key.startswith("hierarchical_"):
                        if no_pipe:
                            result_str += COLOR_YELLOW + "%-35s" % key + COLOR_RESET
                        else:
                            result_str += "%-35s" % key
                    else:
                        result_str += "%-35s" % key

                    # Format byte values
                    try:
                        val_int = int(value)
                        if val_int > 1024:
                            result_str += " %15s (%s)\n" % (value, format_bytes(val_int))
                        else:
                            result_str += " %15s\n" % value
                    except:
                        result_str += " %15s\n" % value
    except:
        return "Error reading memory statistics\n"

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


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
        output = StringIO.StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()

        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""


is_cmd_stopped = None

def run_cginfo(input_str, env_vars, is_cmd_stopped_func,
        show_help=False, no_pipe=True):
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

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        return print_help_msg(op, no_pipe)

    sos_home = env_vars["sos_home"]
    result_str = ""

    # Handle specific options
    if o.show_all:
        result_str += show_cgroup_version(sos_home, no_pipe)
        if not no_pipe:
            result_str += "\n"
        result_str += show_memory_cgroups(sos_home, no_pipe, top_only=False)
        if not no_pipe:
            result_str += "\n"
        result_str += show_cpu_cgroups(sos_home, no_pipe)
        if not no_pipe:
            result_str += "\n"
        result_str += show_oom_events(sos_home, no_pipe)
    elif o.show_list:
        result_str = show_systemd_hierarchy(sos_home, no_pipe)
    elif o.show_memory:
        result_str = show_memory_cgroups(sos_home, no_pipe, top_only=False)
    elif o.show_cpu:
        result_str = show_cpu_cgroups(sos_home, no_pipe)
    elif o.show_oom:
        result_str = show_oom_events(sos_home, no_pipe)
    elif o.show_top:
        result_str = show_memory_cgroups(sos_home, no_pipe, top_only=True)
    elif o.cgroup_path:
        result_str = show_memory_stats(sos_home, o.cgroup_path, no_pipe)
    elif o.show_version:
        result_str = show_cgroup_version(sos_home, no_pipe)
    else:
        # Default: show version and controllers
        result_str = show_cgroup_version(sos_home, no_pipe)

    return result_str
