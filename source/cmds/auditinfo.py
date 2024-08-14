import sys

def description():
    return "Checking audit related information"


def add_command():
    return True


def get_command_info():
    return "audit", run_auditinfo


def run_auditinfo(input_str, env_vars, show_help=False):
    if show_help == True:
        return description()

    return "Checking data at %s" % env_vars["sos_home"]
