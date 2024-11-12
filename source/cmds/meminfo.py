import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import isfile, join

from isos import run_shell_command, column_strings
import screen

def description():
    return "Shows memory related information"


def add_command():
    return True


cmd_name = "meminfo"
def get_command_info():
    return { cmd_name : run_meminfo }


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

def get_file_list(filename):
    result_list = []

    file_list = glob.glob(filename)
    for file in file_list:
        result_list.append(file)

    return result_list


def show_swap_usage(op, no_pipe):
    result_str = ""
    swap_usage_dict = {}
    pid_name_dict = {}
    total_swap = 0
    try:
        pid_list = get_file_list(sos_home + "/proc/[0-9]*")
        for path in pid_list:
            try:
                with open(path + "/status") as f:
                    result_lines = f.readlines()
                    swap_usage = 0
                    pid = os.path.basename(path)
                    for line in result_lines:
                        if line.startswith("VmSwap:"):
                            words = line.split()
                            swap_usage = swap_usage + int(words[1])
                        elif line.startswith("Name:"):
                            pname = line.split()[1]
                            pid_name_dict[pid] = pname

                    if swap_usage > 0:
                        swap_usage_dict[pid] = swap_usage
                        total_swap = total_swap + swap_usage

            except: # Ignore the case that doesn't have status
                pass
    except Exception as e:
        print(e)
        return ""

    sorted_swap_usage = sorted(swap_usage_dict.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = 10
    if (op.all):
        min_number = len(sorted_swap_usage) - 1

    result_str = result_str + screen.get_pipe_aware_line("=" * 58)
    result_str = result_str +\
            screen.get_pipe_aware_line("%-29s %-12s %15s" %
            ("NAME", "PID", "Usage (KB)"))
    result_str = result_str + screen.get_pipe_aware_line("=" * 58)

    print_count = min(len(sorted_swap_usage) - 1, min_number)

    for i in range(0, print_count):
        pid = sorted_swap_usage[i][0]
        pname = pid_name_dict[pid]

        result_str = result_str + \
                screen.get_pipe_aware_line("%-29s %-12s %15s" % 
                (pname,
                 pid,
                 get_size_str(sorted_swap_usage[i][1] * 1024)))

    if print_count < len(sorted_swap_usage) - 1:
        result_str = result_str + screen.get_pipe_aware_line("\t<...>")
    result_str = result_str + screen.get_pipe_aware_line("=" * 58)
    result_str = result_str +\
            screen.get_pipe_aware_line("Total memory usage from swap = %s" %
          (get_size_str(total_swap * 1024)))
    result_str = result_str +\
            screen.get_pipe_aware_line("Notes) The total can be bigger than actual usage due to the shared memory")

    return result_str


def show_slabtop(op, no_pipe):
    result_str = ''
    slab_list = {}
    slab_objsize = {}
    total_slab = 0
    idx_pagesperslab = -1
    idx_num_slabs = -1
    idx_objsize = -1
    try:
        with open(sos_home + '/proc/slabinfo') as f:
            result_lines = f.readlines()
            result_lines[1] = result_lines[1].replace('# name', 'name')
            result_line = result_lines[1].split()
            for i in range(1, len(result_line)):
                if "<pagesperslab>" in result_line[i]:
                    idx_pagesperslab = i
                elif "<num_slabs>" in result_line[i]:
                    idx_num_slabs = i
                elif "<objsize>" in result_line[i]:
                    idx_objsize = i

            if idx_pagesperslab == -1 or idx_num_slabs == -1:
                print("Invalid file")
                return ""

            for i in range(2, len(result_lines)):
                result_line = result_lines[i].split()
                if len(result_line) < idx_num_slabs:
                    continue
                total_used = int(result_line[idx_pagesperslab]) *\
                             int(result_line[idx_num_slabs])
                slab_list[result_line[0]] = total_used
                total_slab = total_slab + total_used
                slab_objsize[result_line[0]] = int(result_line[idx_objsize])

    except Exception as e:
        print(e)
        return ''

    sorted_slabtop = sorted(slab_list.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = 10
    if (op.all):
        min_number = len(sorted_slabtop) - 1

    result_str = result_str + screen.get_pipe_aware_line("=" * 51)
    result_str = result_str +\
            screen.get_pipe_aware_line("%-29s %12s %8s" %
            ("NAME", "TOTAL", "OBJSIZE"))
    result_str = result_str + screen.get_pipe_aware_line("=" * 51)

    print_count = min(len(sorted_slabtop) - 1, min_number)

    for i in range(0, print_count):
        slab_name = sorted_slabtop[i][0]
        obj_size = slab_objsize[slab_name]

        result_str = result_str + \
                screen.get_pipe_aware_line("%-29s %12s %8d" %
                (slab_name,
                 get_size_str(sorted_slabtop[i][1] * 1024),
                 obj_size))


    if print_count < len(sorted_slabtop) - 1:
        result_str = result_str + screen.get_pipe_aware_line("\t<...>")
    result_str = result_str + screen.get_pipe_aware_line("=" * 51)
    result_str = result_str +\
            screen.get_pipe_aware_line("Total memory usage from SLAB = %s" %
          (get_size_str(total_slab * 1024)))

    return result_str


def show_ps_memusage(op, no_pipe):
    result_str = ''
    mem_usage_dict = {}
    total_rss = 0
    try:
        with open(sos_home + '/ps') as f:
            result_lines = f.readlines()
            for i in range(1, len(result_lines)):
                result_line = result_lines[i].split()
                if len(result_line) < 11:
                    continue
                pid = result_line[1]
                if op.all:
                    pname = "%s (%s)" % (result_line[10], pid)
                else:
                    pname = result_line[10]
                rss = int(result_line[5])
                total_rss = total_rss + rss
                if pname in mem_usage_dict:
                    rss = mem_usage_dict[pname] + rss

                if rss != 0:
                    mem_usage_dict[pname] = rss

    except Exception as e:
        print(e)
        return ""

    sorted_usage = sorted(mem_usage_dict.items(),
            key=operator.itemgetter(1), reverse=True)

    result_str = result_str + screen.get_pipe_aware_line("=" * 70)
    result_str = result_str + screen.get_pipe_aware_line("%24s          %-s" % (" [ RSS usage ]", "[ Process name ]"))
    result_str = result_str + screen.get_pipe_aware_line("=" * 70)
    min_number = 10
    if (op.all):
        min_number = len(sorted_usage) - 1

    print_count = min(len(sorted_usage) - 1, min_number)

    for i in range(0, print_count):
        result_str = result_str +\
                screen.get_pipe_aware_line("%14s (%10.2f KiB)   %-s" %
                (get_size_str(sorted_usage[i][1] * 1024),
                 sorted_usage[i][1],
                 sorted_usage[i][0]))

    if print_count < len(sorted_usage) - 1:
        result_str = result_str + screen.get_pipe_aware_line("\t<...>")
    result_str = result_str + screen.get_pipe_aware_line("=" * 70)
    result_str = result_str +\
            screen.get_pipe_aware_line("Total memory usage from user-space = %s" %
          (get_size_str(total_rss * 1024)))

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
    It shows memory usage from process / slab.
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
def run_meminfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home

    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-a', '--all', dest='all', action='store_true',
                  help='Show all entries')

    op.add_option('-s', '--slab', dest='slab', action='store_true',
                  help='Shows slabtop')

    op.add_option("-w", "--swap", dest="swapshow", default=0,
                  action="store_true",
                  help="Show swap usage")

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
    if o.slab: # show slabtop
        result_str = show_slabtop(o, no_pipe)
    elif o.swapshow:
        result_str = show_swap_usage(o, no_pipe)
    else: # process list
        result_str = show_ps_memusage(o, no_pipe)

    return result_str
