import sys
import os
import shutil
import tempfile
from optparse import OptionParser

from isos import run_shell_command


def description():
    return "Analyse data with AI (claude/gemini)"


def add_command():
    return True


cmd_name = "ai"
def get_command_info():
    return { cmd_name : run_ai }


def detect_engine():
    for engine in ["claude", "gemini"]:
        if shutil.which(engine):
            return engine
    return ""


def ai_send_local(prompt_data, engine, model=""):
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt',
                                         mode='w') as fp:
            fp.write(prompt_data)
            temp_path = fp.name
    except Exception as e:
        print("Error writing temp file:", e)
        return ""

    model_opt = ""
    if model != "":
        model_opt = " -m " + model

    if engine == "claude":
        cmd = "cat %s | claude -p %s" % (temp_path, model_opt)
    else:
        cmd = "cat %s | gemini --skip-trust -p 'Analyze the following' %s" % (temp_path, model_opt)

    result_str = run_shell_command(cmd)

    try:
        os.remove(temp_path)
    except:
        pass

    return result_str


def render_result(result_str, no_pipe):
    if not no_pipe:
        return result_str

    try:
        from rich.console import Console
        from rich.markdown import Markdown
        code_theme = os.environ.get('CODE_THEME', 'tango')
        console = Console(color_system="truecolor")
        console.print(Markdown(result_str, code_theme=code_theme))
    except:
        print(result_str)
        print("\nNotes) 'pip install rich' can enhance the output", end='')

    return ""


is_cmd_stopped = None

def run_ai(input_str, env_vars, is_cmd_stopped_func,
           show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: ai [options] [question ...]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    op.add_option("-c", "--cmd",
                  action="store",
                  type="string",
                  default="",
                  dest="cmd_str",
                  help="Run a command and include its output as context")

    op.add_option("-e", "--engine",
                  action="store",
                  type="string",
                  default="",
                  dest="ai_engine",
                  help="Choose AI engine (claude or gemini)")

    op.add_option("-i", "--input",
                  action="store",
                  type="string",
                  default="",
                  dest="input_file",
                  help="Use file content as context")

    op.add_option("-m", "--model",
                  action="store",
                  type="string",
                  default="",
                  dest="ai_model",
                  help="Choose AI model to use")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o is None:
        return ""

    if show_help or o.help:
        op.print_help()
        return ""

    engine = ""
    if o.ai_engine in ("claude", "gemini"):
        if shutil.which(o.ai_engine):
            engine = o.ai_engine
        else:
            print("'%s' is not installed" % o.ai_engine)
            return ""
    else:
        engine = detect_engine()

    if engine == "":
        print("No local AI CLI (claude, gemini) is available.\n"
              "Install claude or gemini CLI to use this command.")
        return ""

    sos_home = env_vars.get("SOS_HOME", ".")

    result_str = ""
    if o.cmd_str != "":
        result_str = run_shell_command(o.cmd_str)
        if result_str.strip() == "":
            print("Command '%s' produced no output" % o.cmd_str)
            return ""
        result_str = "\n\n~~~\n$ " + o.cmd_str + "\n" + result_str + "\n~~~"
    elif o.input_file != "":
        file_path = o.input_file
        if not os.path.isabs(file_path):
            file_path = os.path.join(sos_home, file_path)
        try:
            with open(file_path) as fp:
                result_str = fp.read()
        except Exception as e:
            print(e)
            return ""

    if len(args) > 1:
        prompt = " ".join(args[1:]) + "\n" + result_str
    elif result_str != "":
        prompt = "Analyse the following data from a Linux sosreport" + result_str
    else:
        print("ERROR> ai needs a question or data to analyse.\n"
              "  e.g) ai what is the system status?\n"
              "       ai -c \"cat proc/meminfo\" explain memory usage\n"
              "       ai -i var/log/messages check for errors")
        return ""

    response = ai_send_local(prompt, engine, o.ai_model)
    if response:
        return render_result(response, no_pipe)

    return ""
