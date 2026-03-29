#!/usr/bin/env/python
"""
Interactive Sosreport Shell (isos)

A command-line interface for analyzing Linux sosreport diagnostic data.
Provides interactive shell with:
- Auto-detection and display of files with syntax highlighting
- Automatic directory navigation
- Dynamic command loading from extension modules
- Integration with external tools (xsos)
- Vi-mode input editing with history
- Command piping and output redirection
- Specialized analysis commands for system diagnostics

Architecture:
    The application uses a plugin architecture where commands are
    dynamically loaded from source/cmds/ directory. Each command module
    implements a standard interface (add_command, get_command_info,
    description) to register its functionality.

Usage:
    ./isos.sh [options]

    Once started, the shell accepts:
    - Built-in commands (help, cd, set, eval, exit, etc.)
    - Extension commands (loaded from cmds/ directory)
    - File/directory names (auto-displayed or navigated)
    - Shell commands (prefixed with !)
    - History references (!N, ?N)
    - Pipes (|) and redirects (>)

Environment Variables:
    sos_home: Root directory of sosreport being analyzed
    ISOS_CMD_PATH: Colon-separated paths for command extensions
    ISOS_RULES_PATH: Paths for autocheck detection rules
    WORK_DIR: Starting directory (set by isos.sh wrapper)

Startup:
    If ~/.isosrc exists, each non-comment line is executed on startup.
    Commonly used to run 'xsos' automatically.

Examples:
    # Navigate and view files
    cd proc
    meminfo          # Auto-displays /proc/meminfo with highlighting

    # Run analysis commands
    psinfo -t        # Show top memory processes
    meminfo -s       # Show memory statistics

    # Use shell integration
    cat dmesg | grep -i error
    meminfo > /tmp/memory-analysis.txt

    # Access history
    h                # Show command history
    !5               # Re-run command 5 from original directory
    ?5               # Re-run command 5 from current directory

Author: Daniel Sungju Kwon
Version: 0.1
Copyright: 2024
"""

# --------------------------------------------------------------------
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# --------------------------------------------------------------------

import sys
import ast
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
import shlex
import traceback

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory, FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import WordCompleter, merge_completers
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from prompt_toolkit import print_formatted_text
from prompt_toolkit.key_binding import KeyBindings

from shell_completer import ShellCompleter


# ====================================================================
# Clear Python Cache on Startup
# ====================================================================

def clear_module_cache():
    """
    Clear Python bytecode cache for cmds directory.

    Ensures fresh imports after code updates. Only clears cache for
    command modules, not for the venv libraries.
    """
    try:
        import shutil
        from pathlib import Path

        source_dir = Path(__file__).parent
        cmds_dir = source_dir / 'cmds'

        # Clear cmds/__pycache__
        cmds_pycache = cmds_dir / '__pycache__'
        if cmds_pycache.exists():
            shutil.rmtree(cmds_pycache, ignore_errors=True)

        # Clear any .pyc files in cmds
        for pyc_file in cmds_dir.glob('*.pyc'):
            pyc_file.unlink(missing_ok=True)

    except Exception:
        # Silently ignore cache clearing errors
        pass

# Clear cache on startup to ensure fresh imports
clear_module_cache()


# ====================================================================
# Constants
# ====================================================================

ISOS_VERSION = "0.2"
ISOS_YEARS = "2024-2026"

# Default command path for extension loading
DEFAULT_CMD_PATH = "."

# Default page size for memory calculations (bytes)
DEFAULT_PAGE_SIZE = 4096

# Architectures and their page sizes
ARCH_PAGE_SIZES = {
    "x86_64a": 4096,
    "ppc64le": 65536,
}


# ====================================================================
# Custom Exceptions
# ====================================================================

class CtrlCKeyboardInterrupt(KeyboardInterrupt):
    """
    Custom exception for Ctrl-C handling.

    Allows distinguishing between user Ctrl-C press and actual
    keyboard interrupt, enabling insertion of ^C text instead of
    exiting the application.
    """
    def __init__(self, message):
        self.message = message
        super().__init__()


def safe_eval_expr(expr):
    """
    Evaluate a numeric expression in a safe AST-based evaluator.
    """
    allowed_bin_ops = (
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
    )
    allowed_unary_ops = (
        ast.UAdd,
        ast.USub,
    )

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError("Only numeric values are supported")
            return node.value
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, allowed_bin_ops):
                raise ValueError("Unsupported operator")
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left ** right
            raise ValueError("Unsupported operator")
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, allowed_unary_ops):
                raise ValueError("Unsupported unary operator")
            operand = _eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +operand
            return -operand
        raise ValueError("Invalid expression")

    return _eval(ast.parse(expr, mode="eval"))


# ====================================================================
# Key Bindings
# ====================================================================

bindings = KeyBindings()

@bindings.add('c-c')
def handle_ctrl_c(event):
    """
    Handle Ctrl-C by inserting ^C text instead of interrupting.

    Prevents accidental exits while allowing users to cancel
    current input line.
    """
    event.current_buffer.insert_text('^C')
    raise CtrlCKeyboardInterrupt("CTRL_C")


# ====================================================================
# Global State
# ====================================================================

# Loaded command modules
modules = []

# Command name -> function mapping for extensions
mod_command_set = {}
mod_command_origin = {}
mod_aliases_seen = set()

# Environment variables (sos_home is the most important)
env_vars = {
    "WORK_DIR": os.environ.get("WORK_DIR", os.getcwd()),
    "sos_home": os.getcwd(),
}

# Signal handling state
stop_cmd = False
orig_handler = None

# Command history tracking (separate from prompt_toolkit history)
history_cmds = []
history_cwds = []

# Last command arguments for $0, $1, etc. substitution
last_args = []
last_result = None

# System page size detection
page_size = DEFAULT_PAGE_SIZE


# ====================================================================
# Module Loading
# ====================================================================

def _is_module_path_trusted(path):
    """
    Return True if a module load path is safe to import from.

    A path is considered untrusted if it is world-writable (mode & 0o002),
    which means any user on the system could plant malicious .py files there.
    Prints a warning and returns False for untrusted paths.
    """
    try:
        real_path = os.path.realpath(path)
        if not os.path.isdir(real_path):
            return False
        mode = os.stat(real_path).st_mode
        if mode & 0o002:
            print("Security warning: skipping module path '%s' — directory is world-writable" % path)
            return False
    except OSError:
        return False
    return True


def load_commands():
    """
    Load command extension modules from ISOS_CMD_PATH.

    Searches all directories in ISOS_CMD_PATH (colon-separated) for
    .py files in their cmds/ subdirectories. Modules implementing
    the command interface are loaded and registered.

    Sets:
        modules: List of loaded module objects
        mod_command_set: Dict mapping command names to functions

    Note:
        Clears mod_command_set before loading. Uses DEFAULT_CMD_PATH
        if ISOS_CMD_PATH environment variable not set.
    """
    global modules
    global mod_aliases_seen

    try:
        cmd_path_list = os.environ["ISOS_CMD_PATH"]
    except KeyError:
        cmd_path_list = DEFAULT_CMD_PATH

    mod_command_set.clear()
    mod_aliases_seen.clear()
    path_list = cmd_path_list.split(':')
    for path in path_list:
        try:
            source_path = path + "/cmds"
            if os.path.exists(source_path):
                if not _is_module_path_trusted(source_path):
                    continue
                load_commands_in_a_path(source_path)
        except (IOError, OSError) as e:
            print("Couldn't find %s/cmds directory: %s" % (path, str(e)))


def load_commands_in_a_path(source_path):
    """
    Load all command modules from a specific directory.

    Args:
        source_path: Path to directory containing command .py files

    Note:
        Modules must implement:
        - add_command(): Returns True if should be loaded
        - get_command_info(): Returns {name: function} dict
    """
    global modules

    # Find all .py files
    pysearchre = re.compile('.py$', re.IGNORECASE)
    cmdfiles = sorted(filter(pysearchre.search, os.listdir(source_path)))
    form_module = lambda fp: '.' + os.path.splitext(fp)[0]
    cmds = map(form_module, cmdfiles)

    # Import cmds package
    importlib.import_module('cmds')

    # Load each command module
    for cmd in cmds:
        if not cmd.startswith(".__"):
            try:
                new_module = importlib.import_module(cmd, package="cmds")
                if new_module.add_command() == True:
                    add_command_module(new_module)
            except Exception as e:
                print("Error in adding command %s: %s" % (cmd, str(e)))


def add_command_module(new_module):
    """
    Register a command module in the global command set.

    Args:
        new_module: Module object with get_command_info() function

    Note:
        Replaces existing commands with same name (prints warning)
    """
    global mod_command_set

    try:
        module_name = new_module.__name__
        cmd_set = new_module.get_command_info()
        for cmd_str in cmd_set:
            if not isinstance(cmd_set[cmd_str], type(lambda: None)):
                print("Ignoring '%s' from %s: invalid command handler type" % (cmd_str, module_name))
                continue
            func = cmd_set[cmd_str]
            if cmd_str in mod_command_set:
                prev_mod = mod_command_origin.get(cmd_str, "unknown")
                print("Replacing command '%s' from %s" % (cmd_str, prev_mod))
            if cmd_str in command_set:
                print("Warning: extension command '%s' shadows a built-in command" % (cmd_str))
            mod_command_set[cmd_str] = func
            mod_command_origin[cmd_str] = module_name
        if module_name not in mod_aliases_seen:
            modules.append(new_module)
            mod_aliases_seen.add(module_name)
    except Exception as e:
        print("Failed to add command from %s: %s" % (new_module, str(e)))


def reload_commands(input_str, env_str, is_cmd_stopped=None,
                    show_help=False, no_pipe=True):
    """
    Reload all extension modules without restarting application.

    Usage:
        /reload

    Useful for development - allows testing changes to command modules
    without exiting and restarting isos.

    Args:
        input_str: Command arguments (unused)
        env_str: Environment variables (unused)
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, return help text instead of executing
        no_pipe: True if output goes to terminal

    Returns:
        Empty string (output printed directly)
    """
    global modules

    if show_help:
        return "Usage) /reload\n\n[For developers only]\nReloading isos extension modules"

    for module in modules:
        try:
            print("Reloading [%s]" % (module.__name__), end='')
            module = importlib.reload(module)
            print("... DONE")
        except Exception as e:
            print("... FAILED: %s" % str(e))

    print("Reloading DONE")
    return ""


def show_commands(input_str, env_var, is_cmd_stopped=None,
                  show_help=False, no_pipe=True):
    """
    Display list of loaded extension modules and their functions.

    Usage:
        /list

    Args:
        input_str: Command arguments (unused)
        env_var: Environment variables (unused)
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, return help text instead of executing
        no_pipe: True if output goes to terminal

    Returns:
        String with command -> function mappings, one per line
    """
    if show_help:
        return "Usage) /list\n\n[For developers only]\nShow the extension module list"

    result_str = ""
    for comm in mod_command_set:
        result_str = result_str + ("%s : %s()" % (comm, mod_command_set[comm].__name__)) + "\n"

    return result_str.strip()


def show_command_list():
    """
    Print summary of all loaded commands with descriptions.

    Output format:
        ----- (separator)
        [module_name]: description
        ...
        ----- (separator)
        Total count
        ===== (separator)
    """
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
        except AttributeError:
            print(": No description available")

    print("-" * 75)
    print("There are %d commands available" % (count))
    print("=" * 75)


# ====================================================================
# Built-in Commands
# ====================================================================

def show_usage(input_str, env_vars, is_cmd_stopped,
               show_help=False, no_pipe=True):
    """
    Display help information for commands.

    Usage:
        help              Show all commands
        help <command>    Show help for specific command
        man <command>     Same as help <command>
        help -v           Show version information

    Args:
        input_str: Command line input
        env_vars: Environment variables dict
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: Not used (help always shows help)
        no_pipe: True if output goes to terminal

    Returns:
        Formatted help text string
    """
    words = input_str.split()

    # Show help for specific command
    if len(words) > 1 and words[1] != "help" and words[1] != "man":
        target_idx = input_str.find(words[1])
        if words[1] in command_set:
            return command_set[words[1]](input_str, env_vars, None, True)
        elif words[1] in mod_command_set:
            input_str = input_str[target_idx:].replace(words[1], words[1] + " -h")
            return mod_command_set[words[1]](input_str, env_vars, None, False)

    # Show version
    if len(words) > 1 and words[1] == "-v":
        result_str = "isos v%s\nCopyright (c) %s Sungju Kwon\n\n" % \
                (ISOS_VERSION, ISOS_YEARS)
    else:
        result_str = ""

    # Show all commands
    # Sort with regular commands first, then '/' commands at the end
    result_str = result_str + ("Help\n%s\n" % ("-" * 30))
    count = 0
    combined_dict = command_set | mod_command_set
    # Custom sort: (0, name) for regular commands, (1, name) for '/' commands
    combined_dict = dict(sorted(combined_dict.items(),
                                key=lambda item: (1 if item[0].startswith('/') else 0, item[0])))

    slash_section_started = False
    for key in combined_dict:
        # Add blank line before first '/' command
        if key.startswith('/') and not slash_section_started:
            # End current line if needed
            if (count % 4) != 0:
                result_str = result_str + "\n"
            # Add blank line separator
            result_str = result_str + "\n"
            slash_section_started = True
            count = 0  # Reset count for new section

        result_str = result_str + ("%-10s " % (key))
        count = count + 1
        if ((count % 4) == 0):
            result_str = result_str + "\n"

    if ((count % 4) != 0):
        result_str = result_str + "\n"

    return result_str


def exit_app(input_str, env_vars, is_cmd_stopped=None,
             show_help=False, no_pipe=True):
    """
    Exit the isos application.

    Usage:
        exit

    Args:
        input_str: Command arguments (unused)
        env_vars: Environment variables (unused)
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, return help text instead of exiting
        no_pipe: True if output goes to terminal

    Returns:
        Help text if show_help=True, otherwise exits
    """
    if show_help:
        return "Usage) exit\n\nExit the isos application"

    sys.exit(0)


def eval_expr(input_str, env_vars, is_cmd_stopped=None,
              show_help=False, no_pipe=True):
    """
    Evaluate mathematical expression.

    Args:
        input_str: Expression string (e.g., "eval 1024*1024")
        env_vars: Environment variables (unused)
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, return help text instead of evaluating
        no_pipe: True if output goes to terminal

    Returns:
        Result formatted to 2 decimal places

    Example:
        eval 53828382/1024/1024
        # Returns: "51.33"

    """
    if show_help:
        result = "Calculate expression\n\neval <expression>\n\nExample) eval 53828382/1024/1024\n51.33"
        return result

    expression = input_str.replace("eval ", "", 1).strip()
    if len(expression) == 0:
        return "Usage: eval <expression>"

    try:
        return "%.2f" % (safe_eval_expr(expression))
    except Exception as e:
        return "Invalid expression: %s" % str(e)


def change_dir(input_str, env_vars, is_cmd_stopped,
               show_help=False, no_pipe=True):
    """
    Change current working directory.

    Args:
        input_str: Command string (e.g., "cd /path" or just "cd")
        env_vars: Environment variables dict (uses sos_home for cd with no args)
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, return help text instead of changing directory
        no_pipe: True if output goes to terminal

    Returns:
        Error message if directory change fails, empty string on success

    Note:
        cd with no arguments changes to sos_home
    """
    if show_help:
        result = "Change directory in the app\n\ncd <directory path>"
        return result

    words = input_str.split()
    try:
        if len(words) == 1:
            path = env_vars["sos_home"]
        else:
            path = words[1]
        path = os.path.expanduser(path)
        path = os.path.abspath(path)
        os.chdir(path)
    except (OSError, IOError) as e:
        return ("cd: not a directory: %s (%s)" % (path, str(e)))

    return ""


def set_home(input_str, env_vars, is_cmd_stopped,
             show_help=False, no_pipe=True):
    """
    Set sosreport root directory (shortcut for '/set sos_home').

    Usage:
        /sethome [path]

    Args:
        input_str: Command string (e.g., "/sethome /path")
        env_vars: Environment variables dict
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, return help text
        no_pipe: True if output goes to terminal

    Returns:
        Result from set_env()
    """
    words = input_str.split()
    if show_help:
        result_str = "Usage) /sethome [path]\n\nChange sosreport root directory"
        return result_str

    new_path = "."
    if len(words) > 1:
        new_path = words[1]
    input_str = "/set sos_home %s" % new_path

    return set_env(input_str, env_vars, is_cmd_stopped, show_help, no_pipe)


def set_env(input_str, env_vars, is_cmd_stopped,
            show_help=False, no_pipe=True):
    """
    Set or display environment variables.

    Usage:
        /set                     # Show all variables
        /set var value           # Set variable
        /set var value dir       # Set variable and cd to value
        /set var                 # Delete variable

    Args:
        input_str: Command string
        env_vars: Environment variables dict
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, display all variables
        no_pipe: True if output goes to terminal

    Returns:
        Variable listing if show_help or no args, empty string otherwise

    Note:
        Setting sos_home automatically triggers init_for_sos_home() and
        check_startup_script()
    """
    words = input_str.split()
    if show_help or len(words) == 1:
        result_str = "Usage) /set [var] [value] [dir]\n\nSetting variables\n================="
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

            check_startup_script()
        else:
            del env_vars[words[1]]

        return ""

    if len(words) >= 3:
        env_vars[words[1]] = words[2]

    return ""


def xsos_run(input_str, env_vars, is_cmd_stopped,
             show_help=False, no_pipe=True):
    """
    Run external xsos tool for sosreport analysis.

    Automatically passes sos_home to xsos unless different path specified.

    Args:
        input_str: Command arguments for xsos
        env_vars: Environment variables dict
        is_cmd_stopped: Function to check for Ctrl-C
        show_help: If True, show xsos help
        no_pipe: True if output goes to terminal

    Returns:
        Output from xsos command

    Example:
        xsos            # Run xsos on current sosreport
        xsos -m         # Show memory info
        xsos /other     # Run on different sosreport
    """
    if show_help:
        result = run_shell_command("xsos -h")
        return result

    cmd_idx = input_str.find('xsos')
    input_str = input_str[cmd_idx + 4:]
    sos_home = env_vars["sos_home"]

    try:
        words = input_str.split()
        for word in words:
            if not word.startswith("-"):
                sos_home = os.path.abspath(word)
                input_str = input_str.replace(" %s" % word, "")
                break
    except Exception:
        pass

    input_str = ("xsos %s %s" % (input_str, sos_home))
    result = run_shell_command(input_str)
    return result


# Built-in command registry
command_set = {
    "help" : show_usage,
    "man" : show_usage,
    "cd"   : change_dir,
    "eval" : eval_expr,
    "/set"  : set_env,
    "/sethome" : set_home,
    "xsos" : xsos_run,
    "/reload" : reload_commands,
    "/list" : show_commands,
    "exit" : exit_app,
}


# ====================================================================
# System Detection and Initialization
# ====================================================================

def find_page_size():
    """
    Detect system page size from sosreport data.

    Checks in order:
    1. Architecture from uname output
    2. KernelPageSize from /proc/1/smaps
    3. Falls back to DEFAULT_PAGE_SIZE (4096)

    Sets:
        page_size: Global page size in bytes

    Note:
        Used for memory calculations in various commands
    """
    global page_size
    sos_home = env_vars['sos_home']

    page_size = 0

    # Try to determine from architecture
    try:
        with open(sos_home + "/uname", "r") as f:
            line = f.readlines()[0]
            words = line.split()
            if len(words) > 3:
                kernel_ver = words[2]
                arch = kernel_ver.split(".")[-1]
                if arch in ARCH_PAGE_SIZES:
                    page_size = ARCH_PAGE_SIZES[arch]
                    return
    except (IOError, OSError, IndexError):
        pass

    # Try to read from /proc/1/smaps
    try:
        if os.path.isfile(sos_home + "/proc/1/smaps"):
            pagesize_str = subprocess.check_output(['grep', 'KernelPageSize:',
                    sos_home + '/proc/1/smaps', '-m', '1'])
            words = pagesize_str.split()
            if len(words) == 3:
                if words[2] == b'kB':
                    munit = 1024
                elif words[2] == b'mB':
                    munit = 1024 * 1024
                else:
                    munit = 1024  # Default assumption
                page_size = int(words[1]) * munit
        else:
            # Fall back to local system page size
            page_size = int(subprocess.check_output(['getconf', 'PAGESIZE']))
    except (subprocess.CalledProcessError, ValueError, IndexError, OSError):
        pass

    # Final fallback
    if page_size == 0:
        page_size = DEFAULT_PAGE_SIZE


def set_time_zone(sos_home):
    """
    Set TZ environment variable from sosreport's timedatectl output.

    Allows displaying timestamps in the system's local time rather than
    the analyzing machine's timezone.

    Args:
        sos_home: Root directory of sosreport

    Note:
        Silently fails if timedatectl output not found or can't be parsed
    """
    try:
        path = sos_home + "/sos_commands/systemd/timedatectl"
        with open(path) as f:
            for line in f:
                words = line.split(':')
                if words[0].strip() == "Time zone":
                    os.environ['TZ'] = words[1].split()[0]
                    time.tzset()
        return
    except (IOError, OSError, IndexError, KeyError):
        pass


def init_for_sos_home():
    """
    Initialize environment when sos_home changes.

    Performs:
    - Timezone detection and setting
    - Page size detection

    Note:
        Called automatically when sos_home is set via set or sethome
    """
    set_time_zone(env_vars['sos_home'])
    find_page_size()


# ====================================================================
# Signal Handling
# ====================================================================

def ctrl_c_handler(signum, frame):
    """
    Signal handler for SIGINT (Ctrl-C).

    Sets global stop_cmd flag which can be checked by long-running
    operations via is_cmd_stopped().

    Args:
        signum: Signal number
        frame: Current stack frame
    """
    global stop_cmd
    stop_cmd = True


def start_input_handling():
    """
    Install Ctrl-C handler for command execution.

    Saves original handler for later restoration.
    """
    global stop_cmd, orig_handler
    stop_cmd = False
    orig_handler = signal.signal(signal.SIGINT, ctrl_c_handler)


def end_input_handling():
    """
    Restore original Ctrl-C handler after command execution.

    Resets stop_cmd flag.
    """
    global stop_cmd, orig_handler
    signal.signal(signal.SIGINT, orig_handler)
    stop_cmd = False


def is_cmd_stopped():
    """
    Check if command should stop due to Ctrl-C.

    Returns:
        True if Ctrl-C was pressed during execution

    Note:
        Long-running commands should call this in loops and
        return early if True
    """
    return stop_cmd


# ====================================================================
# Shell Integration
# ====================================================================

def run_shell_command(input_str, pipe_input="", no_pipe=False):
    """
    Execute shell command with optional piped input.

    Args:
        input_str: Shell command to execute (string or list of args)
        pipe_input: String to pipe as stdin (default empty)
        no_pipe: If True, run with subprocess for full terminal output

    Returns:
        Command output as string, or empty string if no_pipe=True

    Example:
        # Run command and capture output
        result = run_shell_command("ls -la")

        # Pipe input to command
        result = run_shell_command("grep ERROR", pipe_input=log_data)

        # Run interactive command
        run_shell_command("vi file.txt", no_pipe=True)
    """
    # Accept pre-split argument lists to avoid shell injection when callers
    # build commands with untrusted file paths or values.
    use_shell = isinstance(input_str, str)

    if len(pipe_input.strip()) != 0:
        input_bytes = pipe_input.encode('utf-8')
        p = Popen(input_str, shell=use_shell, stdout=PIPE, stdin=PIPE, stderr=STDOUT)
        stdout_result = p.communicate(input=input_bytes)[0]
        return stdout_result.decode()
    elif no_pipe == True:
        subprocess.run(input_str, shell=use_shell)
        return ""
    else:
        p = Popen(input_str, shell=use_shell, stdout=PIPE, stderr=STDOUT, text=True)
        result_str, errors = p.communicate()
        return result_str


def get_file_list(pattern):
    """
    Get list of files matching glob pattern.

    Args:
        pattern: Glob pattern (e.g., "*.txt", "/path/to/*.log")

    Returns:
        List of matching file paths

    Example:
        files = get_file_list("*.py")
    """
    files = [f for f in glob.glob(pattern)]
    return files


def column_strings(strings, splitter=" "):
    """
    Format multi-line string into aligned columns.

    Args:
        strings: Multi-line string with column data
        splitter: Column separator (default space)

    Returns:
        Formatted string with aligned columns

    Note:
        Currently unused in codebase
    """
    max_widths = {}
    lines = strings.splitlines()

    # Find maximum width for each column
    for line in lines:
        words = line.split(splitter)
        for idx, word in enumerate(words):
            width = len(word.strip())
            if idx not in max_widths:
                max_widths[idx] = width
            elif width > max_widths[idx]:
                max_widths[idx] = width

    # Format each line with aligned columns
    result_str = ""
    for line in lines:
        words = line.split(splitter)
        sline = ""
        for idx, word in enumerate(words):
            sline = sline + '{word:{width}} '.format(word=word, width=max_widths[idx])
        result_str = result_str + sline + "\n"

    return result_str


# ====================================================================
# Input Handling and Command Execution
# ====================================================================

def substitute_variables(text):
    """
    Substitute command-line variables in input text.

    Supports:
        $0, $1, $2, ... : Arguments from last command
        !$              : Last argument from last command
        $?              : Last result

    Args:
        text: Input text with possible variable references

    Returns:
        Text with variables substituted

    Example:
        Last command was: cat file.txt
        Input: grep ERROR $1
        Result: grep ERROR file.txt
    """
    result = text
    for i, arg in enumerate(last_args):
        result = result.replace(f"${i}", arg)
    if len(last_args) > 0:
        result = result.replace(f"!$", last_args[-1])
    if last_result is not None:
        result = result.replace("$?", str(last_result))
    return result


def handle_input(input_str):
    """
    Parse and execute user input with full shell-like features.

    Supports:
    - Built-in commands and extension commands
    - File/directory auto-detection and display
    - Shell command execution (! prefix)
    - Pipes (|) to shell commands
    - Output redirection (>)
    - Variable substitution ($0, $1, !$, $?)

    Args:
        input_str: Raw input string from user

    Note:
        Sets global last_args for variable substitution
        Updates last_result (currently not fully implemented)
    """
    global last_args

    if len(input_str.strip()) == 0:
        return ""

    # Substitute variables ($0, $1, !$, $?)
    orig_input_str = input_str
    input_str = substitute_variables(input_str)
    if input_str != orig_input_str:
        orig_input_str = input_str
        print("%s%s" % (get_prompt_str()[0], input_str))

    try:
        last_args = shlex.split(input_str)
    except Exception as e:
        print("Error parsing input: %s" % str(e))
        return ""
    shell_part = ""

    # Extract pipe portion
    if "|" in input_str:
        pipe_idx = input_str.find("|")
        shell_part = input_str[pipe_idx + 1:]
        input_str = input_str[:pipe_idx]

    # Extract redirect portion
    ofile_name = ""
    if ">" in input_str:
        ofile_idx = input_str.find(">")
        ofile_name = input_str[ofile_idx + 1:].strip()
        input_str = input_str[:ofile_idx]

    # Check for invalid syntax
    if shell_part != "" and ofile_name != "":
        print("Error: It's not allowed to use redirection in the middle of pipe")
        return ""

    words = input_str.split()
    no_pipe = shell_part == "" and ofile_name == ""

    result_str = ""
    cmd_list = command_set | mod_command_set
    files = get_file_list(words[0])

    # Check if it's a registered command
    if words[0] in cmd_list:
        result_str = cmd_list[words[0]](input_str, env_vars, is_cmd_stopped,
                False, no_pipe)
        if no_pipe:
            if len(result_str) != 0:
                print(result_str)
            return
        else:
            input_str = shell_part

    # Shell command execution (! prefix)
    elif words[0][0] == "!":
        input_str = orig_input_str.strip()[1:]
        shell_part = ""

    # Special handling for common commands
    else:
        # Single 'ls' gets color output
        if words[0] == "ls" and no_pipe:
            run_shell_command(input_str + " --color -p", "", True)
            return

        # Auto-display files or auto-cd directories
        elif len(files) or isdir(words[0]):
            if isdir(words[0]):
                result_str = change_dir("cd %s" % (words[0]), env_vars,
                        is_cmd_stopped, False, no_pipe)
            else:
                if "cat" in cmd_list:
                    input_str = ' '.join(files)
                    result_str = cmd_list["cat"]("cat %s" % (input_str),
                            env_vars, is_cmd_stopped, False, no_pipe)

            if no_pipe:
                if len(result_str) != 0:
                    print(result_str)
                return
            else:
                input_str = shell_part
        else:
            # Default to shell command
            input_str = orig_input_str
            shell_part = ""

    # Handle output redirection
    if ofile_name != "":
        # Restrict redirect targets to the sosreport directory or /tmp.
        # Absolute paths outside these roots require explicit confirmation.
        safe_roots = []
        sos_home_val = env_vars.get("sos_home", "") if env_vars else ""
        if sos_home_val:
            safe_roots.append(os.path.realpath(sos_home_val))
        safe_roots.append(os.path.realpath("/tmp"))

        resolved = os.path.realpath(
            os.path.join(os.getcwd(), ofile_name) if not os.path.isabs(ofile_name) else ofile_name
        )
        in_safe_root = any(
            resolved.startswith(root + os.sep) or resolved == root
            for root in safe_roots
        )
        if not in_safe_root:
            confirm = input(
                "Warning: redirect target '%s' is outside the sosreport directory. Write anyway? [y/N] " % ofile_name
            ).strip().lower()
            if confirm != 'y':
                print("Redirect cancelled.")
                return

        try:
            with open(ofile_name, 'w') as f:
                f.write(result_str)
                return
        except (IOError, OSError) as e:
            print("Error writing to %s: %s" % (ofile_name, str(e)))
            return

    # Execute shell portion of pipe
    result_str = run_shell_command(input_str, result_str, shell_part == "")
    print(result_str, end="")


# ====================================================================
# History Management
# ====================================================================

def parse_history(input_str):
    """
    Parse and execute history-related commands.

    Supports:
        h or history     : Show command history
        h -d            : Show history with directory context
        !N              : Re-execute command N from its original directory
        ?N              : Re-execute command N from current directory

    Args:
        input_str: Input string potentially containing history reference

    Returns:
        Tuple of (command_string, run_path)
        - command_string: Actual command to run (empty if history display)
        - run_path: Directory to run command in (empty for current dir)

    Note:
        Maintains global history_cmds and history_cwds lists
    """
    global history_cmds, history_cwds

    input_str = input_str.strip()
    if len(input_str) == 0:
        return "", ""

    words = input_str.split()
    sos_home = env_vars["sos_home"]

    # Display history
    if words[0] == "h" or words[0] == "history":
        idx = 1
        show_dir = (len(words) > 1 and words[1] == "-d")

        for item in history_cmds:
            item = "<b>%s</b>" % (item)
            if show_dir:
                cmd_path = history_cwds[idx - 1]
                if cmd_path.startswith(sos_home):
                    cmd_path = cmd_path.replace(sos_home, "~")
                item = "%s <ansigreen>[%s]</ansigreen>" % (item, cmd_path)

            print_formatted_text(HTML("[%d] %s" % (idx, item)))
            idx = idx + 1
        return "", ""

    # Expand history references (!N or ?N)
    modified = False
    run_path = ""
    for word in words:
        if word.startswith("!") and word[1:].isdecimal():
            # !N - run from original directory
            hidx = int(word[1:], 10) - 1
            if hidx < 0 or hidx >= len(history_cmds):
                print("History index %d is out of range" % (hidx + 1))
                return "", ""
            input_str = input_str.replace(word, history_cmds[hidx])
            run_path = history_cwds[hidx]
            modified = True
        elif word.startswith("?") and word[1:].isdecimal():
            # ?N - run from current directory
            hidx = int(word[1:], 10) - 1
            if hidx < 0 or hidx >= len(history_cmds):
                print("History index %d is out of range" % (hidx + 1))
                return "", ""
            input_str = input_str.replace(word, history_cmds[hidx])
            modified = True

    if modified:
        print(input_str)

    # Add to history (avoid duplicates)
    if input_str != "":
        hlen = len(history_cmds)
        cwd = os.getcwd()
        if hlen > 0 and history_cmds[hlen - 1] == input_str and \
            history_cwds[hlen - 1] == cwd:
            pass  # Don't add duplicate consecutive entries
        else:
            history_cmds.append(input_str)
            history_cwds.append(cwd)

    return input_str, run_path


def run_one_line(input_str, path):
    """
    Execute a single command line with optional directory change.

    Args:
        input_str: Command string to execute
        path: Directory to change to before execution (empty for current)

    Note:
        Handles signal setup/teardown and restores original directory
    """
    cur_path = os.getcwd()
    if path != "":
        os.chdir(path)

    start_input_handling()
    try:
        handle_input(input_str)
    except Exception as e:
        traceback.print_exc()
        print("Error executing command: %s" % str(e))
    end_input_handling()

    if path != "":
        os.chdir(cur_path)


# ====================================================================
# Prompt Generation
# ====================================================================

# Prompt styles for different situations
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
    """
    Get prompt style for given situation.

    Args:
        situation: One of 'normal', 'warning', 'error'

    Returns:
        Style object for prompt_toolkit
    """
    return styles.get(situation, styles['normal'])


def get_home_dir():
    """
    Get sosreport home directory from environment.

    Returns:
        sos_home path or empty string if not set
    """
    if "sos_home" in env_vars:
        home_path = env_vars["sos_home"]
    else:
        home_path = ""

    return home_path


def get_home_path_str():
    """
    Get hostname and home path for prompt display.

    Returns:
        Tuple of (hostname, home_path)
        hostname read from sosreport/hostname or "$HOME" if not found
    """
    hostname = "$HOME"
    home_path = get_home_dir()
    if home_path != "":
        hostname_str = "%s/hostname" % home_path
        if os.path.exists(hostname_str):
            try:
                with open(hostname_str) as f:
                    hostname = f.read().strip()
            except (IOError, OSError):
                pass

    return hostname, home_path


def get_prompt_str():
    """
    Generate prompt string and style based on current location.

    Returns:
        Tuple of (prompt_string, prompt_style)

    Prompt format:
        Inside sos_home:  hostname/relative/path>  (cyan)
        Outside sos_home: hostname:/absolute/path> (yellow warning)
    """
    hostname, home_path = get_home_path_str()
    cur_path = os.getcwd()

    if cur_path.startswith(home_path):
        return hostname + cur_path[len(home_path):] + "> ", get_prompt_style('normal')
    else:
        return hostname + ":" + cur_path + "> ", get_prompt_style('warning')


# ====================================================================
# Session Initialization
# ====================================================================

def get_input_session():
    """
    Create prompt_toolkit input session with history.

    Attempts to create history file in:
    1. ~/.isos.history
    2. ./.isos.history (if home not writable)
    3. No history file (if all fail)

    Returns:
        PromptSession configured with:
        - File-based history (if available)
        - Vi mode editing
    """
    history_name = expanduser("~") + '/.isos.history'
    fhistory = None
    mode = 'w'

    if os.path.isfile(history_name):
        mode = 'a'

    try:
        open(history_name, mode).close()
    except (IOError, OSError):
        # Try local directory
        history_name = '.isos.history'
        if os.path.isfile(history_name):
            mode = 'a'
        else:
            mode = 'w'
        try:
            open(history_name, mode).close()
        except (IOError, OSError):
            # Give up on file history
            history_name = ''

    if history_name != '':
        fhistory = FileHistory(history_name)

    input_session = PromptSession(history=fhistory, vi_mode=True)

    return input_session


def check_startup_script():
    """
    Execute ~/.isosrc startup script if it exists.

    Each non-comment line is executed as a command.
    Commonly used to run 'xsos' automatically.

    Note:
        Silently ignores errors to prevent startup failures
    """
    try:
        fname = expanduser("~") + "/.isosrc"
        with open(fname) as f:
            for line in f:
                line = line.strip()
                if len(line) > 0 and line[0] != '#':
                    cmd, path = parse_history(line)
                    prompt_str, prompt_style = get_prompt_str()
                    print_formatted_text(HTML("<%s>%s</%s>" % \
                            ("cyan", prompt_str, "cyan")), end="")
                    print_formatted_text(HTML("<%s>%s</%s>" % \
                            ("grey", cmd, "grey")))
                    run_one_line(cmd, path)
    except (IOError, OSError):
        pass


# ====================================================================
# Main Application
# ====================================================================

def isos():
    """
    Main application entry point.

    Performs:
    1. Parse command-line options (currently unused)
    2. Load extension commands from ISOS_CMD_PATH
    3. Set sos_home from WORK_DIR environment variable
    4. Create prompt session with completion
    5. Enter main REPL loop

    REPL loop:
        - Display prompt with hostname and current path
        - Accept input with completion and history
        - Parse and execute commands
        - Handle Ctrl-C gracefully (insert ^C, don't exit)
        - Continue until 'exit' command

    Note:
        Uses global history_cmds list for command history tracking
    """
    global history_cmds

    # Parse command-line options
    op = OptionParser()
    op.add_option("-a", "--all", dest="all", default=0,
            action="store_true",
            help="Show everything")
    op.add_option("-o", "--os", dest="os", default=0,
            action="store_true",
            help="Show general OS information")

    (o, args) = op.parse_args()

    # Load extension commands
    load_commands()

    # Set sosreport home from environment
    work_dir = os.environ.get("WORK_DIR", os.getcwd())
    set_env("set sos_home %s dir" % (work_dir), env_vars, is_cmd_stopped)

    # Create input session
    input_session = get_input_session()

    # Create completers
    shell_completer = ShellCompleter()
    cmd_completer = WordCompleter((command_set | mod_command_set).keys(), WORD=True)
    my_completer = merge_completers(
            [cmd_completer, shell_completer],
            deduplicate=False)

    # Initialize history
    history_cmds = []

    # Main REPL loop
    while True:
        try:
            prompt_str, prompt_style = get_prompt_str()
            input_str = input_session.prompt(prompt_str,
                                             style=prompt_style,
                                             completer=my_completer,
                                             complete_style=CompleteStyle.READLINE_LIKE,
                                             complete_while_typing=True,
                                             key_bindings=bindings,
                                             auto_suggest=AutoSuggestFromHistory())
            cmd, path = parse_history(input_str)
            run_one_line(cmd, path)

        except CtrlCKeyboardInterrupt as e:
            if e.message == "CTRL_C":
                # Ctrl-C just cancels current line, doesn't exit
                pass

        except Exception as e:
            print("Unexpected error: %s" % str(e))


# ====================================================================
# Entry Point
# ====================================================================

if __name__ == '__main__':
    isos()
