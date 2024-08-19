import sys
import time

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
    with open(log_path) as f:
        lines = f.readlines()
        for line in lines:
            line = get_colored_line(line)
            if line != "":
                if no_pipe:
                    print(line)
                else:
                    result_str = result_str + line + "\n"

    return result_str


def run_loginfo(input_str, env_vars, show_help=False, no_pipe=True):
    if show_help == True:
        return description()

    result_str = read_log_basic(env_vars["sos_home"] + "/var/log/messages", no_pipe)
    return result_str
