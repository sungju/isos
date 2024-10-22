#!/usr/bin/env/python
# --------------------------------------------------------------------
# Author: Daniel Sungju Kwon
#
# Analyse page_owner data and make summary
#
# Contributors:
# --------------------------------------------------------------------
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#

import sys
import os
import re
from os.path import expanduser, isfile, isdir, join
from os import listdir
import operator
import subprocess
from subprocess import Popen, PIPE, STDOUT
import ansicolor
from optparse import OptionParser
import importlib
import time
import signal
import glob

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
#from prompt_toolkit.completion import WordCompleter
#from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.completion import merge_completers
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style

from prompt_toolkit.key_binding import KeyBindings
from shell_completer import ShellCompleter


class CtrlCKeyboardInterrupt(KeyboardInterrupt):
    def __init__(self, message):
        self.message = message
        super().__init__()


bindings = KeyBindings()
@bindings.add('c-c')
def _(event):
    # No ctrl-c allowed
    event.current_buffer.insert_text('^C')
    raise CtrlCKeyboardInterrupt("CTRL_C")


modules = []

def load_commands():
    global modules

    try:
        cmd_path_list = os.environ["ISOS_CMD_PATH"]
    except:
        cmd_path_list = '.'

    mod_command_set.clear()
    path_list = cmd_path_list.split(':')
    for path in path_list:
        try:
            source_path = path + "/cmds"
            if os.path.exists(source_path):
                load_commands_in_a_path(source_path)
        except:
            print("Couldn't find %s/cmds directory" % (path))


def show_commands(input_str, env_var, is_cmd_stopped=None, \
        show_help=False, no_pipe=True):
    if show_help:
        return "Show the pluggable command list"

    result_str = ""
    for comm in mod_command_set:
        result_str = result_str + ("%s : %s()" % (comm, mod_command_set[comm].__name__)) + "\n"

    return result_str.strip()


def reload_commands(input_str, env_str, is_cmd_stopped=None,\
        show_help=False, no_pipe=True):
    global modules
    if show_help:
        return "Reloading commands"

    for module in modules:
        try:
            print("Reloading [%s]" % (module.__name__), end='')
            module = importlib.reload(module)
            print("... DONE")
        except:
            print("... FAILED")

    print("Reloading DONE")
    return ""


def show_command_list():
    global modules

    count = len(modules)
    if count == 0:
        print("No command available")
        return

    print("-" * 75)
    for module in modules:
        print("[%s]" % (module.__name__), end='')
        try:
            print(": %s" % (module.description()))
        except:
            print(": No description available")

    print("-" * 75)
    print("There are %d commands available" % (count))
    print("=" * 75)


mod_command_set = { }

def add_command_module(new_module):
    global mod_command_set

    try:
        cmd_set = new_module.get_command_info()
        for cmd_str in cmd_set:
            func = cmd_set[cmd_str]
            if cmd_str in mod_command_set:
                print("Replacing %s from %s" % (cmd_str, mod_command_set[cmd_str]))
            mod_command_set[cmd_str] = func
        modules.append(new_module)
    except Exception as e:
        print("Failed to add command from %s" % (new_module))
        print(e)


def load_commands_in_a_path(source_path):
    global modules

    pysearchre = re.compile('.py$', re.IGNORECASE)
    cmdfiles = filter(pysearchre.search, os.listdir(source_path))
    form_module = lambda fp: '.' + os.path.splitext(fp)[0]
    cmds = map(form_module, cmdfiles)
    importlib.import_module('cmds')
    for cmd in cmds:
        if not cmd.startswith(".__"):
            try:
                new_module = importlib.import_module(cmd, package="cmds")
                if new_module.add_command() == True:
                    add_command_module(new_module)
            except Exception as e:
                print("Error in adding command %s" % (cmd))
                print(e)



def get_input_session():
    history_name = expanduser("~") + '/.isos.history'
    fhistory = None
    mode = 'w'

    if os.path.isfile(history_name):
        mode = 'a'

    try:
        open(history_name, mode).close()
    except:
        history_name = '.isos.history'
        if os.path.isfile(history_name):
            mode = 'a'
        else:
            mode = 'w'
        try:
            open(history_name, mode).close()
        except:
            history_name = ''

    if history_name != '':
        fhistory = FileHistory(history_name)

    input_session = PromptSession(history=fhistory,
                                  vi_mode=True)

    return input_session


def show_usage(input_str, env_vars, is_cmd_stopped,\
        show_help=False, no_pipe=True):
    words = input_str.split()
    if len(words) > 1 and words[1] != "help" and words[1] != "man":
        target_idx = input_str.find(words[1])
        if words[1] in command_set:
            return command_set[words[1]](input_str, env_vars, None, True)
        elif words[1] in mod_command_set:
            input_str = input_str[target_idx:].replace(words[1], words[1] + " -h")
            return mod_command_set[words[1]](input_str, env_vars, None, False)

    result_str = ("Help\n%s\n" % ("-" * 30))
    count = 0
    for key in command_set | mod_command_set:
        result_str = result_str + ("%-10s " % (key))
        count = count + 1
        if ((count % 4) == 0):
            result_str = result_str + "\n"

    if ((count % 4) != 0):
        result_str = result_str + "\n"

    return result_str


def exit_app(input_str, env_vars, is_cmd_stopped = None,\
        show_help=False, no_pipe=True):
    if show_help:
        return "Exit the application"

    sys.exit(0)


def eval_expr(input_str, env_vars, is_cmd_stopped = None,
        show_help=False, no_pipe=True):
    if show_help:
        return "Calculate expression"

    input_str = input_str.replace("eval ", "")
    return "%.2f" % (eval(input_str))


def change_dir(input_str, env_vars, is_cmd_stopped, \
        show_help=False, no_pipe=True):
    if show_help:
        return "Change directory in the app"

    words = input_str.split()
    try:
        if len(words) == 1:
            path = env_vars["sos_home"]
        else:
            path = words[1]
        path = os.path.expanduser(path)
        path = os.path.abspath(path)
        os.chdir(path)
    except:
        return ("cd: not a directory: %s" % (path))

    return ""


env_vars = {
    "sos_home": os.getcwd(),
}

def set_env(input_str, env_vars, is_cmd_stopped,\
        show_help=False, no_pipe=True):
    words = input_str.split()
    if show_help or len(words) == 1:
        result_str = "Setting variables\n================="
        for key in env_vars:
            result_str = result_str + ("\n%-15s : %s" % (key, env_vars[key]))

        return result_str

    if words[1] in env_vars:
        if len(words) >= 3:
            val = words[2]
            cdir = False
            if len(words) >= 4 and words[3] == "dir":
                cdir = True

            if words[1] == "sos_home":
                cdir = True

            if cdir:
                val = os.path.abspath(val)
                change_dir("cd %s" % (val), env_vars, is_cmd_stopped)
                val = os.getcwd()
            env_vars[words[1]] = val

            if words[1] == "sos_home":
                init_for_sos_home()
        else:
            del env_vars[words[1]]

        return ""

    if len(words) >= 3:
        env_vars[words[1]] = words[2]

    return ""


page_size=4096
def find_page_size():
    global page_size
    sos_home = env_vars['sos_home']

    page_size = 0
    try:
        with open(sos_home + "/uname", "r") as f:
            line = f.readlines()[0]
            words = line.split()
            if len(words) > 3:
                kernel_ver = words[2]
                arch = kernel_ver.split(".")[-1]
                if arch == "x86_64a":
                    page_size = 4096
                elif arch == "ppc64le":
                    page_size = 65536

                if page_size != 0:
                    return
    except Exception as e:
        pass


    try:
        if os.path.isfile(sos_home + "/proc/1/smaps"):
            pagesize_str = subprocess.check_output(['grep', 'KernelPageSize:', \
                    sos_home + '/proc/1/smaps', '-m', '1'])
            words = pagesize_str.split()
            if len(words) == 3:
                if words[2] == 'kB':
                    munit = 1024
                elif words[2] == 'mB':
                    munit = 1024 * 1024
                else:
                    munit = 1024 # Who knows
                page_size = int(words[1]) * munit
        else:
            page_size = int(subprocess.check_output(['getconf', 'PAGESIZE']))
    except Exception as e:
        pass

    if page_size == 0:
        page_size = 4096



def init_for_sos_home():
    set_time_zone(env_vars['sos_home'])
    find_page_size()


def xsos_run(input_str, env_vars, is_cmd_stopped,\
        show_help=False, no_pipe=True):
    if show_help:
        return "Run xsos within the app"

    cmd_idx = input_str.find('xsos')
    input_str = input_str[cmd_idx + 4:]

    input_str = ("xsos %s %s" % (input_str, env_vars["sos_home"]))
    result = run_shell_command(input_str)
    return result


def column_strings(strings, splitter=" "):
    max_widths = { }
    lines = strings.splitlines()
    for line in lines:
        words = line.split(splitter)
        for idx, word in enumerate(words):
            width = len(word.strip())
            if idx not in max_widths:
                max_widths[idx] = width
            elif width > max_widths[idx]:
                max_widths[idx] = width

    result_str = ""
    for line in lines:
        words = line.split(splitter)
        sline = ""
        for idx, word in enumerate(words):
            sline = sline + '{word:{width}} '.format(word=word, width=max_widths[idx])
        result_str = result_str + sline + "\n"


    return result_str


def run_shell_command(input_str, pipe_input="", no_pipe=False):
    if len(pipe_input.strip()) != 0:
        input_bytes = pipe_input.encode('utf-8')
        p = Popen(input_str, shell=True, stdout=PIPE, stdin=PIPE, stderr=STDOUT)
        stdout_result = p.communicate(input=input_bytes)[0]
        return stdout_result.decode()
    elif no_pipe == True:
        os.system(input_str)
        return ""
    else:
        p = Popen(input_str, shell=True, stdout=PIPE, stderr=STDOUT, text=True)
        result_str, errors = p.communicate()
        
        return result_str



command_set = {
    "help" : show_usage,
    "man" : show_usage,
    "cd"   : change_dir,
    "eval" : eval_expr,
    "set"  : set_env,
    "xsos" : xsos_run,
    "reload" : reload_commands,
    "list" : show_commands,
    "exit" : exit_app,
}


stop_cmd = False
orig_handler = None

def ctrl_c_handler(signum, frame):
    global stop_cmd
    stop_cmd = True


def start_input_handling():
    global stop_cmd
    global orig_handler
    stop_cmd = False
    orig_handler = signal.signal(signal.SIGINT, ctrl_c_handler)


def end_input_handling():
    global stop_cmd
    global orig_handler
    signal.signal(signal.SIGINT, orig_handler)
    stop_cmd = False


def is_cmd_stopped():
    return stop_cmd


def handle_input(input_str):
    if len(input_str.strip()) == 0:
        return ""

    orig_input_str = input_str
    shell_part = ""

    if "|" in input_str:
        pipe_idx = input_str.find("|")
        shell_part = input_str[pipe_idx + 1:]
        input_str = input_str[:pipe_idx]

    ofile_name = ""
    if ">" in input_str:
        ofile_idx = input_str.find(">")
        ofile_name = input_str[ofile_idx + 1:].strip()
        input_str = input_str[:ofile_idx]

    if shell_part != "" and ofile_name != "":
        print("Error: It's not allowed to use redirection in the middle of pipe")
        return ""
    
    words = input_str.split()
    no_pipe = shell_part == "" and ofile_name == ""

    result_str=""
    cmd_list = command_set | mod_command_set
    files = get_file_list(words[0])
    if words[0] in cmd_list:
        result_str = cmd_list[words[0]](input_str, env_vars, is_cmd_stopped,\
                False, no_pipe)
        if no_pipe:
            if len(result_str) != 0:
                print(result_str)
            return
        else:
            input_str = shell_part
    elif words[0][0] == "!": # Run shell command
        input_str = orig_input_str.strip()[1:]
        shell_part = ""
    else:
        # single ls better to get full featured output
        if words[0] == "ls" and no_pipe:
            run_shell_command(input_str + " --color -p", "", True)
            return
        elif words[0] == "vi":
            run_shell_command(input_str, "", True)
            return
        elif words[0] == "sh":
            run_shell_command(input_str, "", True)
            return
        elif len(files) or isdir(words[0]):
            if isdir(words[0]):
                result_str = change_dir("cd %s" % (words[0]), env_vars,\
                        is_cmd_stopped, False, no_pipe)
            else:
                if "cat" in cmd_list:
                    input_str = ' '.join(files)
                    result_str = cmd_list["cat"]("cat %s" % (input_str),\
                            env_vars, is_cmd_stopped, False, no_pipe)

            if no_pipe:
                if len(result_str) != 0:
                    print(result_str)
                return
            else:
                input_str = shell_part
        else:
            input_str = orig_input_str
            shell_part = ""

    if ofile_name != "":
        try:
            with open(ofile_name, 'w') as f:
                f.write(result_str)
                return
        except Exception as e:
            print(e)
            return

    result_str = run_shell_command(input_str, result_str)
    print(result_str, end="")


'''
def get_file_list():
    #files = [f for f in listdir(".") if isfile(f)]
    files = [f for f in listdir(".")]
    return files
'''

def get_file_list(pattern):
    files = [f for f in glob.glob(pattern)]
    return files



def get_home_dir():
    if "sos_home" in env_vars:
        home_path = env_vars["sos_home"]
    else:
        home_path = ""

    return home_path



styles = {
    'normal': Style.from_dict({
        'prompt': 'ansicyan bold',
    }),
    'warning': Style.from_dict({
        'prompt': 'ansiyellow bold',
    }),
    'error': Style.from_dict({
        'prompt': 'ansired bold',
    }),
}

def get_prompt_style(situation):
    """Return the appropriate style based on the situation."""
    return styles.get(situation, styles['normal'])


def get_prompt_str():
    hostname = "$HOME"
    home_path = get_home_dir()
    if home_path != "":
        hostname_str = "%s/hostname" % home_path
        if os.path.exists(hostname_str):
            with open(hostname_str) as f:
                hostname = f.read().strip()

    cur_path = os.getcwd()

    if cur_path.startswith(home_path):
        return hostname + cur_path[len(home_path):] + "> ", get_prompt_style('normal')
    else:
        return hostname + ":" + cur_path + "> ", get_prompt_style('warning')


def set_time_zone(sos_home):
    try:
        path = sos_home + "/sos_commands/systemd/timedatectl"
        with open(path) as f:
            lines = f.readlines()
            for line in lines:
                words = line.split(':')
                if words[0].strip() == "Time zone":
                    os.environ['TZ'] = words[1].split()[0]
                    time.tzset()
        return
    except:
        pass


def run_one_line(input_str):
    start_input_handling()
    try:
        handle_input(input_str)
    except Exception as e:
        print(e)
    end_input_handling()


def check_startup_script():
    try:
        fname = expanduser("~") + "/.isosrc"
        with open(fname) as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                if len(line) > 0 and line[0] != '#':
                    run_one_line(line)
    except:
        pass


def isos():
    op = OptionParser()
    op.add_option("-a", "--all", dest="all", default=0,
            action="store_true",
            help="Show everything")
    op.add_option("-o", "--os", dest="os", default=0,
            action="store_true",
            help="Show general OS information")

    (o, args) = op.parse_args()

    load_commands()

    work_dir = os.environ.get("WORK_DIR", os.getcwd())
    set_env("set sos_home %s dir" % (work_dir), env_vars, is_cmd_stopped)

    check_startup_script()

    input_session = get_input_session()
    shell_completer = ShellCompleter()
    while True:
        '''
        Both Completer doesn't match with my requirement.
        So, made new completer which was modified from PathCompleter
        file_word_completer = WordCompleter(get_file_list(), WORD=True)
        file_path_completer = PathCompleter()
        file_completer = merge_completers(
                [file_path_completer, file_word_completer],
                deduplicate = False)
        '''
        try:
            prompt_str, prompt_style = get_prompt_str()
            input_str = input_session.prompt(prompt_str,
                                             style=prompt_style,
                                             completer=shell_completer,
                                             complete_style=CompleteStyle.READLINE_LIKE,
                                             complete_while_typing=True,
                                             key_bindings=bindings,
                                            auto_suggest=AutoSuggestFromHistory())

            run_one_line(input_str)
        except CtrlCKeyboardInterrupt as e:
            if e.message == "CTRL_C":
                # It only indiates that ctrl-c is pressed
                pass
        except Exception as e:
            pass


if ( __name__ == '__main__'):
    isos()
