import sys
import time
from optparse import OptionParser
from io import StringIO

import ansicolor

def description():
    return "Shows sar data"


def add_command():
    return True


def get_command_info():
    return { "sar": run_sarinfo }


COLOR_1  = ansicolor.get_color(ansicolor.RED)
COLOR_2  = ansicolor.get_color(ansicolor.GREEN)
COLOR_3  = ansicolor.get_color(ansicolor.YELLOW)
COLOR_4  = ansicolor.get_color(ansicolor.BLUE)
COLOR_5  = ansicolor.get_color(ansicolor.MAGENTA)
COLOR_6  = ansicolor.get_color(ansicolor.CYAN)
COLOR_7  = ansicolor.get_color(ansicolor.YELLOW)
COLOR_8  = ansicolor.get_color(ansicolor.BLUE)
COLOR_9  = ansicolor.get_color(ansicolor.LIGHTRED)
COLOR_10 = ansicolor.get_color(ansicolor.LIGHTGREEN)
COLOR_11 = ansicolor.get_color(ansicolor.LIGHTYELLOW)
COLOR_12 = ansicolor.get_color(ansicolor.LIGHTBLUE)
COLOR_13 = ansicolor.get_color(ansicolor.LIGHTMAGENTA)
COLOR_14 = ansicolor.get_color(ansicolor.LIGHTCYAN)
COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

column_color = { }

def set_color_table(no_pipe):
    global COLOR_ONE, COLOR_TWO, COLOR_THREE
    global COLOR_FOUR, COLOR_FIVE
    global COLOR_RED, COLOR_MAGENTA, COLOR_GREEN
    global COLOR_RESET
    global column_color

    if no_pipe:
        COLOR_1  = ansicolor.get_color(ansicolor.RED)
        COLOR_2  = ansicolor.get_color(ansicolor.GREEN)
        COLOR_3  = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_4  = ansicolor.get_color(ansicolor.BLUE)
        COLOR_5  = ansicolor.get_color(ansicolor.MAGENTA)
        COLOR_6  = ansicolor.get_color(ansicolor.CYAN)
        COLOR_7  = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_8  = ansicolor.get_color(ansicolor.BLUE)
        COLOR_9  = ansicolor.get_color(ansicolor.LIGHTRED)
        COLOR_10 = ansicolor.get_color(ansicolor.LIGHTGREEN)
        COLOR_11 = ansicolor.get_color(ansicolor.LIGHTYELLOW)
        COLOR_12 = ansicolor.get_color(ansicolor.LIGHTBLUE)
        COLOR_13 = ansicolor.get_color(ansicolor.LIGHTMAGENTA)
        COLOR_14 = ansicolor.get_color(ansicolor.LIGHTCYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

        column_color = {
                1 : COLOR_1,
                2 : COLOR_2,
                3 : COLOR_3,
                4 : COLOR_4,
                5 : COLOR_5,
                6 : COLOR_6,
                7 : COLOR_7,
                8 : COLOR_8,
                9 : COLOR_9,
                10 : COLOR_10,
                11 : COLOR_11,
                12 : COLOR_12,
                13 : COLOR_13,
                14 : COLOR_14,
        }
    else:
        COLOR_1 = COLOR_2 = COLOR_3 = COLOR_4 = ""
        COLOR_5 = COLOR_6 = COLOR_7 = COLOR_8 = ""
        COLOR_9 = COLOR_10 = COLOR_11 = COLOR_12 = ""
        COLOR_13 = COLOR_14 = COLOR_RESET = ""

        column_color = {}


def get_colored_line(line):
    words = line.split()

    count = 1
    result_str = ""
    for word in words:
        if is_cmd_stopped():
            return result_str

        colored_word = word
        if count in column_color:
            colored_word = column_color[count] + word + COLOR_RESET
        line = line.replace(word, colored_word, 1)
        mod_idx = line.find(colored_word) + len(colored_word)
        result_str = result_str + line[:mod_idx]
        line = line[mod_idx:]

        count = count + 1

    return result_str


def get_pipe_aware_line(line, no_pipe):
    line = get_colored_line(line)
    if no_pipe:
        print(line)
        line = ""
    else:
        line = line + "\n"

    return line


def show_cpu_usage(options, lines, no_pipe):
    match_headers = [ "CPU", "%usr" ] # start from header_start_idx
    if options.show_all:
        match_columns = []
    elif options.cpu_number != "":
        match_columns = [ options.cpu_number ]
    else:
        match_columns = [ "all" ]

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns)


def pbar(bchar, total, used, bar_len=60):
    bar_count = int((float(used)/total)*bar_len)

    return ('%s' % (bchar * bar_count))


start_idx = 2
def mem_graph_func(line, no_pipe, is_header):
    global start_idx

    result_str = ""
    words = line.split()
    if is_header:
        if words[2] == "kbavail":
            start_idx = 3
        else:
            start_idx = 2

        result_str = ("\n%15s : %s\t%15s : %s\t%15s : %s\n" % (words[start_idx],  COLOR_1 + '#' * 5 + COLOR_RESET, \
                                                        words[start_idx + 3], COLOR_3 + 'C' * 5 + COLOR_RESET, \
                                                        words[start_idx + 10], COLOR_5 + 'S' * 5 + COLOR_RESET))
        result_str = result_str + ('%s  %s\n' % (' '* 16, pbar('=', 100, 100)))
        if no_pipe:
            print(result_str)
            result_str = ''
    else:
        sartime   = words[0]
        kbfree    = int(words[1])
        kbmemused = int(words[start_idx])
        kbpercent = words[start_idx + 1]
        kbcached  = int(words[start_idx + 3])
        kbslab = int(words[start_idx + 10])
        kbtotal   = kbfree + kbmemused
        result_str = ('%s %s%% : %s%s%s' % (sartime, COLOR_8 + kbpercent, COLOR_1 + pbar('#', kbtotal, kbmemused - kbcached - kbslab), \
                                                            COLOR_3 + pbar('C', kbtotal, kbcached), \
                                                            COLOR_5 + pbar('S', kbtotal, kbslab) + COLOR_RESET))
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
    
    result_str = get_pipe_aware_line(lines[0] + "\n", no_pipe)
    idx = 1
    while idx < tot_idx:
        idx, header_line = find_data_header(idx, lines, options, no_pipe, match_headers, graph_func)
        result_str = result_str + header_line

        idx, data_lines = get_matching_data(idx, lines, options, no_pipe, match_columns, graph_func)
        result_str = result_str + data_lines
        if is_cmd_stopped():
            return result_str

    return result_str + get_pipe_aware_line("\n", no_pipe)


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
                result_str = result_str + get_pipe_aware_line("\n" + line + "\n", no_pipe)
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
                result_str = result_str + get_pipe_aware_line(line, no_pipe)
            else:
                result_str = result_str + graph_func(line, no_pipe, is_header=False)

    return idx, result_str


is_cmd_stopped = None
def run_sarinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global header_start_idx
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

    (o, args) = op.parse_args(input_str.split())

    if o.help or show_help == True:
        if no_pipe == False:
            output = StringIO.StringIO()
            op.print_help(file=output)
            contents = output.getvalue()
            output.close()
            return contents
        else:
            op.print_help()
            return ""
    
    set_color_table(no_pipe)
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
            result_str = result_str + get_pipe_aware_line("sar file '%s' cannot read" % (file_path), no_pipe)

    else:
        pass

    return result_str
