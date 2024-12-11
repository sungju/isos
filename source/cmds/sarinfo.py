import sys
import time
from optparse import OptionParser
from io import StringIO

import screen

def description():
    return "Shows sar data"


def add_command():
    return True


def get_command_info():
    return { "sar": run_sarinfo }


def cpu_graph_func(line, no_pipe, is_header):
    words = line.split()
    result_str = ""

    blen = 100
    sartime = ''
    for i in range(0, header_start_idx):
        sartime = sartime + words[i] + ' '

    if is_header:
        line = line.replace('%usr', '%Usr')
        line = line.replace('%nice', '%Nice')
        line = line.replace('%sys', '%Sys')
        line = line.replace('%iowait', '%Iowait')
        line = line.replace('%steal', '%sTeal')
        line = line.replace('%irq', '%irQ')
        line = line.replace('%soft', '%soFt')
        line = line.replace('%guest', '%Guest')
        line = line.replace('%gnice', '%gniCe')
        result_str = screen.get_pipe_aware_line(line)
        result_str = result_str + ('%s  %s\n' % (' '* (len(sartime) + 8), pbar('=', 100, 100, blen)))
        if no_pipe:
            print(result_str.rstrip())
            result_str = ''
    else:
        item1_bar = pbar('U', 100, float(words[header_start_idx + 1]), blen)
        item2_bar = pbar('N', 100, float(words[header_start_idx + 2]), blen)
        item3_bar = pbar('S', 100, float(words[header_start_idx + 3]), blen)
        item4_bar = pbar('I', 100, float(words[header_start_idx + 4]), blen)
        item5_bar = pbar('T', 100, float(words[header_start_idx + 5]), blen)
        item6_bar = pbar('Q', 100, float(words[header_start_idx + 6]), blen)
        item7_bar = pbar('F', 100, float(words[header_start_idx + 7]), blen)
        item8_bar = pbar('G', 100, float(words[header_start_idx + 8]), blen)
        item9_bar = pbar('C', 100, float(words[header_start_idx + 9]), blen)
        avail_bar = pbar('.', blen, blen - len(item1_bar) - len(item2_bar) -\
                len(item3_bar) - len(item4_bar) - len(item5_bar) - len(item6_bar) -\
                len(item7_bar) - len(item8_bar) - len(item9_bar), blen)

        result_str = screen.COLOR_1 + sartime + \
                (' %6.2f : %s%s%s%s%s%s%s%s%s%s' % ( \
                100-float(words[header_start_idx + 10]),
                screen.COLOR_3 + item1_bar,
                screen.COLOR_4 + item2_bar,
                screen.COLOR_5 + item3_bar,
                screen.COLOR_6 + item4_bar,
                screen.COLOR_7 + item5_bar,
                screen.COLOR_8 + item6_bar,
                screen.COLOR_9 + item7_bar,
                screen.COLOR_10 + item8_bar,
                screen.COLOR_11 + item9_bar,
                screen.COLOR_RESET + avail_bar))

        if no_pipe:
            print(result_str)
            result_str = ''

    return result_str


def show_cpu_usage(options, lines, no_pipe):
    match_headers = [ "CPU", "%usr" ] # start from header_start_idx
    if options.show_all:
        match_columns = []
    elif options.cpu_number != "":
        match_columns = [ options.cpu_number ]
    else:
        match_columns = [ "all" ]

    if options.graph:
        graph_func = cpu_graph_func
    else:
        graph_func = None

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns, graph_func)


def pbar(bchar, total, used, bar_len=60):
    bar_count = int((float(used)/total)*bar_len)

    return ('%s' % (bchar * bar_count))


start_idx = 2
item1_idx = 3
item2_idx = 5
item3_idx = 10
item3_char = 'S'
mem_total=0
kbavail_used=False

def mem_graph_func(line, no_pipe, is_header):
    global start_idx
    global item1_idx, item2_idx, item3_idx
    global item3_char
    global mem_total
    global kbavail_used

    result_str = ""
    words = line.split()
    if line.startswith("Average:"):
        return ""

    blen = 60

    if is_header:
        if words[header_start_idx + 1] == "kbavail":
            start_idx = header_start_idx + 2
            kbavail_used = True
        else:
            start_idx = header_start_idx + 1
            kbavail_used = False

        
        item1_idx = start_idx
        item2_idx = start_idx + 3
        item3_idx = -1
        if ' kbslab ' in line:
            item3_idx = start_idx + 9
            if words[item3_idx] != 'kbslab':
                item3_idx = item3_idx + 1

            if words[item3_idx] == 'kbslab':
                item3_char = 'S'
            else:
                item3_idx = -1

        if item3_idx == -1:
            item3_idx = start_idx + 2
            item3_char = 'B'


        try:
            with open(sos_home + "/proc/meminfo") as f:
                line = f.readlines()[0]
                mem_total = int(line.split()[1])
        except Exception as e:
            mem_total = 0

        sartime = ''
        for i in range(0, header_start_idx):
            sartime = sartime + words[i] + ' '


        result_str = ("\n%15s : %s\t%15s : %s\t%15s : %s\n" % (words[item1_idx],  screen.COLOR_1 + '#' * 5 + screen.COLOR_RESET, \
                                                        words[item2_idx], screen.COLOR_3 + 'C' * 5 + screen.COLOR_RESET, \
                                                        words[item3_idx], screen.COLOR_5 + item3_char * 5 + screen.COLOR_RESET))
        result_str = result_str + ('%s  %s\n' % (' '* (len(sartime) + 8), pbar('=', 100, 100, blen)))
        if no_pipe:
            print(result_str.rstrip())
            result_str = ''
    else:
        sartime = ''
        for i in range(0, header_start_idx):
            sartime = sartime + words[i] + ' '
        kbfree    = int(words[header_start_idx])
        kbmemused = int(words[item1_idx])
        kbpercent = words[item1_idx + 1]
        kbcached  = int(words[item2_idx])
        kbitem3 = int(words[item3_idx])
        if mem_total > 0:
            kbtotal = mem_total
        else:
            kbtotal = kbfree + kbmemused


        if not kbavail_used:
            kbmemused = kbmemused - kbcached - kbitem3

        usedbar_str = pbar('#', kbtotal, kbmemused, blen)
        cachebar_str = pbar('C', kbtotal, kbcached, blen)
        item3bar_str = pbar(item3_char, kbtotal, kbitem3, blen)
        availbar_str = pbar('.', blen,\
                blen - len(usedbar_str) - len(cachebar_str) - len(item3bar_str))
        result_str = ('%s%s%6s%% : %s%s%s%s' % (sartime, screen.COLOR_8, kbpercent,\
                screen.COLOR_1 + usedbar_str, screen.COLOR_3 + cachebar_str,\
                screen.COLOR_5 + item3bar_str + screen.COLOR_RESET,\
                availbar_str))
        if no_pipe:
            print(result_str)
            result_str = ''

    return result_str


def show_mem_usage(options, lines, no_pipe):
    match_headers = [ "kbmemfree" ]
    match_columns = []
    if options.graph:
        graph_func = mem_graph_func
    else:
        graph_func = None

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns, graph_func)


def show_net_usage(options, lines, no_pipe):
    match_headers = [ "IFACE", "rxpck/s" ]
    if options.netdev != "":
        match_columns = [ options.netdev ]
    else:
        match_columns = []

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns)


def show_loadavg(options, lines, no_pipe):
    match_headers = [ "runq-sz", "plist-sz" ]
    match_columns = []

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns)


def show_sar_data(options, lines, no_pipe, match_headers, match_columns, graph_func=None):
    result_str = ""
    tot_idx = len(lines)
    if tot_idx == 0:
        return result_str
    
    result_str = screen.get_pipe_aware_line(lines[0] + "\n")
    idx = 1
    while idx < tot_idx:
        idx, header_line = find_data_header(idx, lines, options, no_pipe, match_headers, graph_func)
        result_str = result_str + header_line

        idx, data_lines = get_matching_data(idx, lines, options, no_pipe, match_columns, graph_func)
        result_str = result_str + data_lines
        if is_cmd_stopped():
            return result_str

    return result_str + screen.get_pipe_aware_line("\n")


header_start_idx = 1
def is_line_matching(words, match_words):
    global header_start_idx

    idx = header_start_idx
    for mword in match_words:
        if len(mword) != 0 and words[idx] != mword:
            return False
        idx = idx + 1

    return True


def find_data_header(idx, lines, options, no_pipe, match_headers, graph_func=None):
    global header_start_idx

    result_str = ""
    tot_idx = len(lines)
    len_headers = len(match_headers)
    for line in lines[idx:]:
        words = line.split()
        idx = idx + 1
        if len(words) == 0:
            continue
        if len(words) <= (len_headers + header_start_idx):
            continue
        if len_headers == 0 or is_line_matching(words, match_headers):
            if graph_func == None:
                result_str = result_str + screen.get_pipe_aware_line("\n" + line + "\n")
            else:
                result_str = result_str + graph_func(line, no_pipe, is_header=True)
            break

        if idx > tot_idx:
            break

    return idx, result_str


def get_matching_data(idx, lines, options, no_pipe, match_columns, graph_func=None):
    global is_cmd_stopped

    result_str = ""
    tot_idx = len(lines)
    len_columns = len(match_columns)
    for line in lines[idx:]:
        if is_cmd_stopped():
            return idx, result_str
        idx = idx + 1

        if len(line.strip()) == 0:
            break
        words = line.split()
        if len_columns == 0 or is_line_matching(words, match_columns):
            if graph_func == None:
                result_str = result_str + screen.get_pipe_aware_line(line)
            else:
                result_str = result_str + graph_func(line, no_pipe, is_header=False)

    return idx, result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Examples:
    # Four resource types are selectable
        # -c : CPU usage
        # -l : load average
        # -m : memory usage
        # -n : network usage
    > sar sar14 -c | head -n 4
        Linux 4.18.0-553.16.1.el8_10.x86_64 (test) 	2024-10-14 	_x86_64_	(8 CPU)

        00:00:00        CPU      %usr     %nice      %sys   %iowait    %steal      %irq     %soft    %guest    %gnice     %idle
        00:10:01        all      4.77      0.00      1.67      0.07      0.00      0.23      0.10      0.00      0.00     93.16

    # Data can be shown in bar graph style for CPU and memory usage
    > sar sar28 -gc
        Linux 4.18.0-553.16.1.el8_10.x86_64 (test) 	2024-09-28 	_x86_64_	(8 CPU)
        00:00:00        CPU      %usr     %nice      %sys   %iowait    %steal      %irq     %soft    %guest    %gnice     %idle
                           ====================================================================================================

        00:10:00   18.14 : ###############.....................................................................................
        00:20:01    4.52 : ###.................................................................................................
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
def run_sarinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global header_start_idx
    global sos_home
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: sar [options] <sarfile>"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all data for the specified category')
    op.add_option('-c', '--cpu', dest='cpu_usage', action='store_true',
                  help='show cpu usage')
    op.add_option('-C', '--cpuno', dest='cpu_number', default="",
            action='store', type="string",
            help="Shows only specified CPU data")
    op.add_option('-g', '--graph', dest='graph', action='store_true',
                  help='show data as graph if possible')
    op.add_option('-l', '--load', dest='loadavg', action='store_true',
                  help='show load average')
    op.add_option('-m', '--mem', dest='mem_usage', action='store_true',
                  help='show memory usage')
    op.add_option('-n', '--net', dest='net_usage', action='store_true',
                  help='show network usage')
    op.add_option('-N', '--netdev', dest='netdev', default="",
            action='store', type="string",
            help="Shows only specified net device data")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True or len(args) == 1:
        return print_help_msg(op, no_pipe)

    result_str = ""
    sos_home = env_vars['sos_home']
    for file_path in args[1:]:
        try:
            with open(file_path) as f:
                lines = f.readlines()

                # Adjust header search index due to different date/time format
                # e.g.) "12:00:01 AM" or "00:00:01"
                if len(lines) >= 3:
                    words = lines[2].split()
                    idx = 0
                    tot_idx = len(words)
                    while idx < tot_idx:
                        if words[idx] == "CPU":
                            break
                        idx = idx + 1
                    header_start_idx = idx


                screen.init_data(no_pipe, header_start_idx, is_cmd_stopped)


                if o.cpu_usage:
                    result_str = result_str + show_cpu_usage(o, lines, no_pipe)

                if o.mem_usage:
                    result_str = result_str + show_mem_usage(o, lines, no_pipe)

                if o.loadavg:
                    result_str = result_str + show_loadavg(o, lines, no_pipe)

                if o.net_usage:
                    result_str = result_str + show_net_usage(o, lines, no_pipe)
        except Exception as e:
            print(e)
            result_str = result_str + screen.get_pipe_aware_line("sar file '%s' cannot read" % (file_path))

    else:
        pass

    return result_str
