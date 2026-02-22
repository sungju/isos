import sys
import time
import os
from os import listdir
from os.path import isfile, join, isdir, exists
from optparse import OptionParser
from io import StringIO
import re
from collections import defaultdict

import ansicolor
import screen


def description():
    return "Shows cron related infomation"


def add_command():
    return True


def get_command_info():
    return { "cron": run_croninfo }


def read_cron_basic(log_path, no_pipe, show_path=False, sos_home=""):

    if show_path:
        file_name = log_path.replace(sos_home, "")
        result_str = "=" * 10 + ("> %s <" % file_name) + "=" * 10
    else:
        result_str = ""
    try:
        if no_pipe:
            if show_path:
                print(result_str)
            result_str = ""
        else:
            if show_path:
                result_str = result_str + "\n"

        with open(log_path) as f:
            for line in f:
                if is_cmd_stopped():
                    return result_str

                line = screen.get_colored_line(line)
                if line != "":
                    if no_pipe:
                        print(line)
                    else:
                        result_str = result_str + line + "\n"

            if no_pipe:
                print("")
            else:
                result_str = result_str + "\n"
    except:
        result_str = ""
        pass

    return result_str


def get_files_in_path(mypath):
    if not isdir(mypath):
        return []

    if not mypath.endswith("/"):
        mypath = mypath + "/"

    try:
        onlyfiles = [mypath + f for f in listdir(mypath) if isfile(join(mypath, f))]
        return onlyfiles
    except:
        return []


def get_cron_files(sos_home, include_all=False):
    file_list = []

    # Main crontab
    crontab = sos_home + "/etc/crontab"
    if exists(crontab):
        file_list.append(crontab)

    # Standard directories
    file_list += get_files_in_path(sos_home + "/etc/cron.hourly")
    file_list += get_files_in_path(sos_home + "/etc/cron.daily")
    file_list += get_files_in_path(sos_home + "/etc/cron.weekly")
    file_list += get_files_in_path(sos_home + "/etc/cron.monthly")

    # cron.d directory (was missing before!)
    file_list += get_files_in_path(sos_home + "/etc/cron.d")

    # sos_commands/cron
    file_list += get_files_in_path(sos_home + "/sos_commands/cron")

    # User crontabs if requested
    if include_all:
        file_list += get_files_in_path(sos_home + "/var/spool/cron")

    return file_list


def read_log_with_filter(log_path, no_pipe, filter_func=None):
    result_str = ""
    try:
        with open(log_path) as f:
            for line in f:
                if is_cmd_stopped():
                    return result_str

                if filter_func is None or filter_func(line):
                    line = screen.get_colored_line(line)
                    if line != "":
                        if no_pipe:
                            print(line)
                        else:
                            result_str = result_str + line + "\n"
    except:
        pass

    return result_str


def show_cron_log(sos_home, no_pipe, errors_only=False):
    log_path = sos_home + "/var/log/cron"
    if not exists(log_path):
        return "Cron log not found\n"

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    if errors_only:
        # Filter for errors, failures, or other problematic patterns
        def error_filter(line):
            line_lower = line.lower()
            return any(keyword in line_lower for keyword in
                      ['error', 'fail', 'cannot', 'unable', 'denied', 'fatal'])
        return read_log_with_filter(log_path, no_pipe, error_filter)
    else:
        return read_log_with_filter(log_path, no_pipe)


def show_cron_stats(sos_home, no_pipe):
    log_path = sos_home + "/var/log/cron"
    if not exists(log_path):
        return "Cron log not found\n"

    # Set up colors
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_RESET = ""

    result_str = ""
    job_counts = defaultdict(int)
    user_counts = defaultdict(int)
    anacron_jobs = defaultdict(int)
    total_lines = 0

    try:
        with open(log_path) as f:
            for line in f:
                if is_cmd_stopped():
                    return result_str

                total_lines += 1

                # Match CROND[pid]: (user) CMD (command)
                cmd_match = re.search(r'CROND\[\d+\]:\s+\((\w+)\)\s+CMD\s+\((.+)\)', line)
                if cmd_match:
                    user = cmd_match.group(1)
                    cmd = cmd_match.group(2)
                    user_counts[user] += 1
                    job_counts[cmd] += 1

                # Match anacron jobs
                anacron_match = re.search(r"anacron\[\d+\]:\s+Job\s+`([^']+)'", line)
                if anacron_match:
                    job = anacron_match.group(1)
                    anacron_jobs[job] += 1

    except:
        return "Error reading cron log\n"

    # Build output
    result_str += COLOR_CYAN + "=== Cron Execution Statistics ===" + COLOR_RESET + "\n"
    result_str += "\nTotal log lines: %d\n" % total_lines

    if user_counts:
        result_str += COLOR_YELLOW + "\n--- Jobs by User ---\n" + COLOR_RESET
        for user in sorted(user_counts.keys()):
            result_str += "  %s: %d executions\n" % (user, user_counts[user])

    if job_counts:
        result_str += COLOR_YELLOW + "\n--- Most Frequent Cron Jobs ---\n" + COLOR_RESET
        sorted_jobs = sorted(job_counts.items(), key=lambda x: x[1], reverse=True)
        for cmd, count in sorted_jobs[:10]:  # Top 10
            result_str += "  [%d] %s\n" % (count, cmd)

    if anacron_jobs:
        result_str += COLOR_YELLOW + "\n--- Anacron Jobs ---\n" + COLOR_RESET
        for job in sorted(anacron_jobs.keys()):
            result_str += "  %s: %d executions\n" % (job, anacron_jobs[job])

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_systemd_timers(sos_home, no_pipe):
    timer_path = sos_home + "/sos_commands/systemd/systemctl_list-timers_--all"
    if not exists(timer_path):
        return "Systemd timer information not found\n"

    # Set up colors
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    result_str = COLOR_CYAN + "=== Systemd Timers (Modern Alternative to Cron) ===" + COLOR_RESET + "\n\n"

    if no_pipe:
        print(result_str)
        result_str = ""

    screen.init_data(no_pipe, 1, is_cmd_stopped)
    return result_str + read_cron_basic(timer_path, no_pipe, False, sos_home)


def show_cron_config(sos_home, no_pipe):
    # Set up colors
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    result_str = ""
    config_files = [
        (sos_home + "/etc/anacrontab", "Anacron Configuration"),
        (sos_home + "/etc/sysconfig/crond", "Crond Daemon Configuration"),
        (sos_home + "/etc/cron.allow", "Cron Allow List"),
        (sos_home + "/etc/cron.deny", "Cron Deny List"),
        (sos_home + "/usr/lib/systemd/system/crond.service", "Crond Systemd Service"),
    ]

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    for file_path, title in config_files:
        if exists(file_path):
            header = COLOR_CYAN + ("=== %s ===" % title) + COLOR_RESET + "\n"
            if no_pipe:
                print(header)
            else:
                result_str += header

            result_str += read_cron_basic(file_path, no_pipe, False, sos_home)

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Shows cron-related information from the sosreport.

Examples:
  cron           Show cron configuration files (default)
  cron -a        Show all cron files including user crontabs
  cron -l        Show cron log (/var/log/cron)
  cron -e        Show only errors from cron log
  cron -s        Show execution statistics from cron log
  cron -t        Show systemd timers (modern alternative to cron)
  cron -c        Show configuration files (anacrontab, sysconfig, access control)
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

def run_croninfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: cron [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all cron files including user crontabs')
    op.add_option('-l', '--log', dest='show_log', action='store_true',
                  help='show cron log (/var/log/cron)')
    op.add_option('-e', '--errors', dest='show_errors', action='store_true',
                  help='show only errors from cron log')
    op.add_option('-s', '--stats', dest='show_stats', action='store_true',
                  help='show execution statistics from cron log')
    op.add_option('-t', '--timers', dest='show_timers', action='store_true',
                  help='show systemd timers (modern alternative to cron)')
    op.add_option('-c', '--config', dest='show_config', action='store_true',
                  help='show configuration files (anacrontab, sysconfig, access control)')

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
    if o.show_log:
        result_str = show_cron_log(sos_home, no_pipe, errors_only=False)
    elif o.show_errors:
        result_str = show_cron_log(sos_home, no_pipe, errors_only=True)
    elif o.show_stats:
        result_str = show_cron_stats(sos_home, no_pipe)
    elif o.show_timers:
        result_str = show_systemd_timers(sos_home, no_pipe)
    elif o.show_config:
        result_str = show_cron_config(sos_home, no_pipe)
    else:
        # Default: show cron files
        screen.init_data(no_pipe, 1, is_cmd_stopped)
        cronfile_list = get_cron_files(sos_home, include_all=o.show_all)

        for cfile in cronfile_list:
            if is_cmd_stopped():
                break
            result_str = result_str + read_cron_basic(cfile, no_pipe, True, sos_home)

    return result_str
