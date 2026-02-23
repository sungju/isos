import sys
import os
from os.path import exists, join
from optparse import OptionParser
from io import StringIO
import re

import ansicolor
import screen


def description():
    return "Shows LVM (Logical Volume Manager) related information"


def add_command():
    return True


def get_command_info():
    return { "lvminfo": run_lvminfo }


def format_bytes(bytes_val):
    """Format bytes into human readable format"""
    try:
        bytes_val = float(bytes_val)
        if bytes_val >= 1099511627776:  # 1TB
            return "%.2f TB" % (bytes_val / 1099511627776.0)
        elif bytes_val >= 1073741824:  # 1GB
            return "%.2f GB" % (bytes_val / 1073741824.0)
        elif bytes_val >= 1048576:  # 1MB
            return "%.2f MB" % (bytes_val / 1048576.0)
        elif bytes_val >= 1024:  # 1KB
            return "%.2f KB" % (bytes_val / 1024.0)
        else:
            return "%.0f B" % bytes_val
    except:
        return "N/A"


def parse_size_string(size_str):
    """Parse LVM size string like '3.47t', '99.00g', etc to bytes"""
    if not size_str:
        return 0

    size_str = size_str.strip().lower().replace('<', '')

    multipliers = {
        'b': 1,
        'k': 1024,
        'm': 1048576,
        'g': 1073741824,
        't': 1099511627776,
        'p': 1125899906842624
    }

    try:
        # Extract number and unit
        match = re.match(r'([\d.]+)\s*([bkmgtp])?', size_str)
        if match:
            num = float(match.group(1))
            unit = match.group(2) or 'b'
            return int(num * multipliers.get(unit, 1))
    except:
        pass

    return 0


def show_overview(sos_home, no_pipe):
    """Show LVM overview with VG, PV, LV summary"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_GREEN = ansicolor.get_color(ansicolor.GREEN)
        COLOR_RED = ansicolor.get_color(ansicolor.RED)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_GREEN = COLOR_RED = COLOR_RESET = ""

    result_str = COLOR_CYAN + "=== LVM Overview ===" + COLOR_RESET + "\n\n"

    # Parse VG information
    vgs_file = sos_home + "/sos_commands/lvm2/vgs_-v_-o_vg_mda_count_vg_mda_free_vg_mda_size_vg_mda_used_count_vg_tags_systemid_lock_type_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if exists(vgs_file):
        result_str += COLOR_YELLOW + "Volume Groups:" + COLOR_RESET + "\n"
        result_str += "%-12s %-8s %-6s %-6s %-12s %-12s\n" % ("VG", "#PV", "#LV", "#SN", "VSize", "VFree")
        result_str += "-" * 70 + "\n"

        try:
            with open(vgs_file) as f:
                for line in f:
                    if is_cmd_stopped():
                        break
                    if line.strip() and not line.startswith("VG") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                        parts = line.split()
                        # VG format: VG Attr Ext #PV #LV #SN VSize VFree ...
                        if len(parts) >= 8:
                            vg_name = parts[0]
                            # parts[1] = Attr, parts[2] = Ext (skip these)
                            num_pv = parts[3]
                            num_lv = parts[4]
                            num_sn = parts[5]
                            vsize = parts[6]
                            vfree = parts[7]

                            # Color code based on free space
                            vsize_bytes = parse_size_string(vsize)
                            vfree_bytes = parse_size_string(vfree)

                            if vsize_bytes > 0:
                                free_pct = (vfree_bytes * 100.0) / vsize_bytes
                                if free_pct < 10 and no_pipe:
                                    color = COLOR_RED
                                elif free_pct < 20 and no_pipe:
                                    color = COLOR_YELLOW
                                else:
                                    color = ""
                            else:
                                color = ""
                                free_pct = 0

                            if color:
                                result_str += "%-12s %-8s %-6s %-6s %-12s %s%-12s (%.1f%% free)%s\n" % (
                                    vg_name, num_pv, num_lv, num_sn, vsize, color, vfree, free_pct, COLOR_RESET)
                            else:
                                result_str += "%-12s %-8s %-6s %-6s %-12s %-12s\n" % (
                                    vg_name, num_pv, num_lv, num_sn, vsize, vfree)
        except Exception as e:
            result_str += "Error reading VG information: %s\n" % str(e)

        result_str += "\n"

    # Parse PV information
    pvs_file = sos_home + "/sos_commands/lvm2/pvs_-a_-v_-o_pv_mda_free_pv_mda_size_pv_mda_count_pv_mda_used_count_pe_start_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if exists(pvs_file):
        result_str += COLOR_YELLOW + "Physical Volumes:" + COLOR_RESET + "\n"
        result_str += "%-12s %-12s %-8s %-12s %-12s\n" % ("PV", "VG", "Fmt", "PSize", "PFree")
        result_str += "-" * 60 + "\n"

        try:
            with open(pvs_file) as f:
                for line in f:
                    if is_cmd_stopped():
                        break
                    if line.strip() and not line.startswith("PV") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                        parts = line.split()
                        if len(parts) >= 6:
                            pv = parts[0]
                            vg = parts[1] if parts[1] else "N/A"
                            fmt = parts[2] if parts[2] else "---"
                            psize = parts[4]
                            pfree = parts[5]

                            result_str += "%-12s %-12s %-8s %-12s %-12s\n" % (pv, vg, fmt, psize, pfree)
        except Exception as e:
            result_str += "Error reading PV information: %s\n" % str(e)

        result_str += "\n"

    # Count logical volumes
    lvs_file = sos_home + "/sos_commands/lvm2/lvs_-a_-o_lv_tags_devices_lv_kernel_read_ahead_lv_read_ahead_stripes_stripesize_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if exists(lvs_file):
        lv_count = 0
        try:
            with open(lvs_file) as f:
                for line in f:
                    if line.strip() and not line.startswith("LV") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                        lv_count += 1
        except:
            pass

        result_str += COLOR_YELLOW + "Logical Volumes: " + COLOR_RESET + "%d total\n" % lv_count

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_pvs(sos_home, no_pipe, verbose=False):
    """Show Physical Volume details"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    pvs_file = sos_home + "/sos_commands/lvm2/pvs_-a_-v_-o_pv_mda_free_pv_mda_size_pv_mda_count_pv_mda_used_count_pe_start_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if not exists(pvs_file):
        return "PV information not found\n"

    result_str = COLOR_CYAN + "=== Physical Volume Details ===" + COLOR_RESET + "\n\n"

    if verbose:
        result_str += "%-12s %-12s %-8s %-12s %-12s %-12s %-10s %-10s %-8s\n" % (
            "PV", "VG", "Fmt", "PSize", "PFree", "DevSize", "PMdaFree", "PMdaSize", "#PMda")
        result_str += "-" * 110 + "\n"
    else:
        result_str += "%-12s %-12s %-8s %-12s %-12s %-12s\n" % (
            "PV", "VG", "Fmt", "PSize", "PFree", "UUID")
        result_str += "-" * 80 + "\n"

    try:
        with open(pvs_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break
                if line.strip() and not line.startswith("PV") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                    parts = line.split()
                    if len(parts) >= 6:
                        pv = parts[0]
                        vg = parts[1] if parts[1] else "N/A"
                        fmt = parts[2] if parts[2] else "---"
                        psize = parts[4]
                        pfree = parts[5]
                        devsize = parts[6] if len(parts) > 6 else "N/A"
                        uuid = parts[7] if len(parts) > 7 else "N/A"

                        if verbose and len(parts) >= 11:
                            pmda_free = parts[8]
                            pmda_size = parts[9]
                            pmda_count = parts[10]
                            result_str += "%-12s %-12s %-8s %-12s %-12s %-12s %-10s %-10s %-8s\n" % (
                                pv, vg, fmt, psize, pfree, devsize, pmda_free, pmda_size, pmda_count)
                        else:
                            result_str += "%-12s %-12s %-8s %-12s %-12s %-12s\n" % (
                                pv, vg, fmt, psize, pfree, uuid)
    except:
        return "Error reading PV information\n"

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_vgs(sos_home, no_pipe, verbose=False):
    """Show Volume Group details"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    vgdisplay_file = sos_home + "/sos_commands/lvm2/vgdisplay_-vv_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if not exists(vgdisplay_file):
        return "VG information not found\n"

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str = COLOR_CYAN + "=== Volume Group Details ===" + COLOR_RESET + "\n\n"

    if no_pipe:
        print(result_str)
        result_str = ""

    try:
        with open(vgdisplay_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break

                # Skip verbose debug lines unless verbose mode
                if not verbose and ("Reloading config" in line or "not found in config" in line or
                                   "WARNING:" in line or "/dev/sd" in line or "Using cached" in line or
                                   "Loading config" in line or "Obtaining the complete" in line or
                                   "Processing" in line or "Adding" in line or "Running command" in line):
                    continue

                line = screen.get_colored_line(line.rstrip())
                if no_pipe:
                    print(line)
                else:
                    result_str += line + "\n"
    except:
        return "Error reading VG information\n"

    if no_pipe:
        return ""
    else:
        return result_str


def show_lvs(sos_home, no_pipe, verbose=False):
    """Show Logical Volume details"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    lvs_file = sos_home + "/sos_commands/lvm2/lvs_-a_-o_lv_tags_devices_lv_kernel_read_ahead_lv_read_ahead_stripes_stripesize_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if not exists(lvs_file):
        return "LV information not found\n"

    result_str = COLOR_CYAN + "=== Logical Volume Details ===" + COLOR_RESET + "\n\n"

    if verbose:
        result_str += "%-32s %-12s %-10s %-12s %-30s %-8s\n" % (
            "LV", "VG", "Attr", "LSize", "Devices", "#Str")
        result_str += "-" * 110 + "\n"
    else:
        result_str += "%-32s %-12s %-10s %-12s\n" % ("LV", "VG", "Attr", "LSize")
        result_str += "-" * 70 + "\n"

    try:
        with open(lvs_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break
                if line.strip() and not line.startswith("LV") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                    parts = line.split()
                    if len(parts) >= 4:
                        lv = parts[0]
                        vg = parts[1]
                        attr = parts[2]
                        lsize = parts[3]

                        if verbose and len(parts) >= 8:
                            devices = parts[6]
                            stripes = parts[8]
                            result_str += "%-32s %-12s %-10s %-12s %-30s %-8s\n" % (
                                lv, vg, attr, lsize, devices, stripes)
                        else:
                            result_str += "%-32s %-12s %-10s %-12s\n" % (lv, vg, attr, lsize)
    except:
        return "Error reading LV information\n"

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_filesystem_usage(sos_home, no_pipe):
    """Show filesystem usage for LVM volumes"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_RED = ansicolor.get_color(ansicolor.RED)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_RED = COLOR_RESET = ""

    df_file = sos_home + "/sos_commands/filesys/df_-aliT_-x_autofs"

    if not exists(df_file):
        df_file = sos_home + "/sos_commands/filesys/df_-al_-x_autofs"

    if not exists(df_file):
        return "Filesystem information not found\n"

    result_str = COLOR_CYAN + "=== Filesystem Usage (LVM Volumes) ===" + COLOR_RESET + "\n\n"
    result_str += "%-40s %-8s %12s %12s %12s %6s %s\n" % (
        "Filesystem", "Type", "Size(1K)", "Used", "Available", "Use%", "Mounted on")
    result_str += "-" * 120 + "\n"

    try:
        with open(df_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break

                # Only show mapper devices (LVM)
                if "/dev/mapper/" in line:
                    parts = line.split()
                    if len(parts) >= 7:
                        filesystem = parts[0]
                        # Check if Type column exists
                        if parts[1] in ['xfs', 'ext4', 'ext3', 'ext2', 'btrfs']:
                            fs_type = parts[1]
                            size = parts[2]
                            used = parts[3]
                            avail = parts[4]
                            use_pct = parts[5]
                            mount = ' '.join(parts[6:])
                        else:
                            fs_type = "N/A"
                            size = parts[1]
                            used = parts[2]
                            avail = parts[3]
                            use_pct = parts[4]
                            mount = ' '.join(parts[5:])

                        # Color code based on usage
                        try:
                            pct = int(use_pct.replace('%', ''))
                            if pct >= 90 and no_pipe:
                                color = COLOR_RED
                            elif pct >= 80 and no_pipe:
                                color = COLOR_YELLOW
                            else:
                                color = ""
                        except:
                            color = ""
                            pct = 0

                        if color:
                            result_str += "%-40s %-8s %12s %12s %12s %s%6s%s %s\n" % (
                                filesystem, fs_type, size, used, avail, color, use_pct, COLOR_RESET, mount)
                        else:
                            result_str += "%-40s %-8s %12s %12s %12s %6s %s\n" % (
                                filesystem, fs_type, size, used, avail, use_pct, mount)
    except:
        return "Error reading filesystem information\n"

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def show_dmsetup_info(sos_home, no_pipe):
    """Show device mapper information"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    dmsetup_file = sos_home + "/sos_commands/devicemapper/dmsetup_info_-c"

    if not exists(dmsetup_file):
        return "Device mapper information not found\n"

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str = COLOR_CYAN + "=== Device Mapper Status ===" + COLOR_RESET + "\n\n"

    if no_pipe:
        print(result_str)
        result_str = ""

    try:
        with open(dmsetup_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break

                line = screen.get_colored_line(line.rstrip())
                if no_pipe:
                    print(line)
                else:
                    result_str += line + "\n"
    except:
        return "Error reading device mapper information\n"

    if no_pipe:
        return ""
    else:
        return result_str


def show_lvm_config(sos_home, no_pipe):
    """Show LVM configuration"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_RESET = ""

    config_file = sos_home + "/etc/lvm/lvm.conf"

    if not exists(config_file):
        return "LVM configuration not found\n"

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    result_str = COLOR_CYAN + "=== LVM Configuration (/etc/lvm/lvm.conf) ===" + COLOR_RESET + "\n\n"

    if no_pipe:
        print(result_str)
        result_str = ""

    try:
        with open(config_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break

                line = screen.get_colored_line(line.rstrip())
                if no_pipe:
                    print(line)
                else:
                    result_str += line + "\n"
    except:
        return "Error reading LVM configuration\n"

    if no_pipe:
        return ""
    else:
        return result_str


def show_thin_pools(sos_home, no_pipe):
    """Show thin pool and snapshot information if any"""
    if no_pipe:
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_CYAN = COLOR_YELLOW = COLOR_RESET = ""

    lvs_file = sos_home + "/sos_commands/lvm2/lvs_-a_-o_lv_tags_devices_lv_kernel_read_ahead_lv_read_ahead_stripes_stripesize_--config_global_metadata_read_only_1_--nolocking_--foreign"

    if not exists(lvs_file):
        return "LV information not found\n"

    result_str = COLOR_CYAN + "=== Thin Pools and Snapshots ===" + COLOR_RESET + "\n\n"

    thin_found = False
    snapshot_found = False

    try:
        with open(lvs_file) as f:
            for line in f:
                if is_cmd_stopped():
                    break
                # Look for thin pool or snapshot attributes
                # LV attributes: position 1 = volume type (V=thin, t=thin pool, s=snapshot)
                if line.strip() and not line.startswith("LV") and not line.startswith("WARNING"):
                    parts = line.split()
                    if len(parts) >= 3:
                        attr = parts[2]
                        if len(attr) >= 1:
                            vol_type = attr[0]
                            if vol_type in ['t', 'V']:
                                thin_found = True
                                result_str += line
                            elif vol_type == 's':
                                snapshot_found = True
                                result_str += line
    except:
        return "Error reading LV information\n"

    if not thin_found and not snapshot_found:
        result_str += "No thin pools or snapshots found.\n"
        result_str += "\n" + COLOR_YELLOW + "Note:" + COLOR_RESET + " This system uses traditional thick-provisioned logical volumes.\n"

    if no_pipe:
        print(result_str)
        return ""
    else:
        return result_str


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Shows LVM (Logical Volume Manager) information from the sosreport.

Examples:
  lvminfo           Show LVM overview (default)
  lvminfo -p        Show Physical Volume details
  lvminfo -v        Show Volume Group details
  lvminfo -l        Show Logical Volume details
  lvminfo -u        Show filesystem usage for LVM volumes
  lvminfo -d        Show device mapper status
  lvminfo -t        Show thin pools and snapshots
  lvminfo -c        Show LVM configuration
  lvminfo -a        Show all LVM information

Verbose Options:
  lvminfo -p -V     Show PV details with metadata info
  lvminfo -v -V     Show full VG display output
  lvminfo -l -V     Show LV details with devices and stripes

LVM Components:
  - PV (Physical Volume): Physical disk or partition
  - VG (Volume Group): Pool of physical volumes
  - LV (Logical Volume): Virtual partition from VG
  - PE (Physical Extent): Smallest allocatable unit
    '''

    if no_pipe == False:
        output = StringIO.StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()

        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""


is_cmd_stopped = None

def run_lvminfo(input_str, env_vars, is_cmd_stopped_func,
        show_help=False, no_pipe=True):
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    usage = "Usage: lvminfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-o', '--overview', dest='show_overview', action='store_true',
                  help='show LVM overview (default)')
    op.add_option('-p', '--pv', dest='show_pv', action='store_true',
                  help='show Physical Volume details')
    op.add_option('-v', '--vg', dest='show_vg', action='store_true',
                  help='show Volume Group details')
    op.add_option('-l', '--lv', dest='show_lv', action='store_true',
                  help='show Logical Volume details')
    op.add_option('-u', '--usage', dest='show_usage', action='store_true',
                  help='show filesystem usage for LVM volumes')
    op.add_option('-d', '--dm', dest='show_dm', action='store_true',
                  help='show device mapper status')
    op.add_option('-t', '--thin', dest='show_thin', action='store_true',
                  help='show thin pools and snapshots')
    op.add_option('-c', '--config', dest='show_config', action='store_true',
                  help='show LVM configuration')
    op.add_option('-V', '--verbose', dest='verbose', action='store_true',
                  help='verbose output (use with -p, -v, or -l)')
    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all LVM information')

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        return print_help_msg(op, no_pipe)

    sos_home = env_vars["sos_home"]
    result_str = ""

    # Handle specific options
    if o.show_all:
        result_str += show_overview(sos_home, no_pipe)
        if not no_pipe:
            result_str += "\n"
        result_str += show_pvs(sos_home, no_pipe, verbose=True)
        if not no_pipe:
            result_str += "\n"
        result_str += show_vgs(sos_home, no_pipe, verbose=False)
        if not no_pipe:
            result_str += "\n"
        result_str += show_lvs(sos_home, no_pipe, verbose=True)
        if not no_pipe:
            result_str += "\n"
        result_str += show_filesystem_usage(sos_home, no_pipe)
        if not no_pipe:
            result_str += "\n"
        result_str += show_thin_pools(sos_home, no_pipe)
    elif o.show_pv:
        result_str = show_pvs(sos_home, no_pipe, verbose=o.verbose)
    elif o.show_vg:
        result_str = show_vgs(sos_home, no_pipe, verbose=o.verbose)
    elif o.show_lv:
        result_str = show_lvs(sos_home, no_pipe, verbose=o.verbose)
    elif o.show_usage:
        result_str = show_filesystem_usage(sos_home, no_pipe)
    elif o.show_dm:
        result_str = show_dmsetup_info(sos_home, no_pipe)
    elif o.show_thin:
        result_str = show_thin_pools(sos_home, no_pipe)
    elif o.show_config:
        result_str = show_lvm_config(sos_home, no_pipe)
    else:
        # Default: show overview
        result_str = show_overview(sos_home, no_pipe)

    return result_str
