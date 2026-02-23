"""
LVM Information Command

Displays LVM (Logical Volume Manager) information from sosreports including:
- Volume Group overview and details
- Physical Volume information
- Logical Volume details
- Filesystem usage on LVM volumes
- Device mapper status
- Thin pools and snapshots
"""

import sys
import os
from os.path import exists, join
from optparse import OptionParser
from io import StringIO
import re

import ansicolor
import screen
from .cmd_helpers import (
    ColorManager, OutputBuilder, format_bytes,
    parse_lvm_size, calculate_percentage, get_sos_file_path,
    THRESHOLD_VG_CRITICAL, THRESHOLD_VG_WARNING
)


def description():
    return "Shows LVM (Logical Volume Manager) related information"


def add_command():
    return True


def get_command_info():
    return {"lvminfo": run_lvminfo}


# Global state
is_cmd_stopped = None


def show_overview(sos_home, colors, output):
    """
    Show LVM overview with VG, PV, LV summary.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== LVM Overview ===", colors.cyan, colors.reset)
    output.add_line("")

    # Parse VG information
    vgs_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "vgs_-v_-o_vg_mda_count_vg_mda_free_vg_mda_size_vg_mda_used_count_vg_tags_systemid_lock_type_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if exists(vgs_file):
        output.add_colored_line("Volume Groups:", colors.yellow, colors.reset)
        output.add_line("%-12s %-8s %-6s %-6s %-12s %-12s" %
                       ("VG", "#PV", "#LV", "#SN", "VSize", "VFree"))
        output.add_line("-" * 70)

        try:
            with open(vgs_file, 'r') as f:
                for line in f:
                    if is_cmd_stopped():
                        break
                    if line.strip() and not line.startswith("VG") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                        parts = line.split()
                        # VG format: VG Attr Ext #PV #LV #SN VSize VFree ...
                        if len(parts) >= 8:
                            vg_name = parts[0]
                            num_pv = parts[3]
                            num_lv = parts[4]
                            num_sn = parts[5]
                            vsize = parts[6]
                            vfree = parts[7]

                            # Color code based on free space
                            vsize_bytes = parse_lvm_size(vsize)
                            vfree_bytes = parse_lvm_size(vfree)
                            free_pct = calculate_percentage(vfree_bytes, vsize_bytes)

                            if output.no_pipe and free_pct > 0:
                                # Note: VG warning is reversed - low free % is bad
                                if free_pct < THRESHOLD_VG_CRITICAL:
                                    color = colors.red
                                elif free_pct < THRESHOLD_VG_WARNING:
                                    color = colors.yellow
                                else:
                                    color = ""

                                if color:
                                    output.add_line("%-12s %-8s %-6s %-6s %-12s %s%-12s (%.1f%% free)%s" % (
                                        vg_name, num_pv, num_lv, num_sn, vsize,
                                        color, vfree, free_pct, colors.reset))
                                else:
                                    output.add_line("%-12s %-8s %-6s %-6s %-12s %-12s" % (
                                        vg_name, num_pv, num_lv, num_sn, vsize, vfree))
                            else:
                                output.add_line("%-12s %-8s %-6s %-6s %-12s %-12s" % (
                                    vg_name, num_pv, num_lv, num_sn, vsize, vfree))
        except (IOError, OSError) as e:
            output.add_line("Error reading VG information: %s" % str(e))

        output.add_line("")

    # Parse PV information
    pvs_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "pvs_-a_-v_-o_pv_mda_free_pv_mda_size_pv_mda_count_pv_mda_used_count_pe_start_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if exists(pvs_file):
        output.add_colored_line("Physical Volumes:", colors.yellow, colors.reset)
        output.add_line("%-12s %-12s %-8s %-12s %-12s" %
                       ("PV", "VG", "Fmt", "PSize", "PFree"))
        output.add_line("-" * 60)

        try:
            with open(pvs_file, 'r') as f:
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

                            output.add_line("%-12s %-12s %-8s %-12s %-12s" %
                                          (pv, vg, fmt, psize, pfree))
        except (IOError, OSError) as e:
            output.add_line("Error reading PV information: %s" % str(e))

        output.add_line("")

    # Count logical volumes
    lvs_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "lvs_-a_-o_lv_tags_devices_lv_kernel_read_ahead_lv_read_ahead_stripes_stripesize_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if exists(lvs_file):
        lv_count = 0
        try:
            with open(lvs_file, 'r') as f:
                for line in f:
                    if line.strip() and not line.startswith("LV") and not line.startswith("WARNING") and not line.startswith("Reloading"):
                        lv_count += 1
        except (IOError, OSError):
            pass

        output.add_line("%sLogical Volumes:%s %d total" %
                       (colors.yellow, colors.reset, lv_count) if output.no_pipe
                       else "Logical Volumes: %d total" % lv_count)


def show_pvs(sos_home, colors, output, verbose=False):
    """
    Show Physical Volume details.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
        verbose: Show verbose information
    """
    pvs_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "pvs_-a_-v_-o_pv_mda_free_pv_mda_size_pv_mda_count_pv_mda_used_count_pe_start_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if not exists(pvs_file):
        output.add_line("PV information not found")
        return

    output.add_colored_line("=== Physical Volume Details ===", colors.cyan, colors.reset)
    output.add_line("")

    if verbose:
        output.add_line("%-12s %-12s %-8s %-12s %-12s %-12s %-10s %-10s %-8s" % (
            "PV", "VG", "Fmt", "PSize", "PFree", "DevSize", "PMdaFree", "PMdaSize", "#PMda"))
        output.add_line("-" * 110)
    else:
        output.add_line("%-12s %-12s %-8s %-12s %-12s %-12s" % (
            "PV", "VG", "Fmt", "PSize", "PFree", "UUID"))
        output.add_line("-" * 80)

    try:
        with open(pvs_file, 'r') as f:
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
                            output.add_line("%-12s %-12s %-8s %-12s %-12s %-12s %-10s %-10s %-8s" % (
                                pv, vg, fmt, psize, pfree, devsize, pmda_free, pmda_size, pmda_count))
                        else:
                            output.add_line("%-12s %-12s %-8s %-12s %-12s %-12s" % (
                                pv, vg, fmt, psize, pfree, uuid))
    except (IOError, OSError):
        output.add_line("Error reading PV information")


def show_vgs(sos_home, colors, output, verbose=False):
    """
    Show Volume Group details.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
        verbose: Show verbose debug output
    """
    vgdisplay_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "vgdisplay_-vv_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if not exists(vgdisplay_file):
        output.add_line("VG information not found")
        return

    output.add_colored_line("=== Volume Group Details ===", colors.cyan, colors.reset)
    output.add_line("")

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    try:
        with open(vgdisplay_file, 'r') as f:
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
                output.add_line(line)
    except (IOError, OSError):
        output.add_line("Error reading VG information")


def show_lvs(sos_home, colors, output, verbose=False):
    """
    Show Logical Volume details.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
        verbose: Show verbose information
    """
    lvs_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "lvs_-a_-o_lv_tags_devices_lv_kernel_read_ahead_lv_read_ahead_stripes_stripesize_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if not exists(lvs_file):
        output.add_line("LV information not found")
        return

    output.add_colored_line("=== Logical Volume Details ===", colors.cyan, colors.reset)
    output.add_line("")

    if verbose:
        output.add_line("%-32s %-12s %-10s %-12s %-30s %-8s" % (
            "LV", "VG", "Attr", "LSize", "Devices", "#Str"))
        output.add_line("-" * 110)
    else:
        output.add_line("%-32s %-12s %-10s %-12s" % ("LV", "VG", "Attr", "LSize"))
        output.add_line("-" * 70)

    try:
        with open(lvs_file, 'r') as f:
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
                            output.add_line("%-32s %-12s %-10s %-12s %-30s %-8s" % (
                                lv, vg, attr, lsize, devices, stripes))
                        else:
                            output.add_line("%-32s %-12s %-10s %-12s" % (lv, vg, attr, lsize))
    except (IOError, OSError):
        output.add_line("Error reading LV information")


def show_filesystem_usage(sos_home, colors, output):
    """
    Show filesystem usage for LVM volumes.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    df_file = get_sos_file_path(sos_home, "sos_commands", "filesys", "df_-aliT_-x_autofs")

    if not exists(df_file):
        df_file = get_sos_file_path(sos_home, "sos_commands", "filesys", "df_-al_-x_autofs")

    if not exists(df_file):
        output.add_line("Filesystem information not found")
        return

    output.add_colored_line("=== Filesystem Usage (LVM Volumes) ===", colors.cyan, colors.reset)
    output.add_line("")
    output.add_line("%-40s %-8s %12s %12s %12s %6s %s" % (
        "Filesystem", "Type", "Size(1K)", "Used", "Available", "Use%", "Mounted on"))
    output.add_line("-" * 120)

    try:
        with open(df_file, 'r') as f:
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
                            color = colors.get_threshold_color(pct) if output.no_pipe else ""
                        except ValueError:
                            color = ""

                        if color and output.no_pipe:
                            output.add_line("%-40s %-8s %12s %12s %12s %s%6s%s %s" % (
                                filesystem, fs_type, size, used, avail, color, use_pct, colors.reset, mount))
                        else:
                            output.add_line("%-40s %-8s %12s %12s %12s %6s %s" % (
                                filesystem, fs_type, size, used, avail, use_pct, mount))
    except (IOError, OSError):
        output.add_line("Error reading filesystem information")


def show_dmsetup_info(sos_home, colors, output):
    """
    Show device mapper information.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    dmsetup_file = get_sos_file_path(sos_home, "sos_commands", "devicemapper", "dmsetup_info_-c")

    if not exists(dmsetup_file):
        output.add_line("Device mapper information not found")
        return

    output.add_colored_line("=== Device Mapper Status ===", colors.cyan, colors.reset)
    output.add_line("")

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    try:
        with open(dmsetup_file, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    break

                line = screen.get_colored_line(line.rstrip())
                output.add_line(line)
    except (IOError, OSError):
        output.add_line("Error reading device mapper information")


def show_lvm_config(sos_home, colors, output):
    """
    Show LVM configuration.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    config_file = get_sos_file_path(sos_home, "etc", "lvm", "lvm.conf")

    if not exists(config_file):
        output.add_line("LVM configuration not found")
        return

    output.add_colored_line("=== LVM Configuration (/etc/lvm/lvm.conf) ===", colors.cyan, colors.reset)
    output.add_line("")

    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    try:
        with open(config_file, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    break

                line = screen.get_colored_line(line.rstrip())
                output.add_line(line)
    except (IOError, OSError):
        output.add_line("Error reading LVM configuration")


def show_thin_pools(sos_home, colors, output):
    """
    Show thin pool and snapshot information if any.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    lvs_file = get_sos_file_path(sos_home, "sos_commands", "lvm2",
        "lvs_-a_-o_lv_tags_devices_lv_kernel_read_ahead_lv_read_ahead_stripes_stripesize_--config_global_metadata_read_only_1_--nolocking_--foreign")

    if not exists(lvs_file):
        output.add_line("LV information not found")
        return

    output.add_colored_line("=== Thin Pools and Snapshots ===", colors.cyan, colors.reset)
    output.add_line("")

    thin_found = False
    snapshot_found = False

    try:
        with open(lvs_file, 'r') as f:
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
                                output.add_line(line.rstrip())
                            elif vol_type == 's':
                                snapshot_found = True
                                output.add_line(line.rstrip())
    except (IOError, OSError):
        output.add_line("Error reading LV information")
        return

    if not thin_found and not snapshot_found:
        output.add_line("No thin pools or snapshots found.")
        output.add_line("")
        if output.no_pipe:
            output.add_line("%sNote:%s This system uses traditional thick-provisioned logical volumes." %
                          (colors.yellow, colors.reset))
        else:
            output.add_line("Note: This system uses traditional thick-provisioned logical volumes.")


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


def run_lvminfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    """
    Main entry point for lvminfo command.

    Args:
        input_str: Command arguments
        env_vars: Environment variables dict
        is_cmd_stopped_func: Function to check if command should stop
        show_help: Show help message
        no_pipe: True if output goes to terminal

    Returns:
        Result string (empty if output went to terminal)
    """
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

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help:
        return print_help_msg(op, no_pipe)

    # Initialize helpers
    sos_home = env_vars["sos_home"]
    colors = ColorManager(no_pipe)
    output = OutputBuilder(no_pipe)

    # Execute requested operation
    try:
        if o.show_all:
            show_overview(sos_home, colors, output)
            output.add_line("")
            show_pvs(sos_home, colors, output, verbose=True)
            output.add_line("")
            show_vgs(sos_home, colors, output, verbose=False)
            output.add_line("")
            show_lvs(sos_home, colors, output, verbose=True)
            output.add_line("")
            show_filesystem_usage(sos_home, colors, output)
            output.add_line("")
            show_thin_pools(sos_home, colors, output)
        elif o.show_pv:
            show_pvs(sos_home, colors, output, verbose=o.verbose)
        elif o.show_vg:
            show_vgs(sos_home, colors, output, verbose=o.verbose)
        elif o.show_lv:
            show_lvs(sos_home, colors, output, verbose=o.verbose)
        elif o.show_usage:
            show_filesystem_usage(sos_home, colors, output)
        elif o.show_dm:
            show_dmsetup_info(sos_home, colors, output)
        elif o.show_thin:
            show_thin_pools(sos_home, colors, output)
        elif o.show_config:
            show_lvm_config(sos_home, colors, output)
        else:
            # Default: show overview
            show_overview(sos_home, colors, output)

    except Exception as e:
        output.add_line("Unexpected error: %s" % str(e))

    return output.get_result()
