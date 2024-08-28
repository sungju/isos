import os
import sys
import time
from optparse import OptionParser
from io import StringIO
from subprocess import Popen, PIPE, STDOUT

import ansicolor

def description():
    return "Shows perf report"


def add_command():
    return True


def get_command_info():
    return { "perf": run_perf }


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


def run_shell_command(input_str, pipe_input="", no_pipe=False):
    if len(pipe_input.strip()) != 0:
        input_bytes = pipe_input.encode('utf-8')
        p = Popen(input_str, shell=True, stdout=PIPE, stdin=PIPE, stderr=STDOUT)
        stdout_result = p.communicate(input=input_bytes)[0]
        return stdout_result.decode()
    elif no_pipe == True:
        os.system(input_str)
        return ""
    else:
        p = Popen(input_str, shell=True, stdout=PIPE, stderr=STDOUT, text=True)
        result_str, errors = p.communicate()

        return result_str


def run_perf_report(perf_cmd_str, no_pipe, options):
    result = run_shell_command(perf_cmd_str, "", no_pipe=False)
    lines = result.splitlines()
    total_lines = len(lines)
    result_str = ""

    line = get_colored_line(perf_cmd_str + "\n" + "=" * 78)
    if no_pipe:
        print(line)
    else:
        result_str = result_str + line + "\n"

    if options.lines > 0:
        print_count = options.lines + 1
    else:
        print_count = total_lines

    for line in lines:
        if print_count == 0:
            break
        line = get_colored_line(line)
        if line != "":
            print_count = print_count - 1
            if no_pipe:
                print(line)
            else:
                result_str = result_str + line + "\n"

    if options.lines > 0 and (options.lines + 1) != total_lines:
        line = "\n\t\t......"
        if no_pipe:
            print(line)
        else:
            result_str = result_str + line + "\n"

    return result_str


is_cmd_stopped = None
def run_perf(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: perf [options] <perf data>"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-l', '--lines', dest='lines', default=0,
            action='store', type="int",
            help="Shows only specified lines from the top")
    op.add_option('-m', '--meta', dest='show_meta', action='store_true',
                  help='show cpu utilisation')
    op.add_option('-s', '--sort', dest='sortby', default=0,
            action='store', type="int",
            help="Show data with different options")
    op.add_option('-q', '--quiet', dest='quiet', action='store_true',
                  help='Do not show any warnings or messages.')

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
            perf_cmd_str = "perf report -f --stdio --kallsyms=%s/proc/kallsyms -i %s" % \
                    (sos_home, file_path)
            if o.show_meta:
                perf_cmd_str = perf_cmd_str + " --header"
            if o.quiet:
                perf_cmd_str = perf_cmd_str + " -q"

            if o.sortby == 0:
                perf_cmd_str = perf_cmd_str + " -s overhead_sys,comm --show-cpu-utilization"
            elif o.sortby == 1:
                perf_cmd_str = perf_cmd_str + " --no-children -s comm,dso"
            elif o.sortby == 2:
                perf_cmd_str = perf_cmd_str + " -s overhead,overhead_us,overhead_sys,comm"

            result_str = result_str + run_perf_report(perf_cmd_str, no_pipe, o)
        except Exception as e:
            print(e)
            result_str = result_str + get_pipe_aware_line("perf file '%s' cannot read" % (file_path), no_pipe)

    else:
        pass

    return result_str
