import sys
import time
from optparse import OptionParser
from io import StringIO

import ansicolor


def description():
    return "Shows various logs"


def add_command():
    return True


def get_command_info():
    return { "log": run_loginfo }


COLOR_ONE   = ansicolor.get_color(ansicolor.YELLOW)
COLOR_TWO   = ansicolor.get_color(ansicolor.GREEN)
COLOR_THREE = ansicolor.get_color(ansicolor.RED)
COLOR_FOUR  = ansicolor.get_color(ansicolor.CYAN)
COLOR_FIVE  = ansicolor.get_color(ansicolor.LIGHTCYAN)
COLOR_RED   = ansicolor.get_color(ansicolor.LIGHTRED)
COLOR_MAGENTA = ansicolor.get_color(ansicolor.MAGENTA)
COLOR_GREEN = ansicolor.get_color(ansicolor.GREEN)
COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

column_color = { }

def set_color_table(no_pipe):
    global COLOR_ONE, COLOR_TWO, COLOR_THREE
    global COLOR_FOUR, COLOR_FIVE
    global COLOR_RED, COLOR_MAGENTA, COLOR_GREEN
    global COLOR_RESET
    global column_color

    if no_pipe:
        COLOR_ONE   = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_TWO   = ansicolor.get_color(ansicolor.GREEN)
        COLOR_THREE = ansicolor.get_color(ansicolor.RED)
        COLOR_FOUR  = ansicolor.get_color(ansicolor.CYAN)
        COLOR_FIVE  = ansicolor.get_color(ansicolor.LIGHTCYAN)
        COLOR_RED   = ansicolor.get_color(ansicolor.LIGHTRED)
        COLOR_MAGENTA = ansicolor.get_color(ansicolor.MAGENTA)
        COLOR_GREEN = ansicolor.get_color(ansicolor.GREEN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

        column_color = {
                1 : COLOR_ONE,
                2 : COLOR_ONE,
                3 : COLOR_TWO,
                4 : COLOR_THREE,
                5 : COLOR_FOUR,
        }
    else:
        COLOR_ONE = COLOR_TWO = COLOR_THREE = ""
        COLOR_FOUR = COLOR_FIVE = ""
        COLOR_RED = COLOR_MAGENTA = COLOR_GREEN = COLOR_RESET = ""
        column_color = {}


def get_colored_line(line):
    words = line.split()
    result_str = ""
    count = 1
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


def read_log_basic(log_path, no_pipe):

    set_color_table(no_pipe)

    result_str = ""
    try:
        with open(log_path) as f:
            lines = f.readlines()
            for line in lines:
                if is_cmd_stopped():
                    return result_str

                line = get_colored_line(line)
                if line != "":
                    if no_pipe:
                        print(line)
                    else:
                        result_str = result_str + line + "\n"
    except:
        result_str = ""

    return result_str


is_cmd_stopped = None
def run_loginfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: log [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option("-b", "--boot", dest="journalctl_boot", default=0,
            action="store_true",
            help="Shows journalctl --no-pager --boot")
    op.add_option("-c", "--cron", dest="cron_log", default=0,
            action="store_true",
            help="Shows cron log")
    op.add_option("-d", "--disk", dest="journalctl_disk", default=0,
            action="store_true",
            help="Shows journalctl --disk-usage")
    op.add_option("-n", "--nopager", dest="journalctl_nopager", default=0,
            action="store_true",
            help="Shows journalctl --no-pager")
    op.add_option("-s", "--secure", dest="secure_log", default=0,
            action="store_true",
            help="Shows secure log")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

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

    result_str = ""
    if o.cron_log:
        result_str = read_log_basic(env_vars["sos_home"] + "/var/log/cron", no_pipe)
    elif o.secure_log:
        result_str = read_log_basic(env_vars["sos_home"] + "/var/log/secure", no_pipe)
    elif o.journalctl_disk:
        result_str = read_log_basic(env_vars["sos_home"] + "/sos_commands/logs/journalctl_--disk-usage", no_pipe)
    elif o.journalctl_nopager:
        result_str = read_log_basic(env_vars["sos_home"] + "/sos_commands/logs/journalctl_--no-pager", no_pipe)
    elif o.journalctl_boot:
        result_str = read_log_basic(env_vars["sos_home"] + "/sos_commands/logs/journalctl_--no-pager_--boot", no_pipe)
    else:
        result_str = read_log_basic(env_vars["sos_home"] + "/var/log/messages", no_pipe)


    return result_str
