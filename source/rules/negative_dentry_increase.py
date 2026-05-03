"""
 Written by Daniel Sungju Kwon
"""
import sys
import ntpath
import operator
import math

import rules_helper as rh


def get_dentry_memory_info(sos_home, nr_negative):
    """
    Parse /proc/slabinfo to get the dentry slab objsize and calculate
    the estimated memory consumed by negative dentries.

    Returns (memory_bytes, objsize) on success, or (None, None) on any error.
    """
    try:
        with open(sos_home + '/proc/slabinfo') as f:
            result_lines = f.readlines()

        if len(result_lines) < 3:
            return None, None

        # Header line: "# name  <active_objs> <num_objs> <objsize> ..."
        header = result_lines[1].replace('# name', 'name').split()
        idx_objsize = -1
        for i, col in enumerate(header):
            if '<objsize>' in col:
                idx_objsize = i
                break

        if idx_objsize == -1:
            return None, None

        # Find the 'dentry' entry
        for line in result_lines[2:]:
            parts = line.split()
            if len(parts) > idx_objsize and parts[0] == 'dentry':
                objsize = int(parts[idx_objsize])
                if objsize <= 0:
                    return None, None
                memory_bytes = nr_negative * objsize
                return memory_bytes, objsize

        # dentry entry not found
        return None, None

    except Exception:
        return None, None


def is_major():
    return True


def description():
    return "Checking negative dentry increase bug"


def add_rule(sysinfo):
    if sysinfo is None or "RELEASE" not in sysinfo:
        return True

    release = sysinfo["RELEASE"]
    if ("el7" in release or "el8" in release or "el9" in release):
        return True

    return False


# Threshold: if negative dentries exceed this percentage of total dentries
# it's considered abnormal
NEGATIVE_DENTRY_PERCENT_THRESHOLD = 50


def run_rule(basic_data):
    env_vars = basic_data["env_vars"]
    sos_home = env_vars["sos_home"]
    try:
        # Read /proc/sys/fs/dentry-state
        # Format: nr_dentry nr_unused age_limit want_pages dummy nr_negative
        with open(sos_home + "/proc/sys/fs/dentry-state") as f:
            line = f.readline().strip()
            values = line.split()

            if len(values) < 6:
                return None

            nr_dentry = int(values[0])
            nr_unused = int(values[1])
            nr_negative = int(values[4])

            if nr_dentry == 0:
                return None

            # Calculate percentage of negative dentries
            negative_percent = (nr_negative / nr_dentry) * 100

            if negative_percent < NEGATIVE_DENTRY_PERCENT_THRESHOLD:
                return None

            # Estimate memory consumed by negative dentries via /proc/slabinfo
            memory_bytes, objsize = get_dentry_memory_info(sos_home, nr_negative)
            if memory_bytes is not None:
                memory_info = "\n  Estimated memory consumed by negative dentries: %s" \
                              " (%d bytes/dentry × %d dentries)" % \
                              (rh.get_size_str(memory_bytes), objsize, nr_negative)
            else:
                memory_info = ""

            result_dict = {}
            result_dict["TITLE"] = "Negative dentry increase bug detected by %s" % \
                                    ntpath.basename(__file__)
            result_dict["MSG"] = "Negative dentry leak detected (%.1f%% of total dentries)%s\n\n" \
                    "/proc/sys/fs/dentry-state:\n" \
                    "  nr_dentry   : %d\n" \
                    "  nr_unused   : %d\n" \
                    "  age_limit   : %d\n" \
                    "  want_pages  : %d\n" \
                    "  nr_negative : %d (%.1f%% of nr_dentry)\n" \
                    "  dummy       : %d\n\n" \
                    "This indicates a negative dentry leak issue." % \
                    (negative_percent, memory_info,
                     int(values[0]), int(values[1]), int(values[2]),
                     int(values[3]), nr_negative, negative_percent, int(values[5]))
            result_dict["KCS_TITLE"] = "Negative dentry increase causing memory pressure"
            result_dict["KCS_URL"] = "https://access.redhat.com/solutions/7086240"
            result_dict["RESOLUTION"] = "Please upgrade kernel as specified in the KCS"
            result_dict["KERNELS"] = {
                    "kernel-5.14.0-503.11.1.el9_5",
                    "kernel-5.14.0-427.40.1.el9_4",
                    "kernel-5.14.0-284.90.1.el9_2",
                    "kernel-4.18.0-553.22.1.el8_10",
                    "kernel-4.18.0-477.75.1.el8_8" }

            return [result_dict]
    except Exception as e:
        print(e)
        return None



def negative_dentry_increase():
    import pprint
    pp = pprint.PrettyPrinter(indent=0, width=180)
    pp.pprint(run_rule(None))


if ( __name__ == '__main__'):
    negative_dentry_increase()
