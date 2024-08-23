import sys
import time
import os
from os import listdir
from os.path import isfile, join
from optparse import OptionParser
from io import StringIO

import ansicolor


def description():
    return "Shows cron related infomation"


def add_command():
    return True


def get_command_info():
    return { "cron": run_croninfo }


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
                2 : COLOR_TWO,
                3 : COLOR_THREE,
                4 : COLOR_FOUR,
                5 : COLOR_FIVE,
                6 : COLOR_RED,
                7 : COLOR_MAGENTA,
                8 : COLOR_GREEN,
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


def read_cron_basic(log_path, no_pipe, show_path=False, sos_home=""):

    if show_path:
        file_name = log_path.replace(sos_home, "")
        result_str = "=" * 10 + ("> %s <" % file_name) + "=" * 10
    try:
        if no_pipe:
            print(result_str)
            result_str = ""
        else:
            result_str = result_str + "\n"

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

            if no_pipe:
                print("")
            else:
                result_str = result_str + "\n"
    except:
        result_str = ""
        pass

    return result_str


def get_files_in_path(mypath):
    if not mypath.endswith("/"):
        mypath = mypath + "/"

    onlyfiles = [mypath + f for f in listdir(mypath) if isfile(join(mypath, f))]
    return onlyfiles


def get_cron_files(sos_home):
    file_list = [sos_home + "/etc/crontab"] +\
                get_files_in_path(sos_home + "/etc/cron.hourly") +\
                get_files_in_path(sos_home + "/etc/cron.daily") +\
                get_files_in_path(sos_home + "/etc/cron.monthly") +\
                get_files_in_path(sos_home + "/etc/cron.weekly") +\
                get_files_in_path(sos_home + "/sos_commands/cron")

    return file_list


is_cmd_stopped = None

def run_croninfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: cron [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

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

    sos_home = env_vars["sos_home"]
    cronfile_list = get_cron_files(sos_home)

    result_str = ""
    for cfile in cronfile_list:
        result_str = result_str + read_cron_basic(cfile, no_pipe, True, sos_home)

    return result_str
