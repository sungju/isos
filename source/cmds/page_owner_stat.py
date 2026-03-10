import sys
import os
import operator
import subprocess
import ansicolor
from optparse import OptionParser
from io import StringIO
import traceback

import screen
from soshelpers import get_main

def description():
    return "Analyse page_owner text"


def add_command():
    return True


def get_command_info():
    return { "powner": page_owner_stat }


def get_size_str(size):
    size_str = ""
    if size > (1024 * 1024 * 1024): # GiB
        size_str = "%.1f GiB" % (size / (1024*1024*1024))
    elif size > (1024 * 1024): # MiB
        size_str = "%.1f MiB" % (size / (1024*1024))
    elif size > (1024): # KiB
        size_str = "%.1f KiB" % (size / (1024))
    else:
        size_str = "%.0f B" % (size)

    return size_str


def get_module_usage_bar(module_usage_list, total_size, width=80):
    """
    Generate a single-line bar graph showing module usage distribution with colors

    Args:
        module_usage_list: List of (module_name, pages) tuples for top modules
        total_size: Total allocated size across all modules
        width: Total width of bar in characters

    Returns:
        Tuple of (bar_string, legend_string)
    """
    if total_size == 0 or len(module_usage_list) == 0:
        return ("", "")

    # Symbols for different modules (up to 10 different symbols)
    symbols = ['█', '▓', '▒', '░', '▪', '▫', '◆', '◇', '●', '○']

    # Colors for each module (10 distinct colors)
    colors = [
        ansicolor.RED,
        ansicolor.GREEN,
        ansicolor.YELLOW,
        ansicolor.BLUE,
        ansicolor.MAGENTA,
        ansicolor.CYAN,
        ansicolor.LIGHTRED,
        ansicolor.LIGHTGREEN,
        ansicolor.LIGHTYELLOW,
        ansicolor.LIGHTCYAN,
    ]

    bar_content = ""
    legend_lines = []
    reset = ansicolor.get_color(ansicolor.RESET)

    # Build the bar content (without boundaries)
    bar_length = 0
    for idx, (mod_name, pages) in enumerate(module_usage_list):
        if idx >= 10:  # Only show top 10
            break

        # Calculate how many characters this module should occupy
        percentage = (pages * 100.0 / total_size)
        chars = int((pages / total_size) * width)
        bar_length += chars

        # Use different symbol and color for each module
        symbol = symbols[idx % len(symbols)]
        color = ansicolor.get_color(colors[idx % len(colors)])

        bar_content += color + (symbol * chars) + reset

        # Build legend entry with color
        legend_lines.append("%s%s%s %s (%.1f%%)" % (color, symbol, reset, mod_name, percentage))

    # Fill remaining space with a dimmed character to show unused portion
    if bar_length < width:
        dim_color = ansicolor.get_color(ansicolor.BLACK)
        bar_content += dim_color + ("·" * (width - bar_length)) + reset

    # Add boundaries to the bar
    bar = "[" + bar_content + "]"

    # Format legend in columns (2 columns for better readability)
    legend = "\nLegend:\n"
    for i in range(0, len(legend_lines), 2):
        left = legend_lines[i]
        right = legend_lines[i + 1] if i + 1 < len(legend_lines) else ""
        legend += "  %-50s  %s\n" % (left, right)

    return (bar, legend)


alloc_by_dict = {}
alloc_type_dict = {}
alloc_module_dict = {}
page_size=4096

def handle_a_file(filename, options):
    global alloc_by_dict
    global alloc_type_dict
    global alloc_module_dict

    alloc_by_dict = {}
    alloc_type_dict = {}
    alloc_module_dict = {}

    if not os.path.isfile(filename):
        return screen.get_pipe_aware_line("File '%s' does not exist" % (filename))

    global page_size


    result_str = ""
    try:
        if options.pagesize != 0:
            page_size = options.pagesize
        else:
            page_size = get_main().page_size
    except Exception as e:
        pass

    with open(filename, 'r') as f:
        current_pos = f.tell()
        f.seek(0, 2)
        file_size = f.tell()
        f.seek(current_pos)

        while True: # Skip leading garbage lines
            line = f.readline()
            if line.strip() != "" and not line.startswith(" "):
                break

        while line:
            by_type = ""
            by_whom = ""
            mod_name = ""

            if get_main().stop_cmd:
                get_main().stop_cmd = False
                print("\n")
                break

            print("%6.2f %% of file %s has been completed" % ((f.tell() / file_size) * 100, filename), end="\r")
            
            try:
                if ("times," in line) and ("pages," in line):
                    words = line.split()
                    times = int(words[0])
                    pages = int(words[2])
                    by_type = words[6]
                    while True:
                        line = f.readline().rstrip()
                        if line.startswith(" "):
                            break

                    while True:
                        if ("0x" not in line):
                            break
                        by_whom = by_whom + "\n\t" + line
                        if "[" in line and mod_name == "":
                            mod_name = line[line.find("[") + 1:-1]
                        line = f.readline().strip()

                else:
                    words = line.split()
                    if ("times:" in line):
                        times = int(words[0])
                        words = f.readline().split(",")
                    elif words[0] == "PFN": # It's from page_owner.so extension
                        times = 1           # https://github.com/k-hagio/crash-pageowner
                        words = f.readline().split(",")
                    else:
                        times = 1
                        words = line.split(",")

                    if (len(line.strip()) == 0):
                        continue

                    if words[0].startswith("Page allocated via order"):
                        by_type = ""
                    elif len(words) >= 4 and words[0] == 'Page':
                        by_type = words[3].split()[2]
                    else:
                        by_type = ""

                    pages = 2**int(words[0].split()[-1])
                    pages = pages * times
                    while True:
                        line = f.readline().rstrip()
                        if line.startswith(" "):
                            break

                    while True:
                        line = f.readline().strip()
                        if len(line) == 0:
                            break
                        by_whom = by_whom + "\n\t" + line
                        words = line.split()
                        if "[" in words[-1] and mod_name == "":
                            mod_name = words[-1][1:-1]

            except ValueError as e:
                print(e)
                traceback.print_exc()


            alloc_pages = pages
            if by_whom != "":
                if by_whom in alloc_by_dict:
                    pages = pages + alloc_by_dict[by_whom]

                alloc_by_dict[by_whom] = pages

            if by_type != "":
                pages = alloc_pages
                if by_type in alloc_type_dict:
                    pages = pages + alloc_type_dict[by_type]

                alloc_type_dict[by_type] = pages

            if mod_name != "":
                pages = alloc_pages
                if mod_name in alloc_module_dict:
                    pages = pages + alloc_module_dict[mod_name]

                alloc_module_dict[mod_name] = pages

            # read next line
            while True:
                line = f.readline()
                if not line:  # EOF
                    break
                if line.startswith("Charged to "):
                    continue
                if line.strip():  # Non-empty line
                    break
    
    print(" " * 70, end="\r")
    if options.number > 0:
        n_items = options.number
    else:
        n_items = 10
    n_items = n_items - 1

    if len(alloc_by_dict) > 0:
        result_str = result_str + screen.get_pipe_aware_line("By call trace")
        result_str = result_str + screen.get_pipe_aware_line("=============")
        sorted_usage = sorted(alloc_by_dict.items(),
                key=operator.itemgetter(1), reverse=options.reverse)
                        
        sum_size = 0
        print_count = 0
        total_count = len(sorted_usage) - 1
        if options.all:
            print_start = 0
            print_end = total_count
        else:
            if options.reverse:
                print_start = 0
                print_end = min(total_count, n_items)
            else:
                print_start = total_count - n_items
                if print_start < 0:
                    print_start = 0
                print_end = total_count

        skip_printed = False

        for by_whom, pages in sorted_usage:
            sum_size = sum_size + pages

            if print_start <= print_count <= print_end:
                result_str = result_str + \
                        screen.get_pipe_aware_line("\n%s : %s" % \
                            (get_size_str(pages * page_size), by_whom))
            else:
                if len(sorted_usage) > n_items:
                    if not skip_printed:
                        result_str = result_str + \
                                screen.get_pipe_aware_line("\n%15s %d %s" % (
                                        "... < skipped ",
                                        len(sorted_usage) - n_items,
                                        " items > ..."))
                    skip_printed = True

            print_count = print_count + 1

        if sum_size > 0:
            result_str = result_str +\
                    screen.get_pipe_aware_line("\nTotal allocated size : %s (%s kB)" % \
                          (get_size_str(sum_size * page_size),
                           '{:,.0f}'.format(sum_size * page_size / 1024)))


    if len(alloc_module_dict) > 0:
        result_str = result_str + screen.get_pipe_aware_line("\n")
        result_str = result_str + \
                screen.get_pipe_aware_line("By allocated modules")
        result_str = result_str + \
                screen.get_pipe_aware_line("====================")
        sorted_usage = sorted(alloc_module_dict.items(),
                key=operator.itemgetter(1), reverse=options.reverse)

        sum_size = 0
        print_count = 0
        total_count = len(sorted_usage) - 1
        if options.all:
            print_start = 0
            print_end = total_count
        else:
            if options.reverse:
                print_start = 0
                print_end = min(total_count, n_items)
            else:
                print_start = total_count - n_items
                if print_start < 0:
                    print_start = 0
                print_end = total_count

        skip_printed = False
        for mod_name, pages in sorted_usage:
            sum_size = sum_size + pages

            if print_start <= print_count <= print_end:
                result_str = result_str + \
                        screen.get_pipe_aware_line("%10s : %s" % \
                            (get_size_str(pages * page_size), mod_name))
            else:
                if len(sorted_usage) > n_items:
                    if not skip_printed:
                        result_str = result_str + \
                                screen.get_pipe_aware_line("\n%15s %d %s" % \
                                        ( "... < skipped ",
                                        len(sorted_usage) - n_items,
                                        " items > ..."))
                    skip_printed = True

            print_count = print_count + 1

        if sum_size > 0:
            result_str = result_str + \
                    screen.get_pipe_aware_line("\nTotal allocated by modules : %s (%s kB)" % \
                              (get_size_str(sum_size * page_size),
                               '{:,.0f}'.format(sum_size * page_size / 1024)))

            # Add bar graph visualization for top 10 modules (always show largest)
            # Sort in descending order regardless of display options
            top_modules_sorted = sorted(alloc_module_dict.items(),
                                       key=operator.itemgetter(1), reverse=True)
            top_modules = top_modules_sorted[:min(10, len(top_modules_sorted))]
            bar, legend = get_module_usage_bar(top_modules, sum_size, width=80)
            if bar:
                result_str = result_str + screen.get_pipe_aware_line("\nModule Usage Distribution:")
                result_str = result_str + screen.get_pipe_aware_line(bar)
                result_str = result_str + screen.get_pipe_aware_line(legend)


    if len(alloc_type_dict) > 0:
        result_str = result_str + screen.get_pipe_aware_line("\n")
        result_str = result_str + screen.get_pipe_aware_line("By allocation type")
        result_str = result_str + screen.get_pipe_aware_line("==================")
        sorted_usage = sorted(alloc_type_dict.items(),
                key=operator.itemgetter(1), reverse=options.reverse)

        sum_size = 0
        print_count = 0
        total_count = len(sorted_usage) - 1
        if options.all:
            print_start = 0
            print_end = total_count
        else:
            if options.reverse:
                print_start = 0
                print_end = min(total_count, n_items)
            else:
                print_start = total_count - n_items
                if print_start < 0:
                    print_start = 0
                print_end = total_count

        skip_printed = False
        for by_type, pages in sorted_usage:
            sum_size = sum_size + pages

            if print_start <= print_count <= print_end:
                result_str = result_str + \
                        screen.get_pipe_aware_line("%10s : %s" % \
                            (get_size_str(pages * page_size), by_type))
            else:
                if len(sorted_usage) > n_items:
                    if not skip_printed:
                        result_str = result_str + \
                            screen.get_pipe_aware_line("\n%15s %d %s" % (
                                    "... < skipped ",
                                    len(sorted_usage) - n_items,
                                    " items > ..."))
                    skip_printed = True

            print_count = print_count + 1

    result_str = result_str + \
        screen.get_pipe_aware_line("\nNotes: Calculation was done with pagesize=%d" % (page_size))

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Examples:
    # To see summary with 20 entries of call trace and module list
    > powner sorted_page_owner.txt

    # To see specific number of entries only. ex) 5 entries only.
    > powner sorted_page_owner.txt -n 5

    # To see all entries.
    > powner sorted_page_owner.txt -a

    # Specify the page size when the system falsely detect the page size.
    > powner sorted_page_owner.txt -p 65536
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


sos_home=""
is_cmd_stopped = None
def page_owner_stat(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global header_start_idx
    global sos_home
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: powner [options] <page_owner.txt ...>"

    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option("-a", "--all", dest="all", default=0,
            action="store_true",
            help="Show all list")

    op.add_option("-n", "--number", dest="number", default=0,
            type=int, action="store",
            help="Show number of entries only")

    op.add_option("-p", "--pagesize", dest="pagesize", default=0,
            type=int, action="store",
            help="Set kernel pagesize. ex) ppc64le = 65536")

    op.add_option("-r", "--reverse", dest="reverse", default=0,
            action="store_true",
            help="Show in reverse")


    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True or len(args) == 1:
        return print_help_msg(op, no_pipe)

    result_str = ""
    sos_home = env_vars['sos_home']
    screen.init_data(no_pipe, 0, is_cmd_stopped)

    # Set up semantic column coloring for page owner statistics
    if no_pipe:
        screen.column_color = {
            1: screen.COLOR_1,   # Size - RED (critical memory allocation)
            2: screen.COLOR_6,   # Call trace/Module/Type - CYAN (path/identifier)
            3: screen.COLOR_3,   # Module name - YELLOW (identifier)
        }

    for file_path in args[1:]:
        try:
            result_str = result_str + handle_a_file(file_path, o)
        except Exception as e:
            print(e)
            result_str = result_str + screen.get_pipe_aware_line("page_owner file '%s' cannot read" % (file_path))


    return result_str
