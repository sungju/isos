import sys
import time
from optparse import OptionParser
import os
from os import listdir
from os.path import isfile, join
from io import StringIO

import ansicolor


def description():
    return "Checking audit related information"


def add_command():
    return True


def get_command_info():
    return { "audit": run_auditinfo }


COLOR_ONE   = ansicolor.get_color(ansicolor.YELLOW)
COLOR_TWO   = ansicolor.get_color(ansicolor.GREEN)
COLOR_THREE = ansicolor.get_color(ansicolor.RED)
COLOR_FOUR  = ansicolor.get_color(ansicolor.CYAN)
COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

keyword_color = { }
column_color = { }

def set_color_table(no_pipe):
    global COLOR_ONE, COLOR_TWO, COLOR_THREE
    global COLOR_FOUR, COLOR_RESET
    global keyword_color
    global column_color

    if no_pipe:
        COLOR_ONE   = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_TWO   = ansicolor.get_color(ansicolor.GREEN)
        COLOR_THREE = ansicolor.get_color(ansicolor.RED)
        COLOR_FOUR  = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

        keyword_color = {
                "type=" : COLOR_ONE,
                "syscall=" : COLOR_ONE,
                "SYSCALL=" : COLOR_ONE,
                "msg=audit(" : COLOR_TWO,
                "key=" : COLOR_THREE,
                "comm=" : COLOR_FOUR,
        }

        column_color = {
                1 : COLOR_ONE,
                2 : COLOR_TWO,
                3 : COLOR_THREE,
                4 : COLOR_FOUR,
        }
    else:
        COLOR_ONE = COLOR_TWO = COLOR_THREE = ""
        COLOR_FOUR = COLOR_RESET = ""
        keyword_color = {}
        column_color = {}


def get_colored_line(line):
    global keyword_color

    result_str = ""
    words = line.split()
    for word in words:
        for keyword in keyword_color:
            if word.startswith(keyword):
                word = keyword_color[keyword] + word + COLOR_RESET
        result_str = result_str + word + " "

    return result_str.strip() + "\n"


def get_colored_line_per_column(line):
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


def read_audit_file(audit_path, no_pipe, is_log=True, show_path=False, sos_home=""):
    set_color_table(no_pipe)
    result_str = ""
    if show_path:
        file_name = audit_path.replace(sos_home, "")
        result_str = "=" * 10 + ("> %s <" % file_name) + "=" * 10
    try:
        if no_pipe:
            print(result_str)
            result_str = ""
        else:
            result_str = result_str + "\n"

        with open(audit_path) as f:
            lines = f.readlines()
            for line in lines:
                if is_cmd_stopped():
                    break
                if is_log:
                    words = line.split()
                    epoch = words[1][len("msg=audit("):-2]
                    localtime = time.ctime(float(epoch.split(':')[0]))
                    line = get_colored_line(line)
                    line = line.replace(epoch, localtime)
                else:
                    line = get_colored_line_per_column(line)

                if no_pipe:
                    print(line.strip())
                else:
                    result_str = result_str + line
            if no_pipe:
                print()
    except:
        result_str = ""

    return result_str.strip()


def get_files_in_path(mypath, extension):
    if not mypath.endswith("/"):
        mypath = mypath + "/"

    onlyfiles = [mypath + f for f in listdir(mypath) if isfile(join(mypath, f)) and f.endswith(extension)]
    return onlyfiles


def get_audit_config_files(sos_home):
    return get_files_in_path(sos_home + "/etc/audit/", ".conf") + \
            get_files_in_path(sos_home + "/etc/audit/plugins.d/", ".conf")


def get_audit_rules_files(sos_home):
    return get_files_in_path(sos_home + "/etc/audit/", ".rules") + \
            get_files_in_path(sos_home + "/etc/audit/rules.d/", ".rules")


def get_audit_status_files(sos_home):
    return get_files_in_path(sos_home + "/sos_commands/auditd", "")


is_cmd_stopped = None

def run_auditinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: audit [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option("-c", "--config", dest="audit_config", default=0,
            action="store_true",
            help="Shows auditd configuration")
    op.add_option("-r", "--rules", dest="audit_rules", default=0,
            action="store_true",
            help="Shows audit rules")
    op.add_option("-s", "--status", dest="audit_status", default=0,
            action="store_true",
            help="Shows current audit status")

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

    sos_home = env_vars["sos_home"]
    result_str = ""
    if o.audit_config:
        files = get_audit_config_files(sos_home)
        for cfile in files:
            result_str = result_str + read_audit_file(cfile, no_pipe, \
                    False, True, sos_home)
    elif o.audit_rules:
        files = get_audit_rules_files(sos_home)
        for rfile in files:
            result_str = result_str + read_audit_file(rfile, no_pipe, \
                    False, True, sos_home)
    elif o.audit_status:
        files = get_audit_status_files(sos_home)
        for rfile in files:
            result_str = result_str + read_audit_file(rfile, no_pipe, \
                    False, True, sos_home)
    else:
        result_str = read_audit_file(sos_home + "/var/log/audit/audit.log", no_pipe)
    return result_str
