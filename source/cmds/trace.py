import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import operator
from os.path import isfile, join

from isos import run_shell_command
import screen

def description():
    return "Shows trace-cmd related data"


def add_command():
    return True


cmd_name = "trace"
def get_command_info():
    return { cmd_name : run_traceinfo }


delay_time_dict = {}
print_max_count = 20
reverse_print = True

def show_delay_list_in_file(file_path):
    result_str = ""
    try:
        with open(file_path) as f:
            lines = f.readlines()
            for line in lines:
                add_consumed_time(line)

            result_str = show_delay_times()
    except Exception as e:
        print(e)
        result_str = result_str + screen.get_pipe_aware_line("Error in handling file %s" %\
                file_path)

    return result_str


def show_delay_times():
    global delay_time_dict
    global print_max_count
    global reverse_print

    sorted_delay = sorted(delay_time_dict.items(),
            key=operator.itemgetter(1), reverse=reverse_print)

    if print_max_count < 0:
        print_max_count = len(sorted_delay)

    print_count = 0
    result_str = ""
    for by_whom, delay_time in sorted_delay:
        by_whom = by_whom[by_whom.find("funcgraph_exit:") + 16:].strip()
        result_str = result_str + screen.get_pipe_aware_line(by_whom)

        print_count = print_count + 1
        if print_count > print_max_count - 1:
            if len(sorted_delay) > print_max_count:
                result_str = result_str + \
                        screen.get_pipe_aware_line("\t%15s %d %s\n" % \
                        ("   ... < skiped ",\
                        len(sorted_delay) - print_max_count,\
                        " items with less delays > ..."))
                break

    return result_str


def add_consumed_time(line):
    global delay_time_dict

    funcexit_idx = line.find('funcgraph_exit:')
    if funcexit_idx < 0:
        return

    delay_time = line[funcexit_idx + 16:].split('|')[0].strip()
    if not delay_time[0].isnumeric():
        delay_time = delay_time[1:]

    delay_value = float(delay_time[:-3])
    delay_time_dict[line] = int(delay_value * 1000)


sos_home=""
is_cmd_stopped = None
def run_traceinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home
    global print_max_count
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options] [trace.dat files]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option('-l', '--lines', dest='lines', default=0,
            action='store', type="int",
            help="Specify the maximum lines to print ( -1 means all)")

    op.add_option('-g', '--graph', dest='graph', action='store_true',
                  help='convert trace.dat to funcgraph')

    op.add_option('-o', '--outfile', dest='outfile', default="",
            action='store', type="string",
            help="Save the output to the specified file")


    op.add_option('-t', '--time', dest='time', action='store_true',
                  help='Shows the most spent functions')


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
    sos_home = env_vars['sos_home']
    data_list = args[1:]

    if o.outfile != "":
        no_pipe = True


    if o.lines != 0:
        print_max_count = o.lines
    else:
        print_max_count = 20 # default

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    if not o.time and 'trace.dat' not in data_list and isfile('trace.dat'):
        data_list.append('trace.dat')

    count = 0
    for file_path in data_list:
        try:
            if o.time:
                show_delay_list_in_file(file_path)
                continue
            

            count = count + 1
            ofile = o.outfile
            ofile = ofile.replace("%d", ("%d" % count))
            ofile = ofile.replace("%f", os.path.splitext(os.path.basename(file_path))[0])
            if ofile != "":
                ofile = " > " + ofile

            result = run_shell_command("trace-cmd report -O fgraph:tailprint %s %s" % (file_path, ofile),
                    "", no_pipe=no_pipe)
            result_str = result_str + screen.get_pipe_aware_line(result)
        except Exception as e:
            print(e)
            result_str = result_str + screen.get_pipe_aware_line("trace-cmd report for '%s' failed" % (file_path))

    else:
        pass

    return result_str
