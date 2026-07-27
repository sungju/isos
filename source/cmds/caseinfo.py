import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import expanduser, isfile, isdir, join
import traceback
from datetime import datetime
import re


from isos import run_shell_command, column_strings
import screen
from soshelpers import get_main

def description():
    return "Shows system overview and case information"


def add_command():
    return True


cmd_name = "ci"
def get_command_info():
    return { cmd_name : run_caseinfo }


TAINT_FLAGS = [
    (0, 'P', "Proprietary module loaded"),
    (1, 'F', "Module force loaded"),
    (2, 'S', "Kernel running on out-of-spec system"),
    (3, 'R', "Module force unloaded"),
    (4, 'M', "Processor reported MCE"),
    (5, 'B', "Bad page referenced"),
    (6, 'U', "User requested taint"),
    (7, 'D', "Kernel recently died (OOPS or BUG)"),
    (8, 'A', "ACPI table overridden"),
    (9, 'W', "Warning issued"),
    (10, 'C', "Staging driver loaded"),
    (11, 'I', "Workaround for hardware bug applied"),
    (12, 'O', "Out-of-tree module loaded"),
    (13, 'E', "Unsigned module loaded"),
    (14, 'L', "Soft lockup occurred"),
    (15, 'K', "Live-patched kernel"),
    (16, 'X', "Auxiliary taint (distro-defined)"),
    (17, 'T', "Kernel built with struct randomization"),
]


def show_caseinfo(options, no_pipe):
    result_str = ''

    case_path_root = ""
    try:
        case_path_root = os.environ["CASE_PATH_ROOT"]
    except:
        pass

    caseno_str = ""
    if case_path_root != "":
        caseno_str = os.path.dirname(sos_home).replace(case_path_root, "", 1).split("/")[0]
    else:
        path_list = os.path.dirname(sos_home).split("/")
        for path in path_list:
            if path.isdigit():
                caseno_str = path
                break

    if no_pipe:
        title_c = screen.COLOR_TITLE
        info_c = screen.COLOR_INFO
        reset_c = screen.COLOR_RESET
    else:
        title_c = info_c = reset_c = ""

    if caseno_str:
        result_str += screen.get_pipe_aware_line(
            "%sCase No:%s %s" % (title_c, reset_c, caseno_str))

    try:
        with open(sos_home + "/uname") as f:
            line = f.readlines()[0]
            words = line.split()
            result_str += screen.get_pipe_aware_line(
                "%sHostname:%s %s" % (title_c, reset_c, words[1]))
            result_str += screen.get_pipe_aware_line(
                "%sKernel:%s   %s" % (title_c, reset_c, words[2]))
    except:
        pass

    return result_str


def show_os_release(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        reset_c = screen.COLOR_RESET
    else:
        title_c = reset_c = ""

    release_str = ""
    try:
        with open(sos_home + "/etc/redhat-release") as f:
            release_str = f.readline().strip()
    except:
        try:
            with open(sos_home + "/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        release_str = line.split("=", 1)[1].strip().strip('"')
                        break
        except:
            pass

    if release_str:
        result_str += screen.get_pipe_aware_line(
            "%sOS:%s       %s" % (title_c, reset_c, release_str))

    return result_str


def show_uptime(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        reset_c = screen.COLOR_RESET
    else:
        title_c = reset_c = ""

    uptime_str = ""
    try:
        with open(sos_home + "/uptime") as f:
            uptime_str = f.readline().strip()
    except:
        pass

    if not uptime_str:
        try:
            with open(sos_home + "/proc/uptime") as f:
                secs = float(f.readline().split()[0])
                days = int(secs // 86400)
                hours = int((secs % 86400) // 3600)
                mins = int((secs % 3600) // 60)
                parts = []
                if days > 0:
                    parts.append("%d day(s)" % days)
                if hours > 0:
                    parts.append("%d hour(s)" % hours)
                parts.append("%d min(s)" % mins)
                uptime_str = ", ".join(parts)
        except:
            pass

    if uptime_str:
        result_str += screen.get_pipe_aware_line(
            "%sUptime:%s  %s" % (title_c, reset_c, uptime_str))

    return result_str


def show_selinux(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        info_c = screen.COLOR_INFO
        warn_c = screen.COLOR_WARNING
        crit_c = screen.COLOR_CRITICAL
        reset_c = screen.COLOR_RESET
    else:
        title_c = info_c = warn_c = crit_c = reset_c = ""

    mode = ""
    try:
        with open(sos_home + "/sos_commands/selinux/sestatus") as f:
            for line in f:
                if "Current mode:" in line:
                    mode = line.split(":", 1)[1].strip()
                    break
                elif "SELinux status:" in line:
                    status = line.split(":", 1)[1].strip()
                    if status == "disabled":
                        mode = "disabled"
                        break
    except:
        try:
            with open(sos_home + "/etc/selinux/config") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SELINUX=") and not line.startswith("SELINUXTYPE="):
                        mode = line.split("=", 1)[1].strip()
                        break
        except:
            pass

    if mode:
        if mode == "enforcing":
            color = info_c
        elif mode == "permissive":
            color = warn_c
        elif mode == "disabled":
            color = crit_c
        else:
            color = reset_c
        result_str += screen.get_pipe_aware_line(
            "%sSELinux:%s %s%s%s" % (title_c, reset_c, color, mode, reset_c))

    return result_str


def show_runlevel(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        reset_c = screen.COLOR_RESET
    else:
        title_c = reset_c = ""

    target = ""
    try:
        with open(sos_home + "/sos_commands/systemd/systemctl_get-default") as f:
            target = f.readline().strip()
    except:
        try:
            files = glob.glob(sos_home + "/sos_commands/systemd/systemctl_get*default*")
            if files:
                with open(files[0]) as f:
                    target = f.readline().strip()
        except:
            pass

    if not target:
        try:
            with open(sos_home + "/runlevel") as f:
                target = "runlevel " + f.readline().strip()
        except:
            pass

    if target:
        result_str += screen.get_pipe_aware_line(
            "%sDefault:%s %s" % (title_c, reset_c, target))

    return result_str


def show_cmdline(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        reset_c = screen.COLOR_RESET
    else:
        title_c = reset_c = ""

    try:
        with open(sos_home + "/proc/cmdline") as f:
            cmdline = f.readline().strip()
            result_str += screen.get_pipe_aware_line(
                "%sCmdline:%s %s" % (title_c, reset_c, cmdline))
    except:
        pass

    return result_str


def show_kernel_taint(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        warn_c = screen.COLOR_WARNING
        info_c = screen.COLOR_INFO
        reset_c = screen.COLOR_RESET
    else:
        title_c = warn_c = info_c = reset_c = ""

    taint_val = 0
    try:
        with open(sos_home + "/proc/sys/kernel/tainted") as f:
            taint_val = int(f.readline().strip())
    except:
        return result_str

    if taint_val == 0:
        result_str += screen.get_pipe_aware_line(
            "%sTaint:%s   %s0 (not tainted)%s" % (title_c, reset_c, info_c, reset_c))
    else:
        flags = []
        for bit, letter, desc in TAINT_FLAGS:
            if taint_val & (1 << bit):
                flags.append((letter, desc))

        flag_str = "".join([f[0] for f in flags])
        result_str += screen.get_pipe_aware_line(
            "%sTaint:%s   %s%d (%s)%s" % (
                title_c, reset_c, warn_c, taint_val, flag_str, reset_c))
        for letter, desc in flags:
            result_str += screen.get_pipe_aware_line(
                "           %s%s%s: %s" % (warn_c, letter, reset_c, desc))

    return result_str


def show_loaded_modules_summary(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        title_c = warn_c = reset_c = ""

    total = 0
    oot_count = 0
    tainted_modules = []

    try:
        path = sos_home + "/lsmod"
        if not os.path.isfile(path):
            path = sos_home + "/proc/modules"

        with open(path) as f:
            for line in f:
                if is_cmd_stopped and is_cmd_stopped():
                    break
                words = line.split()
                if not words:
                    continue
                if words[0] == "Module":
                    continue
                total += 1
    except:
        pass

    try:
        with open(sos_home + "/proc/modules") as f:
            for line in f:
                words = line.split()
                if len(words) >= 6:
                    taints = words[-1] if words[-1] != "-" else ""
                    if "O" in taints:
                        oot_count += 1
                    if taints and taints not in ("-", "(Live)"):
                        tainted_modules.append((words[0], taints))
    except:
        pass

    if total > 0:
        mod_str = "%d loaded" % total
        if oot_count > 0:
            mod_str += ", %s%d out-of-tree%s" % (warn_c, oot_count, reset_c)
        result_str += screen.get_pipe_aware_line(
            "%sModules:%s %s" % (title_c, reset_c, mod_str))

    return result_str


def show_kdump(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        hdr_c = screen.COLOR_HEADER
        info_c = screen.COLOR_INFO
        warn_c = screen.COLOR_WARNING
        crit_c = screen.COLOR_CRITICAL
        reset_c = screen.COLOR_RESET
    else:
        title_c = hdr_c = info_c = warn_c = crit_c = reset_c = ""

    result_str += screen.get_pipe_aware_line("\n%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line("%sKDUMP CONFIGURATION%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))

    crashkernel = ""
    try:
        with open(sos_home + "/proc/cmdline") as f:
            cmdline = f.readline()
            match = re.search(r'crashkernel=(\S+)', cmdline)
            if match:
                crashkernel = match.group(1)
    except:
        pass

    if crashkernel:
        result_str += screen.get_pipe_aware_line(
            "%scrashkernel:%s %s" % (title_c, reset_c, crashkernel))
    else:
        result_str += screen.get_pipe_aware_line(
            "%scrashkernel:%s %snot configured%s" % (
                title_c, reset_c, crit_c, reset_c))

    kdump_service = ""
    try:
        service_files = glob.glob(
            sos_home + "/sos_commands/systemd/systemctl_list-unit*")
        for sf in service_files:
            with open(sf) as f:
                for line in f:
                    if "kdump" in line:
                        words = line.split()
                        if len(words) >= 4:
                            kdump_service = "%s (%s)" % (words[2], words[3])
                        break
            if kdump_service:
                break
    except:
        pass

    if kdump_service:
        if "running" in kdump_service.lower() or "active" in kdump_service.lower():
            color = info_c
        else:
            color = warn_c
        result_str += screen.get_pipe_aware_line(
            "%sService:%s      %s%s%s" % (title_c, reset_c, color, kdump_service, reset_c))

    kdump_target = ""
    kdump_opts = []
    try:
        with open(sos_home + "/etc/kdump.conf") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("path "):
                    kdump_opts.append(("Dump path", line.split(None, 1)[1]))
                elif line.startswith("core_collector "):
                    kdump_opts.append(("Collector", line.split(None, 1)[1]))
                elif line.startswith("default "):
                    kdump_opts.append(("Default action", line.split(None, 1)[1]))
                elif any(line.startswith(t) for t in
                         ["ext4 ", "ext3 ", "xfs ", "nfs ", "ssh ", "raw "]):
                    kdump_target = line
    except:
        pass

    if kdump_target:
        result_str += screen.get_pipe_aware_line(
            "%sDump target:%s  %s" % (title_c, reset_c, kdump_target))

    for label, value in kdump_opts:
        result_str += screen.get_pipe_aware_line(
            "%s%-14s%s %s" % (title_c, label + ":", reset_c, value))

    return result_str


def show_subscription(no_pipe):
    result_str = ""

    if no_pipe:
        title_c = screen.COLOR_TITLE
        hdr_c = screen.COLOR_HEADER
        info_c = screen.COLOR_INFO
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        title_c = hdr_c = info_c = warn_c = reset_c = ""

    result_str += screen.get_pipe_aware_line("\n%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line("%sSUBSCRIPTION STATUS%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))

    identity_found = False
    try:
        id_files = glob.glob(
            sos_home + "/sos_commands/subscription_manager/subscription-manager_identity")
        if not id_files:
            id_files = glob.glob(
                sos_home + "/sos_commands/subscription_manager/*identity*")
        for path in id_files:
            with open(path) as f:
                content = f.read().strip()
                if content:
                    identity_found = True
                    for line in content.splitlines():
                        result_str += screen.get_pipe_aware_line("  " + line)
    except:
        pass

    status_found = False
    try:
        status_files = glob.glob(
            sos_home + "/sos_commands/subscription_manager/subscription-manager_list*")
        for path in status_files:
            if is_cmd_stopped and is_cmd_stopped():
                break
            with open(path) as f:
                content = f.read().strip()
                if content and "No installed products" not in content:
                    status_found = True
                    for line in content.splitlines()[:20]:
                        if "Status:" in line:
                            val = line.split(":", 1)[1].strip()
                            if val.lower() in ("subscribed", "current"):
                                color = info_c
                            else:
                                color = warn_c
                            result_str += screen.get_pipe_aware_line(
                                "  %s%s%s" % (color, line.strip(), reset_c))
                        else:
                            result_str += screen.get_pipe_aware_line(
                                "  " + line.strip())
            if status_found:
                break
    except:
        pass

    if not identity_found and not status_found:
        result_str += screen.get_pipe_aware_line("  No subscription data found")

    return result_str


def show_system(options, no_pipe):
    result_str = screen.get_pipe_aware_line('\n')

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = reset_c = ""

    try:
        with open(sos_home + "/dmidecode") as f:
            bios_check_started = False
            for line in f:
                sline = line.strip()
                if sline == "BIOS Information":
                    bios_check_started = True
                    line = screen.get_pipe_aware_line(line)
                    result_str = result_str + line
                    continue
                elif sline == "Characteristics:":
                    bios_check_started = False
                    continue
                elif bios_check_started and len(sline) == 0:
                    bios_check_started = False
                    continue

                if bios_check_started:
                    line = screen.get_pipe_aware_line(line)
                    result_str = result_str + line
    except:
        pass

    result_str = screen.get_pipe_aware_line(result_str)

    try:
        with open(sos_home + "/date") as f:
            lines = f.readlines()
            result_str = result_str +\
                   screen.get_pipe_aware_line("Date and Time\n")
            break_print = False
            local_time = ''
            for line in lines:
                if line.strip().startswith("Time zone:"):
                    break_print = True
                if "Local time:" in line:
                    local_time = line.strip()
                line = screen.get_pipe_aware_line(line)
                result_str = result_str + line
                if break_print:
                    break

            if local_time != '':
                local_time = local_time.strip()[len("Local time:"):].strip()
                tz=local_time.split()[-1]
                local_time = local_time.replace(tz, "")
                datetime_fmt = '%a %Y-%m-%d %H:%M:%S'
                dt = datetime.strptime(local_time.strip(), datetime_fmt)
                date_ago = datetime.now() - dt
                result_str = result_str +\
                        screen.get_pipe_aware_line(
                                "\tCollected %d day(s) ago." % (date_ago.days))
    except:
        pass

    result_str = screen.get_pipe_aware_line(result_str)

    return result_str


def print_sys_help_msg(no_pipe):
    msg = '''ci -s  --  Show system information

SYNOPSIS
    ci -s

DESCRIPTION
    Displays system hardware information from the sosreport in addition
    to the default case summary, including:
    - BIOS information from dmidecode (vendor, version, release date)
    - Date and time at collection, timezone, and how many days ago
      the sosreport was collected

OPTIONS
    -s, --sys
        Show system information (BIOS, date/time, collection age).

    -h, --help
        Show this help message.

EXAMPLES
    example.com> ci -s
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
    System overview and case information

Examples:
    ci           Show system overview (OS, kernel, uptime, SELinux, taint)
    ci -s        Also show BIOS info and collection date/time
    ci -a        Show all information (overview + kdump + subscription)
    ci -k        Show kdump configuration
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


sos_home=""
is_cmd_stopped = None
def run_caseinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home

    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-s', '--sys', dest='sys', action='store_true',
                  help='Show system information')

    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='Show all information')

    op.add_option('-k', '--kdump', dest='kdump', action='store_true',
                  help='Show kdump configuration')

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        if o.sys:
            return print_sys_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)

    result_str = ""
    sos_home = env_vars['sos_home']

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str += show_caseinfo(o, no_pipe)
    result_str += show_os_release(no_pipe)
    result_str += show_uptime(no_pipe)
    result_str += show_selinux(no_pipe)
    result_str += show_runlevel(no_pipe)
    result_str += show_cmdline(no_pipe)
    result_str += show_kernel_taint(no_pipe)
    result_str += show_loaded_modules_summary(no_pipe)

    if o.sys or o.show_all:
        result_str += show_system(o, no_pipe)

    if o.kdump or o.show_all:
        result_str += show_kdump(no_pipe)

    if o.show_all:
        result_str += show_subscription(no_pipe)

    return result_str
