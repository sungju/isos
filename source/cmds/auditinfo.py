import sys
import time

def description():
    return "Checking audit related information"


def add_command():
    return True


def get_command_info():
    return "audit", run_auditinfo


def read_audit_log(audit_path):
    result_str = ""
    with open(audit_path) as f:
        lines = f.readlines()
        for line in lines:
            words = line.split()
            epoch = words[1][len("msg=audit("):-2]
            localtime = time.ctime(float(epoch.split(':')[0]))
            result_str = result_str + line.replace(epoch, localtime)

    return result_str


def run_auditinfo(input_str, env_vars, show_help=False):
    if show_help == True:
        return description()

    result_str = read_audit_log(env_vars["sos_home"] + "/var/log/audit/audit.log")
    return result_str
