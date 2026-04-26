"""
 Written by Daniel Sungju Kwon
"""
import sys
import ntpath
import operator
import math
import re

import rules_helper as rh


def is_major():
    return True


def description():
    return "RHEL 9.6/9.7: NULL pointer dereference in cifs_debug_dirs_proc_show() during sosreport collection"


def add_rule(sysinfo):
    if sysinfo is None or "RELEASE" not in sysinfo:
        return True

    release = sysinfo["RELEASE"]
    if ("el9") in release:
        return True

    return False


def run_rule(basic_data):
    try:
        if basic_data == None:
            log_string = rh.get_data(basic_data, "log")
        else:
            log_string = basic_data["log_str"]

        # Primary detection: cifs_debug_dirs_proc_show in panic
        pos_cifs_debug = log_string.find("cifs_debug_dirs_proc_show")
        # Support both x86_64 and aarch64 NULL pointer dereference messages
        pos_null_deref = log_string.find("BUG: kernel NULL pointer dereference")
        if pos_null_deref < 0:
            pos_null_deref = log_string.find("Unable to handle kernel NULL pointer dereference")

        if pos_cifs_debug < 0 or pos_null_deref < 0:
            return None

        # Additional verification: look for typical panic signatures
        has_raw_spin_lock = "raw_spin_lock" in log_string or "_raw_spin_lock" in log_string
        has_cr2_null = "CR2: 0000000000000000" in log_string
        has_sos_process = "Comm: sos" in log_string

        # Find the start of the panic message (look for timestamp or '[')
        pos_panic_start = log_string.rfind('[', 0, pos_null_deref)
        if pos_panic_start < 0:
            pos_panic_start = log_string.rfind('\n', 0, pos_null_deref)
            if pos_panic_start < 0:
                pos_panic_start = 0

        # Find end of panic trace
        end_trace_pos = log_string.find('---[ end trace', pos_panic_start)
        if end_trace_pos >= 0:
            end_pos = log_string.find('\n', end_trace_pos)
            if end_pos >= 0:
                end_pos += 1
            else:
                end_pos = len(log_string)
        else:
            # Look for next kernel message
            end_pos = log_string.find('\n[', pos_panic_start + 1)
            if end_pos >= 0:
                end_pos += 1
            else:
                end_pos = len(log_string)

        # Extract relevant panic excerpt
        panic_msg = log_string[pos_panic_start:end_pos]

        # Check kernel version to determine if it's vulnerable
        env_vars = basic_data.get("env_vars", {})
        sos_home = env_vars.get("sos_home", "")

        kernel_version = ""
        vulnerable = False
        try:
            with open(sos_home + "/proc/version") as f:
                kernel_version = f.readline().strip()
                # Vulnerable versions:
                # RHEL 9.6: before 5.14.0-570.79.1.el9_6
                # RHEL 9.7: before 5.14.0-611.24.1.el9_7
                if "5.14.0-570" in kernel_version and "el9_6" in kernel_version:
                    # Parse minor version: 5.14.0-570.X.Y
                    match = re.search(r'5\.14\.0-570\.(\d+)', kernel_version)
                    if match:
                        minor = int(match.group(1))
                        if minor < 79:
                            vulnerable = True
                elif "5.14.0-611" in kernel_version and "el9_7" in kernel_version:
                    # Parse minor version: 5.14.0-611.X.Y
                    match = re.search(r'5\.14\.0-611\.(\d+)', kernel_version)
                    if match:
                        minor = int(match.group(1))
                        if minor < 24:
                            vulnerable = True
        except Exception:
            pass

        result_dict = {}
        result_dict["TITLE"] = "CIFS NULL pointer dereference bug detected by %s" % \
                                ntpath.basename(__file__)

        msg_parts = ["Kernel panic detected in cifs_debug_dirs_proc_show():\n"]
        msg_parts.append(panic_msg)
        msg_parts.append("\n\nDetected signatures:")
        if has_raw_spin_lock:
            msg_parts.append("\n  - _raw_spin_lock in call trace")
        if has_cr2_null:
            msg_parts.append("\n  - CR2: 0000000000000000 (NULL pointer)")
        if has_sos_process:
            msg_parts.append("\n  - Triggered by sos process")

        if kernel_version:
            msg_parts.append("\n\nKernel version: %s" % kernel_version)
            if vulnerable:
                msg_parts.append(" (VULNERABLE)")

        result_dict["MSG"] = "".join(msg_parts)
        result_dict["KCS_TITLE"] = "NULL pointer dereference in cifs_debug_dirs_proc_show() during sosreport collection"
        result_dict["KCS_URL"] = "https://access.redhat.com/solutions/7135230"
        result_dict["RESOLUTION"] = "RHEL 9.7: Upgrade to kernel-5.14.0-611.24.1.el9_7 or later (RHSA-2026:1764). " \
                                   "RHEL 9.6: Upgrade to kernel-5.14.0-570.79.1.el9_6 or later (RHSA-2026:1765). " \
                                   "Workaround: Avoid running 'sos report' or reading /proc/fs/cifs/open_dirs when CIFS mounts are active."
        result_dict["KERNELS"] = {
            "kernel-5.14.0-570.79.1.el9_6",
            "kernel-5.14.0-611.24.1.el9_7"
        }

        return [result_dict]
    except Exception as e:
        print(e)
        return None



def cifs_debug_dirs_null_deref():
    import pprint
    pp = pprint.PrettyPrinter(indent=0, width=180)
    pp.pprint(run_rule(None))


if ( __name__ == '__main__'):
    cifs_debug_dirs_null_deref()
