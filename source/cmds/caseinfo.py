import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import expanduser, isfile, isdir, join
import traceback


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

    result_str = screen.get_pipe_aware_line("Case No: " + caseno_str)

    return result_str


def show_system(options, no_pipe):
    result_str = ''

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
    It shows case related information
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
        return print_help_msg(op, no_pipe)
    
    result_str = ""
    sos_home = env_vars['sos_home']

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str = ""
    result_str = show_caseinfo(o, no_pipe)
    if o.sys:
        result_str = result_str + show_system(o, no_pipe)

    return result_str
