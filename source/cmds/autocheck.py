import sys
import time
from optparse import OptionParser
from io import StringIO
import os
import glob
import operator
from os.path import expanduser, isfile, isdir, join
import traceback

import re
import importlib


from isos import run_shell_command, column_strings
import screen
import ansicolor
from soshelpers import get_main


modules = []
sysinfo = {}

def description():
    return "Detects known issues"


def add_command():
    return True


cmd_name = "autocheck"
def get_command_info():
    return { cmd_name : run_autocheck }



def get_system_info():
    global sysinfo

    try:
        with open(sos_home + "/dmidecode") as f:
            lines = f.readlines()
            for line in lines:
                if ':' not in line:
                    continue
                words = line.split(':', 1)
                sysinfo[words[0].strip()] = words[1].strip()
    except:
        pass

    try:
        with open(sos_home + "/uname") as f:
            line = f.readlines()[0]
            words = line.split()
            sysinfo["NODENAME"] = words[1]
            sysinfo["RELEASE"] = words[2]
            sysinfo["VERSION"] = line[line.find(words[3]):line.find(" " + words[12])].strip()
            sysinfo["MACHINE"] = words[12]
    except:
        pass

    try:
        with open(sos_home + "/uptime") as f:
            line = f.readlines()[0].strip()
            words = line[line.find('up') + 2:].split(',')
            sysinfo["UPTIME"] = words[0].strip() + ", " + words[1]
            sysinfo["LOAD AVERAGE"] = line[line.find("load average:") + 14:]
    except:
        pass


def load_rules():
    global modules

    cmd_path_list = ""
    try:
        cmd_path_list = os.environ["ISOS_RULES_PATH"]
    except:
        pass
    if cmd_path_list == "":
        cmd_path_list = os.path.dirname(os.path.abspath(get_main().__file__))

    path_list = cmd_path_list.split(':')
    source_path = ""
    modules = []
    for path in path_list:
        try:
            if os.path.exists(path + "/rules"):
                source_path = path + "/rules"
                load_rules_in_a_path(source_path)
        except Exception as e:
            print(e)
            print ("Couldn't find %s/rules directory" % (path))

    return modules

def show_rules_list():
    global modules

    result_str = ""
    count = len(modules)
    if count == 0:
        result_str = result_str + \
                screen.get_pipe_color_line("No rules available for this system")
        return

    result_str = result_str + screen.get_pipe_color_line("-" * 75)
    for module in modules:
        result_str = result_str + screen.get_pipe_color_line("[%s]" % (module.__name__), "blue", end='')
        if module.is_major():
            mod_color = "green"
        else:
            mod_color = ""
        try:
            result_str = result_str + \
                    screen.get_pipe_color_line(": %s" % (module.description()),
                            mod_color)
        except:
            result_str = result_str + \
                    screen.get_pipe_color_line(": No description available")


    result_str = result_str + screen.get_pipe_color_line("-" * 75)
    result_str = result_str + \
            screen.get_pipe_color_line("There are %d rules available for this system" % (count))
    result_str = result_str + screen.get_pipe_color_line("=" * 75)

    return result_str


def load_rules_in_a_path(source_path):
    global modules
    global sysinfo

    pysearchre = re.compile('.py$', re.IGNORECASE)
    rulefiles = filter(pysearchre.search, os.listdir(source_path))
    form_module = lambda fp: '.' + os.path.splitext(fp)[0]
    rules = map(form_module, rulefiles)
    importlib.import_module('rules')
    for rule in rules:
        if not rule.startswith('.__'):
            try:
                new_module = importlib.import_module(rule, package="rules")
                if new_module.add_rule(sysinfo) == True:
                   modules.append(new_module)
            except Exception as e:
                print("Error in adding rule %s" % (rule))
                print(e)


def print_result(result_list):
    result_str = ""
    for result_dict in result_list:
        result_str = result_str + screen.get_pipe_color_line("=" * 75)
        if "TITLE" in result_dict:
            result_str = result_str + \
                    screen.get_pipe_color_line("ISSUE: %s" % result_dict["TITLE"], "brown")
        else:
            result_str = result_str + \
                    screen.get_pipe_color_line("No title given", "brown")
        result_str = result_str + screen.get_pipe_color_line("-" * 75)
        if "MSG" in result_dict:
            result_str = result_str + \
                    screen.get_pipe_color_line(result_dict["MSG"])
        else:
            result_str = result_str + \
                    screen.get_pipe_color_line("No message given")
        result_str = result_str + screen.get_pipe_color_line("-" * 75)

        result_str = result_str + screen.get_pipe_color_line("KCS:", "green")
        if "KCS_TITLE" in result_dict:
            result_str = result_str + \
                    screen.get_pipe_color_line("\t%s" % result_dict["KCS_TITLE"])
        else:
            result_str = result_str + \
                    screen.get_pipe_color_line("\tNo subject for KCS")
        if "KCS_URL" in result_dict:
            result_str = result_str + \
                    screen.get_pipe_color_line("\t%s" % result_dict["KCS_URL"],
                            "blue")
        else:
            result_str = result_str + \
                    screen.get_pipe_color_line("\tNo URL for KCS", "blue")

        result_str = result_str + screen.get_pipe_color_line("Resolution:", "green")
        if "RESOLUTION" in result_dict:
            result_str = result_str + \
                    screen.get_pipe_color_line("\t%s" % result_dict["RESOLUTION"], "red")
        else:
            result_str = result_str + \
                    screen.get_pipe_color_line("\tNo resolution given", "red")

        result_str = result_str + \
                screen.get_pipe_color_line("Fixed kernel version:", "green")
        if "KERNELS" in result_dict:
            kernels = result_dict["KERNELS"]
            for kernel in kernels:
                result_str = result_str + \
                        screen.get_pipe_color_line("\t%s" % kernel, "cyan")
        else:
            result_str = result_str + \
                    screen.get_pipe_color_line("\tNo resolution given", "cyan")

        result_str = result_str + \
                screen.get_pipe_color_line("Current kernel version: %s" % sysinfo["RELEASE"], "grey")

        result_str = result_str + screen.get_pipe_color_line("-" * 75)

    return result_str


def get_file_content(path):
    try:
        with open(sos_home + path) as f:
            lines = "".join(f.readlines())
            return lines
    except:
        return "Error reading %s" % path


def run_rules():
    global modules
    global sysinfo

    result_str = ""

    issue_count = 0
    log_str = get_file_content("/var/log/messages")
    basic_data = {
        "sysinfo" : sysinfo,
        "log_str" : log_str,
        "env_vars" : env_vars,
    }

    for module in modules:
        try:
            if not options.do_all and not module.is_major():
                continue
            result_list = module.run_rule(basic_data)
            if result_list != None:
                issue_count = issue_count + len(result_list)
                result_str = result_str + print_result(result_list)
        except:
            result_str = result_str + \
                    screen.get_pipe_color_line("Error running rule %s" % (module))

    if issue_count > 0:
        result_str = result_str + screen.get_pipe_color_line("*" * 75)
        result_str = result_str + \
                screen.get_pipe_color_line("\tWARNING: %d issue%s detected" %
                    (issue_count, "s" if issue_count > 1 else ""),
                    "red")
        result_str = result_str + screen.get_pipe_color_line("*" * 75)
    else:
        result_str = result_str + \
                screen.get_pipe_color_line("No issues detected")


    return result_str


def reload_rules():
    global modules

    result_str = ""
    for module in modules:
        try:
            result_str = result_str + \
                    screen.get_pipe_color_line("Reloading [%s]" % (module.__name__), end='')
            module = importlib.reload(module)
            result_str = result_str + screen.get_pipe_color_line("... DONE")
        except:
            result_str = result_str + screen.get_pipe_color_line("... FAILED")

    result_str = result_str + screen.get_pipe_color_line("Reloading DONE")

    return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
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
options = None
no_pipe = True
env_vars = None

def run_autocheck(input_str, l_env_vars, is_cmd_stopped_func,\
        show_help=False, l_no_pipe=True):
    global is_cmd_stopped
    global sos_home
    global options
    global no_pipe
    global env_vars

    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: %s [options]" % (cmd_name)
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option("-a", "--all",
                  action="store_true",
                  dest="do_all",
                  default=False,
                  help="Do try all rules. default is doing major rules only")

    op.add_option("-l", "--list",
                  action="store_true",
                  dest="list",
                  default=False,
                  help="Shows the currently available rules")

    op.add_option("-r", "--reload",
                  action="store_true",
                  dest="reload",
                  default=False,
                  help="Re-load rules")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    options = o
    no_pipe = l_no_pipe
    env_vars = l_env_vars

    if o.help or show_help == True:
        return print_help_msg(op, no_pipe)
    
    result_str = ""
    sos_home = env_vars['sos_home']

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    get_system_info()

    load_rules()

    result_str = ""

    if o.reload == True:
        result_str = reload_rules()
    elif o.list == True:
        result_str = show_rules_list()
    else:
        result_str = run_rules()

    return result_str
