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

    count = len(modules)
    if count == 0:
        print("No rules available for this system")
        return

    print("-" * 75)
    for module in modules:
        ansicolor.set_color(ansicolor.BLUE)
        print("[%s]" % (module.__name__), end='')
        if module.is_major():
            ansicolor.set_color(ansicolor.GREEN)
        else:
            ansicolor.set_color(ansicolor.RESET)
        try:
            print(": %s" % (module.description()))
        except:
            print(": No description available")

        ansicolor.set_color(ansicolor.RESET)


    print("-" * 75)
    print("There are %d rules available for this vmcore" % (count))
    print("=" * 75)


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
    for result_dict in result_list:
        print("=" * 75)
        ansicolor.set_color(ansicolor.LIGHTRED)
        if "TITLE" in result_dict:
            print("ISSUE: %s" % result_dict["TITLE"])
        else:
            print("No title given")
        ansicolor.set_color(ansicolor.RESET)
        print("-" * 75)
        if "MSG" in result_dict:
            print(result_dict["MSG"])
        else:
            print("No message given")
        print("-" * 75)

        print("KCS:")
        if "KCS_TITLE" in result_dict:
            print("\t%s" % result_dict["KCS_TITLE"])
        else:
            print("\tNo subject for KCS")
        ansicolor.set_color(ansicolor.BLUE)
        if "KCS_URL" in result_dict:
            print("\t%s" % result_dict["KCS_URL"])
        else:
            print("\tNo URL for KCS")
        ansicolor.set_color(ansicolor.RESET)

        print("Resolution:")
        ansicolor.set_color(ansicolor.RED)
        if "RESOLUTION" in result_dict:
            print("\t%s" % result_dict["RESOLUTION"])
        else:
            print("\tNo resolution given")
        ansicolor.set_color(ansicolor.RESET)

        print("Fixed kernel version: current = %s" % sysinfo["RELEASE"])
        ansicolor.set_color(ansicolor.CYAN)
        if "KERNELS" in result_dict:
            kernels = result_dict["KERNELS"]
            for kernel in kernels:
                print("\t%s" % kernel)
        else:
            print("\tNo resolution given")

        ansicolor.set_color(ansicolor.RESET)
        print("-" * 75)


def get_file_content(path):
    try:
        with open(sos_home + path) as f:
            lines = "".join(f.readlines())
            return lines
    except:
        return "Error reading %s" % path


def run_rules(options, env_vars):
    global modules
    global sysinfo

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
                print_result(result_list)
        except:
            print("Error running rule %s" % (module))

    if issue_count > 0:
        print("*" * 75)
        ansicolor.set_color(ansicolor.RED | ansicolor.BLINK)
        print("\tWARNING: %d issue%s detected" %
              (issue_count, "s" if issue_count > 1 else ""))
        ansicolor.set_color(ansicolor.RESET)
        print("*" * 75)
    else:
        print("No issues detected")


    return ""


def reload_rules():
    global modules

    for module in modules:
        try:
            print("Reloading [%s]" % (module.__name__), end='')
            module = importlib.reload(module)
            print("... DONE")
        except:
            print("... FAILED")

    print("Reloading DONE")


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
def run_autocheck(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home

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
        result_str = run_rules(o, env_vars)

    return result_str
