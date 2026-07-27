from optparse import OptionParser
from io import StringIO
import os
import glob
import re

import screen
import ansicolor


def description():
    return "Disk, filesystem and storage analysis"


def add_command():
    return True


cmd_name = "diskinfo"
def get_command_info():
    return { cmd_name : run_diskinfo }


sos_home = ""
is_cmd_stopped = None


def find_sos_file(base, *candidates):
    for candidate in candidates:
        path = os.path.join(base, candidate)
        if os.path.exists(path):
            return path
    return None


def show_block_devices(sos_home, no_pipe):
    result_str = ""
    result_str += screen.get_pipe_aware_line(
        "%s%s Block Devices %s%s" % (
            screen.COLOR_TITLE, "=" * 28, "=" * 28, screen.COLOR_RESET))

    lsblk_file = None
    block_dir = os.path.join(sos_home, "sos_commands", "block")
    if os.path.isdir(block_dir):
        try:
            candidates = glob.glob(os.path.join(block_dir, "lsblk*"))
            if candidates:
                lsblk_file = candidates[0]
        except:
            pass

    if not lsblk_file:
        lsblk_file = find_sos_file(sos_home, "lsblk")

    if not lsblk_file:
        result_str += screen.get_pipe_aware_line("  Block device data not available")
        return result_str

    try:
        with open(lsblk_file) as f:
            first_line = True
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break
                line = line.rstrip()
                if first_line:
                    result_str += screen.get_pipe_aware_line(
                        "%s%s%s" % (screen.COLOR_HEADER, line, screen.COLOR_RESET))
                    first_line = False
                else:
                    result_str += screen.get_pipe_aware_line(line)
    except:
        result_str += screen.get_pipe_aware_line("  Error reading block device data")

    return result_str


def show_filesystem_usage(sos_home, no_pipe):
    result_str = ""
    result_str += screen.get_pipe_aware_line(
        "%s%s Filesystem Usage %s%s" % (
            screen.COLOR_TITLE, "=" * 26, "=" * 26, screen.COLOR_RESET))

    df_file = find_sos_file(sos_home,
        "sos_commands/filesys/df_-al_-x_autofs",
        "sos_commands/filesys/df_-aliT_-x_autofs",
        "sos_commands/filesys/df_-h",
        "df")

    if not df_file:
        result_str += screen.get_pipe_aware_line("  Filesystem data not available")
        return result_str

    try:
        with open(df_file) as f:
            first_line = True
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break
                line = line.rstrip()
                if first_line:
                    result_str += screen.get_pipe_aware_line(
                        "%s%s%s" % (screen.COLOR_HEADER, line, screen.COLOR_RESET))
                    first_line = False
                    continue

                color = ""
                reset = ""
                if no_pipe:
                    match = re.search(r'(\d+)%', line)
                    if match:
                        pct = int(match.group(1))
                        if pct >= 90:
                            color = screen.COLOR_CRITICAL
                            reset = screen.COLOR_RESET
                        elif pct >= 75:
                            color = screen.COLOR_WARNING
                            reset = screen.COLOR_RESET

                result_str += screen.get_pipe_aware_line(
                    "%s%s%s" % (color, line, reset))
    except:
        result_str += screen.get_pipe_aware_line("  Error reading filesystem data")

    return result_str


def show_mount_info(sos_home, no_pipe):
    result_str = ""
    result_str += screen.get_pipe_aware_line(
        "%s%s Mount Points %s%s" % (
            screen.COLOR_TITLE, "=" * 28, "=" * 29, screen.COLOR_RESET))

    mount_file = find_sos_file(sos_home,
        "sos_commands/filesys/mount_-l",
        "proc/mounts")

    if mount_file:
        try:
            with open(mount_file) as f:
                result_str += screen.get_pipe_aware_line(
                    "%sActive Mounts:%s" % (screen.COLOR_HEADER, screen.COLOR_RESET))
                for line in f:
                    if is_cmd_stopped and is_cmd_stopped():
                        break
                    result_str += screen.get_pipe_aware_line(line.rstrip())
        except:
            result_str += screen.get_pipe_aware_line("  Error reading mount data")
    else:
        result_str += screen.get_pipe_aware_line("  Mount data not available")

    result_str += screen.get_pipe_aware_line("")

    fstab_file = find_sos_file(sos_home, "etc/fstab")
    if fstab_file:
        result_str += screen.get_pipe_aware_line(
            "%s%s /etc/fstab %s%s" % (
                screen.COLOR_TITLE, "=" * 29, "=" * 30, screen.COLOR_RESET))
        try:
            with open(fstab_file) as f:
                for line in f:
                    if is_cmd_stopped and is_cmd_stopped():
                        break
                    result_str += screen.get_pipe_aware_line(line.rstrip())
        except:
            result_str += screen.get_pipe_aware_line("  Error reading fstab")
    else:
        result_str += screen.get_pipe_aware_line("  /etc/fstab not available")

    return result_str


def show_multipath(sos_home, no_pipe):
    result_str = ""
    result_str += screen.get_pipe_aware_line(
        "%s%s Multipath Configuration %s%s" % (
            screen.COLOR_TITLE, "=" * 22, "=" * 23, screen.COLOR_RESET))

    mp_file = None
    mp_dir = os.path.join(sos_home, "sos_commands", "multipath")
    if os.path.isdir(mp_dir):
        try:
            candidates = glob.glob(os.path.join(mp_dir, "multipath_-ll*"))
            if not candidates:
                candidates = glob.glob(os.path.join(mp_dir, "multipath*"))
            if candidates:
                mp_file = candidates[0]
        except:
            pass

    if not mp_file:
        result_str += screen.get_pipe_aware_line("  No multipath configuration found.")
        return result_str

    try:
        with open(mp_file) as f:
            content = f.read().strip()
            if not content:
                result_str += screen.get_pipe_aware_line("  No multipath configuration found.")
                return result_str

            for line in content.splitlines():
                if is_cmd_stopped and is_cmd_stopped():
                    break
                line = line.rstrip()
                color = ""
                reset = ""
                if no_pipe:
                    if "failed" in line.lower() or "faulty" in line.lower():
                        color = screen.COLOR_CRITICAL
                        reset = screen.COLOR_RESET
                    elif "active" in line.lower() and "ready" in line.lower():
                        color = screen.COLOR_SUCCESS
                        reset = screen.COLOR_RESET
                result_str += screen.get_pipe_aware_line(
                    "%s%s%s" % (color, line, reset))
    except:
        result_str += screen.get_pipe_aware_line("  Error reading multipath data")

    return result_str


def show_disk_stats(sos_home, no_pipe):
    result_str = ""
    result_str += screen.get_pipe_aware_line(
        "%s%s Disk I/O Statistics %s%s" % (
            screen.COLOR_TITLE, "=" * 24, "=" * 25, screen.COLOR_RESET))

    diskstats_file = find_sos_file(sos_home, "proc/diskstats")
    if not diskstats_file:
        result_str += screen.get_pipe_aware_line("  Disk statistics not available")
        return result_str

    header = "%-12s %12s %12s %12s %12s %14s %14s %12s" % (
        "Device", "Reads", "Rd Merged", "Writes", "Wr Merged",
        "Sect Read", "Sect Written", "IO Time(ms)")
    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (screen.COLOR_HEADER, header, screen.COLOR_RESET))
    result_str += screen.get_pipe_aware_line("-" * 110)

    try:
        with open(diskstats_file) as f:
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break
                parts = line.split()
                if len(parts) < 14:
                    continue

                dev = parts[2]
                reads_completed = parts[3]
                reads_merged = parts[4]
                sectors_read = parts[5]
                writes_completed = parts[7]
                writes_merged = parts[8]
                sectors_written = parts[9]
                io_time = parts[12]

                if reads_completed == "0" and writes_completed == "0":
                    continue

                result_str += screen.get_pipe_aware_line(
                    "%-12s %12s %12s %12s %12s %14s %14s %12s" % (
                        dev, reads_completed, reads_merged,
                        writes_completed, writes_merged,
                        sectors_read, sectors_written, io_time))
    except:
        result_str += screen.get_pipe_aware_line("  Error reading disk statistics")

    return result_str


def show_scheduler(sos_home, no_pipe):
    result_str = ""
    result_str += screen.get_pipe_aware_line(
        "%s%s I/O Schedulers %s%s" % (
            screen.COLOR_TITLE, "=" * 27, "=" * 27, screen.COLOR_RESET))

    scheduler_pattern = os.path.join(sos_home, "sys", "block", "*", "queue", "scheduler")
    scheduler_files = glob.glob(scheduler_pattern)

    if not scheduler_files:
        result_str += screen.get_pipe_aware_line("  I/O scheduler data not available")
        return result_str

    header = "%-20s %s" % ("Device", "Scheduler")
    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (screen.COLOR_HEADER, header, screen.COLOR_RESET))
    result_str += screen.get_pipe_aware_line("-" * 50)

    for sched_file in sorted(scheduler_files):
        if is_cmd_stopped and is_cmd_stopped():
            break
        try:
            dev = sched_file.split("/sys/block/")[1].split("/")[0] if "/sys/block/" in sched_file else "unknown"
            with open(sched_file) as f:
                content = f.read().strip()

            active_match = re.search(r'\[([^\]]+)\]', content)
            active_sched = active_match.group(1) if active_match else content

            color = ""
            reset = ""
            if no_pipe:
                color = screen.COLOR_INFO
                reset = screen.COLOR_RESET

            result_str += screen.get_pipe_aware_line(
                "%-20s %s%s%s" % (dev, color, active_sched, reset))
        except:
            pass

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''diskinfo -- Disk, filesystem and storage analysis

Examples:
    diskinfo           Show block devices and filesystem usage
    diskinfo -a        Show all disk information
    diskinfo -f        Show filesystem usage with color-coded capacity
    diskinfo -m        Show mount points and fstab
    diskinfo -M        Show multipath configuration
    diskinfo -s        Show disk I/O statistics
    diskinfo -S        Show I/O schedulers
    '''

    if no_pipe:
        op.print_help()
        print(cmd_examples)
        return ""
    else:
        output = StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()
        return contents + "\n" + cmd_examples


def run_diskinfo(input_str, env_vars, is_cmd_stopped_func,
                 show_help=False, no_pipe=True):
    global sos_home, is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func
    sos_home = env_vars['sos_home']

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    op = OptionParser(usage="Usage: diskinfo [options]", add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-b', '--block', dest='block', action='store_true',
                  help='show block devices')
    op.add_option('-f', '--filesystem', dest='filesystem', action='store_true',
                  help='show filesystem usage')
    op.add_option('-m', '--mount', dest='mount', action='store_true',
                  help='show mount points and fstab')
    op.add_option('-M', '--multipath', dest='multipath', action='store_true',
                  help='show multipath configuration')
    op.add_option('-s', '--stats', dest='stats', action='store_true',
                  help='show disk I/O statistics')
    op.add_option('-S', '--scheduler', dest='scheduler', action='store_true',
                  help='show I/O schedulers')
    op.add_option('-a', '--all', dest='all', action='store_true',
                  help='show all disk information')

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help:
        return print_help_msg(op, no_pipe)

    result_str = ""

    show_default = not (o.block or o.filesystem or o.mount or
                        o.multipath or o.stats or o.scheduler or o.all)

    if o.all:
        result_str += show_block_devices(sos_home, no_pipe)
        result_str += screen.get_pipe_aware_line("")
        result_str += show_filesystem_usage(sos_home, no_pipe)
        result_str += screen.get_pipe_aware_line("")
        result_str += show_mount_info(sos_home, no_pipe)
        result_str += screen.get_pipe_aware_line("")
        result_str += show_multipath(sos_home, no_pipe)
        result_str += screen.get_pipe_aware_line("")
        result_str += show_disk_stats(sos_home, no_pipe)
        result_str += screen.get_pipe_aware_line("")
        result_str += show_scheduler(sos_home, no_pipe)
    else:
        if show_default or o.block:
            result_str += show_block_devices(sos_home, no_pipe)
            result_str += screen.get_pipe_aware_line("")
        if show_default or o.filesystem:
            result_str += show_filesystem_usage(sos_home, no_pipe)
            result_str += screen.get_pipe_aware_line("")
        if o.mount:
            result_str += show_mount_info(sos_home, no_pipe)
            result_str += screen.get_pipe_aware_line("")
        if o.multipath:
            result_str += show_multipath(sos_home, no_pipe)
            result_str += screen.get_pipe_aware_line("")
        if o.stats:
            result_str += show_disk_stats(sos_home, no_pipe)
            result_str += screen.get_pipe_aware_line("")
        if o.scheduler:
            result_str += show_scheduler(sos_home, no_pipe)

    return result_str
