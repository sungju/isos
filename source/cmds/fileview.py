import sys
import time
from optparse import OptionParser
from io import StringIO
import glob
from os.path import expanduser, isfile, isdir, join

import ansicolor

def description():
    return "Shows file content"


def add_command():
    return True


def get_command_info():
    return { "cat": run_fileview }


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


def show_file_content(file_path, no_pipe, options, show_name=False):
    set_color_table(no_pipe)

    result_str = ""
    try:
        with open(file_path) as f:
            lines = f.readlines()
            if show_name:
                line = get_colored_line("\n%s < %s > %s\n" %\
                        ("=" * 10, file_path, "=" * 10))
                if no_pipe:
                    print(line)
                else:
                    result_str = result_str + line + '\n'

            for line in lines:
                if is_cmd_stopped():
                    return result_str

                line = get_colored_line(line)
                if no_pipe:
                    print(line)
                else:
                    result_str = result_str + line + "\n"
    except:
        result_str ="File '%s' cannot read" % (file_path)

    return result_str


def get_file_list(filename):
    result_list = []

    file_list = glob.glob(filename)
    for file in file_list:
        if isdir(file):
            flist = get_file_list(file + "/*")
            result_list = result_list + flist
        else:
            result_list.append(file)

    return result_list


def print_help_msg(op, no_pipe):
    cmd_examples = '''
It shows file content with different color for each columns.
Wildcard is allowed which can be used to see multiple files

Example)
    > cat proc/*/stack

    ========== < proc/1/stack > ==========
    [<0>] ep_poll+0x348/0x3b0
    [<0>] do_epoll_wait+0xa3/0xc0
    [<0>] __x64_sys_epoll_wait+0x60/0x100
    [<0>] do_syscall_64+0x5c/0x90
    [<0>] entry_SYSCALL_64_after_hwframe+0x64/0xce

    ========== < proc/10/stack > ==========
    [<0>] worker_thread+0xbb/0x3a0
    [<0>] kthread+0xd9/0x100
    [<0>] ret_from_fork+0x22/0x30
    ...

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
def run_fileview(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: cat [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True or len(args) == 1:
        return print_help_msg(op, no_pipe)

    result_str = ''
    file_list = []
    for fname in args[1:]:
        file_list = file_list + get_file_list(fname)

    for afile in file_list:
        result_str = result_str + show_file_content(afile, no_pipe, o, show_name=len(file_list) > 1)

    return result_str
