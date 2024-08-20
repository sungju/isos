import sys
import time

import ansicolor

import signal

stop_cmd = False

def ctrl_c_handler(signum, frame):
    global stop_cmd
    stop_cmd = True


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
        for keyword in keyword_color:
            if word.startswith(keyword):
                word = keyword_color[keyword] + word + COLOR_RESET
        result_str = result_str + word + " "

    return result_str.strip() + "\n"


def read_audit_log(audit_path, no_pipe):
    global stop_cmd

    set_color_table(no_pipe)
    result_str = ""
    try:
        with open(audit_path) as f:
            lines = f.readlines()
            for line in lines:
                if stop_cmd:
                    break
                words = line.split()
                epoch = words[1][len("msg=audit("):-2]
                localtime = time.ctime(float(epoch.split(':')[0]))
                line = get_colored_line(line)
                line = line.replace(epoch, localtime)
                if no_pipe:
                    print(line.strip())
                else:
                    result_str = result_str + line
    except:
        result_str = ""

    return result_str.strip()


def run_auditinfo(input_str, env_vars, show_help=False, no_pipe=True):
    global stop_cmd

    if show_help == True:
        return description()

    stop_cmd = False
    orig_handler = signal.signal(signal.SIGINT, ctrl_c_handler)

    result_str = read_audit_log(env_vars["sos_home"] + "/var/log/audit/audit.log", no_pipe)
    signal.signal(signal.SIGINT, orig_handler)
    return result_str
