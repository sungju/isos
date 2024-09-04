import os
import sys
import time
from optparse import OptionParser
from io import StringIO
from subprocess import Popen, PIPE, STDOUT
from isos import run_shell_command

import ansicolor

def description():
    return "Shows kernel related information"


def add_command():
    return True


def get_command_info():
    return { "kernel": run_kernel }


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


def taint_str(taint_val):
    result_str = ''
    taint_meaning = {
            0 : "P/G : TAINT_PROPRIETARY_MODULE",
            1 : "F   : TAINT_FORCED_MODULE",
            2 : "S   : TAINT_UNSAFE_SMP(4-7), TAINT_CPU_OUT_OF_SPEC(8-9)",
            3 : "R   : TAINT_FORCED_RMMOD",
            4 : "M   : TAINT_MACHINE_CHECK",
            5 : "B   : TAINT_BAD_PAGE",
            6 : "U   : TAINT_USER",
            7 : "D   : TAINT_DIE",
            8 : "A   : TAINT_OVERRIDDEN_ACPI_TABLE",
            9 : "W   : TAINT_WARN",
            10: "C   : TAINT_CRAP",
            11: "I   : TAINT_FIRMWARE_WORKARUND",
            12: "O   : TAINT_OOT_MODULE",
            13: "E   : TAINT_UNSIGNED_MODULE",
            14: "L   : TAINT_SOFTLOCKUP",
            15: "K   : TAINT_LIVEPATCH",
            16: "X   : TAINT_AUX",
            17: "T   : TAINT_RANDSTRUCT",
            26: "P   : TAINT_PARTNER_SUPPORTED",
    }
    idx = 0
    while taint_val:
        if (taint_val & 0x1) == 0x1 and idx in taint_meaning:
            result_str = result_str + taint_meaning[idx] + "\n"
        idx = idx + 1
        taint_val = taint_val >> 1

    return result_str


def show_taint_info(no_pipe, options):
    # 1. Extract kernel version from sos_commands/kernel/uname_-a
    # 2. find weak-updates from sos_commands/kernel/modinfo_ALL_MODULES
    # 3. kernel.tainted from sos_commands/kernel/sysctl_-a
    kerver_str = ""
    try:
        with open('sos_commands/kernel/uname_-a') as f:
            result = f.readlines()[0]
            words = result.split()
            kerver_str = words[2]
            result_str = get_pipe_aware_line("Kernel version : " + kerver_str, no_pipe)
    except Exception as e:
        result_str = result_str + get_pipe_aware_line(e, no_pipe)
        
    try:
        with open('sos_commands/kernel/modinfo_ALL_MODULES') as f:
            lines = f.readlines()
            result_str = result_str + \
                    get_pipe_aware_line('\n%s\n%s\n' % \
                                        ('Tainted modules', '=' * 20), no_pipe)
            for line in lines:
                if 'weak-updates' in line:
                    modname = line[line.rfind('/') + 1:]
                    result_str = result_str + get_pipe_aware_line(modname + '\n', no_pipe)
    except Exception as e:
        result_str = result_str + get_pipe_aware_line(e, no_pipe)


    try:
        with open('sos_commands/kernel/sysctl_-a') as f:
            lines = f.readlines()
            kernel_tainted = ''
            for line in lines:
                if 'kernel.tainted =' in line:
                    kernel_tainted = line
                    break

            if kernel_tainted != '':
                result_str = result_str + \
                        get_pipe_aware_line('\n%s\n%s\n%s\n' % \
                                        ('kernel.tainted', '=' * 20, kernel_tainted), \
                                        no_pipe)
                taint_val = int(kernel_tainted.split()[2])
                result_str = result_str + \
                        get_pipe_aware_line(taint_str(taint_val), no_pipe)

    except Exception as e:
        result_str = result_str + get_pipe_aware_line(e, no_pipe)


    return result_str


is_cmd_stopped = None
def run_kernel(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: kernel [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-t', '--taint', dest='show_taint', action='store_true',
                  help='show kernel taint status')

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

    if o.show_taint:
        result_str = show_taint_info(no_pipe, o)

    return result_str
