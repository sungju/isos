"""
Hardware Information Command

Displays comprehensive hardware information from sosreports including:
- System information (manufacturer, model, BIOS)
- CPU details (cores, sockets, flags, topology)
- Memory configuration (total, DIMMs, NUMA)
- Disk and storage devices
- PCI devices (network cards, storage controllers)
- Overall hardware summary with component relationships

This command provides an easy way to understand the hardware configuration
and see relationships between components (CPU-memory-disk).
"""

import sys
import os
from os.path import exists, join
from optparse import OptionParser
from io import StringIO
import re
from collections import defaultdict

import ansicolor
import screen
from cmd_helpers import (
    ColorManager, OutputBuilder, format_bytes,
    get_sos_file_path
)


def description():
    return "Shows comprehensive hardware information"


def add_command():
    return True


def get_command_info():
    return {"hwinfo": run_hwinfo}


# Constants
SIZE_1GB = 1073741824
SIZE_1MB = 1048576
SIZE_1KB = 1024


def parse_dmidecode(sos_home):
    """
    Parse dmidecode output for system hardware information.

    Args:
        sos_home: Root directory of sosreport

    Returns:
        Dict containing:
        - 'system': System manufacturer, product, serial
        - 'bios': BIOS vendor, version, date
        - 'chassis': Chassis type, manufacturer
        - 'memory_devices': List of memory DIMMs
        - 'processor': Processor information
    """
    dmi_path = get_sos_file_path(sos_home, "sos_commands", "hardware", "dmidecode")
    if not exists(dmi_path):
        dmi_path = get_sos_file_path(sos_home, "dmidecode")

    if not exists(dmi_path):
        return {}

    data = {
        'system': {},
        'bios': {},
        'chassis': {},
        'memory_devices': [],
        'processor': {}
    }

    try:
        with open(dmi_path, 'r') as f:
            current_section = None
            current_device = {}

            for line in f:
                line = line.rstrip()

                # Section headers
                if line.startswith('Handle'):
                    # Save previous device
                    if current_section == 'Memory Device' and current_device:
                        data['memory_devices'].append(current_device)
                    current_device = {}

                elif 'System Information' in line:
                    current_section = 'System Information'
                elif 'BIOS Information' in line:
                    current_section = 'BIOS Information'
                elif 'Chassis Information' in line:
                    current_section = 'Chassis Information'
                elif 'Memory Device' in line and 'Memory Device Mapped Address' not in line:
                    current_section = 'Memory Device'
                elif 'Processor Information' in line:
                    current_section = 'Processor Information'

                # Parse fields
                elif line.startswith('\t') and ':' in line:
                    key, value = line.strip().split(':', 1)
                    value = value.strip()

                    if current_section == 'System Information':
                        if key == 'Manufacturer':
                            data['system']['manufacturer'] = value
                        elif key == 'Product Name':
                            data['system']['product'] = value
                        elif key == 'Serial Number':
                            data['system']['serial'] = value
                        elif key == 'UUID':
                            data['system']['uuid'] = value

                    elif current_section == 'BIOS Information':
                        if key == 'Vendor':
                            data['bios']['vendor'] = value
                        elif key == 'Version':
                            data['bios']['version'] = value
                        elif key == 'Release Date':
                            data['bios']['date'] = value

                    elif current_section == 'Chassis Information':
                        if key == 'Manufacturer':
                            data['chassis']['manufacturer'] = value
                        elif key == 'Type':
                            data['chassis']['type'] = value

                    elif current_section == 'Memory Device':
                        if key == 'Size':
                            current_device['size'] = value
                        elif key == 'Type':
                            current_device['type'] = value
                        elif key == 'Speed':
                            current_device['speed'] = value
                        elif key == 'Locator':
                            current_device['locator'] = value
                        elif key == 'Manufacturer':
                            current_device['manufacturer'] = value

                    elif current_section == 'Processor Information':
                        if not data['processor']:  # Only get first processor
                            if key == 'Version':
                                data['processor']['version'] = value
                            elif key == 'Max Speed':
                                data['processor']['max_speed'] = value
                            elif key == 'Current Speed':
                                data['processor']['current_speed'] = value
                            elif key == 'Core Count':
                                data['processor']['core_count'] = value
                            elif key == 'Thread Count':
                                data['processor']['thread_count'] = value

    except (IOError, OSError):
        pass

    return data


def parse_lscpu(sos_home):
    """
    Parse lscpu output for CPU information.

    Args:
        sos_home: Root directory of sosreport

    Returns:
        Dict with CPU details (architecture, cores, sockets, NUMA, etc.)
    """
    lscpu_path = get_sos_file_path(sos_home, "sos_commands", "processor", "lscpu")

    if not exists(lscpu_path):
        return {}

    data = {}

    try:
        with open(lscpu_path, 'r') as f:
            for line in f:
                if ':' not in line:
                    continue

                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                data[key] = value

    except (IOError, OSError):
        pass

    return data


def parse_meminfo(sos_home):
    """
    Parse /proc/meminfo for memory statistics.

    Args:
        sos_home: Root directory of sosreport

    Returns:
        Dict with memory values in KB
    """
    meminfo_path = get_sos_file_path(sos_home, "proc", "meminfo")

    if not exists(meminfo_path):
        return {}

    data = {}

    try:
        with open(meminfo_path, 'r') as f:
            for line in f:
                if ':' not in line:
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    value = int(parts[1])  # Value in KB
                    data[key] = value

    except (IOError, OSError, ValueError):
        pass

    return data


def parse_lsblk(sos_home):
    """
    Parse lsblk output for block device information.

    Args:
        sos_home: Root directory of sosreport

    Returns:
        List of block devices with details
    """
    lsblk_path = get_sos_file_path(sos_home, "sos_commands", "block", "lsblk")

    if not exists(lsblk_path):
        return []

    devices = []

    try:
        with open(lsblk_path, 'r') as f:
            for line in f:
                line = line.rstrip()
                if line and not line.startswith('NAME'):
                    devices.append(line)

    except (IOError, OSError):
        pass

    return devices


def parse_lspci(sos_home):
    """
    Parse lspci output for PCI device information.

    Args:
        sos_home: Root directory of sosreport

    Returns:
        List of PCI devices
    """
    lspci_path = get_sos_file_path(sos_home, "sos_commands", "pci", "lspci_-nnvv")

    if not exists(lspci_path):
        lspci_path = get_sos_file_path(sos_home, "lspci")

    if not exists(lspci_path):
        return []

    devices = []
    current_device = {}

    try:
        with open(lspci_path, 'r') as f:
            for line in f:
                line = line.rstrip()

                # New device starts with bus address
                if line and not line.startswith('\t'):
                    if current_device:
                        devices.append(current_device)
                    current_device = {'desc': line}
                elif line.startswith('\tSubsystem:'):
                    current_device['subsystem'] = line.strip()

            # Add last device
            if current_device:
                devices.append(current_device)

    except (IOError, OSError):
        pass

    return devices


def show_summary(sos_home, colors, output):
    """
    Show overall hardware summary.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== Hardware Summary ===", colors.cyan, colors.reset)
    output.add_line("")

    # System Information
    dmi_data = parse_dmidecode(sos_home)
    if dmi_data.get('system'):
        sys_info = dmi_data['system']
        output.add_colored_line("System:", colors.yellow, colors.reset)
        output.add_line("  Manufacturer: %s" % sys_info.get('manufacturer', 'N/A'))
        output.add_line("  Product:      %s" % sys_info.get('product', 'N/A'))
        output.add_line("  Serial:       %s" % sys_info.get('serial', 'N/A'))
        output.add_line("")

    # CPU Information
    cpu_data = parse_lscpu(sos_home)
    if cpu_data:
        output.add_colored_line("CPU:", colors.yellow, colors.reset)
        output.add_line("  Model:        %s" % cpu_data.get('Model name', 'N/A'))
        output.add_line("  Architecture: %s" % cpu_data.get('Architecture', 'N/A'))
        output.add_line("  CPUs:         %s" % cpu_data.get('CPU(s)', 'N/A'))
        output.add_line("  Sockets:      %s" % cpu_data.get('Socket(s)', 'N/A'))
        output.add_line("  Cores/Socket: %s" % cpu_data.get('Core(s) per socket', 'N/A'))
        output.add_line("  Threads/Core: %s" % cpu_data.get('Thread(s) per core', 'N/A'))
        output.add_line("")

    # Memory Information
    mem_data = parse_meminfo(sos_home)
    if mem_data:
        total_kb = mem_data.get('MemTotal', 0)
        total_gb = total_kb / (SIZE_1GB / SIZE_1KB)
        available_kb = mem_data.get('MemAvailable', 0)
        available_gb = available_kb / (SIZE_1GB / SIZE_1KB)

        output.add_colored_line("Memory:", colors.yellow, colors.reset)
        output.add_line("  Total:        %.1f GB (%s KB)" % (total_gb, format_bytes(total_kb * SIZE_1KB)))
        output.add_line("  Available:    %.1f GB (%s KB)" % (available_gb, format_bytes(available_kb * SIZE_1KB)))

        # Count DIMMs
        mem_devices = [d for d in dmi_data.get('memory_devices', [])
                       if d.get('size', 'No Module Installed') != 'No Module Installed']
        if mem_devices:
            output.add_line("  DIMMs:        %d installed" % len(mem_devices))
        output.add_line("")

    # Disk Information
    devices = parse_lsblk(sos_home)
    disk_count = sum(1 for line in devices if not line.startswith('├') and not line.startswith('└'))
    if disk_count > 0:
        output.add_colored_line("Storage:", colors.yellow, colors.reset)
        output.add_line("  Block Devices: %d" % disk_count)
        output.add_line("")

    # BIOS Information
    if dmi_data.get('bios'):
        bios_info = dmi_data['bios']
        output.add_colored_line("BIOS:", colors.yellow, colors.reset)
        output.add_line("  Vendor:       %s" % bios_info.get('vendor', 'N/A'))
        output.add_line("  Version:      %s" % bios_info.get('version', 'N/A'))
        output.add_line("  Date:         %s" % bios_info.get('date', 'N/A'))


def show_cpu_info(sos_home, colors, output):
    """
    Show detailed CPU information.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== CPU Information ===", colors.cyan, colors.reset)
    output.add_line("")

    cpu_data = parse_lscpu(sos_home)

    if not cpu_data:
        output.add_line("No CPU information available")
        return

    # Basic Info
    output.add_colored_line("Architecture & Model:", colors.yellow, colors.reset)
    for key in ['Architecture', 'CPU op-mode(s)', 'Byte Order', 'Model name',
                'BIOS Model name', 'Vendor ID', 'CPU family', 'Model', 'Stepping']:
        if key in cpu_data:
            output.add_line("  %-20s %s" % (key + ':', cpu_data[key]))
    output.add_line("")

    # Topology
    output.add_colored_line("Topology:", colors.yellow, colors.reset)
    for key in ['CPU(s)', 'On-line CPU(s) list', 'Socket(s)',
                'Core(s) per socket', 'Thread(s) per core']:
        if key in cpu_data:
            output.add_line("  %-20s %s" % (key + ':', cpu_data[key]))
    output.add_line("")

    # NUMA
    numa_nodes = cpu_data.get('NUMA node(s)')
    if numa_nodes:
        output.add_colored_line("NUMA Configuration:", colors.yellow, colors.reset)
        output.add_line("  %-20s %s" % ('NUMA nodes:', numa_nodes))
        for key in sorted(cpu_data.keys()):
            if key.startswith('NUMA node') and 'CPU(s)' in key:
                output.add_line("  %-20s %s" % (key + ':', cpu_data[key]))
        output.add_line("")

    # Cache
    output.add_colored_line("Cache:", colors.yellow, colors.reset)
    for key in ['L1d cache', 'L1i cache', 'L2 cache', 'L3 cache']:
        if key in cpu_data:
            output.add_line("  %-20s %s" % (key + ':', cpu_data[key]))
    output.add_line("")

    # Virtualization
    if 'Hypervisor vendor' in cpu_data or 'Virtualization type' in cpu_data:
        output.add_colored_line("Virtualization:", colors.yellow, colors.reset)
        for key in ['Hypervisor vendor', 'Virtualization type', 'Virtualization']:
            if key in cpu_data:
                output.add_line("  %-20s %s" % (key + ':', cpu_data[key]))
        output.add_line("")

    # Frequency
    if 'CPU MHz' in cpu_data or 'BogoMIPS' in cpu_data:
        output.add_colored_line("Frequency:", colors.yellow, colors.reset)
        for key in ['CPU MHz', 'CPU max MHz', 'CPU min MHz', 'BogoMIPS']:
            if key in cpu_data:
                output.add_line("  %-20s %s" % (key + ':', cpu_data[key]))


def show_memory_info(sos_home, colors, output):
    """
    Show detailed memory information.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== Memory Information ===", colors.cyan, colors.reset)
    output.add_line("")

    # Get memory statistics
    mem_data = parse_meminfo(sos_home)

    if mem_data:
        output.add_colored_line("Memory Statistics:", colors.yellow, colors.reset)
        total_kb = mem_data.get('MemTotal', 0)
        free_kb = mem_data.get('MemFree', 0)
        available_kb = mem_data.get('MemAvailable', 0)
        cached_kb = mem_data.get('Cached', 0)
        buffers_kb = mem_data.get('Buffers', 0)
        swap_total_kb = mem_data.get('SwapTotal', 0)
        swap_free_kb = mem_data.get('SwapFree', 0)

        output.add_line("  %-20s %s" % ('Total:', format_bytes(total_kb * SIZE_1KB)))
        output.add_line("  %-20s %s" % ('Free:', format_bytes(free_kb * SIZE_1KB)))
        output.add_line("  %-20s %s" % ('Available:', format_bytes(available_kb * SIZE_1KB)))
        output.add_line("  %-20s %s" % ('Cached:', format_bytes(cached_kb * SIZE_1KB)))
        output.add_line("  %-20s %s" % ('Buffers:', format_bytes(buffers_kb * SIZE_1KB)))
        output.add_line("  %-20s %s" % ('Swap Total:', format_bytes(swap_total_kb * SIZE_1KB)))
        output.add_line("  %-20s %s" % ('Swap Free:', format_bytes(swap_free_kb * SIZE_1KB)))
        output.add_line("")

    # Get DIMM information from dmidecode
    dmi_data = parse_dmidecode(sos_home)
    mem_devices = dmi_data.get('memory_devices', [])

    installed_dimms = [d for d in mem_devices
                       if d.get('size', 'No Module Installed') != 'No Module Installed']

    if installed_dimms:
        output.add_colored_line("Installed Memory Modules:", colors.yellow, colors.reset)
        output.add_line("  %-15s %-10s %-15s %-15s %s" %
                       ('Locator', 'Size', 'Type', 'Speed', 'Manufacturer'))
        output.add_line("  " + "-" * 75)

        for dimm in installed_dimms:
            output.add_line("  %-15s %-10s %-15s %-15s %s" % (
                dimm.get('locator', 'N/A')[:15],
                dimm.get('size', 'N/A')[:10],
                dimm.get('type', 'N/A')[:15],
                dimm.get('speed', 'N/A')[:15],
                dimm.get('manufacturer', 'N/A')[:30]
            ))


def show_disk_info(sos_home, colors, output):
    """
    Show disk and block device information.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== Disk and Block Devices ===", colors.cyan, colors.reset)
    output.add_line("")

    devices = parse_lsblk(sos_home)

    if not devices:
        output.add_line("No block device information available")
        return

    output.add_colored_line("Block Device Tree:", colors.yellow, colors.reset)
    screen.init_data(output.no_pipe, 1, is_cmd_stopped)

    for line in devices:
        colored_line = screen.get_colored_line(line)
        output.add_line(colored_line)


def show_pci_info(sos_home, colors, output):
    """
    Show PCI device information.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== PCI Devices ===", colors.cyan, colors.reset)
    output.add_line("")

    devices = parse_lspci(sos_home)

    if not devices:
        output.add_line("No PCI device information available")
        return

    # Categorize devices
    network = []
    storage = []
    other = []

    for dev in devices:
        desc = dev.get('desc', '')
        if 'Ethernet' in desc or 'Network' in desc:
            network.append(dev)
        elif 'SATA' in desc or 'SCSI' in desc or 'IDE' in desc or 'RAID' in desc or 'NVMe' in desc:
            storage.append(dev)
        else:
            other.append(dev)

    # Show network devices
    if network:
        output.add_colored_line("Network Controllers:", colors.yellow, colors.reset)
        for dev in network:
            output.add_line("  " + dev['desc'])
        output.add_line("")

    # Show storage controllers
    if storage:
        output.add_colored_line("Storage Controllers:", colors.yellow, colors.reset)
        for dev in storage:
            output.add_line("  " + dev['desc'])
        output.add_line("")

    # Show other devices
    if other:
        output.add_colored_line("Other PCI Devices:", colors.yellow, colors.reset)
        for dev in other[:10]:  # Limit to first 10
            output.add_line("  " + dev['desc'])
        if len(other) > 10:
            output.add_line("  ... and %d more devices" % (len(other) - 10))


def show_system_info(sos_home, colors, output):
    """
    Show system information from dmidecode.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance
    """
    output.add_colored_line("=== System Information ===", colors.cyan, colors.reset)
    output.add_line("")

    dmi_data = parse_dmidecode(sos_home)

    if not dmi_data:
        output.add_line("No system information available")
        return

    # System
    if dmi_data.get('system'):
        sys_info = dmi_data['system']
        output.add_colored_line("System:", colors.yellow, colors.reset)
        output.add_line("  %-20s %s" % ('Manufacturer:', sys_info.get('manufacturer', 'N/A')))
        output.add_line("  %-20s %s" % ('Product Name:', sys_info.get('product', 'N/A')))
        output.add_line("  %-20s %s" % ('Serial Number:', sys_info.get('serial', 'N/A')))
        output.add_line("  %-20s %s" % ('UUID:', sys_info.get('uuid', 'N/A')))
        output.add_line("")

    # BIOS
    if dmi_data.get('bios'):
        bios_info = dmi_data['bios']
        output.add_colored_line("BIOS:", colors.yellow, colors.reset)
        output.add_line("  %-20s %s" % ('Vendor:', bios_info.get('vendor', 'N/A')))
        output.add_line("  %-20s %s" % ('Version:', bios_info.get('version', 'N/A')))
        output.add_line("  %-20s %s" % ('Release Date:', bios_info.get('date', 'N/A')))
        output.add_line("")

    # Chassis
    if dmi_data.get('chassis'):
        chassis_info = dmi_data['chassis']
        output.add_colored_line("Chassis:", colors.yellow, colors.reset)
        output.add_line("  %-20s %s" % ('Manufacturer:', chassis_info.get('manufacturer', 'N/A')))
        output.add_line("  %-20s %s" % ('Type:', chassis_info.get('type', 'N/A')))
        output.add_line("")

    # Processor (from dmidecode)
    if dmi_data.get('processor'):
        proc_info = dmi_data['processor']
        output.add_colored_line("Processor (DMI):", colors.yellow, colors.reset)
        output.add_line("  %-20s %s" % ('Version:', proc_info.get('version', 'N/A')))
        output.add_line("  %-20s %s" % ('Max Speed:', proc_info.get('max_speed', 'N/A')))
        output.add_line("  %-20s %s" % ('Current Speed:', proc_info.get('current_speed', 'N/A')))
        output.add_line("  %-20s %s" % ('Core Count:', proc_info.get('core_count', 'N/A')))
        output.add_line("  %-20s %s" % ('Thread Count:', proc_info.get('thread_count', 'N/A')))


def print_help_msg(op, no_pipe):
    """Generate help message."""
    cmd_examples = '''
Shows comprehensive hardware information from the sosreport.

Examples:
  hwinfo           Show overall hardware summary (default)
  hwinfo -c        Show detailed CPU information
  hwinfo -m        Show detailed memory information
  hwinfo -d        Show disk and block devices
  hwinfo -p        Show PCI devices
  hwinfo -s        Show system information (BIOS, motherboard, etc.)
  hwinfo -a        Show all hardware information

Hardware Categories:
  - System: Manufacturer, model, serial numbers
  - CPU: Architecture, cores, sockets, NUMA topology
  - Memory: Total memory, DIMMs, configuration
  - Disk: Block devices, storage controllers
  - PCI: Network cards, storage controllers, other devices
    '''

    if no_pipe:
        op.print_help()
        print(cmd_examples)
        return ""
    else:
        output = StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()
        return contents + "\n" + cmd_examples


# Global state
is_cmd_stopped = None


def run_hwinfo(input_str, env_vars, is_cmd_stopped_func,
               show_help=False, no_pipe=True):
    """
    Main entry point for hwinfo command.

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

    # Parse command line options
    usage = "Usage: hwinfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-c', '--cpu', dest='show_cpu', action='store_true',
                  help='show detailed CPU information')
    op.add_option('-m', '--memory', dest='show_memory', action='store_true',
                  help='show detailed memory information')
    op.add_option('-d', '--disk', dest='show_disk', action='store_true',
                  help='show disk and block devices')
    op.add_option('-p', '--pci', dest='show_pci', action='store_true',
                  help='show PCI devices')
    op.add_option('-s', '--system', dest='show_system', action='store_true',
                  help='show system information (BIOS, motherboard, etc.)')
    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all hardware information')

    try:
        (o, args) = op.parse_args(input_str.split())
    except Exception:
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
            show_summary(sos_home, colors, output)
            output.add_line("")
            show_cpu_info(sos_home, colors, output)
            output.add_line("")
            show_memory_info(sos_home, colors, output)
            output.add_line("")
            show_disk_info(sos_home, colors, output)
            output.add_line("")
            show_pci_info(sos_home, colors, output)
            output.add_line("")
            show_system_info(sos_home, colors, output)
        elif o.show_cpu:
            show_cpu_info(sos_home, colors, output)
        elif o.show_memory:
            show_memory_info(sos_home, colors, output)
        elif o.show_disk:
            show_disk_info(sos_home, colors, output)
        elif o.show_pci:
            show_pci_info(sos_home, colors, output)
        elif o.show_system:
            show_system_info(sos_home, colors, output)
        else:
            # Default: show summary
            show_summary(sos_home, colors, output)

    except Exception as e:
        output.add_line("Unexpected error: %s" % str(e))

    return output.get_result()
