import sys
import time

import ansicolor

def description():
    return "Shows process related information"


def add_command():
    return True


def get_command_info():
    return { "ps": run_psinfo }


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
        3 : COLOR_TWO,
        4 : COLOR_TWO,
        5 : COLOR_FOUR,
        6 : COLOR_THREE,
        11: COLOR_FIVE,
}

total_vsz = 0
total_rss = 0

def get_colored_line(line):
    global total_vsz
    global total_rss

    words = line.split()
    if words[1] == "-": # Don't need to help empty process
        return ""

    count = 1
    result_str = ""
    for word in words:
        colored_word = word
        if count in column_color:
            colored_word = column_color[count] + word + COLOR_RESET
        line = line.replace(word, colored_word, 1)
        mod_idx = line.find(colored_word) + len(colored_word)
        result_str = result_str + line[:mod_idx]
        line = line[mod_idx:]
        try:
            if count == 5: # VSZ
                total_vsz = total_vsz + int(word)
            elif count == 6: # RSS
                total_rss = total_rss + int(word)
        except:
            pass

        count = count + 1

    return result_str


def get_size_str(size, coloring = False):
    size_str = ""
    if size > (1024 * 1024 * 1024): # GiB
        size_str = "%.1f GiB" % (size / (1024*1024*1024))
        if coloring == True:
            size_str = COLOR_RED + size_str + COLOR_RESET
    elif size > (1024 * 1024): # MiB
        size_str = "%.1f MiB" % (size / (1024*1024))
        if coloring == True:
            size_str = COLOR_MAGENTA + size_str + COLOR_RESET
    elif size > (1024): # KiB
        size_str = "%.1f KiB" % (size / (1024))
        if coloring == True:
            size_str = COLOR_GREEN + size_str + COLOR_RESET
    else:
        size_str = "%.0f B" % (size)

    return size_str


def read_ps_basic(ps_path):
    global total_vsz
    global total_rss

    total_vsz = total_rss = 0


    result_str = ""
    with open(ps_path) as f:
        lines = f.readlines()
        for line in lines:
            line = get_colored_line(line)
            if line != "":
                result_str = result_str + line + "\n"

        result_str = result_str + \
                ("\n\tTotal VSZ = %s, Total RSS = %s\n" % \
                (get_size_str(total_vsz * 1024, True),
                    get_size_str(total_rss * 1024, True)))

    return result_str


def run_psinfo(input_str, env_vars, show_help=False):
    if show_help == True:
        return description()

    result_str = read_ps_basic(env_vars["sos_home"] + "/ps")
    return result_str
