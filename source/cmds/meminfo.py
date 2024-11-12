import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import expanduser, isfile, isdir, join


from isos import run_shell_command, column_strings
import screen
from soshelpers import get_main

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

def get_file_list(filename, checkdir=True):
    result_list = []

    file_list = glob.glob(filename)
    for file in file_list:
        if isdir(file) and checkdir:
            flist = get_file_list(file + "/*")
            result_list = result_list + flist
        else:
            result_list.append(file)

    return result_list


def show_oom_meminfo(op, no_pipe, meminfo_dict):
    result_str = ""
    page_size = get_main().page_size
    result_str = result_str + screen.get_pipe_aware_line("\n%s" % ('#' * 46))
    result_str = result_str +\
            screen.get_pipe_aware_line("%-30s %15s" %
                    ("Category", "Size"))
    result_str = result_str + screen.get_pipe_aware_line("%s" % ('-' * 46))

    for key in meminfo_dict:
        try:
            val = meminfo_dict[key]
            if val.endswith("B"):
                size_str = val
            else:
                size_str = get_size_str(int(val.split('#')[0]) * page_size)
            result_str = result_str +\
                    screen.get_pipe_aware_line("%-30s %15s" % 
                            (key, size_str))
        except:
            pass
    result_str = result_str + screen.get_pipe_aware_line("%s" % ('~' * 46))

    return result_str


def show_oom_memory_usage(op, no_pipe, oom_dict, total_usage):
    result_str = ""
    sorted_oom_dict = sorted(oom_dict.items(),
                            key=operator.itemgetter(1), reverse=True)
    min_number = 10
    if (op.all):
        min_number = len(sorted_oom_dict) - 1

    result_str = result_str + screen.get_pipe_aware_line("=" * 58)
    result_str = result_str +\
            screen.get_pipe_aware_line("%-40s %15s" %
            ("NAME", "Usage"))
    result_str = result_str + screen.get_pipe_aware_line("=" * 58)

    print_count = min(len(sorted_oom_dict) - 1, min_number)

    for i in range(0, print_count):
        pname = sorted_oom_dict[i][0]

        mem_usage = sorted_oom_dict[i][1]
        result_str = result_str + \
                screen.get_pipe_aware_line("%-40s %15s" %
                (pname, get_size_str(mem_usage)))

    if print_count < len(sorted_oom_dict) - 1:
        result_str = result_str + screen.get_pipe_aware_line("\t<...>")
    result_str = result_str + screen.get_pipe_aware_line("=" * 58)
    result_str = result_str +\
            screen.get_pipe_aware_line("Total memory usage from processes = %s" %
                    get_size_str(total_usage))

    return result_str


def show_oom_events(op, args, no_pipe):
    result_str = ""
    file_list = []
    for file in args[1:]:
        file_list = file_list + get_file_list(file, True)
        
    if len(file_list) == 0:
        file_list.append(sos_home + "/var/log/messages")

    is_first_oom = True
    page_size = get_main().page_size
    for file in file_list:
        if not isfile(file):
            print("Not a file : '%s'" % (file))
            continue
        try:
            with open(file) as f:
                result_lines = f.readlines()
                oom_invoked = False
                oom_meminfo = False
                oom_ps_started = False
                rss_index = -1
                pid_index = -1
                pname_index = -1
                oom_dict = {}
                meminfo_dict = {}
                total_usage = 0
                for line in result_lines:
                    if "invoked oom-killer:" in line:
                        oom_invoked = True
                        if not is_first_oom:
                            line = "\n" + line
                        result_str = result_str + \
                                screen.get_pipe_aware_line(line.rstrip())
                        is_first_oom = False
                        continue

                    if oom_invoked and "Mem-Info:" in line:
                        oom_meminfo = True
                        continue

                    if oom_meminfo:
                        if " Node " not in line and "shmem:" in line:
                            line = line[line.find(" kernel: ") + 9:]
                            words = line.split()
                            for entry in words:
                                key_val = entry.split(':')
                                meminfo_dict[key_val[0]] = key_val[1]
                            continue
                        elif " hugepages_total" in line:
                            line = line[line.find("hugepages_total="):]
                            words = line.split()
                            for entry in words:
                                key_val = entry.split('=')
                                meminfo_dict[key_val[0]] = key_val[1]
                            continue
                        elif " total pagecache pages" in line:
                            line = line[line.find(" kernel: ") + 9:]
                            words = line.split()
                            meminfo_dict["Pagecaches"] = words[0]


                    if oom_invoked and "uid" in line and "total_vm" in line:
                        oom_ps_started = True
                        oom_meminfo = False
                        line = line.split(":")[3]
                        line = line.replace("[", "")
                        line = line.replace("]", "")
                        words = line.split()
                        for i in range(0, len(words)):
                            if words[i] == "rss":
                                rss_index = i
                            elif words[i] == "pid":
                                pid_index = i
                            elif words[i] == "name":
                                pname_index = i

                        continue

                    if not oom_ps_started:
                        continue

                    if "[" not in line: #end of oom_ps
                        result_str = result_str +\
                                show_oom_memory_usage(op, no_pipe, oom_dict, total_usage)
                        if op.details:
                            result_str = result_str +\
                                    show_oom_meminfo(op, no_pipe, meminfo_dict)
                        oom_invoked = False
                        oom_meminfo = False
                        oom_ps_started = False
                        rss_index = -1
                        pid_index = -1
                        pname_index = -1
                        oom_dict = {}
                        meminfo_dict = {}
                        total_usage = 0
                        continue

                    line = line.split(":")[3]
                    line = line.replace("[", "")
                    line = line.replace("]", "")
                    words = line.split()
                    if len(words) <= pname_index:
                        continue
                    pid = words[pid_index]
                    rss = int(words[rss_index]) * page_size
                    total_usage = total_usage + rss
                    pname = words[pname_index]
                    if op.all:
                        pname = pname + (" (%s)" % pid)
                    if pname in oom_dict:
                        rss = rss + oom_dict[pname]
                    oom_dict[pname] = rss

        except Exception as e:
            print(e)


    return result_str


def show_swap_usage(op, no_pipe):
    result_str = ""
    swap_usage_dict = {}
    total_swap = 0
    try:
        pid_list = get_file_list(sos_home + "/proc/[0-9]*", checkdir=False)
        for path in pid_list:
            try:
                with open(path + "/status") as f:
                    result_lines = f.readlines()
                    swap_usage = 0
                    pid = os.path.basename(path)
                    pname = ""
                    for line in result_lines:
                        if line.startswith("VmSwap:"):
                            words = line.split()
                            swap_usage = swap_usage + int(words[1])
                        elif line.startswith("Name:"):
                            pname = line.split()[1]

                    if swap_usage > 0:
                        if op.all:
                            pname = pname + (" (%s)" % pid)
                        total_swap = total_swap + swap_usage
                        if pname in swap_usage_dict:
                            swap_usage = swap_usage + swap_usage_dict[pname]
                        swap_usage_dict[pname] = swap_usage

            except Exception as ie:
                # Ignore the case that doesn't have status
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
            screen.get_pipe_aware_line("%-42s %15s" %
            ("NAME", "Usage"))
    result_str = result_str + screen.get_pipe_aware_line("=" * 58)

    print_count = min(len(sorted_swap_usage) - 1, min_number)

    for i in range(0, print_count):
        pname = sorted_swap_usage[i][0]

        result_str = result_str + \
                screen.get_pipe_aware_line("%-42s %15s" % 
                (pname, get_size_str(sorted_swap_usage[i][1] * 1024)))

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
                if result_line[5] == "-":
                    continue
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

Example)
    To see oom events, you can specify log name or default file (/var/log/messages)
    will be used.

    example.com> meminfo -o
    Nov  9 01:12:50 example.com kernel: https-jsse-nio- invoked oom-killer: ...
    ==========================================================
    NAME                                               Usage
    ==========================================================
    java                                            11.2 GiB
    nft                                              1.3 GiB
    ...
        <...>
    ==========================================================
    Total memory usage from processes = 14.0 GiB
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

    usage = "Usage: %s [options] [file names]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-a', '--all', dest='all', action='store_true',
                  help='Show all entries')

    op.add_option('-d', '--details', dest='details', action='store_true',
                  help='Show further details')

    op.add_option('-o', '--oom', dest='oom', action='store_true',
                  help='Shows OOM events')


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
    elif o.oom:
        result_str = show_oom_events(o, args, no_pipe)
    elif o.swapshow:
        result_str = show_swap_usage(o, no_pipe)
    else: # process list
        result_str = show_ps_memusage(o, no_pipe)

    return result_str
