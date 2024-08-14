import sys
import time

import ansicolor

def description():
    return "Checking audit related information"


def add_command():
    return True


def get_command_info():
    return "audit", run_auditinfo


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

def get_colored_line(line):
    result_str = ""
    words = line.split()
    for word in words:
        for keyword in keyword_color:
            if word.startswith(keyword):
                word = keyword_color[keyword] + word + COLOR_RESET
        result_str = result_str + word + " "

    return result_str.strip() + "\n"


def read_audit_log(audit_path):
    result_str = ""
    with open(audit_path) as f:
        lines = f.readlines()
        for line in lines:
            words = line.split()
            epoch = words[1][len("msg=audit("):-2]
            localtime = time.ctime(float(epoch.split(':')[0])).replace(' ', '_')
            line = line.replace(epoch, localtime)
            result_str = result_str + get_colored_line(line)

    return result_str.strip()


def run_auditinfo(input_str, env_vars, show_help=False):
    if show_help == True:
        return description()

    result_str = read_audit_log(env_vars["sos_home"] + "/var/log/audit/audit.log")
    return result_str
