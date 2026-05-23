import sys
import time
from optparse import OptionParser
import os
from os import listdir
from os.path import isfile, join
from io import StringIO

import ansicolor
import screen


def description():
    return "Checking audit related information"


def add_command():
    return True


def get_command_info():
    return { "audit": run_auditinfo }


COLOR_ONE   = ""
COLOR_TWO   = ""
COLOR_THREE = ""
COLOR_FOUR  = ""
COLOR_RESET = ""

keyword_color = { }

def set_color_table(no_pipe):
    global COLOR_ONE, COLOR_TWO, COLOR_THREE
    global COLOR_FOUR, COLOR_RESET
    global keyword_color

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
    else:
        COLOR_ONE = COLOR_TWO = COLOR_THREE = ""
        COLOR_FOUR = COLOR_RESET = ""
        keyword_color = {}


def get_colored_line(line):
    global keyword_color

    result_str = ""
    words = line.split()
    for word in words:
        if is_cmd_stopped():
            return result_str

        for keyword in keyword_color:
            if word.startswith(keyword):
                word = keyword_color[keyword] + word + COLOR_RESET
        result_str = result_str + word + " "

    return result_str.strip() + "\n"


def get_colored_line_per_column(line):
    return screen.get_colored_line(line)


def read_audit_file(audit_path, no_pipe, is_log=True, show_path=False, sos_home=""):
    set_color_table(no_pipe)
    screen.init_data(no_pipe, 1, is_cmd_stopped)
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
            for line in f:
                if is_cmd_stopped():
                    break
                if is_log:
                    try:
                        words = line.split()
                        epoch = line[line.find(" msg=audit(") + 11:]
                        epoch = epoch[:epoch.find(")")]
                        if len(epoch.strip()) > 0:
                            localtime = time.ctime(float(epoch.split(':')[0]))
                        line = get_colored_line(line)
                        if len(epoch.strip()) > 0:
                            line = line.replace(epoch, localtime)
                    except:
                        pass
                else:
                    line = get_colored_line_per_column(line)

                if no_pipe:
                    print(line.strip())
                else:
                    result_str = result_str + line
            if no_pipe:
                print()
    except Exception as e:
        print(e)
        result_str = ""

    return result_str.strip()


def get_files_in_path(mypath, extension):
    if not mypath.endswith("/"):
        mypath = mypath + "/"

    onlyfiles = []
    try:
        onlyfiles = [mypath + f for f in listdir(mypath) if isfile(join(mypath, f)) and f.endswith(extension)]
    except:
        pass
    return onlyfiles


def get_audit_config_files(sos_home):
    return get_files_in_path(sos_home + "/etc/audit/", ".conf") + \
            get_files_in_path(sos_home + "/etc/audit/plugins.d/", ".conf")


def get_audit_rules_files(sos_home):
    return get_files_in_path(sos_home + "/etc/audit/", ".rules") + \
            get_files_in_path(sos_home + "/etc/audit/rules.d/", ".rules")


def get_audit_status_files(sos_home):
    return get_files_in_path(sos_home + "/sos_commands/auditd", "")


def print_config_help_msg(no_pipe):
    msg = '''audit -c  --  Show auditd configuration

SYNOPSIS
    audit -c

DESCRIPTION
    Displays auditd configuration files from the sosreport, including:
    - /etc/audit/auditd.conf (main daemon configuration)
    - /etc/audit/plugins.d/*.conf (plugin configurations)

    Each file is shown with a header separator and syntax highlighting.

OPTIONS
    -c, --config
        Show auditd configuration files.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> audit -c
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_rules_help_msg(no_pipe):
    msg = '''audit -r  --  Show audit rules

SYNOPSIS
    audit -r

DESCRIPTION
    Displays audit rule files from the sosreport, including:
    - /etc/audit/*.rules
    - /etc/audit/rules.d/*.rules

    Each file is shown with a header separator and syntax highlighting.

OPTIONS
    -r, --rules
        Show audit rules.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> audit -r
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_status_help_msg(no_pipe):
    msg = '''audit -s  --  Show current audit status

SYNOPSIS
    audit -s

DESCRIPTION
    Displays audit status output files collected under
    sos_commands/auditd/ in the sosreport (e.g. auditctl -s output).

OPTIONS
    -s, --status
        Show current audit status.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> audit -s
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
- Shows /var/log/audit/audit.log with system's time.
- Shows audit rules

Examples:
    > audit -c
    ==========> /etc/audit/auditd.conf <==========
    #
    # This file controls the configuration of the audit daemon
    #

    local_events = yes
    write_logs = yes
    log_file = /var/log/audit/audit.log
    log_group = root
    ...

    '''

    if no_pipe == False:
        output = StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()

        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""


is_cmd_stopped = None

def run_auditinfo(input_str, env_vars, is_cmd_stopped_func,\
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: audit [options]"
    cmd_examples = ""

    op = OptionParser(usage=usage, epilog=cmd_examples, add_help_option=False)
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

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        if o.audit_config:
            return print_config_help_msg(no_pipe)
        elif o.audit_rules:
            return print_rules_help_msg(no_pipe)
        elif o.audit_status:
            return print_status_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)

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
