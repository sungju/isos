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
import subprocess
import ansicolor
from optparse import OptionParser

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.shortcuts import CompleteStyle

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


def show_usage(input_str, show_help=False):
    words = input_str.split()
    if len(words) > 1 and words[1] != "help":
        if words[1] in command_set:
            command_set[words[1]](input_str, True)
            return True

    print("Help")
    print("-" * 30)
    count = 0
    for key in command_set:
        print("%-10s " % (key), end="")
        count = count + 1
        if ((count % 4) == 0):
            print("")

    if ((count % 4) != 0):
        print("")

    return True


def exit_app(input_str, show_help=False):
    if show_help:
        print("Exit the application")
        return True

    return False

def change_dir(input_str, show_help=False):
    if show_help:
        print("Change directory in the app")
        return True

    shell_cmd_part = ""
    if "|" in input_str:
        pipe_idx = input_str.find("|")
        shell_cmd_part = input_str[pipe_idx + 1:]
        input_str = input_str[:pipe_idx]

    words = input_str.split()
    try:
        if len(words) == 1:
            path = env_vars["sos_home"]
        else:
            path = words[1]
        path = os.path.abspath(path)
        os.chdir(path)
    except:
        print("cd: not a directory: %s" % (path))

    if shell_cmd_part != "":
        run_shell_command(shell_cmd_part)

    return True


env_vars = {
    "sos_home": os.getcwd(),
}

def set_env(input_str, show_help=False):
    words = input_str.split()
    if show_help or len(words) == 1:
        print("Setting variables")
        print("=================")
        for key in env_vars:
            print("%-15s : %s " % (key, env_vars[key]))

        return True

    if words[1] in env_vars:
        if len(words) >= 3:
            val = words[2]
            if len(words) >= 4 and words[3] == "dir":
                val = os.path.abspath(val)
                change_dir("cd %s" % (val))
            env_vars[words[1]] = val
        else:
            del env_vars[words[1]]

        return True

    if len(words) >= 3:
        env_vars[words[1]] = words[2]

    return True


def xsos_run(input_str, show_help=False):
    if show_help:
        print("Run xsos within the app")
        return True

    cmd_idx = input_str.find('xsos')
    input_str = input_str[cmd_idx + 4:]

    input_str = ("xsos %s %s" % (env_vars["sos_home"], input_str))
    run_shell_command(input_str)
    return True


def run_shell_command(input_str):
    p = subprocess.Popen(input_str, shell=True, stderr=subprocess.PIPE)

    try:
        while True:
            out = p.stderr.read(1)
            if out == '' and p.poll() != None:
                break
            if out != '':
                sys.stdout.write(out)
                sys.stdout.flush()
    except:
        pass

    return True


command_set = {
    "help" : show_usage,
    "cd"   : change_dir,
    "set"  : set_env,
    "xsos" : xsos_run,
    "exit" : exit_app,
}

def handle_input(input_str):
    if len(input_str.strip()) == 0:
        return True

    words = re.split(' |\|', input_str)
    if words[0] in command_set:
        return command_set[words[0]](input_str)

    run_shell_command(input_str)

    return True

def get_file_list():
    #files = [f for f in listdir(".") if isfile(f)]
    files = [f for f in listdir(".")]
    return files


def isos():
    op = OptionParser()
    op.add_option("-a", "--all", dest="all", default=0,
            action="store_true",
            help="Show everything")
    op.add_option("-o", "--os", dest="os", default=0,
            action="store_true",
            help="Show general OS information")

    (o, args) = op.parse_args()

    work_dir = os.environ.get("WORK_DIR", os.getcwd())
    set_env("set sos_home %s dir" % (work_dir))

    input_session = get_input_session()
    while True:
        file_completer = WordCompleter(get_file_list())
        input_str = input_session.prompt('> ',
                                         completer=file_completer,
                                         complete_style=CompleteStyle.READLINE_LIKE,
                                         complete_while_typing=True,
                                        auto_suggest=AutoSuggestFromHistory())
        cont = handle_input(input_str)
        if not cont:
            return


if ( __name__ == '__main__'):
    isos()
