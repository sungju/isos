import sys
import time
from optparse import OptionParser
from io import StringIO

import ansicolor
import screen


def description():
    return "Shows process related information"


def add_command():
    return True


cmd_name = "psinfo"
def get_command_info():
    return { "%s" % cmd_name : run_psinfo }


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
                3 : COLOR_TWO,
                4 : COLOR_TWO,
                5 : COLOR_FOUR,
                6 : COLOR_THREE,
                11: COLOR_FIVE,
        }
    else:
        COLOR_ONE = COLOR_TWO = COLOR_THREE = ""
        COLOR_FOUR = COLOR_FIVE = ""
        COLOR_RED = COLOR_MAGENTA = COLOR_GREEN = COLOR_RESET = ""
        column_color = {}


total_vsz = 0
total_rss = 0

def calc_total_mem(lines):
    global total_vsz
    global total_rss

    total_vsz = total_rss = 0

    for line in lines:
        words = line.split()
        if words[1] == "=":
            continue

        try:
            total_vsz = total_vsz + int(words[4])
            total_rss = total_rss + int(words[5])
        except:
            pass


def get_colored_line(line):
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


def sorted_by(lines, sort_by, reverse=True):
    result_list = [lines[0]]
    del lines[0]
    sort_idx = 0
    if sort_by == "cpu":
        sort_idx = 2
    elif sort_by == "vsz":
        sort_idx = 4
    elif sort_by == "rss":
        sort_idx = 5

    sorted_list = sorted(lines, key=lambda x: float(x.split()[sort_idx]), reverse=reverse)
    return result_list + sorted_list


def remove_empty_ps_line(lines):
    result_list = []
    for line in lines:
        words = line.split()
        if len(words) < 2 or words[1] == "-":
            continue
        result_list.append(line)

    return result_list


def read_ps_basic(ps_path, no_pipe, options):
    global total_vsz
    global total_rss

    set_color_table(no_pipe)

    result_str = ""
    with open(ps_path) as f:
        lines = remove_empty_ps_line(f.readlines())
        total_lines = len(lines)
        if options.lines_to_print > 0:
            print_count = options.lines_to_print + 1
        else:
            print_count = total_lines

        if options.sort_by != "":
            lines = sorted_by(lines, options.sort_by,\
                    print_count != total_lines)

        calc_total_mem(lines)
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

        if options.lines_to_print > 0 and \
                (options.lines_to_print + 1) != total_lines:
            line = "\n\t\t......"
            if no_pipe:
                print(line)
            else:
                result_str = result_str + line + "\n"

        total_str = ("\n\tTotal VSZ = %s, Total RSS = %s\n" % \
                (get_size_str(total_vsz * 1024, True),
                    get_size_str(total_rss * 1024, True)))
        if no_pipe:
            print(total_str)
        else:
            result_str = result_str + total_str

    return result_str


def show_ps_tree(sos_home, no_pipe, options):
    result_str = ""
    pid = options.process_details
    try:
        with open(sos_home + "/sos_commands/process/pidstat_-tl") as f:
            for line in f:
                words = line.split()
                if len(words) > 3 and words[2] == pid:
                    result_str = result_str +\
                        screen.get_pipe_aware_line(
                            "CPU Usage: %s, usr: %s, sys: %s, guest: %s, wait: %s" %\
                            (words[8], words[4], words[5], words[6], words[7]))
    except Exception as e:
        #print(e)
        pass

    try:
        with open(sos_home + "/sos_commands/process/ps_auxwwwm") as f:
            for line in f:
                words = line.split()
                if len(words) > 7 and words[1] == pid:
                    result_str = result_str + screen.get_pipe_aware_line(
                            "MEM Usage: %s, VSZ: %s, RSS: %s" %\
                            (words[3], get_size_str(int(words[4])),\
                             get_size_str(int(words[5]))))
                    break
        result_str = result_str + screen.get_pipe_aware_line("")
    except Exception as e:
        #print(e)
        pass


    try:
        with open(sos_home + "/sos_commands/process/ps_-elfL") as f:
            for line in f:
                if pid in line:
                    words = line.split()
                    if len(words) < 17:
                        continue
                    pstate = words[1]
                    if words[3] == words[5]: # thread leader
                        cmd_str = line[line.find(words[15]) + len(words[15]):].strip()
                        result_str = result_str +\
                                screen.get_pipe_aware_line(
                                        "%s (%s) [%s] by %s" % (cmd_str, pid, pstate, words[2]))
                    else:
                        wchan = words[12]
                        result_str = result_str + \
                                screen.get_pipe_aware_line(
                                        "\t+- %s (%s) [%s]" % (words[5], wchan, pstate))

    except Exception as e:
        #print(e)
        pass


    proc_dir = sos_home + ("/proc/%s" % (pid))
    try:
        with open(proc_dir + "/stack") as f:
            result_str = result_str + screen.get_pipe_aware_line("\nCall Trace:\n")
            for line in f:
                result_str = result_str + screen.get_pipe_aware_line("  " + line)
    except Exception as e:
        #print(e)
        pass


    try:
        with open(proc_dir + "/limits") as f:
            result_str = result_str + screen.get_pipe_aware_line("\n\n")
            for line in f:
                result_str = result_str + screen.get_pipe_aware_line(line)
    except Exception as e:
        #print(e)
        pass



    return result_str


def show_process_details(sos_home, no_pipe, options):
    result_str = show_ps_tree(sos_home, no_pipe, options)


    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Examples:
    # To see only specified number of lines
    > psinfo -l 10

    # To sort by resource type. It shows the highest at the bottom
    # unless specifying line numbers with -l
    > psinfo -s rss 
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
def run_psinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-l', '--lines', dest='lines_to_print', default=0,
            action='store', type="int",
            help="Shows only specified number of lines from the top")
    op.add_option('-p', '--pid', dest='process_details', default='',
            action='store', type="string",
            help="Shows details of a specified process")
    op.add_option('-s', '--sort', dest='sort_by', default="",
            action='store', type="string",
            help="Sorts the output by one of the below options\n" + \
                    "\tcpu : CPU usage\n" + \
                    "\tvsz : Virtual memory usage\n" + \
                    "\trss : RSS usage\n")


    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""


    if o.help or show_help == True:
        return print_help_msg(op, no_pipe)

    sos_home = env_vars["sos_home"]
    screen.init_data(no_pipe, 1, is_cmd_stopped)

    if o.process_details:
        result_str = show_process_details(sos_home, no_pipe, o)
    else:
        result_str = read_ps_basic(sos_home + "/ps", no_pipe, o)

    return result_str
