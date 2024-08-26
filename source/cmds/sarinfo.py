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
    match_headers = { "CPU", "%usr" } # start from 2nd column
    if options.show_all:
        match_columns = {}
    elif options.cpu_number != "":
        match_columns = { options.cpu_number }
    else:
        match_columns = { "all" }

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns)


def show_mem_usage(options, lines, no_pipe):
    match_headers = { "kbmemfree", "kbmemused" }
    match_columns = {}

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns)


def show_loadavg(options, lines, no_pipe):
    match_headers = { "runq-sz", "plist-sz" }
    match_columns = {}

    return show_sar_data(options, lines, no_pipe, match_headers, match_columns)


def show_sar_data(options, lines, no_pipe, match_headers, match_columns):
    result_str = ""
    tot_idx = len(lines)
    if tot_idx == 0:
        return result_str
    
    result_str = get_pipe_aware_line(lines[0] + "\n", no_pipe)
    idx = 1
    while idx < tot_idx:
        idx, header_line = find_data_header(idx, lines, options, no_pipe, match_headers)
        result_str = result_str + header_line

        idx, cpu_lines = get_matching_data(idx, lines, options, no_pipe, match_columns)
        result_str = result_str + cpu_lines
        if is_cmd_stopped():
            return result_str

    return result_str + get_pipe_aware_line("\n", no_pipe)


def is_line_matching(words, match_words):
    idx = 1
    for mword in match_words:
        if len(mword) != 0 and words[idx] != mword:
            return False
        idx = idx + 1

    return True


def find_data_header(idx, lines, options, no_pipe, match_headers):
    result_str = ""
    tot_idx = len(lines)
    len_headers = len(match_headers)
    for line in lines[idx:]:
        # skip until find 'CPU'
        words = line.split()
        idx = idx + 1
        if len(words) == 0:
            continue
        if len(words) <= len_headers:
            continue
        if len_headers == 0 or is_line_matching(words, match_headers):
            result_str = result_str + get_pipe_aware_line("\n" + line + "\n", no_pipe)
            break

        if idx > tot_idx:
            break

    return idx, result_str


def get_matching_data(idx, lines, options, no_pipe, match_columns):
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
            result_str = result_str + get_pipe_aware_line(line, no_pipe)

    return idx, result_str


is_cmd_stopped = None
def run_sarinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
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
    op.add_option('-l', '--load', dest='loadavg', action='store_true',
                  help='show load average')
    op.add_option('-m', '--mem', dest='mem_usage', action='store_true',
                  help='show memory usage')

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

                if o.cpu_usage:
                    result_str = result_str + show_cpu_usage(o, lines, no_pipe)

                if o.mem_usage:
                    result_str = result_str + show_mem_usage(o, lines, no_pipe)

                if o.loadavg:
                    result_str = result_str + show_loadavg(o, lines, no_pipe)
        except Exception as e:
            print(e)
            result_str = result_str + get_pipe_aware_line("sar file '%s' cannot read" % (file_path), no_pipe)

    else:
        pass

    return result_str
