import os
import sys
import time
from optparse import OptionParser
from io import StringIO
from subprocess import Popen, PIPE, STDOUT
from isos import run_shell_command

import ansicolor
import screen

def description():
    return "Shows kernel related information"


def add_command():
    return True


def get_command_info():
    return { "mods": run_modules }


def get_pipe_aware_line(line, no_pipe):
    line = screen.get_colored_line(line)
    if no_pipe:
        print(line)
        line = ""
    else:
        line = line + "\n"

    return line


def translate_taint_val(taint_val):
    result_str = ''
    bits_list = []
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
            27: "h/r : TAINT_SUPPORT_REMOVED",
    }
    idx = 0
    while taint_val:
        if (taint_val & 0x1) == 0x1:
            bits_list.append("%d" % idx)
            if idx in taint_meaning:
                result_str = result_str + taint_meaning[idx] + "\n"
        idx = idx + 1
        taint_val = taint_val >> 1

    return result_str, ','.join(bits_list)


def show_taint_info(sos_home, no_pipe, options):
    # 1. Extract kernel version from sos_commands/kernel/uname_-a
    # 2. find 3rd party modules from proc/modules
    # 3. kernel.tainted from sos_commands/kernel/sysctl_-a
    result_str = ""
    try:
        with open(sos_home + '/sos_commands/kernel/uname_-a') as f:
            result = f.readlines()[0]
            words = result.split()
            kerver_str = words[2]
            result_str = get_pipe_aware_line("Kernel version : " + kerver_str, no_pipe)
    except Exception as e:
        result_str = result_str + get_pipe_aware_line(e, no_pipe)
        
    try:
        with open(sos_home + '/proc/modules') as f:
            result_str = result_str + \
                    get_pipe_aware_line('\n%s\n%s\n' % \
                                        ('Tainted modules', '=' * 20), no_pipe)
            for line in f:
                line = line.strip()
                words = line.split()
                modname = words[0] + '.ko'
                addr_idx = len(words) - 1
                if not line.endswith(")"):
                    continue

                addr_idx = addr_idx - 1
                modaddr = words[addr_idx]
                result_str = result_str + get_pipe_aware_line(modaddr + ' : ' + modname + '\n', no_pipe)

    except Exception as e:
        result_str = result_str + get_pipe_aware_line(e, no_pipe)


    try:
        with open(sos_home + '/sos_commands/kernel/sysctl_-a') as f:
            kernel_tainted = ''
            for line in f:
                if 'kernel.tainted =' in line:
                    kernel_tainted = line
                    break

            if kernel_tainted != '':
                result_str = result_str + \
                        get_pipe_aware_line('\n%s\n%s\n%s\n' % \
                                        ('kernel.tainted', '=' * 20, kernel_tainted), \
                                        no_pipe)
                taint_val = int(kernel_tainted.split()[2])
                taint_str, taint_bits = translate_taint_val(taint_val)
                result_str = result_str + \
                        get_pipe_aware_line("Bits: %s" % taint_bits, no_pipe) +\
                        get_pipe_aware_line(taint_str, no_pipe) + \
                        get_pipe_aware_line("\nKCS : https://access.redhat.com/solutions/40594", no_pipe)

    except Exception as e:
        result_str = result_str + get_pipe_aware_line(e, no_pipe)

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
It shows tainted module information

Examples:
    > mods
    Kernel version : 5.14.0-284.66.1.el9_2.x86_64

    Tainted modules
    ====================
    0xffffffffc11e8000 : scini.ko

    kernel.tainted
    ====================
    kernel.tainted = 12289
    Bits: 0,12,13
    P/G : TAINT_PROPRIETARY_MODULE
    O   : TAINT_OOT_MODULE
    E   : TAINT_UNSIGNED_MODULE

    KCS : https://access.redhat.com/solutions/40594

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
def run_modules(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: mods [options]"
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

    screen.init_data(no_pipe, 1, is_cmd_stopped)
    result_str = ""
    sos_home = env_vars['sos_home']

    result_str = show_taint_info(sos_home, no_pipe, o)

    return result_str
