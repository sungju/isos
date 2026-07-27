import sys
import time
from optparse import OptionParser
from io import StringIO
import os

import ansicolor
import screen


def description():
    return "Shows process related information"


def add_command():
    return True


cmd_name = "psinfo"
def get_command_info():
    return { "%s" % cmd_name : run_psinfo }


COLOR_RED   = ""
COLOR_MAGENTA = ""
COLOR_GREEN = ""
COLOR_RESET = ""

def set_color_table(no_pipe):
    global COLOR_RED, COLOR_MAGENTA, COLOR_GREEN, COLOR_RESET

    if no_pipe:
        COLOR_RED   = ansicolor.get_color(ansicolor.LIGHTRED)
        COLOR_MAGENTA = ansicolor.get_color(ansicolor.MAGENTA)
        COLOR_GREEN = ansicolor.get_color(ansicolor.GREEN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_RED = COLOR_MAGENTA = COLOR_GREEN = COLOR_RESET = ""


total_vsz = 0
total_rss = 0

def calc_total_mem(lines):
    global total_vsz
    global total_rss

    total_vsz = total_rss = 0

    for line in lines:
        words = line.split()
        if words[1] == "=":
            continue

        try:
            total_vsz = total_vsz + int(words[4])
            total_rss = total_rss + int(words[5])
        except:
            pass


def get_colored_line(line, no_pipe, is_header=False):
    """
    Apply context-based coloring to ps output line.

    Args:
        line: The ps output line
        no_pipe: Whether outputting to terminal
        is_header: True if this is the header line

    Returns:
        Colored line string
    """
    words = line.split()
    if len(words) < 2:
        return line

    if words[1] == "-":  # Don't need to show empty process
        return ""

    if not no_pipe:
        return line

    # For header line, color with COLOR_HEADER
    if is_header:
        return screen.COLOR_HEADER + line + screen.COLOR_RESET

    # For data lines, apply whole-line coloring based on resource usage
    # Typical ps format: USER   PID  %CPU %MEM    VSZ   RSS TTY STAT START   TIME COMMAND
    try:
        # Check CPU and memory usage to determine line color
        # words[2] = %CPU, words[3] = %MEM
        if len(words) > 3:
            cpu_val = float(words[2])
            mem_val = float(words[3])

            # High CPU or Memory - use CRITICAL color for entire line
            if cpu_val > 50.0 or mem_val > 50.0:
                return screen.COLOR_CRITICAL + line + screen.COLOR_RESET
            # Medium CPU or Memory - use WARNING color for entire line
            elif cpu_val > 20.0 or mem_val > 20.0:
                return screen.COLOR_WARNING + line + screen.COLOR_RESET
            # Low usage - no color (normal black text)
    except (ValueError, IndexError):
        # If parsing fails, just return the original line with no color
        pass

    return line


def get_size_str(size, coloring = False):
    size_str = ""
    if size > (1024 * 1024 * 1024): # GiB
        size_str = "%.1f GiB" % (size / (1024*1024*1024))
        if coloring == True:
            size_str = COLOR_RED + size_str + COLOR_RESET
    elif size > (1024 * 1024): # MiB
        size_str = "%.1f MiB" % (size / (1024*1024))
        if coloring == True:
            size_str = COLOR_MAGENTA + size_str + COLOR_RESET
    elif size > (1024): # KiB
        size_str = "%.1f KiB" % (size / (1024))
        if coloring == True:
            size_str = COLOR_GREEN + size_str + COLOR_RESET
    else:
        size_str = "%.0f B" % (size)

    return size_str


def sorted_by(lines, sort_by, reverse=True):
    result_list = [lines[0]]
    del lines[0]
    sort_idx = 0
    if sort_by == "cpu":
        sort_idx = 2
    elif sort_by == "vsz":
        sort_idx = 4
    elif sort_by == "rss":
        sort_idx = 5

    sorted_list = sorted(lines, key=lambda x: float(x.split()[sort_idx]), reverse=reverse)
    return result_list + sorted_list


def remove_empty_ps_line(lines):
    result_list = []
    for line in lines:
        words = line.split()
        if len(words) < 2 or words[1] == "-":
            continue
        result_list.append(line)

    return result_list


def filter_by_keyword(lines, keyword):
    """Keep header plus lines whose COMMAND field contains keyword (case-insensitive)."""
    if not keyword:
        return lines
    kw = keyword.lower()
    result = [lines[0]]  # always keep header
    for line in lines[1:]:
        words = line.split()
        # COMMAND starts at index 10 in standard ps output
        cmd = " ".join(words[10:]).lower() if len(words) > 10 else ""
        if kw in cmd:
            result.append(line)
    return result


def read_ps_basic(ps_path, no_pipe, options):
    global total_vsz
    global total_rss

    set_color_table(no_pipe)
    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str = ""
    with open(ps_path) as f:
        lines = remove_empty_ps_line(f.readlines())
        lines = filter_by_keyword(lines, getattr(options, 'keyword', ''))
        total_lines = len(lines)
        if options.lines_to_print > 0:
            print_count = options.lines_to_print + 1
        else:
            print_count = total_lines

        if options.sort_by != "":
            lines = sorted_by(lines, options.sort_by,\
                    print_count != total_lines)

        calc_total_mem(lines)
        for idx, line in enumerate(lines):
            if print_count == 0:
                break
            # First line is the header
            is_header = (idx == 0)
            line = get_colored_line(line, no_pipe, is_header)
            if line != "":
                print_count = print_count - 1
                if no_pipe:
                    print(line)
                else:
                    result_str = result_str + line + "\n"

        if options.lines_to_print > 0 and \
                (options.lines_to_print + 1) != total_lines:
            line = "\n\t\t......"
            if no_pipe:
                print(line)
            else:
                result_str = result_str + line + "\n"

        # Format total summary with context-based colors
        if no_pipe:
            total_str = ("\n\t%sTotal VSZ%s = %s, %sTotal RSS%s = %s\n" % (
                screen.COLOR_TITLE, screen.COLOR_RESET,
                get_size_str(total_vsz * 1024, True),
                screen.COLOR_TITLE, screen.COLOR_RESET,
                get_size_str(total_rss * 1024, True)
            ))
        else:
            total_str = ("\n\tTotal VSZ = %s, Total RSS = %s\n" % (
                get_size_str(total_vsz * 1024, False),
                get_size_str(total_rss * 1024, False)
            ))

        if no_pipe:
            print(total_str)
        else:
            result_str = result_str + total_str

    return result_str


def show_ps_tree(sos_home, no_pipe, options):
    result_str = ""
    pid = options.process_details

    # Color setup
    title_color = screen.COLOR_TITLE if no_pipe else ""
    info_color = screen.COLOR_INFO if no_pipe else ""
    important_color = screen.COLOR_IMPORTANT if no_pipe else ""
    reset_color = screen.COLOR_RESET if no_pipe else ""

    try:
        with open(sos_home + "/sos_commands/process/pidstat_-tl") as f:
            for line in f:
                words = line.split()
                if len(words) > 3 and words[2] == pid:
                    formatted_line = (
                        "%sCPU Usage:%s %s%s%s, %susr:%s %s, %ssys:%s %s, "
                        "%sguest:%s %s, %swait:%s %s" % (
                            title_color, reset_color,
                            important_color, words[8], reset_color,
                            info_color, reset_color, words[4],
                            info_color, reset_color, words[5],
                            info_color, reset_color, words[6],
                            info_color, reset_color, words[7]
                        )
                    )
                    result_str = result_str + screen.get_pipe_aware_line(formatted_line)
    except Exception as e:
        pass

    try:
        with open(sos_home + "/sos_commands/process/ps_auxwwwm") as f:
            for line in f:
                words = line.split()
                if len(words) > 7 and words[1] == pid:
                    formatted_line = (
                        "%sMEM Usage:%s %s%s%s, %sVSZ:%s %s, %sRSS:%s %s" % (
                            title_color, reset_color,
                            important_color, words[3], reset_color,
                            info_color, reset_color, get_size_str(int(words[4])),
                            info_color, reset_color, get_size_str(int(words[5]))
                        )
                    )
                    result_str = result_str + screen.get_pipe_aware_line(formatted_line)
                    break
        result_str = result_str + screen.get_pipe_aware_line("")
    except Exception as e:
        pass

    try:
        with open(sos_home + "/sos_commands/process/ps_-elfL") as f:
            for line in f:
                if pid in line:
                    words = line.split()
                    if len(words) < 17:
                        continue
                    pstate = words[1]
                    if words[3] == words[5]: # thread leader
                        cmd_str = line[line.find(words[15]) + len(words[15]):].strip()
                        formatted_line = "%s%s%s (%s) [%s] by %s" % (
                            screen.COLOR_HIGHLIGHT if no_pipe else "",
                            cmd_str,
                            reset_color,
                            pid, pstate, words[2]
                        )
                        result_str = result_str + screen.get_pipe_aware_line(formatted_line)
                    else:
                        wchan = words[12]
                        result_str = result_str + screen.get_pipe_aware_line(
                            "\t+- %s (%s) [%s]" % (words[5], wchan, pstate))
    except Exception as e:
        pass

    proc_dir = sos_home + ("/proc/%s" % (pid))
    try:
        with open(proc_dir + "/stack") as f:
            title_line = "%sCall Trace:%s\n" % (title_color, reset_color)
            result_str = result_str + screen.get_pipe_aware_line("\n" + title_line)
            for line in f:
                result_str = result_str + screen.get_pipe_aware_line("  " + line)
    except Exception as e:
        pass

    try:
        with open(proc_dir + "/limits") as f:
            result_str = result_str + screen.get_pipe_aware_line("\n\n")
            for line in f:
                result_str = result_str + screen.get_pipe_aware_line(line)
    except Exception as e:
        pass

    return result_str


def show_process_details(sos_home, no_pipe, options):
    result_str = show_ps_tree(sos_home, no_pipe, options)


    return result_str


def parse_ps_states(sos_home):
    """Parse ps output and categorize processes by state."""
    ps_path = sos_home + "/ps"
    states = {'R': 0, 'S': 0, 'D': 0, 'Z': 0, 'T': 0, 'I': 0, 'other': 0}
    dstate_procs = []
    zombie_procs = []
    all_procs = []
    total = 0

    if not os.path.isfile(ps_path):
        return states, dstate_procs, zombie_procs, all_procs, total

    try:
        with open(ps_path) as f:
            lines = f.readlines()
            for line in lines[1:]:
                words = line.split()
                if len(words) < 11 or words[1] == "-":
                    continue
                total += 1
                stat = words[7]
                if not stat:
                    continue

                first_char = stat[0]
                if first_char in states:
                    states[first_char] += 1
                else:
                    states['other'] += 1

                try:
                    proc_info = {
                        'user': words[0],
                        'pid': words[1],
                        'cpu': float(words[2]),
                        'mem': float(words[3]),
                        'vsz': int(words[4]),
                        'rss': int(words[5]),
                        'stat': stat,
                        'cmd': " ".join(words[10:]),
                    }
                    all_procs.append(proc_info)

                    if first_char == 'D':
                        dstate_procs.append(proc_info)
                    elif first_char == 'Z':
                        zombie_procs.append(proc_info)
                except (ValueError, IndexError):
                    pass
    except:
        pass

    return states, dstate_procs, zombie_procs, all_procs, total


def show_process_summary(sos_home, no_pipe):
    result_str = ""
    states, dstate_procs, zombie_procs, _, total = parse_ps_states(sos_home)

    if total == 0:
        return result_str

    if no_pipe:
        title_c = screen.COLOR_TITLE
        info_c = screen.COLOR_INFO
        warn_c = screen.COLOR_WARNING
        crit_c = screen.COLOR_CRITICAL
        reset_c = screen.COLOR_RESET
    else:
        title_c = info_c = warn_c = crit_c = reset_c = ""

    parts = ["%sTotal:%s %d" % (title_c, reset_c, total)]

    if states['R'] > 0:
        parts.append("%s%d running%s" % (info_c, states['R'], reset_c))
    if states['S'] > 0:
        parts.append("%d sleeping" % states['S'])
    if states['I'] > 0:
        parts.append("%d idle" % states['I'])
    if states['T'] > 0:
        parts.append("%s%d stopped%s" % (warn_c, states['T'], reset_c))
    if states['D'] > 0:
        parts.append("%s%d D-state (uninterruptible)%s" % (
            crit_c, states['D'], reset_c))
    if states['Z'] > 0:
        parts.append("%s%d zombie%s" % (crit_c, states['Z'], reset_c))

    result_str += screen.get_pipe_aware_line(", ".join(parts))
    result_str += screen.get_pipe_aware_line("")

    return result_str


def show_dstate_processes(sos_home, no_pipe):
    result_str = ""
    _, dstate_procs, _, _, _ = parse_ps_states(sos_home)

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        crit_c = screen.COLOR_CRITICAL
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = crit_c = reset_c = ""

    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sD-STATE (UNINTERRUPTIBLE SLEEP) PROCESSES%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, "=" * 70, reset_c))

    if not dstate_procs:
        result_str += screen.get_pipe_aware_line("No D-state processes found")
        return result_str

    result_str += screen.get_pipe_aware_line(
        "%s%d D-state process(es) found:%s" % (
            crit_c, len(dstate_procs), reset_c))
    result_str += screen.get_pipe_aware_line("")

    hdr = "%-8s %8s %6s %6s  %s" % ("USER", "PID", "%CPU", "%MEM", "COMMAND")
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    result_str += screen.get_pipe_aware_line("-" * 70)

    for proc in dstate_procs:
        if is_cmd_stopped and is_cmd_stopped():
            break
        line = "%-8s %8s %6.1f %6.1f  %s" % (
            proc['user'][:8], proc['pid'],
            proc['cpu'], proc['mem'], proc['cmd'][:50])
        result_str += screen.get_pipe_aware_line(
            "%s%s%s" % (crit_c, line, reset_c))

        proc_stack = sos_home + "/proc/%s/stack" % proc['pid']
        if os.path.isfile(proc_stack):
            try:
                with open(proc_stack) as f:
                    for sline in f:
                        sline = sline.strip()
                        if sline and not sline.startswith("0x"):
                            result_str += screen.get_pipe_aware_line(
                                "    %s" % sline)
            except:
                pass
            result_str += screen.get_pipe_aware_line("")

    return result_str


def show_zombie_processes(sos_home, no_pipe):
    result_str = ""
    _, _, zombie_procs, _, _ = parse_ps_states(sos_home)

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        crit_c = screen.COLOR_CRITICAL
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = crit_c = reset_c = ""

    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sZOMBIE PROCESSES%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, "=" * 70, reset_c))

    if not zombie_procs:
        result_str += screen.get_pipe_aware_line("No zombie processes found")
        return result_str

    result_str += screen.get_pipe_aware_line(
        "%s%d zombie process(es) found:%s" % (
            crit_c, len(zombie_procs), reset_c))
    result_str += screen.get_pipe_aware_line("")

    hdr = "%-8s %8s %6s %6s  %s" % ("USER", "PID", "%CPU", "%MEM", "COMMAND")
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    result_str += screen.get_pipe_aware_line("-" * 70)

    for proc in zombie_procs:
        if is_cmd_stopped and is_cmd_stopped():
            break
        line = "%-8s %8s %6.1f %6.1f  %s" % (
            proc['user'][:8], proc['pid'],
            proc['cpu'], proc['mem'], proc['cmd'])
        result_str += screen.get_pipe_aware_line(
            "%s%s%s" % (crit_c, line, reset_c))

    return result_str


def show_top_consumers(sos_home, no_pipe, count=5):
    result_str = ""
    _, _, _, all_procs, _ = parse_ps_states(sos_home)

    if not all_procs:
        return result_str

    if no_pipe:
        hdr_c = screen.COLOR_HEADER
        title_c = screen.COLOR_TITLE
        warn_c = screen.COLOR_WARNING
        reset_c = screen.COLOR_RESET
    else:
        hdr_c = title_c = warn_c = reset_c = ""

    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, "=" * 70, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%sTOP RESOURCE CONSUMERS%s" % (hdr_c, reset_c))
    result_str += screen.get_pipe_aware_line(
        "%s%s%s" % (hdr_c, "=" * 70, reset_c))

    top_cpu = sorted(all_procs, key=lambda x: x['cpu'], reverse=True)[:count]
    top_mem = sorted(all_procs, key=lambda x: x['rss'], reverse=True)[:count]

    result_str += screen.get_pipe_aware_line(
        "\n%sTop %d by CPU:%s" % (title_c, count, reset_c))
    hdr = "  %-8s %8s %6s  %s" % ("USER", "PID", "%CPU", "COMMAND")
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    for proc in top_cpu:
        color = warn_c if proc['cpu'] > 20.0 else ""
        result_str += screen.get_pipe_aware_line(
            "%s  %-8s %8s %6.1f  %s%s" % (
                color, proc['user'][:8], proc['pid'],
                proc['cpu'], proc['cmd'][:50], reset_c))

    result_str += screen.get_pipe_aware_line(
        "\n%sTop %d by Memory (RSS):%s" % (title_c, count, reset_c))
    hdr = "  %-8s %8s %10s  %s" % ("USER", "PID", "RSS", "COMMAND")
    result_str += screen.get_pipe_aware_line("%s%s%s" % (hdr_c, hdr, reset_c))
    for proc in top_mem:
        rss_str = get_size_str(proc['rss'] * 1024, no_pipe)
        color = warn_c if proc['mem'] > 20.0 else ""
        result_str += screen.get_pipe_aware_line(
            "%s  %-8s %8s %10s  %s%s" % (
                color, proc['user'][:8], proc['pid'],
                rss_str, proc['cmd'][:50], reset_c))

    result_str += screen.get_pipe_aware_line("")
    return result_str


def print_pid_help_msg(no_pipe):
    msg = '''psinfo -p  --  Show detailed information for a process

SYNOPSIS
    psinfo -p <PID>

DESCRIPTION
    Displays detailed information for a specific process ID, including:
    - CPU usage: %CPU, user, sys, guest, wait (from pidstat -tl)
    - Memory usage: %MEM, VSZ, RSS (from ps auxwwwm)
    - Process tree: command, threads, wait channels, state (from ps -elfL)
    - Call trace: kernel stack from /proc/<PID>/stack
    - Resource limits from /proc/<PID>/limits

OPTIONS
    -p, --pid <PID>
        Show details of the specified process.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> psinfo -p 1234
    example.com> psinfo -p 1
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Examples:
    # To see only specified number of lines
    > psinfo -l 10

    # To sort by resource type. It shows the highest at the bottom
    # unless specifying line numbers with -l
    > psinfo -s rss

    # To filter process list by task name (case-insensitive)
    > psinfo -k java
    > psinfo -k httpd -s rss

    # Process state analysis
    > psinfo -S            Show process state summary
    > psinfo -d            Show D-state processes with stack traces
    > psinfo -z            Show zombie processes
    > psinfo -t            Show top CPU and memory consumers
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


is_cmd_stopped = None
def run_psinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-l', '--lines', dest='lines_to_print', default=0,
            action='store', type="int",
            help="Shows only specified number of lines from the top")
    op.add_option('-p', '--pid', dest='process_details', default='',
            action='store', type="string",
            help="Shows details of a specified process")
    op.add_option('-k', '--keyword', dest='keyword', default='',
            action='store', type='string',
            help='Filter process list by task name (case-insensitive substring match)')
    op.add_option('-s', '--sort', dest='sort_by', default="",
            action='store', type="string",
            help="Sorts the output by one of the below options\n" + \
                    "\tcpu : CPU usage\n" + \
                    "\tvsz : Virtual memory usage\n" + \
                    "\trss : RSS usage\n")

    op.add_option('-d', '--dstate', dest='show_dstate', action='store_true',
                  help='Show D-state (uninterruptible sleep) processes')
    op.add_option('-z', '--zombie', dest='show_zombie', action='store_true',
                  help='Show zombie processes')
    op.add_option('-t', '--top', dest='show_top', action='store_true',
                  help='Show top CPU and memory consumers')
    op.add_option('-S', '--summary', dest='show_summary', action='store_true',
                  help='Show process state summary')

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""


    if o.help or show_help == True:
        if o.process_details:
            return print_pid_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)

    sos_home = env_vars["sos_home"]
    screen.init_data(no_pipe, 1, is_cmd_stopped)

    if o.show_dstate:
        return show_dstate_processes(sos_home, no_pipe)
    elif o.show_zombie:
        return show_zombie_processes(sos_home, no_pipe)
    elif o.show_top:
        return show_top_consumers(sos_home, no_pipe)
    elif o.show_summary:
        return show_process_summary(sos_home, no_pipe)
    elif o.process_details:
        result_str = show_process_details(sos_home, no_pipe, o)
    else:
        result_str = show_process_summary(sos_home, no_pipe)
        result_str += read_ps_basic(sos_home + "/ps", no_pipe, o)

    return result_str
