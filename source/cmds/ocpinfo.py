#!/usr/bin/env python3
"""
ocpinfo - OpenShift Container Platform information analyzer for isos

This command analyzes OCP data from sosreports and must-gather archives.
Inspired by sos4ocp (https://github.com/vlours/sos4ocp.git)
"""

import sys
import os
import re
from optparse import OptionParser
from io import StringIO

import ansicolor
import screen
import table_formatter


def description():
    return "Shows OpenShift Container Platform (OCP) related information"


def add_command():
    return True


cmd_name = "ocpinfo"
def get_command_info():
    return { "%s" % cmd_name : run_ocpinfo }


# Color constants
COLOR_RED = ""
COLOR_YELLOW = ""
COLOR_GREEN = ""
COLOR_BLUE = ""
COLOR_CYAN = ""
COLOR_MAGENTA = ""
COLOR_RESET = ""


def set_color_table(no_pipe):
    global COLOR_RED, COLOR_YELLOW, COLOR_GREEN, COLOR_BLUE, COLOR_CYAN, COLOR_MAGENTA, COLOR_RESET

    if no_pipe:
        COLOR_RED = ansicolor.get_color(ansicolor.LIGHTRED)
        COLOR_YELLOW = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_GREEN = ansicolor.get_color(ansicolor.GREEN)
        COLOR_BLUE = ansicolor.get_color(ansicolor.BLUE)
        COLOR_CYAN = ansicolor.get_color(ansicolor.CYAN)
        COLOR_MAGENTA = ansicolor.get_color(ansicolor.MAGENTA)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)
    else:
        COLOR_RED = COLOR_YELLOW = COLOR_GREEN = COLOR_BLUE = COLOR_CYAN = COLOR_MAGENTA = COLOR_RESET = ""


def read_file(filepath):
    """Read file content safely"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except:
        return ""


def read_lines(filepath):
    """Read file lines safely"""
    content = read_file(filepath)
    return content.splitlines() if content else []


def get_size_str(size_bytes):
    """Convert bytes to human-readable size"""
    if size_bytes > (1024 * 1024 * 1024):  # GiB
        return "%.1f GiB" % (size_bytes / (1024*1024*1024))
    elif size_bytes > (1024 * 1024):  # MiB
        return "%.1f MiB" % (size_bytes / (1024*1024))
    elif size_bytes > 1024:  # KiB
        return "%.1f KiB" % (size_bytes / 1024)
    else:
        return "%d B" % size_bytes


def show_cluster_info(sosreport_path):
    """Show OCP cluster overview information"""
    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}")
    print(f"{COLOR_BLUE}OpenShift Cluster Information{COLOR_RESET}")
    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")

    # Read kubelet journal for version info
    kubelet_journal = os.path.join(sosreport_path, "sos_commands/openshift/journalctl_--no-pager_--unit_kubelet")
    if os.path.exists(kubelet_journal):
        lines = read_lines(kubelet_journal)
        for line in lines[:50]:  # Check first 50 lines
            if "Kubelet version" in line or "Starting kubelet" in line:
                print(f"Kubelet: {line.strip()}")
                break

    # Read CRI-O info
    crio_info_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_info")
    if os.path.exists(crio_info_path):
        content = read_file(crio_info_path)
        if content:
            print(f"\n{COLOR_CYAN}Container Runtime:{COLOR_RESET}")
            for line in content.splitlines()[:20]:
                if '"version"' in line.lower() or '"runtimeVersion"' in line.lower():
                    print(f"  {line.strip()}")

    # Read CRI-O version
    crio_version_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_version")
    if os.path.exists(crio_version_path):
        content = read_file(crio_version_path)
        if content:
            print(f"\n{COLOR_CYAN}CRI-O Version:{COLOR_RESET}")
            for line in content.splitlines():
                print(f"  {line.strip()}")

    # Read hostname
    hostname_path = os.path.join(sosreport_path, "hostname")
    if os.path.exists(hostname_path):
        hostname = read_file(hostname_path).strip()
        print(f"\n{COLOR_CYAN}Node Hostname:{COLOR_RESET} {hostname}")

    # Read RHCOS version
    rhcos_path = os.path.join(sosreport_path, "sos_commands/rhcos/rpm-ostree_status")
    if os.path.exists(rhcos_path):
        lines = read_lines(rhcos_path)
        print(f"\n{COLOR_CYAN}RHCOS Version:{COLOR_RESET}")
        for line in lines[:10]:
            if "Version:" in line or "Commit:" in line:
                print(f"  {line.strip()}")

    print(f"\n{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")


def show_pods_info(sosreport_path, options):
    """Show pod information"""
    crictl_pods_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_pods")

    if not os.path.exists(crictl_pods_path):
        print(f"{COLOR_RED}Error: crictl pods output not found{COLOR_RESET}")
        return

    lines = read_lines(crictl_pods_path)
    if not lines:
        print(f"{COLOR_RED}Error: crictl pods output is empty{COLOR_RESET}")
        return

    # Parse header
    header = lines[0] if lines else ""
    data_lines = lines[1:]

    # Filter by namespace if specified
    if options.namespace:
        data_lines = [line for line in data_lines if options.namespace in line]

    # Filter by state if specified
    if options.state:
        data_lines = [line for line in data_lines if options.state in line]

    # Filter by pattern if specified (case-insensitive)
    if options.filter:
        data_lines = [line for line in data_lines if options.filter.lower() in line.lower()]

    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}")
    print(f"{COLOR_BLUE}Pod Information ({len(data_lines)} pods){COLOR_RESET}")
    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")

    # Count by state and namespace
    # crictl pods format: POD_ID CREATED(variable) STATE NAME NAMESPACE ATTEMPT RUNTIME
    # STATE is always "Ready" or "NotReady" or similar status word
    state_counts = {}
    namespace_counts = {}

    for line in data_lines:
        # Find STATE by looking for Ready/NotReady
        state = None
        namespace = None

        # Match pattern: STATE is a single word status after the timestamp
        match = re.search(r'\s+(Ready|NotReady|Running|Exited|Created|Paused)\s+', line)
        if match:
            state = match.group(1)
            state_counts[state] = state_counts.get(state, 0) + 1

            # Namespace is several fields after state
            # Format: STATE NAME NAMESPACE ...
            parts_after_state = line[match.end():].split()
            if len(parts_after_state) >= 2:
                namespace = parts_after_state[1]
                namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1

    # Show summary
    if not options.detail:
        print(f"{COLOR_CYAN}Pods by State:{COLOR_RESET}")
        for state in sorted(state_counts.keys()):
            count = state_counts[state]
            color = COLOR_GREEN if state == "Ready" else COLOR_YELLOW if state == "NotReady" else COLOR_RED
            print(f"  {color}{state:15s}{COLOR_RESET}: {count:4d}")

        print(f"\n{COLOR_CYAN}Pods by Namespace (top 10):{COLOR_RESET}")
        for namespace, count in sorted(namespace_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {namespace:40s}: {count:4d}")

    # Show detailed list if requested
    if options.detail:
        print(f"\n{COLOR_CYAN}{header}{COLOR_RESET}")
        print("-" * 80)

        count = 0
        for line in data_lines:
            if options.limit and count >= options.limit:
                remaining = len(data_lines) - count
                print(f"\n{COLOR_YELLOW}... and {remaining} more pods{COLOR_RESET}")
                break

            # Color based on state
            match = re.search(r'\s+(Ready|NotReady|Running|Exited|Created|Paused)\s+', line)
            if match:
                state = match.group(1)
                if state == "Ready" or state == "Running":
                    print(f"{COLOR_GREEN}{line}{COLOR_RESET}")
                elif state == "NotReady":
                    print(f"{COLOR_YELLOW}{line}{COLOR_RESET}")
                else:
                    print(line)
            else:
                print(line)
            count += 1

    print(f"\n{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")


def show_containers_info(sosreport_path, options):
    """Show container information"""
    crictl_ps_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_ps_-a")

    if not os.path.exists(crictl_ps_path):
        # Try without -a flag
        crictl_ps_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_ps")
        if not os.path.exists(crictl_ps_path):
            print(f"{COLOR_RED}Error: crictl ps output not found{COLOR_RESET}")
            return

    lines = read_lines(crictl_ps_path)
    if not lines:
        print(f"{COLOR_RED}Error: crictl ps output is empty{COLOR_RESET}")
        return

    header = lines[0] if lines else ""
    data_lines = lines[1:]

    # Filter by pattern if specified (case-insensitive)
    if options.filter:
        data_lines = [line for line in data_lines if options.filter.lower() in line.lower()]

    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}")
    print(f"{COLOR_BLUE}Container Information ({len(data_lines)} containers){COLOR_RESET}")
    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")

    # Count by state
    # crictl ps format: CONTAINER IMAGE CREATED STATE NAME ...
    # STATE is a single word status like "Running", "Exited", etc.
    state_counts = {}
    for line in data_lines:
        # Match pattern: STATE is a status word after the timestamp
        match = re.search(r'\s+(Running|Exited|Created|Paused|Unknown)\s+', line)
        if match:
            state = match.group(1)
            state_counts[state] = state_counts.get(state, 0) + 1

    print(f"{COLOR_CYAN}Containers by State:{COLOR_RESET}")
    for state in sorted(state_counts.keys()):
        count = state_counts[state]
        color = COLOR_GREEN if state == "Running" else COLOR_YELLOW if state == "Exited" else COLOR_RED
        print(f"  {color}{state:15s}{COLOR_RESET}: {count:4d}")

    # Show detailed list if requested
    if options.detail:
        print(f"\n{COLOR_CYAN}{header}{COLOR_RESET}")
        print("-" * 80)

        count = 0
        for line in data_lines:
            if options.limit and count >= options.limit:
                remaining = len(data_lines) - count
                print(f"\n{COLOR_YELLOW}... and {remaining} more containers{COLOR_RESET}")
                break

            # Color based on state
            match = re.search(r'\s+(Running|Exited|Created|Paused|Unknown)\s+', line)
            if match:
                state = match.group(1)
                if state == "Running":
                    print(f"{COLOR_GREEN}{line}{COLOR_RESET}")
                else:
                    print(f"{COLOR_YELLOW}{line}{COLOR_RESET}")
            else:
                print(line)
            count += 1

    print(f"\n{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")


def show_images_info(sosreport_path, options):
    """Show container images information"""
    crictl_images_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_images")

    if not os.path.exists(crictl_images_path):
        print(f"{COLOR_RED}Error: crictl images output not found{COLOR_RESET}")
        return

    lines = read_lines(crictl_images_path)
    if not lines:
        print(f"{COLOR_RED}Error: crictl images output is empty{COLOR_RESET}")
        return

    header = lines[0] if lines else ""
    data_lines = lines[1:]

    # Filter by pattern if specified (case-insensitive)
    if options.filter:
        data_lines = [line for line in data_lines if options.filter.lower() in line.lower()]

    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}")
    print(f"{COLOR_BLUE}Container Images ({len(data_lines)} images){COLOR_RESET}")
    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")

    # Calculate total size
    total_size = 0
    for line in data_lines:
        words = line.split()
        if len(words) >= 4:
            size_str = words[3]
            # Parse size (e.g., "123MB", "1.5GB")
            try:
                if "GB" in size_str:
                    size_val = float(size_str.replace("GB", ""))
                    total_size += size_val * 1024 * 1024 * 1024
                elif "MB" in size_str:
                    size_val = float(size_str.replace("MB", ""))
                    total_size += size_val * 1024 * 1024
                elif "KB" in size_str:
                    size_val = float(size_str.replace("KB", ""))
                    total_size += size_val * 1024
            except:
                pass

    print(f"{COLOR_CYAN}Total Images Size:{COLOR_RESET} {get_size_str(total_size)}")

    if options.detail:
        print(f"\n{COLOR_CYAN}{header}{COLOR_RESET}")
        print("-" * 80)

        count = 0
        for line in data_lines:
            if options.limit and count >= options.limit:
                remaining = len(data_lines) - count
                print(f"\n{COLOR_YELLOW}... and {remaining} more images{COLOR_RESET}")
                break
            print(line)
            count += 1

    print(f"\n{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")


def show_resource_stats(sosreport_path):
    """Show container resource statistics"""
    crictl_stats_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_stats")

    if not os.path.exists(crictl_stats_path):
        print(f"{COLOR_YELLOW}Warning: crictl stats output not found{COLOR_RESET}")
        return

    lines = read_lines(crictl_stats_path)
    if not lines:
        return

    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}")
    print(f"{COLOR_BLUE}Container Resource Statistics{COLOR_RESET}")
    print(f"{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")

    # Show top consumers
    print(f"{COLOR_CYAN}Top Resource Consumers:{COLOR_RESET}\n")

    for line in lines[:20]:  # Show first 20 lines including header
        print(line)

    print(f"\n{COLOR_BLUE}{'=' * 80}{COLOR_RESET}\n")


def print_help_msg(op, no_pipe):
    """Print help message following isos pattern"""
    cmd_examples = '''
Examples:
    # Show cluster overview (default)
    > ocpinfo

    # Show pod information
    > ocpinfo -p

    # Show detailed pod list (first 10)
    > ocpinfo -p -d -l 10

    # Filter pods by namespace
    > ocpinfo -p -n openshift-kube-apiserver

    # Show container information
    > ocpinfo -c

    # Show container images
    > ocpinfo -i

    # Show resource statistics
    > ocpinfo -s

    # Show all information
    > ocpinfo -a

    # Show pods in specific namespace with details
    > ocpinfo -p -d -n jbsb-ci

    # Show only NotReady pods
    > ocpinfo -p --state NotReady

    # Filter pods containing "api" in any field
    > ocpinfo -p -d -f api

    # Filter containers for specific image
    > ocpinfo -c -d -f sonarqube

    # Combine filters: namespace and pattern
    > ocpinfo -p -d -n jbsb-ci -f quarkus

    # Show only pods matching pattern with limit
    > ocpinfo -p -d -f portal -l 5
    '''

    if no_pipe == False:
        output = StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()
        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""


def run_ocpinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    """Main entry point for ocpinfo command"""

    usage = "Usage: %s [options]" % (cmd_name)

    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option("-p", "--pods", dest="pods", default=False,
                  action="store_true",
                  help="Show pod information")
    op.add_option("-c", "--containers", dest="containers", default=False,
                  action="store_true",
                  help="Show container information")
    op.add_option("-i", "--images", dest="images", default=False,
                  action="store_true",
                  help="Show container images")
    op.add_option("-s", "--stats", dest="stats", default=False,
                  action="store_true",
                  help="Show resource statistics")
    op.add_option("-d", "--detail", dest="detail", default=False,
                  action="store_true",
                  help="Show detailed information")
    op.add_option("-n", "--namespace", dest="namespace", default="",
                  type="string", action="store",
                  help="Filter by namespace")
    op.add_option("--state", dest="state", default="",
                  type="string", action="store",
                  help="Filter by state (Ready, NotReady, Running, etc.)")
    op.add_option("-l", "--limit", dest="limit", default=0,
                  type="int", action="store",
                  help="Limit number of items to display")
    op.add_option("-f", "--filter", dest="filter", default="",
                  type="string", action="store",
                  help="Filter lines containing pattern (case-insensitive)")
    op.add_option("-a", "--all", dest="all", default=False,
                  action="store_true",
                  help="Show all information (equivalent to -p -c -i -s)")

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        return print_help_msg(op, no_pipe)

    # Set colors
    set_color_table(no_pipe)

    # Get sosreport path
    sosreport_path = os.getcwd()

    # Check if we're in a sosreport directory
    if not os.path.exists(os.path.join(sosreport_path, "sos_commands")):
        print(f"{COLOR_RED}Error: Not in a sosreport directory{COLOR_RESET}")
        print("Please run this command from within an extracted sosreport")
        return

    # If no specific option, show cluster overview
    if not (o.pods or o.containers or o.images or o.stats or o.all):
        show_cluster_info(sosreport_path)
        return ""

    # Show all if requested
    if o.all:
        show_cluster_info(sosreport_path)
        show_pods_info(sosreport_path, o)
        show_containers_info(sosreport_path, o)
        show_images_info(sosreport_path, o)
        show_resource_stats(sosreport_path)
        return ""

    # Show specific information
    if o.pods:
        show_pods_info(sosreport_path, o)

    if o.containers:
        show_containers_info(sosreport_path, o)

    if o.images:
        show_images_info(sosreport_path, o)

    if o.stats:
        show_resource_stats(sosreport_path)

    return ""


if __name__ == "__main__":
    # For testing
    def dummy_is_stopped():
        return False
    run_ocpinfo(" ".join(sys.argv[1:]), {}, dummy_is_stopped, False, True)
