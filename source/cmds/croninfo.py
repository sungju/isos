"""
Cron Information Command

Displays cron-related information from sosreports including:
- Cron configuration files
- Cron logs and execution statistics
- Systemd timers (modern alternative)
- Configuration settings
"""

import sys
import os
from os import listdir
from os.path import isfile, join, isdir, exists
from optparse import OptionParser
from io import StringIO
import re
from collections import defaultdict

import ansicolor
import screen
from cmd_helpers import ColorManager, OutputBuilder, get_sos_file_path


def description():
    return "Shows cron related information"


def add_command():
    return True


def get_command_info():
    return {"cron": run_croninfo}


# Constants
CRON_DIRS = [
    "etc/cron.hourly",
    "etc/cron.daily",
    "etc/cron.weekly",
    "etc/cron.monthly",
    "etc/cron.d",
    "sos_commands/cron"
]

ERROR_KEYWORDS = ['error', 'fail', 'cannot', 'unable', 'denied', 'fatal']


def get_files_in_path(mypath):
    """
    Get list of files in directory.

    Args:
        mypath: Directory path

    Returns:
        List of file paths, or empty list if directory doesn't exist
    """
    if not isdir(mypath):
        return []

    try:
        return [join(mypath, f) for f in listdir(mypath)
                if isfile(join(mypath, f))]
    except (IOError, OSError):
        return []


def get_cron_files(sos_home, include_all=False):
    """
    Get list of cron-related files from sosreport.

    Args:
        sos_home: Root of sosreport
        include_all: Include user crontabs from /var/spool/cron

    Returns:
        List of file paths
    """
    file_list = []

    # Main crontab
    crontab = get_sos_file_path(sos_home, "etc", "crontab")
    if exists(crontab):
        file_list.append(crontab)

    # Standard directories
    for cron_dir in CRON_DIRS:
        dir_path = get_sos_file_path(sos_home, cron_dir)
        file_list.extend(get_files_in_path(dir_path))

    # User crontabs if requested
    if include_all:
        user_cron_path = get_sos_file_path(sos_home, "var", "spool", "cron")
        file_list.extend(get_files_in_path(user_cron_path))

    return file_list


def read_cron_file(file_path, sos_home, colors, output, show_path=True):
    """
    Read and display cron file with syntax highlighting.

    Args:
        file_path: Path to cron file
        sos_home: Sosreport root (for relative path display)
        colors: ColorManager instance
        output: OutputBuilder instance
        show_path: Show file path header
    """
    if show_path:
        rel_path = file_path.replace(sos_home, "")
        header = "=" * 10 + (" %s " % rel_path) + "=" * 10
        output.add_colored_line(header, colors.cyan, colors.reset)

    try:
        with open(file_path, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    return

                line = screen.get_colored_line(line.rstrip())
                if line:
                    output.add_line(line)

        output.add_line("")

    except (IOError, OSError):
        pass


def show_cron_log(sos_home, colors, output, errors_only=False):
    """
    Show cron log with optional error filtering.

    Args:
        sos_home: Sosreport root
        colors: ColorManager instance
        output: OutputBuilder instance
        errors_only: Only show error lines
    """
    log_path = get_sos_file_path(sos_home, "var", "log", "cron")

    if not exists(log_path):
        output.add_line("Cron log not found")
        return

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    try:
        with open(log_path, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    return

                # Filter for errors if requested
                if errors_only:
                    line_lower = line.lower()
                    if not any(keyword in line_lower for keyword in ERROR_KEYWORDS):
                        continue

                line = screen.get_colored_line(line.rstrip())
                if line:
                    output.add_line(line)

    except (IOError, OSError):
        output.add_line("Error reading cron log")


def show_cron_stats(sos_home, colors, output):
    """
    Show execution statistics from cron log.

    Args:
        sos_home: Sosreport root
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    log_path = get_sos_file_path(sos_home, "var", "log", "cron")

    if not exists(log_path):
        output.add_line("Cron log not found")
        return

    # Precompile regex patterns
    crond_pattern = re.compile(r'CROND\[\d+\]:\s+\((\w+)\)\s+CMD\s+\((.+)\)')
    anacron_pattern = re.compile(r"anacron\[\d+\]:\s+Job\s+`([^']+)'")

    # Statistics counters
    job_counts = defaultdict(int)
    user_counts = defaultdict(int)
    anacron_jobs = defaultdict(int)
    total_lines = 0

    try:
        with open(log_path, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    return

                total_lines += 1

                # Match CROND executions
                cmd_match = crond_pattern.search(line)
                if cmd_match:
                    user = cmd_match.group(1)
                    cmd = cmd_match.group(2)
                    user_counts[user] += 1
                    job_counts[cmd] += 1
                    continue

                # Match anacron jobs
                anacron_match = anacron_pattern.search(line)
                if anacron_match:
                    job = anacron_match.group(1)
                    anacron_jobs[job] += 1

    except (IOError, OSError):
        output.add_line("Error reading cron log")
        return

    # Build statistics output
    output.add_colored_line("=== Cron Execution Statistics ===",
                           colors.cyan, colors.reset)
    output.add_line("")
    output.add_line("Total log lines: %d" % total_lines)

    if user_counts:
        output.add_line("")
        output.add_colored_line("--- Jobs by User ---",
                               colors.yellow, colors.reset)
        for user in sorted(user_counts.keys()):
            output.add_line("  %s: %d executions" % (user, user_counts[user]))

    if job_counts:
        output.add_line("")
        output.add_colored_line("--- Most Frequent Cron Jobs (Top 10) ---",
                               colors.yellow, colors.reset)
        sorted_jobs = sorted(job_counts.items(),
                           key=lambda x: x[1], reverse=True)
        for cmd, count in sorted_jobs[:10]:
            output.add_line("  [%d] %s" % (count, cmd))

    if anacron_jobs:
        output.add_line("")
        output.add_colored_line("--- Anacron Jobs ---",
                               colors.yellow, colors.reset)
        for job in sorted(anacron_jobs.keys()):
            output.add_line("  %s: %d executions" % (job, anacron_jobs[job]))


def show_systemd_timers(sos_home, colors, output):
    """
    Show systemd timer information.

    Args:
        sos_home: Sosreport root
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    timer_path = get_sos_file_path(sos_home, "sos_commands", "systemd",
                                   "systemctl_list-timers_--all")

    if not exists(timer_path):
        output.add_line("Systemd timer information not found")
        return

    output.add_colored_line("=== Systemd Timers (Modern Alternative to Cron) ===",
                           colors.cyan, colors.reset)
    output.add_line("")

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    try:
        with open(timer_path, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    return

                line = screen.get_colored_line(line.rstrip())
                output.add_line(line)

    except (IOError, OSError):
        output.add_line("Error reading systemd timer information")


def show_cron_config(sos_home, colors, output):
    """
    Show cron configuration files.

    Args:
        sos_home: Sosreport root
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    config_files = [
        ("etc/anacrontab", "Anacron Configuration"),
        ("etc/sysconfig/crond", "Crond Daemon Configuration"),
        ("etc/cron.allow", "Cron Allow List"),
        ("etc/cron.deny", "Cron Deny List"),
        ("usr/lib/systemd/system/crond.service", "Crond Systemd Service"),
    ]

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    for rel_path, title in config_files:
        file_path = get_sos_file_path(sos_home, rel_path)

        if not exists(file_path):
            continue

        header = "=== %s ===" % title
        output.add_colored_line(header, colors.cyan, colors.reset)
        output.add_line("")

        try:
            with open(file_path, 'r') as f:
                for line in f:
                    if is_cmd_stopped():
                        return

                    line = screen.get_colored_line(line.rstrip())
                    output.add_line(line)

            output.add_line("")

        except (IOError, OSError):
            output.add_line("Error reading file")
            output.add_line("")


def print_help_msg(op, no_pipe):
    """Generate help message."""
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

    if no_pipe:
        op.print_help()
        print(cmd_examples)
        return ""
    else:
        output = StringIO.StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()
        return contents + "\n" + cmd_examples


# Global state
is_cmd_stopped = None


def run_croninfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    """
    Main entry point for cron command.

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

    # Parse command line options
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

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help:
        return print_help_msg(op, no_pipe)

    # Initialize helpers
    sos_home = env_vars["sos_home"]
    colors = ColorManager(no_pipe)
    output = OutputBuilder(no_pipe)

    # Execute requested operation
    try:
        if o.show_log:
            show_cron_log(sos_home, colors, output, errors_only=False)
        elif o.show_errors:
            show_cron_log(sos_home, colors, output, errors_only=True)
        elif o.show_stats:
            show_cron_stats(sos_home, colors, output)
        elif o.show_timers:
            show_systemd_timers(sos_home, colors, output)
        elif o.show_config:
            show_cron_config(sos_home, colors, output)
        else:
            # Default: show cron files
            screen.init_data(no_pipe, 1, is_cmd_stopped)
            cronfile_list = get_cron_files(sos_home, include_all=o.show_all)

            for cfile in cronfile_list:
                if is_cmd_stopped():
                    break
                read_cron_file(cfile, sos_home, colors, output, show_path=True)

    except Exception as e:
        output.add_line("Unexpected error: %s" % str(e))

    return output.get_result()
