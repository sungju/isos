from optparse import OptionParser
from io import StringIO
import os

import screen


def description():
    return "Kernel sysctl tunables analysis"


def add_command():
    return True


cmd_name = "sysctl"
def get_command_info():
    return { cmd_name : run_sysctlinfo }


IMPORTANT_TUNABLES = {
    "vm": {
        "vm.swappiness": {
            "default": "60",
            "description": "Controls how aggressively the kernel swaps",
        },
        "vm.dirty_ratio": {
            "default": "20",
            "description": "Max % of memory for dirty pages before forced writeback",
        },
        "vm.dirty_background_ratio": {
            "default": "10",
            "description": "% threshold for background writeback",
        },
        "vm.overcommit_memory": {
            "default": "0",
            "description": "0=heuristic, 1=always, 2=strict",
        },
        "vm.overcommit_ratio": {
            "default": "50",
            "description": "% of RAM for overcommit when mode=2",
        },
        "vm.min_free_kbytes": {
            "default": None,
            "description": "Minimum free memory reserved for kernel",
        },
        "vm.panic_on_oom": {
            "default": "0",
            "description": "Panic instead of OOM-kill",
        },
        "vm.zone_reclaim_mode": {
            "default": "0",
            "description": "NUMA zone reclaim behavior",
        },
        "vm.vfs_cache_pressure": {
            "default": "100",
            "description": "Tendency to reclaim dentry/inode cache",
        },
        "vm.max_map_count": {
            "default": "65530",
            "description": "Max mmap regions per process",
        },
    },
    "net": {
        "net.core.somaxconn": {
            "default": "4096",
            "description": "Max socket listen backlog",
        },
        "net.core.netdev_max_backlog": {
            "default": "1000",
            "description": "Max packets queued on input",
        },
        "net.core.rmem_max": {
            "default": "212992",
            "description": "Max receive socket buffer",
        },
        "net.core.wmem_max": {
            "default": "212992",
            "description": "Max send socket buffer",
        },
        "net.core.netdev_budget": {
            "default": "300",
            "description": "NAPI budget per CPU",
        },
        "net.ipv4.tcp_max_syn_backlog": {
            "default": "256",
            "description": "Max SYN queue length",
        },
        "net.ipv4.tcp_fin_timeout": {
            "default": "60",
            "description": "FIN-WAIT-2 timeout in seconds",
        },
        "net.ipv4.tcp_keepalive_time": {
            "default": "7200",
            "description": "TCP keepalive idle time in seconds",
        },
        "net.ipv4.ip_forward": {
            "default": "0",
            "description": "Enable IP forwarding",
        },
        "net.ipv4.tcp_syncookies": {
            "default": "1",
            "description": "SYN cookie protection",
        },
        "net.ipv4.conf.all.rp_filter": {
            "default": "0",
            "description": "Reverse path filtering",
        },
    },
    "kernel": {
        "kernel.panic": {
            "default": "0",
            "description": "Seconds before reboot on panic (0=no reboot)",
        },
        "kernel.panic_on_oops": {
            "default": "0",
            "description": "Panic on kernel oops",
        },
        "kernel.shmmax": {
            "default": None,
            "description": "Max shared memory segment size",
        },
        "kernel.sem": {
            "default": "32000\t1024000000\t500\t32000",
            "description": "Semaphore limits (SEMMSL SEMMNS SEMOPM SEMMNI)",
        },
        "kernel.pid_max": {
            "default": "4194304",
            "description": "Max PID value",
        },
        "kernel.threads-max": {
            "default": None,
            "description": "Max threads system-wide",
        },
        "kernel.hung_task_timeout_secs": {
            "default": "120",
            "description": "Hung task detection timeout in seconds",
        },
        "kernel.nmi_watchdog": {
            "default": "0",
            "description": "NMI watchdog",
        },
        "kernel.sysrq": {
            "default": "16",
            "description": "SysRq key functions bitmask",
        },
    },
}


def parse_sysctl(sos_home):
    result = {}
    sysctl_path = sos_home + "/sos_commands/kernel/sysctl_-a"
    if not os.path.isfile(sysctl_path):
        return result

    try:
        with open(sysctl_path) as f:
            for line in f:
                line = line.strip()
                if " = " in line:
                    key, _, value = line.partition(" = ")
                    result[key.strip()] = value.strip()
    except:
        pass

    return result


def show_category_tunables(sysctl_dict, category, no_pipe):
    result_str = ""
    tunables = IMPORTANT_TUNABLES.get(category, {})
    if not tunables:
        return result_str

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        info_c = screen.COLOR_INFO
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = info_c = warn_c = reset_c = ""

    category_labels = {
        "vm": "VM (Virtual Memory)",
        "net": "Network",
        "kernel": "Kernel",
    }
    label = category_labels.get(category, category)
    result_str += screen.get_pipe_aware_line(
        "%s%s %s Tunables %s%s" % (hdr_c, "=" * 20, label, "=" * 20, reset_c))
    result_str += screen.get_pipe_aware_line("")

    for key in sorted(tunables.keys()):
        if is_cmd_stopped and is_cmd_stopped():
            break

        info = tunables[key]
        default_val = info["default"]
        desc = info["description"]
        current_val = sysctl_dict.get(key)

        if current_val is None:
            continue

        if default_val is None:
            tag = "%s[SET]%s" % (info_c, reset_c)
            result_str += screen.get_pipe_aware_line(
                "  %s = %s  %s" % (key, current_val, tag))
        elif current_val == default_val:
            tag = "%s[DEFAULT]%s" % (info_c, reset_c)
            result_str += screen.get_pipe_aware_line(
                "  %s = %s  %s" % (key, current_val, tag))
        else:
            tag = "%s[CUSTOM]%s" % (warn_c, reset_c)
            result_str += screen.get_pipe_aware_line(
                "  %s = %s  %s" % (key, current_val, tag))
            result_str += screen.get_pipe_aware_line(
                "    (default: %s)" % default_val)

        result_str += screen.get_pipe_aware_line("    %s" % desc)
        result_str += screen.get_pipe_aware_line("")

    return result_str


def show_all_nondefault(sysctl_dict, no_pipe):
    result_str = ""

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = warn_c = reset_c = ""

    result_str += screen.get_pipe_aware_line(
        "%s%s All Non-Default Tunables %s%s" % (hdr_c, "=" * 20, "=" * 20, reset_c))
    result_str += screen.get_pipe_aware_line("")

    all_known = {}
    for category in IMPORTANT_TUNABLES:
        for key, info in IMPORTANT_TUNABLES[category].items():
            all_known[key] = info

    count = 0
    for key in sorted(sysctl_dict.keys()):
        if is_cmd_stopped and is_cmd_stopped():
            break

        if key not in all_known:
            continue

        info = all_known[key]
        default_val = info["default"]
        current_val = sysctl_dict[key]

        if default_val is None:
            continue

        if current_val != default_val:
            tag = "%s[CUSTOM]%s" % (warn_c, reset_c)
            result_str += screen.get_pipe_aware_line(
                "  %s = %s  %s" % (key, current_val, tag))
            result_str += screen.get_pipe_aware_line(
                "    (default: %s)" % default_val)
            result_str += screen.get_pipe_aware_line(
                "    %s" % info["description"])
            result_str += screen.get_pipe_aware_line("")
            count += 1

    if count == 0:
        result_str += screen.get_pipe_aware_line(
            "  All known tunables are at default values.")
    else:
        result_str += screen.get_pipe_aware_line(
            "  Total: %d tunable(s) differ from defaults" % count)
    result_str += screen.get_pipe_aware_line("")

    return result_str


def show_filter_tunables(sysctl_dict, keyword, no_pipe):
    result_str = ""

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        info_c = screen.COLOR_INFO
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = info_c = warn_c = reset_c = ""

    result_str += screen.get_pipe_aware_line(
        "%s%s Tunables matching '%s' %s%s" % (
            hdr_c, "=" * 20, keyword, "=" * 20, reset_c))
    result_str += screen.get_pipe_aware_line("")

    all_known = {}
    for category in IMPORTANT_TUNABLES:
        for key, info in IMPORTANT_TUNABLES[category].items():
            all_known[key] = info

    keyword_lower = keyword.lower()
    count = 0

    for key in sorted(sysctl_dict.keys()):
        if is_cmd_stopped and is_cmd_stopped():
            break

        if keyword_lower not in key.lower():
            continue

        current_val = sysctl_dict[key]

        if key in all_known:
            info = all_known[key]
            default_val = info["default"]

            if default_val is None:
                tag = "%s[SET]%s" % (info_c, reset_c)
            elif current_val == default_val:
                tag = "%s[DEFAULT]%s" % (info_c, reset_c)
            else:
                tag = "%s[CUSTOM]%s" % (warn_c, reset_c)

            result_str += screen.get_pipe_aware_line(
                "  %s = %s  %s" % (key, current_val, tag))
            if default_val is not None and current_val != default_val:
                result_str += screen.get_pipe_aware_line(
                    "    (default: %s)" % default_val)
            result_str += screen.get_pipe_aware_line(
                "    %s" % info["description"])
        else:
            result_str += screen.get_pipe_aware_line(
                "  %s = %s" % (key, current_val))

        result_str += screen.get_pipe_aware_line("")
        count += 1

    if count == 0:
        result_str += screen.get_pipe_aware_line(
            "  No tunables matching '%s'" % keyword)
    else:
        result_str += screen.get_pipe_aware_line(
            "  Total: %d tunable(s) found" % count)
    result_str += screen.get_pipe_aware_line("")

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Analyzes kernel sysctl tunables from the sosreport.

Examples:
    sysctl             Show important tunables summary (all categories)
    sysctl -v          Show VM (virtual memory) tunables only
    sysctl -n          Show network tunables only
    sysctl -k          Show kernel tunables only
    sysctl -a          Show all non-default tunables
    sysctl -f vm.dirty Show tunables matching "vm.dirty"
'''

    if no_pipe:
        op.print_help()
        print(cmd_examples)
        return ""
    else:
        buf = StringIO()
        op.print_help(file=buf)
        contents = buf.getvalue()
        buf.close()
        return contents + "\n" + cmd_examples


sos_home = ""
is_cmd_stopped = None

def run_sysctlinfo(input_str, env_vars, is_cmd_stopped_func,
                   show_help=False, no_pipe=True):
    global sos_home, is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func
    sos_home = env_vars["sos_home"]

    usage = "Usage: sysctl [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option("-h", "--help", dest="help", action="store_true",
                  help="show this help message and exit")
    op.add_option("-v", "--vm", dest="show_vm", action="store_true",
                  help="show VM tunables only")
    op.add_option("-n", "--net", dest="show_net", action="store_true",
                  help="show network tunables only")
    op.add_option("-k", "--kernel", dest="show_kernel", action="store_true",
                  help="show kernel tunables only")
    op.add_option("-a", "--all", dest="show_all", action="store_true",
                  help="show all non-default tunables")
    op.add_option("-f", "--filter", dest="filter_str", default="",
                  help="filter tunables by keyword")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o is None:
        return ""

    if o.help or show_help:
        return print_help_msg(op, no_pipe)

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    sysctl_dict = parse_sysctl(sos_home)
    if not sysctl_dict:
        return screen.get_pipe_aware_line(
            "sysctl data not found (sos_commands/kernel/sysctl_-a)")

    result_str = ""
    if o.filter_str:
        result_str = show_filter_tunables(sysctl_dict, o.filter_str, no_pipe)
    elif o.show_vm:
        result_str = show_category_tunables(sysctl_dict, "vm", no_pipe)
    elif o.show_net:
        result_str = show_category_tunables(sysctl_dict, "net", no_pipe)
    elif o.show_kernel:
        result_str = show_category_tunables(sysctl_dict, "kernel", no_pipe)
    elif o.show_all:
        result_str = show_all_nondefault(sysctl_dict, no_pipe)
    else:
        for category in ["vm", "net", "kernel"]:
            if is_cmd_stopped and is_cmd_stopped():
                break
            result_str += show_category_tunables(sysctl_dict, category, no_pipe)

    return result_str
