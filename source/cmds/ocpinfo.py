#!/usr/bin/env python3
"""
ocpinfo - OpenShift Container Platform information analyzer for isos

This command analyzes OCP data from sosreports and must-gather archives.
Inspired by sos4ocp (https://github.com/vlours/sos4ocp.git)
"""

import sys
import os
import re
import json
from optparse import OptionParser
from io import StringIO

import ansicolor
import screen
import table_formatter
from cmd_helpers import format_bytes, ColorManager


def description():
    return "Shows OpenShift Container Platform (OCP) related information"


def add_command():
    return True


cmd_name = "ocpinfo"
def get_command_info():
    return { "%s" % cmd_name : run_ocpinfo }


# Status value constants
class StatusValues:
    """OpenShift status value constants"""
    TRUE = "True"
    FALSE = "False"
    UNKNOWN = "Unknown"


class PodStates:
    """Pod state constants"""
    READY = "Ready"
    NOT_READY = "NotReady"
    RUNNING = "Running"
    EXITED = "Exited"


class MustGatherPaths:
    """Centralized must-gather path definitions"""
    def __init__(self, root):
        self.root = root
        self.cluster_scoped = os.path.join(root, "cluster-scoped-resources/config.openshift.io")
        self.etcd_info = os.path.join(root, "etcd_info")

    def cluster_version_file(self):
        return os.path.join(self.cluster_scoped, "clusterversions.yaml")

    def cluster_operators_dir(self):
        return os.path.join(self.cluster_scoped, "clusteroperators")

    def etcd_file(self, filename):
        return os.path.join(self.etcd_info, filename)


def read_file(filepath):
    """Read file content safely"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except (IOError, OSError):
        return ""


def read_lines(filepath):
    """Read file lines safely"""
    content = read_file(filepath)
    return content.splitlines() if content else []


def read_must_gather_file(filepath, description, colors):
    """Read must-gather file with consistent error handling"""
    content = read_file(filepath)
    if not content:
        print(f"{colors.red}Error: {description} not found or empty{colors.reset}")
        return None
    return content


def extract_yaml_value(content, key, strip_quotes=True):
    """Extract value from simple YAML key:value pairs

    Args:
        content: YAML content string
        key: Key to search for
        strip_quotes: Whether to strip quotes from value

    Returns:
        First value found or None
    """
    for line in content.splitlines():
        line = line.strip()
        if f'{key}:' in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                value = parts[1].strip()
                if strip_quotes:
                    value = value.strip('"').strip("'")
                if value and not value.startswith('{') and value != 'v1':
                    return value
    return None


def find_condition_status(lines, condition_type):
    """Find status value for a given condition type in YAML lines

    Args:
        lines: List of YAML lines
        condition_type: Condition type to search for (e.g., 'Available')

    Returns:
        Status string or None
    """
    for i, line in enumerate(lines):
        if f'type: {condition_type}' in line or f'type: "{condition_type}"' in line:
            # Look for status in next few lines
            for j in range(i + 1, min(i + 10, len(lines))):
                if 'status:' in lines[j]:
                    return lines[j].split(':', 1)[1].strip().strip('"').strip("'")
    return None


def print_section_header(title, colors, width=80):
    """Print consistent section header"""
    print(f"{colors.blue}{'=' * width}{colors.reset}")
    print(f"{colors.blue}{title}{colors.reset}")
    print(f"{colors.blue}{'=' * width}{colors.reset}\n")


def print_section_footer(colors, width=80):
    """Print consistent section footer"""
    print(f"\n{colors.blue}{'=' * width}{colors.reset}\n")


def find_must_gather_root(base_path=None):
    """Find must-gather root directory"""
    if base_path is None:
        base_path = os.getcwd()

    try:
        for item in os.listdir(base_path):
            if item.startswith('quay-io-openshift-release-dev') or \
               item.startswith('must-gather'):
                full_path = os.path.join(base_path, item)
                if os.path.isdir(full_path):
                    return full_path
    except (IOError, OSError):
        pass
    return None


def detect_data_sources(base_path=None):
    """Detect available data sources (sosreport and/or must-gather)

    Returns:
        dict with keys: 'sosreport', 'must-gather', 'must-gather-root'
    """
    if base_path is None:
        base_path = os.getcwd()

    must_gather_path = find_must_gather_root(base_path)
    sources = {
        'sosreport': os.path.exists(os.path.join(base_path, 'sos_commands')),
        'must-gather': must_gather_path is not None,
        'must-gather-root': must_gather_path
    }
    return sources


def show_cluster_version(must_gather_root, colors):
    """Show OpenShift cluster version information"""
    print_section_header("OpenShift Cluster Version", colors)

    paths = MustGatherPaths(must_gather_root)
    version_file = paths.cluster_version_file()

    content = read_must_gather_file(version_file, "Cluster version file", colors)
    if not content:
        return

    # Parse version information using helper functions
    current_version = extract_yaml_value(content, 'version')
    channel = extract_yaml_value(content, 'channel')
    cluster_id = extract_yaml_value(content, 'clusterID')

    if current_version:
        print(f"{colors.cyan}Current Version:{colors.reset} {colors.green}{current_version}{colors.reset}")

    if channel:
        print(f"{colors.cyan}Update Channel:{colors.reset} {channel}")

    if cluster_id:
        print(f"{colors.cyan}Cluster ID:{colors.reset} {cluster_id}")

    # Check for conditions (split content once for efficiency)
    lines = content.splitlines()

    # Define conditions with their color rules
    conditions = {
        'Available': lambda status: colors.green if status == StatusValues.TRUE else colors.red,
        'Progressing': lambda status: colors.yellow if status == StatusValues.TRUE else colors.green,
        'Failing': lambda status: colors.red if status == StatusValues.TRUE else colors.green,
    }

    status_printed = False
    for condition_name, color_func in conditions.items():
        status = find_condition_status(lines, condition_name)
        if status:
            if not status_printed:
                print(f"\n{colors.cyan}Status:{colors.reset}")
                status_printed = True
            color = color_func(status)
            print(f"  {condition_name}: {color}{status}{colors.reset}")

    print_section_footer(colors)


def parse_operator_file(filepath, name):
    """Parse a single operator YAML file

    Args:
        filepath: Path to operator YAML file
        name: Operator name (from filename)

    Returns:
        dict with operator info or None if parse fails
    """
    content = read_file(filepath)
    if not content:
        return None

    lines = content.splitlines()

    # Extract status conditions using helper
    available = find_condition_status(lines, 'Available')
    progressing = find_condition_status(lines, 'Progressing')
    degraded = find_condition_status(lines, 'Degraded')

    # Extract version
    version = extract_yaml_value(content, 'version')

    return {
        'name': name,
        'available': available,
        'progressing': progressing,
        'degraded': degraded,
        'version': version
    }


def show_cluster_operators(must_gather_root, options, colors):
    """Show cluster operators status"""
    print_section_header("Cluster Operators", colors)

    paths = MustGatherPaths(must_gather_root)
    operators_dir = paths.cluster_operators_dir()

    # Get all operator files - filter by name first if filter specified (efficiency improvement)
    operator_files = []
    try:
        for filename in os.listdir(operators_dir):
            if filename.endswith('.yaml'):
                name = filename.replace('.yaml', '')
                # Early name filtering to avoid reading unnecessary files
                if hasattr(options, 'filter') and options.filter:
                    if options.filter.lower() not in name.lower():
                        continue
                operator_files.append((filename, name))
    except (IOError, OSError):
        print(f"{colors.red}Error: Could not list operators{colors.reset}")
        return

    operator_files.sort()

    # Parse each operator file
    operators = []
    for filename, name in operator_files:
        filepath = os.path.join(operators_dir, filename)
        op_data = parse_operator_file(filepath, name)
        if op_data:
            operators.append(op_data)

    # Filter by state if specified
    if hasattr(options, 'state') and options.state:
        state_lower = options.state.lower()
        filtered = []
        for op in operators:
            if state_lower == 'degraded' and op['degraded'] == StatusValues.TRUE:
                filtered.append(op)
            elif state_lower == 'progressing' and op['progressing'] == StatusValues.TRUE:
                filtered.append(op)
            elif state_lower == 'available' and op['available'] == StatusValues.TRUE:
                filtered.append(op)
        operators = filtered

    print(f"{colors.cyan}Total Operators: {len(operators)}{colors.reset}\n")

    # Count by status
    available_count = sum(1 for op in operators if op['available'] == StatusValues.TRUE)
    degraded_count = sum(1 for op in operators if op['degraded'] == StatusValues.TRUE)
    progressing_count = sum(1 for op in operators if op['progressing'] == StatusValues.TRUE)

    print(f"{colors.cyan}Status Summary:{colors.reset}")
    print(f"  {colors.green}Available: {available_count}{colors.reset}")
    print(f"  {colors.red}Degraded: {degraded_count}{colors.reset}")
    print(f"  {colors.yellow}Progressing: {progressing_count}{colors.reset}")

    # Show detailed list if requested
    if hasattr(options, 'detail') and options.detail:
        print(f"\n{colors.cyan}{'Operator':<40} {'Available':<12} {'Degraded':<12} {'Progressing':<12}{colors.reset}")
        print("-" * 80)

        count = 0
        for op in operators:
            if hasattr(options, 'limit') and options.limit and count >= options.limit:
                remaining = len(operators) - count
                print(f"\n{colors.yellow}... and {remaining} more operators{colors.reset}")
                break

            name = op['name'][:39] if len(op['name']) > 39 else op['name']

            # Color code based on status
            avail_color = colors.green if op['available'] == StatusValues.TRUE else colors.red
            deg_color = colors.red if op['degraded'] == StatusValues.TRUE else colors.green
            prog_color = colors.yellow if op['progressing'] == StatusValues.TRUE else colors.green

            avail_str = f"{avail_color}{op['available'] or StatusValues.UNKNOWN:<12}{colors.reset}"
            deg_str = f"{deg_color}{op['degraded'] or StatusValues.UNKNOWN:<12}{colors.reset}"
            prog_str = f"{prog_color}{op['progressing'] or StatusValues.UNKNOWN:<12}{colors.reset}"

            print(f"{name:<40} {avail_str} {deg_str} {prog_str}")
            count += 1

    print_section_footer(colors)


def show_etcd_health(must_gather_root, colors):
    """Show ETCD cluster health"""
    print_section_header("ETCD Cluster Health", colors)

    paths = MustGatherPaths(must_gather_root)

    # Read endpoint health
    health_file = paths.etcd_file("endpoint_health.json")
    content = read_file(health_file)
    if content:
        try:
            health_data = json.loads(content)
            print(f"{colors.cyan}ETCD Endpoints Health:{colors.reset}\n")

            healthy_count = 0
            for endpoint in health_data:
                ep = endpoint.get('endpoint', 'Unknown')
                health = endpoint.get('health', False)
                took = endpoint.get('took', 'N/A')

                status_color = colors.green if health else colors.red
                status_text = "Healthy" if health else "Unhealthy"

                print(f"  {ep:<40} {status_color}{status_text:<12}{colors.reset} (took: {took})")
                if health:
                    healthy_count += 1

            print(f"\n{colors.cyan}Summary: {colors.green}{healthy_count}/{len(health_data)}{colors.reset} endpoints healthy")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"{colors.red}Error parsing endpoint health: {e}{colors.reset}")

    # Read member list
    member_file = paths.etcd_file("member_list.json")
    content = read_file(member_file)
    if content:
        try:
            member_data = json.loads(content)
            if 'members' in member_data:
                print(f"\n{colors.cyan}ETCD Members:{colors.reset}")
                print(f"  Total members: {len(member_data['members'])}")
        except (json.JSONDecodeError, ValueError):
            pass

    # Read endpoint status
    status_file = paths.etcd_file("endpoint_status.json")
    content = read_file(status_file)
    if content:
        try:
            status_data = json.loads(content)
            print(f"\n{colors.cyan}ETCD Status Details:{colors.reset}\n")

            for endpoint in status_data:
                ep = endpoint.get('Endpoint', 'Unknown')
                status = endpoint.get('Status', {})
                leader = status.get('header', {}).get('member_id', 'Unknown')
                db_size = status.get('dbSize', 0)

                print(f"  {ep}")
                print(f"    Leader ID: {leader}")
                print(f"    DB Size: {format_bytes(db_size, precision=1)}")
        except (json.JSONDecodeError, ValueError):
            pass

    # Read alarms
    alarm_file = paths.etcd_file("alarm_list.json")
    content = read_file(alarm_file)
    if content:
        try:
            alarm_data = json.loads(content)
            if alarm_data and 'alarms' in alarm_data and alarm_data['alarms']:
                print(f"\n{colors.red}ETCD Alarms:{colors.reset}")
                for alarm in alarm_data['alarms']:
                    print(f"  {colors.red}⚠ {alarm}{colors.reset}")
            else:
                print(f"\n{colors.green}No ETCD alarms{colors.reset}")
        except (json.JSONDecodeError, ValueError):
            pass

    print_section_footer(colors)


def show_cluster_info(sosreport_path, colors):
    """Show OCP cluster overview information"""
    print_section_header("OpenShift Cluster Information", colors)

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
            print(f"\n{colors.cyan}Container Runtime:{colors.reset}")
            for line in content.splitlines()[:20]:
                if '"version"' in line.lower() or '"runtimeVersion"' in line.lower():
                    print(f"  {line.strip()}")

    # Read CRI-O version
    crio_version_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_version")
    if os.path.exists(crio_version_path):
        content = read_file(crio_version_path)
        if content:
            print(f"\n{colors.cyan}CRI-O Version:{colors.reset}")
            for line in content.splitlines():
                print(f"  {line.strip()}")

    # Read hostname
    hostname_path = os.path.join(sosreport_path, "hostname")
    if os.path.exists(hostname_path):
        hostname = read_file(hostname_path).strip()
        print(f"\n{colors.cyan}Node Hostname:{colors.reset} {hostname}")

    # Read RHCOS version
    rhcos_path = os.path.join(sosreport_path, "sos_commands/rhcos/rpm-ostree_status")
    if os.path.exists(rhcos_path):
        lines = read_lines(rhcos_path)
        print(f"\n{colors.cyan}RHCOS Version:{colors.reset}")
        for line in lines[:10]:
            if "Version:" in line or "Commit:" in line:
                print(f"  {line.strip()}")

    print_section_footer(colors)


def show_pods_info(sosreport_path, options, colors):
    """Show pod information"""
    crictl_pods_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_pods")

    if not os.path.exists(crictl_pods_path):
        print(f"{colors.red}Error: crictl pods output not found{colors.reset}")
        return

    lines = read_lines(crictl_pods_path)
    if not lines:
        print(f"{colors.red}Error: crictl pods output is empty{colors.reset}")
        return

    # Parse header
    header = lines[0] if lines else ""
    data_lines = lines[1:]

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        data_lines = [line for line in data_lines if options.namespace in line]

    # Filter by state if specified
    if hasattr(options, 'state') and options.state:
        data_lines = [line for line in data_lines if options.state in line]

    # Filter by pattern if specified (case-insensitive)
    if hasattr(options, 'filter') and options.filter:
        data_lines = [line for line in data_lines if options.filter.lower() in line.lower()]

    print(f"{colors.blue}{'=' * 80}{colors.reset}")
    print(f"{colors.blue}Pod Information ({len(data_lines)} pods){colors.reset}")
    print(f"{colors.blue}{'=' * 80}{colors.reset}\n")

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
    if not (hasattr(options, 'detail') and options.detail):
        print(f"{colors.cyan}Pods by State:{colors.reset}")
        for state in sorted(state_counts.keys()):
            count = state_counts[state]
            color = colors.green if state == PodStates.READY else colors.yellow if state == PodStates.NOT_READY else colors.red
            print(f"  {color}{state:15s}{colors.reset}: {count:4d}")

        print(f"\n{colors.cyan}Pods by Namespace (top 10):{colors.reset}")
        for namespace, count in sorted(namespace_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {namespace:40s}: {count:4d}")

    # Show detailed list if requested
    if hasattr(options, 'detail') and options.detail:
        print(f"\n{colors.cyan}{header}{colors.reset}")
        print("-" * 80)

        count = 0
        for line in data_lines:
            if hasattr(options, 'limit') and options.limit and count >= options.limit:
                remaining = len(data_lines) - count
                print(f"\n{colors.yellow}... and {remaining} more pods{colors.reset}")
                break

            # Color based on state
            match = re.search(r'\s+(Ready|NotReady|Running|Exited|Created|Paused)\s+', line)
            if match:
                state = match.group(1)
                if state == PodStates.READY or state == PodStates.RUNNING:
                    print(f"{colors.green}{line}{colors.reset}")
                elif state == PodStates.NOT_READY:
                    print(f"{colors.yellow}{line}{colors.reset}")
                else:
                    print(line)
            else:
                print(line)
            count += 1

    print(f"\n{colors.blue}{'=' * 80}{colors.reset}\n")


def show_containers_info(sosreport_path, options, colors):
    """Show container information"""
    crictl_ps_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_ps_-a")

    if not os.path.exists(crictl_ps_path):
        # Try without -a flag
        crictl_ps_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_ps")
        if not os.path.exists(crictl_ps_path):
            print(f"{colors.red}Error: crictl ps output not found{colors.reset}")
            return

    lines = read_lines(crictl_ps_path)
    if not lines:
        print(f"{colors.red}Error: crictl ps output is empty{colors.reset}")
        return

    header = lines[0] if lines else ""
    data_lines = lines[1:]

    # Filter by pattern if specified (case-insensitive)
    if hasattr(options, 'filter') and options.filter:
        data_lines = [line for line in data_lines if options.filter.lower() in line.lower()]

    print(f"{colors.blue}{'=' * 80}{colors.reset}")
    print(f"{colors.blue}Container Information ({len(data_lines)} containers){colors.reset}")
    print(f"{colors.blue}{'=' * 80}{colors.reset}\n")

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

    print(f"{colors.cyan}Containers by State:{colors.reset}")
    for state in sorted(state_counts.keys()):
        count = state_counts[state]
        color = colors.green if state == PodStates.RUNNING else colors.yellow if state == PodStates.EXITED else colors.red
        print(f"  {color}{state:15s}{colors.reset}: {count:4d}")

    # Show detailed list if requested
    if hasattr(options, 'detail') and options.detail:
        print(f"\n{colors.cyan}{header}{colors.reset}")
        print("-" * 80)

        count = 0
        for line in data_lines:
            if hasattr(options, 'limit') and options.limit and count >= options.limit:
                remaining = len(data_lines) - count
                print(f"\n{colors.yellow}... and {remaining} more containers{colors.reset}")
                break

            # Color based on state
            match = re.search(r'\s+(Running|Exited|Created|Paused|Unknown)\s+', line)
            if match:
                state = match.group(1)
                if state == PodStates.RUNNING:
                    print(f"{colors.green}{line}{colors.reset}")
                else:
                    print(f"{colors.yellow}{line}{colors.reset}")
            else:
                print(line)
            count += 1

    print(f"\n{colors.blue}{'=' * 80}{colors.reset}\n")


def show_images_info(sosreport_path, options, colors):
    """Show container images information"""
    crictl_images_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_images")

    if not os.path.exists(crictl_images_path):
        print(f"{colors.red}Error: crictl images output not found{colors.reset}")
        return

    lines = read_lines(crictl_images_path)
    if not lines:
        print(f"{colors.red}Error: crictl images output is empty{colors.reset}")
        return

    header = lines[0] if lines else ""
    data_lines = lines[1:]

    # Filter by pattern if specified (case-insensitive)
    if hasattr(options, 'filter') and options.filter:
        data_lines = [line for line in data_lines if options.filter.lower() in line.lower()]

    print(f"{colors.blue}{'=' * 80}{colors.reset}")
    print(f"{colors.blue}Container Images ({len(data_lines)} images){colors.reset}")
    print(f"{colors.blue}{'=' * 80}{colors.reset}\n")

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
            except (ValueError, AttributeError):
                pass

    print(f"{colors.cyan}Total Images Size:{colors.reset} {format_bytes(total_size, precision=1)}")

    if options.detail:
        print(f"\n{colors.cyan}{header}{colors.reset}")
        print("-" * 80)

        count = 0
        for line in data_lines:
            if options.limit and count >= options.limit:
                remaining = len(data_lines) - count
                print(f"\n{colors.yellow}... and {remaining} more images{colors.reset}")
                break
            print(line)
            count += 1

    print(f"\n{colors.blue}{'=' * 80}{colors.reset}\n")


def show_resource_stats(sosreport_path, colors):
    """Show container resource statistics"""
    crictl_stats_path = os.path.join(sosreport_path, "sos_commands/crio/crictl_stats")

    if not os.path.exists(crictl_stats_path):
        print(f"{colors.yellow}Warning: crictl stats output not found{colors.reset}")
        return

    lines = read_lines(crictl_stats_path)
    if not lines:
        return

    print_section_header("Container Resource Statistics", colors)

    # Show top consumers
    print(f"{colors.cyan}Top Resource Consumers:{colors.reset}\n")

    for line in lines[:20]:  # Show first 20 lines including header
        print(line)

    print_section_footer(colors)


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

    # Must-gather features (requires must-gather archive)
    # Show cluster version
    > ocpinfo --version

    # Show cluster operators status
    > ocpinfo --operators

    # Show detailed operators list
    > ocpinfo --operators -d

    # Filter degraded operators
    > ocpinfo --operators --state Degraded

    # Show ETCD cluster health
    > ocpinfo --etcd
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
    op.add_option("--version", dest="show_version", default=False,
                  action="store_true",
                  help="Show cluster version (must-gather)")
    op.add_option("--operators", dest="operators", default=False,
                  action="store_true",
                  help="Show cluster operators status (must-gather)")
    op.add_option("--etcd", dest="etcd", default=False,
                  action="store_true",
                  help="Show ETCD cluster health (must-gather)")

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        return print_help_msg(op, no_pipe)

    # Create color manager
    colors = ColorManager(no_pipe)

    # Detect data sources
    base_path = os.getcwd()
    sources = detect_data_sources(base_path)

    # Check what data is available
    must_gather_root = sources.get('must-gather-root')
    sosreport_available = sources.get('sosreport', False)
    must_gather_available = sources.get('must-gather', False)

    # Handle must-gather specific options
    if o.show_version or o.operators or o.etcd:
        if not must_gather_available:
            # Determine what's available and provide helpful message
            print(f"{colors.red}Error: Must-gather options not available{colors.reset}")
            print()

            # Build list of requested options
            requested = []
            if o.show_version:
                requested.append("--version")
            if o.operators:
                requested.append("--operators")
            if o.etcd:
                requested.append("--etcd")

            print(f"Requested option(s): {', '.join(requested)}")
            print(f"{colors.yellow}These options require a must-gather archive{colors.reset}")
            print()

            if sosreport_available:
                # In sosreport - show available options
                print(f"{colors.cyan}You are in a sosreport directory:{colors.reset}")
                print(f"  {base_path}")
                print()
                print(f"{colors.green}Available sosreport options:{colors.reset}")
                print("  ocpinfo              - Show cluster overview")
                print("  ocpinfo -p           - Show pods")
                print("  ocpinfo -c           - Show containers")
                print("  ocpinfo -i           - Show images")
                print("  ocpinfo -s           - Show resource stats")
                print("  ocpinfo -a           - Show all information")
            else:
                # Not in any OCP directory
                print(f"{colors.yellow}Current directory:{colors.reset} {base_path}")
                print()
                print("Please run this command from within a must-gather archive directory")

            return ""

        # Show requested must-gather information
        if o.show_version:
            show_cluster_version(must_gather_root, colors)

        if o.operators:
            show_cluster_operators(must_gather_root, o, colors)

        if o.etcd:
            show_etcd_health(must_gather_root, colors)

        return ""

    # Handle sosreport options (pods, containers, images, stats)
    if o.pods or o.containers or o.images or o.stats or o.all:
        if not sosreport_available:
            # Determine what's available and provide helpful message
            print(f"{colors.red}Error: Sosreport options not available{colors.reset}")
            print()

            # Build list of requested options
            requested = []
            if o.pods:
                requested.append("-p/--pods")
            if o.containers:
                requested.append("-c/--containers")
            if o.images:
                requested.append("-i/--images")
            if o.stats:
                requested.append("-s/--stats")
            if o.all:
                requested.append("-a/--all")

            print(f"Requested option(s): {', '.join(requested)}")
            print(f"{colors.yellow}These options require a sosreport directory{colors.reset}")
            print()

            if must_gather_available:
                # In must-gather - show available options
                print(f"{colors.cyan}You are in a must-gather directory:{colors.reset}")
                print(f"  {base_path}")
                print()
                print(f"{colors.green}Available must-gather options:{colors.reset}")
                print("  ocpinfo              - Show cluster version")
                print("  ocpinfo --version    - Show cluster version")
                print("  ocpinfo --operators  - Show cluster operators status")
                print("  ocpinfo --etcd       - Show ETCD cluster health")
            else:
                # Not in any OCP directory
                print(f"{colors.yellow}Current directory:{colors.reset} {base_path}")
                print()
                print("Please run this command from within a sosreport directory")

            return ""

        sosreport_path = base_path

        # Show all if requested
        if o.all:
            show_cluster_info(sosreport_path, colors)
            show_pods_info(sosreport_path, o, colors)
            show_containers_info(sosreport_path, o, colors)
            show_images_info(sosreport_path, o, colors)
            show_resource_stats(sosreport_path, colors)
            return ""

        # Show specific information
        if o.pods:
            show_pods_info(sosreport_path, o, colors)

        if o.containers:
            show_containers_info(sosreport_path, o, colors)

        if o.images:
            show_images_info(sosreport_path, o, colors)

        if o.stats:
            show_resource_stats(sosreport_path, colors)

        return ""

    # No specific option - show cluster overview
    # Prefer must-gather if available, otherwise sosreport
    if must_gather_available:
        show_cluster_version(must_gather_root, colors)
    elif sosreport_available:
        show_cluster_info(base_path, colors)
    else:
        print(f"{colors.red}Error: No OCP data found{colors.reset}")
        print()
        print(f"{colors.yellow}Current directory:{colors.reset} {base_path}")
        print()
        print("This command requires either:")
        print(f"  {colors.cyan}• A sosreport directory{colors.reset} (contains 'sos_commands/' subdirectory)")
        print(f"  {colors.cyan}• A must-gather directory{colors.reset} (contains 'quay-io-*' or 'must-gather*' subdirectory)")
        print()
        print("Please navigate to a sosreport or must-gather directory and try again.")

    return ""


if __name__ == "__main__":
    # For testing
    def dummy_is_stopped():
        return False
    run_ocpinfo(" ".join(sys.argv[1:]), {}, dummy_is_stopped, False, True)
