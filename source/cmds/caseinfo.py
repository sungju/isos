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


from isos import run_shell_command, column_strings
import screen
from soshelpers import get_main

def description():
    return "Shows case related information"


def add_command():
    return True


cmd_name = "ci"
def get_command_info():
    return { cmd_name : run_caseinfo }


def show_caseinfo(options, no_pipe):
    result_str = ''

    case_path_root = ""
    try:
        case_path_root = os.environ["CASE_PATH_ROOT"]
    except:
        pass

    if case_path_root != "":
        caseno_str = os.path.dirname(sos_home).replace(case_path_root, "", 1).split("/")[0]
    else:
        path_list = os.path.dirname(sos_home).split("/")
        for path in path_list:
            if path.isdigit():
                caseno_str = path
                break

    result_str = "Case No: " + caseno_str
    try:
        with open(sos_home + "/uname") as f:
            line = f.readlines()[0]
            words = line.split()
            result_str = result_str + ", Kernel: " + words[2] +\
                    "\nHostname: " + words[1]
    except:
        pass


    try:
        with open(sos_home + "/proc/cmdline") as f:
            result_str = result_str + "\n- - - -\n" + f.readlines()[0]
    except:
        pass

    result_str = screen.get_pipe_aware_line(result_str)

    return result_str


def show_system(options, no_pipe):
    result_str = screen.get_pipe_aware_line('\n')

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
    It shows case related information

Examples:
    ci           Show case number, kernel, hostname, and cmdline
    ci -s        Also show BIOS info and collection date/time
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

    result_str = ""
    result_str = show_caseinfo(o, no_pipe)
    if o.sys:
        result_str = result_str + show_system(o, no_pipe)

    return result_str
