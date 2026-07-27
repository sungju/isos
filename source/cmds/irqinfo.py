from optparse import OptionParser
from io import StringIO
import os
import glob

import screen


def description():
    return "Interrupt and softirq analysis"


def add_command():
    return True


cmd_name = "irqinfo"
def get_command_info():
    return { cmd_name : run_irqinfo }


def show_interrupts(no_pipe, show_all_cpus=False):
    result_str = ""
    intr_path = sos_home + "/proc/interrupts"
    if not os.path.isfile(intr_path):
        return screen.get_pipe_aware_line("proc/interrupts not found")

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = warn_c = reset_c = ""

    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sINTERRUPT STATISTICS (from /proc/interrupts)%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line("")

    try:
        with open(intr_path) as f:
            lines = f.readlines()
    except:
        return result_str + screen.get_pipe_aware_line("Error reading proc/interrupts")

    if not lines:
        return result_str + screen.get_pipe_aware_line("proc/interrupts is empty")

    header = lines[0].rstrip()
    cpu_names = header.split()
    num_cpus = len(cpu_names)
    condensed = num_cpus > 8 and not show_all_cpus

    if condensed:
        first_cpus = cpu_names[:4]
        last_cpus = cpu_names[-4:]
        col_w = 12
        hdr = "%18s" % ""
        for c in first_cpus:
            hdr += "%*s" % (col_w, c)
        hdr += "  ...  "
        for c in last_cpus:
            hdr += "%*s" % (col_w, c)
        result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    else:
        result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, header, reset_c))

    total_sources = 0
    high_irq_threshold = 1000000

    for line in lines[1:]:
        if is_cmd_stopped and is_cmd_stopped():
            break

        line = line.rstrip()
        if not line:
            continue

        total_sources += 1
        parts = line.split()
        if len(parts) < 2:
            result_str += screen.get_pipe_aware_line(line)
            continue

        irq_label = parts[0]
        counts = []
        extra_parts = []
        for p in parts[1:]:
            try:
                counts.append(int(p))
            except ValueError:
                extra_parts = parts[1 + len(counts):]
                break

        has_high = any(c > high_irq_threshold for c in counts)

        if condensed and len(counts) >= num_cpus:
            first_counts = counts[:4]
            last_counts = counts[-4:]
            col_w = 12
            row = "%18s" % irq_label
            for c in first_counts:
                row += "%*s" % (col_w, "{:,}".format(c))
            row += "  ...  "
            for c in last_counts:
                row += "%*s" % (col_w, "{:,}".format(c))
            if extra_parts:
                row += "  " + " ".join(extra_parts)
        else:
            row = line

        if has_high:
            result_str += screen.get_pipe_aware_line(
                "%s%s%s" % (warn_c, row, reset_c))
        else:
            result_str += screen.get_pipe_aware_line(row)

    result_str += screen.get_pipe_aware_line("")
    result_str += screen.get_pipe_aware_line(
        "Total interrupt sources: %d" % total_sources)
    if condensed:
        result_str += screen.get_pipe_aware_line(
            "(%d CPUs, showing first 4 and last 4. Use -a for full view)" % num_cpus)

    return result_str


def _read_sysctl_values():
    result = {}
    sysctl_path = sos_home + "/sos_commands/kernel/sysctl_-a"
    if not os.path.isfile(sysctl_path):
        return result

    try:
        with open(sysctl_path) as f:
            for line in f:
                line = line.strip()
                if " = " in line:
                    key, _, val = line.partition(" = ")
                    result[key.strip()] = val.strip()
    except:
        pass
    return result


def show_softirq(no_pipe):
    result_str = ""
    stat_path = sos_home + "/proc/softnet_stat"
    if not os.path.isfile(stat_path):
        return screen.get_pipe_aware_line("proc/softnet_stat not found")

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        warn_c = screen.COLOR_WARNING
        crit_c = screen.COLOR_CRITICAL
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = warn_c = crit_c = reset_c = ""

    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sSOFTNET STATISTICS (from /proc/softnet_stat)%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line("")

    try:
        with open(stat_path) as f:
            lines = f.readlines()
    except:
        return result_str + screen.get_pipe_aware_line(
            "Error reading proc/softnet_stat")

    if not lines:
        return result_str + screen.get_pipe_aware_line("proc/softnet_stat is empty")

    hdr = "%-6s %14s %10s %14s" % ("CPU", "Processed", "Dropped", "Time_Squeeze")
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    result_str += screen.get_pipe_aware_line("-" * 48)

    total_processed = 0
    total_dropped = 0
    total_squeeze = 0
    warnings = []

    for cpu_idx, line in enumerate(lines):
        if is_cmd_stopped and is_cmd_stopped():
            break

        line = line.strip()
        if not line:
            continue

        cols = line.split()
        if len(cols) < 3:
            continue

        try:
            processed = int(cols[0], 16)
            dropped = int(cols[1], 16)
            time_squeeze = int(cols[2], 16)
        except ValueError:
            continue

        total_processed += processed
        total_dropped += dropped
        total_squeeze += time_squeeze

        row = "%-6d %14s %10s %14s" % (
            cpu_idx,
            "{:,}".format(processed),
            "{:,}".format(dropped),
            "{:,}".format(time_squeeze),
        )

        if dropped > 0:
            result_str += screen.get_pipe_aware_line(
                "%s%s   << CRITICAL%s" % (crit_c, row, reset_c))
            warnings.append(
                "CPU %d has %s dropped packets - "
                "check net.core.netdev_max_backlog" % (
                    cpu_idx, "{:,}".format(dropped)))
        elif time_squeeze > 0:
            result_str += screen.get_pipe_aware_line(
                "%s%s   << WARNING%s" % (warn_c, row, reset_c))
            warnings.append(
                "CPU %d has %s time_squeeze events - "
                "check net.core.netdev_budget" % (
                    cpu_idx, "{:,}".format(time_squeeze)))
        else:
            result_str += screen.get_pipe_aware_line(row)

    result_str += screen.get_pipe_aware_line("-" * 48)
    result_str += screen.get_pipe_aware_line("%-6s %14s %10s %14s" % (
        "Total",
        "{:,}".format(total_processed),
        "{:,}".format(total_dropped),
        "{:,}".format(total_squeeze),
    ))
    result_str += screen.get_pipe_aware_line("")

    if warnings:
        for w in warnings:
            result_str += screen.get_pipe_aware_line(
                "%sWARNING: %s%s" % (warn_c, w, reset_c))

        tunables = _read_sysctl_values()
        if "net.core.netdev_max_backlog" in tunables and total_dropped > 0:
            result_str += screen.get_pipe_aware_line(
                "  Current net.core.netdev_max_backlog = %s" %
                tunables["net.core.netdev_max_backlog"])
        if "net.core.netdev_budget" in tunables and total_squeeze > 0:
            result_str += screen.get_pipe_aware_line(
                "  Current net.core.netdev_budget = %s" %
                tunables["net.core.netdev_budget"])
        result_str += screen.get_pipe_aware_line("")

    return result_str


def show_softirq_tunables(no_pipe):
    result_str = ""

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = warn_c = reset_c = ""

    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sSOFTIRQ RELATED TUNABLES%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line("")

    tunables = _read_sysctl_values()

    if not tunables:
        return result_str + screen.get_pipe_aware_line(
            "sos_commands/kernel/sysctl_-a not found")

    tunable_defaults = {
        "net.core.netdev_budget": "300",
        "net.core.netdev_max_backlog": "1000",
        "net.core.netdev_budget_usecs": "2000",
    }

    hdr = "%-40s %15s %10s" % ("Tunable", "Value", "Default")
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    result_str += screen.get_pipe_aware_line("-" * 67)

    for key in sorted(tunable_defaults.keys()):
        default = tunable_defaults[key]
        current = tunables.get(key, "N/A")

        if current == "N/A":
            status = ""
        elif current != default:
            status = " (CUSTOM)"
        else:
            status = " (default)"

        row = "%-40s %15s %10s%s" % (key, current, default, status)
        if current != "N/A" and current != default:
            result_str += screen.get_pipe_aware_line(
                "%s%s%s" % (warn_c, row, reset_c))
        else:
            result_str += screen.get_pipe_aware_line(row)

    result_str += screen.get_pipe_aware_line("")
    return result_str


def show_softirq_counts(no_pipe):
    result_str = ""
    sirq_path = sos_home + "/proc/softirqs"
    if not os.path.isfile(sirq_path):
        return screen.get_pipe_aware_line("proc/softirqs not found")

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = reset_c = ""

    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sSOFTIRQ COUNTS BY TYPE (from /proc/softirqs)%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line("")

    try:
        with open(sirq_path) as f:
            lines = f.readlines()
    except:
        return result_str + screen.get_pipe_aware_line("Error reading proc/softirqs")

    if not lines:
        return result_str + screen.get_pipe_aware_line("proc/softirqs is empty")

    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, lines[0].rstrip(), reset_c))

    type_totals = []

    for line in lines[1:]:
        if is_cmd_stopped and is_cmd_stopped():
            break

        line = line.rstrip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 2:
            result_str += screen.get_pipe_aware_line(line)
            continue

        irq_type = parts[0].rstrip(":")
        counts = []
        for p in parts[1:]:
            try:
                counts.append(int(p))
            except ValueError:
                break

        total = sum(counts)
        type_totals.append((irq_type, total))
        result_str += screen.get_pipe_aware_line(line)

    result_str += screen.get_pipe_aware_line("")
    result_str += screen.get_pipe_aware_line(
        "%s%-16s %20s%s" % (hdr_c, "Type", "Total", reset_c))
    result_str += screen.get_pipe_aware_line("-" * 38)

    for irq_type, total in sorted(type_totals, key=lambda x: x[1], reverse=True):
        result_str += screen.get_pipe_aware_line(
            "%-16s %20s" % (irq_type, "{:,}".format(total)))

    result_str += screen.get_pipe_aware_line("")
    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
irqinfo -- Interrupt and softirq analysis

Examples:
    irqinfo            Show softirq summary and interrupt overview
    irqinfo -s         Detailed softirq/softnet_stat analysis
    irqinfo -i         Full interrupt table
    irqinfo -t         Show related kernel tunables
    irqinfo -a         Show all interrupt and softirq information
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

def run_irqinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    global sos_home, is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func
    sos_home = env_vars["sos_home"]

    usage = "Usage: irqinfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-i', '--interrupts', dest='show_interrupts',
                  action='store_true',
                  help='show full interrupt table')
    op.add_option('-s', '--softirq', dest='show_softirq',
                  action='store_true',
                  help='detailed softirq/softnet_stat analysis')
    op.add_option('-t', '--tunables', dest='show_tunables',
                  action='store_true',
                  help='show related kernel tunables')
    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all interrupt and softirq information')

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

    result_str = ""
    if o.show_all:
        result_str += show_softirq(no_pipe)
        result_str += show_softirq_counts(no_pipe)
        result_str += show_softirq_tunables(no_pipe)
        result_str += show_interrupts(no_pipe, show_all_cpus=True)
    elif o.show_interrupts:
        result_str += show_interrupts(no_pipe)
    elif o.show_softirq:
        result_str += show_softirq(no_pipe)
        result_str += show_softirq_counts(no_pipe)
    elif o.show_tunables:
        result_str += show_softirq_tunables(no_pipe)
    else:
        result_str += show_softirq(no_pipe)
        intr_path = sos_home + "/proc/interrupts"
        if os.path.isfile(intr_path):
            result_str += screen.get_pipe_aware_line("")
            try:
                with open(intr_path) as f:
                    lines = f.readlines()
                src_count = len(lines) - 1 if lines else 0
                cpu_names = lines[0].split() if lines else []
                result_str += screen.get_pipe_aware_line(
                    "Interrupt overview: %d sources across %d CPUs "
                    "(use -i for full table)" % (src_count, len(cpu_names)))
            except:
                pass

    return result_str
