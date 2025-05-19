import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import expanduser, isfile, isdir, join
import traceback
from itertools import chain


from isos import run_shell_command, column_strings
import screen
from soshelpers import get_main

def description():
    return "Shows SYSV IPC usage"


def add_command():
    return True


cmd_name = "ipcinfo"
def get_command_info():
    return { cmd_name : run_ipcinfo }


def get_size_str(size):
    size_str = ""
    if size > (1024 * 1024 * 1024): # GiB
        size_str = "%.1f GiB" % (size / (1024*1024*1024))
    elif size > (1024 * 1024): # MiB
        size_str = "%.1f MiB" % (size / (1024*1024))
    elif size > (1024): # KiB
        size_str = "%.1f KiB" % (size / (1024))
    else:
        size_str = "%.0f B" % (size)

    return size_str


IPC_NONE = 0
IPC_MSG = 1
IPC_SHM = 2
IPC_SEM = 3

def show_shmem(op, no_pipe):
    result_str = ''
    total_rss = 0
    shmem_usage_dict = {}
    shmem_total_usage = 0
    ipc_mode = IPC_NONE
    ipc_title = ""
    try:
        with open(sos_home + '/sos_commands/sysvipc/ipcs') as f:
            result_lines = f.readlines()
            for i in range(1, len(result_lines)):
                result_line = result_lines[i].strip()
                if "Shared Memory Segments" in result_line:
                    ipc_mode = IPC_SHM
                    ipc_title = result_line
                    continue
                elif "key" in result_line and ipc_mode == IPC_SHM:
                    ipc_title = ipc_title + "\n" + result_line
                    continue
                elif len(result_line) == 0:
                    if ipc_mode == IPC_SHM:
                        sorted_usage = sorted(shmem_usage_dict.items(),
                                key=operator.itemgetter(1), reverse=False)
                        result_str = result_str + screen.get_pipe_aware_line(ipc_title)
                        for i in range(0, len(sorted_usage)):
                            result_str = result_str + screen.get_pipe_aware_line(sorted_usage[i][0])

                        result_str = result_str + \
                                screen.get_pipe_aware_line("\n\tTotal shared memory allocation = %s" % get_size_str(shmem_total_usage))

                    result_str = result_str + \
                            screen.get_pipe_aware_line("")
                    ipc_mode = IPC_NONE
                    continue

                if ipc_mode == IPC_SHM:
                    words = result_line.split()
                    try:
                        alloc_bytes = int(words[4])
                        if alloc_bytes > 0:
                            result_line = result_line.replace(words[4],
                                    '{: >{}}'.format(get_size_str(alloc_bytes), len(words[4])))
                            shmem_usage_dict[result_line] = alloc_bytes
                            shmem_total_usage = shmem_total_usage + alloc_bytes
                    except:
                        pass
                else:
                    result_str = result_str + \
                            screen.get_pipe_aware_line(result_line)
    except Exception as e:
        print(e)
        return ""


    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
    It shows SYSV IPC usage
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
def run_ipcinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home

    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options] [file names]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')


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

    result_str = show_shmem(o, no_pipe)

    return result_str
