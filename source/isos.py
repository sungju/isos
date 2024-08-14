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
from os.path import expanduser, isfile, join
from os import listdir
import operator
from subprocess import Popen, PIPE, STDOUT
import ansicolor
from optparse import OptionParser
import importlib
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import CompleteStyle

modules = []

def load_commands():
    global modules

    try:
        cmd_path_list = os.environ["ISOS_CMD_PATH"]
    except:
        cmd_path_list = '.'

    path_list = cmd_path_list.split(':')
    for path in path_list:
        try:
            source_path = path + "/cmds"
            if os.path.exists(source_path):
                load_commands_in_a_path(source_path)
        except:
            print("Couldn't find %s/cmds directory" % (path))


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
        cmd_str, func = new_module.get_command_info()
        if cmd_str in mod_command_set:
            print("Replacing %s from %s" % (cmd_str, mod_command_set[cmd_str]))
        mod_command_set[cmd_str] = func
        modules.append(new_module)
    except:
        print("Failed to add command from %s" % (new_module))


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


def show_usage(input_str, env_vars, show_help=False):
    words = input_str.split()
    if len(words) > 1 and words[1] != "help":
        if words[1] in command_set:
            return command_set[words[1]](input_str, env_vars, True)
        elif words[1] in mod_command_set:
            return mod_command_set[words[1]](input_str, env_vars, True)

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


def exit_app(input_str, env_vars, show_help=False):
    if show_help:
        return "Exit the application"

    sys.exit(0)

def change_dir(input_str, env_vars, show_help=False):
    if show_help:
        return "Change directory in the app"

    words = input_str.split()
    try:
        if len(words) == 1:
            path = env_vars["sos_home"]
        else:
            path = words[1]
        path = os.path.abspath(path)
        os.chdir(path)
    except:
        return ("cd: not a directory: %s" % (path))

    return ""


env_vars = {
    "sos_home": os.getcwd(),
}

def set_env(input_str, env_vars, show_help=False):
    words = input_str.split()
    if show_help or len(words) == 1:
        result_str = "Setting variables\n================="
        for key in env_vars:
            result_str = result_str + ("\n%-15s : %s" % (key, env_vars[key]))

        return result_str

    if words[1] in env_vars:
        if len(words) >= 3:
            val = words[2]
            if len(words) >= 4 and words[3] == "dir":
                val = os.path.abspath(val)
                change_dir("cd %s" % (val), env_vars)
                val = os.getcwd()
            env_vars[words[1]] = val
        else:
            del env_vars[words[1]]

        return ""

    if len(words) >= 3:
        env_vars[words[1]] = words[2]

    return ""


def xsos_run(input_str, env_vars, show_help=False):
    if show_help:
        return "Run xsos within the app"

    cmd_idx = input_str.find('xsos')
    input_str = input_str[cmd_idx + 4:]

    input_str = ("xsos %s %s" % (input_str, env_vars["sos_home"]))
    result = run_shell_command(input_str)
    return result


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
    "cd"   : change_dir,
    "set"  : set_env,
    "xsos" : xsos_run,
    "exit" : exit_app,
}

def handle_input(input_str):
    if len(input_str.strip()) == 0:
        return ""

    orig_input_str = input_str
    shell_part = ""

    if "|" in input_str:
        pipe_idx = input_str.find("|")
        shell_part = input_str[pipe_idx + 1:]
        input_str = input_str[:pipe_idx]

    words = input_str.split()
    result_str=""
    cmd_list = command_set | mod_command_set
    if words[0] in cmd_list:
        result_str = cmd_list[words[0]](input_str, env_vars, False)
        if len(shell_part) == 0:
            if len(result_str) != 0:
                print(result_str)
            return
        else:
            input_str = shell_part
    else:
        # single ls better to get full featured output
        if words[0] == "ls" and shell_part == "":
            run_shell_command(input_str + " --color -p", "", True)
            return
        elif words[0] == "vi":
            run_shell_command(input_str, "", True)
            return

        input_str = orig_input_str
        shell_part = ""

    result_str = run_shell_command(input_str, result_str)
    print(result_str, end="")


def get_file_list():
    #files = [f for f in listdir(".") if isfile(f)]
    files = [f for f in listdir(".")]
    return files


def get_home_dir():
    if "sos_home" in env_vars:
        home_path = env_vars["sos_home"]
    else:
        home_path = ""

    return home_path


def get_prompt_str():
    hostname = "$HOME"
    home_path = get_home_dir()
    if home_path != "":
        hostname_str = "%s/hostname" % home_path
        if os.path.exists(hostname_str):
            with open(hostname_str) as f:
                hostname = f.read().strip()

    cur_path = os.getcwd()

    return hostname + cur_path[len(home_path):] + "> "


def set_time_zone(sos_home):
    path = sos_home + "/sos_commands/systemd/timedatectl"
    with open(path) as f:
        lines = f.readlines()
        for line in lines:
            words = line.split(':')
            if words[0].strip() == "Time zone":
                os.environ['TZ'] = words[1].split()[0]
                time.tzset()


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
    set_env("set sos_home %s dir" % (work_dir), env_vars)
    set_time_zone(env_vars['sos_home'])

    input_session = get_input_session()
    while True:
        file_completer = WordCompleter(get_file_list())
        input_str = input_session.prompt(get_prompt_str(),
                                         completer=file_completer,
                                         complete_style=CompleteStyle.READLINE_LIKE,
                                         complete_while_typing=True,
                                        auto_suggest=AutoSuggestFromHistory())
        handle_input(input_str)


if ( __name__ == '__main__'):
    isos()
