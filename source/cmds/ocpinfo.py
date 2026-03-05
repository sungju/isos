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
import yaml
from optparse import OptionParser
from io import StringIO
from datetime import datetime

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


class InspectPaths:
    """Centralized inspect data path definitions"""
    def __init__(self, root):
        self.root = root
        self.namespaces_dir = os.path.join(root, "namespaces")

    def namespace_dir(self, namespace):
        return os.path.join(self.namespaces_dir, namespace)

    def namespace_file(self, namespace, resource_type, resource_file):
        """Get path to a resource file in a namespace

        Args:
            namespace: Namespace name
            resource_type: Resource type directory (e.g., 'core', 'apps')
            resource_file: Resource filename (e.g., 'pods.yaml', 'events.yaml')
        """
        return os.path.join(self.namespaces_dir, namespace, resource_type, resource_file)

    def pods_dir(self, namespace):
        return os.path.join(self.namespaces_dir, namespace, "pods")

    def pod_logs_dir(self, namespace, pod_name, container_name):
        return os.path.join(self.namespaces_dir, namespace, "pods", pod_name,
                          container_name, container_name, "logs")


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


def find_inspect_root(base_path=None):
    """Find inspect root directory"""
    if base_path is None:
        base_path = os.getcwd()

    # Check for namespaces directory (key indicator of inspect data)
    namespaces_dir = os.path.join(base_path, 'namespaces')
    if os.path.isdir(namespaces_dir):
        # Verify it's inspect data by checking for timestamp file
        if os.path.exists(os.path.join(base_path, 'timestamp')):
            return base_path

    # Check subdirectories for inspect.local.* pattern
    try:
        for item in os.listdir(base_path):
            if item.startswith('inspect.local'):
                full_path = os.path.join(base_path, item)
                if os.path.isdir(full_path):
                    namespaces_dir = os.path.join(full_path, 'namespaces')
                    if os.path.isdir(namespaces_dir):
                        return full_path
    except (IOError, OSError):
        pass

    return None


def detect_data_sources(base_path=None):
    """Detect available data sources (sosreport, must-gather, and/or inspect)

    Returns:
        dict with keys: 'sosreport', 'must-gather', 'must-gather-root', 'inspect', 'inspect-root'
    """
    if base_path is None:
        base_path = os.getcwd()

    must_gather_path = find_must_gather_root(base_path)
    inspect_path = find_inspect_root(base_path)

    sources = {
        'sosreport': os.path.exists(os.path.join(base_path, 'sos_commands')),
        'must-gather': must_gather_path is not None,
        'must-gather-root': must_gather_path,
        'inspect': inspect_path is not None,
        'inspect-root': inspect_path
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


def get_inspect_namespaces(inspect_root):
    """Get list of namespaces in inspect data

    Returns:
        List of namespace names
    """
    paths = InspectPaths(inspect_root)
    namespaces = []

    try:
        if os.path.isdir(paths.namespaces_dir):
            for item in os.listdir(paths.namespaces_dir):
                ns_path = os.path.join(paths.namespaces_dir, item)
                if os.path.isdir(ns_path):
                    namespaces.append(item)
    except (IOError, OSError):
        pass

    return sorted(namespaces)


def load_yaml_resources(filepath):
    """Load YAML resources from file (handles multi-document YAML and List objects)

    Returns:
        List of resource dicts
    """
    content = read_file(filepath)
    if not content:
        return []

    try:
        # Handle multi-document YAML
        documents = list(yaml.safe_load_all(content))
        resources = []

        for doc in documents:
            if not doc or not isinstance(doc, dict):
                continue

            # Check if this is a List object (kind ends with 'List' and has 'items' field)
            # Examples: List, PodList, EventList, DeploymentList, etc.
            kind = doc.get('kind', '')
            if kind.endswith('List') and 'items' in doc:
                # Extract items from List
                resources.extend(doc['items'])
            else:
                # Regular resource
                resources.append(doc)

        return resources
    except yaml.YAMLError:
        return []


def show_inspect_namespaces(inspect_root, colors):
    """Show namespaces in inspect data"""
    print_section_header("Namespaces in Inspect Data", colors)

    namespaces = get_inspect_namespaces(inspect_root)

    if not namespaces:
        print(f"{colors.yellow}No namespaces found{colors.reset}")
        print_section_footer(colors)
        return

    print(f"{colors.cyan}Total Namespaces: {len(namespaces)}{colors.reset}\n")

    # Count resources in each namespace
    paths = InspectPaths(inspect_root)

    # Print header
    print(f"{colors.cyan}{'Namespace':<40} {'Pods':<8} {'Services':<10} {'Deployments':<12}{colors.reset}")
    print("-" * 80)

    for ns in namespaces:
        # Count pods
        pods_file = paths.namespace_file(ns, "core", "pods.yaml")
        pods = load_yaml_resources(pods_file)
        pod_count = len([p for p in pods if p.get('kind') == 'Pod'])

        # Count services
        svc_file = paths.namespace_file(ns, "core", "services.yaml")
        services = load_yaml_resources(svc_file)
        svc_count = len([s for s in services if s.get('kind') == 'Service'])

        # Count deployments
        deploy_file = paths.namespace_file(ns, "apps", "deployments.yaml")
        deployments = load_yaml_resources(deploy_file)
        deploy_count = len([d for d in deployments if d.get('kind') == 'Deployment'])

        print(f"{ns:<40} {pod_count:<8} {svc_count:<10} {deploy_count:<12}")

    print_section_footer(colors)


def show_inspect_events(inspect_root, options, colors):
    """Show events from inspect data"""
    print_section_header("Events", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    all_events = []

    # Load events from all namespaces
    for ns in namespaces:
        events_file = paths.namespace_file(ns, "core", "events.yaml")
        events = load_yaml_resources(events_file)

        for event in events:
            if event.get('kind') == 'Event':
                event['_namespace'] = ns
                all_events.append(event)

    if not all_events:
        print(f"{colors.yellow}No events found{colors.reset}")
        print_section_footer(colors)
        return

    # Filter by type if specified
    if hasattr(options, 'event_type') and options.event_type:
        all_events = [e for e in all_events if e.get('type') == options.event_type]

    # Filter by pattern if specified
    if hasattr(options, 'filter') and options.filter:
        filter_lower = options.filter.lower()
        all_events = [e for e in all_events if
                     filter_lower in e.get('message', '').lower() or
                     filter_lower in e.get('reason', '').lower() or
                     filter_lower in e.get('_namespace', '').lower()]

    # Sort by last timestamp (most recent first)
    all_events.sort(key=lambda e: e.get('lastTimestamp', ''), reverse=True)

    # Count by type
    warning_count = sum(1 for e in all_events if e.get('type') == 'Warning')
    normal_count = sum(1 for e in all_events if e.get('type') == 'Normal')

    print(f"{colors.cyan}Total Events: {len(all_events)}{colors.reset}")
    print(f"  {colors.red}Warnings: {warning_count}{colors.reset}")
    print(f"  {colors.green}Normal: {normal_count}{colors.reset}\n")

    # Apply limit
    limit = options.limit if hasattr(options, 'limit') and options.limit else 20
    display_events = all_events[:limit]

    print(f"{colors.cyan}Recent Events (showing {len(display_events)}):{colors.reset}\n")

    for event in display_events:
        event_type = event.get('type', 'Unknown')
        count = event.get('count', 1)
        reason = event.get('reason', 'Unknown')
        message = event.get('message', '')
        last_time = event.get('lastTimestamp', 'Unknown')
        involved = event.get('involvedObject', {})
        obj_kind = involved.get('kind', 'Unknown')
        obj_name = involved.get('name', 'Unknown')
        namespace = event.get('_namespace', 'Unknown')

        # Color based on type
        type_color = colors.red if event_type == 'Warning' else colors.green

        print(f"{type_color}{event_type:<10}{colors.reset} ", end='')
        print(f"Count: {count:<6} Age: {last_time[:19] if len(last_time) >= 19 else last_time:<19}")
        print(f"  Reason: {reason}")
        print(f"  Object: {obj_kind}/{obj_name} (ns: {namespace})")
        print(f"  Message: {message}")
        print()

    if len(all_events) > limit:
        remaining = len(all_events) - limit
        print(f"{colors.yellow}... and {remaining} more events{colors.reset}")

    print_section_footer(colors)


def show_inspect_pods(inspect_root, options, colors):
    """Show pods from inspect data"""
    print_section_header("Pods", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    all_pods = []

    # Load pods from all namespaces
    for ns in namespaces:
        pods_file = paths.namespace_file(ns, "core", "pods.yaml")
        pods = load_yaml_resources(pods_file)

        for pod in pods:
            if pod.get('kind') == 'Pod':
                pod['_namespace'] = ns
                all_pods.append(pod)

    # Filter by pattern if specified
    if hasattr(options, 'filter') and options.filter:
        filter_lower = options.filter.lower()
        all_pods = [p for p in all_pods if
                   filter_lower in p.get('metadata', {}).get('name', '').lower() or
                   filter_lower in p.get('_namespace', '').lower()]

    # Filter by phase if specified
    if hasattr(options, 'state') and options.state:
        all_pods = [p for p in all_pods if
                   p.get('status', {}).get('phase') == options.state]

    if not all_pods:
        print(f"{colors.yellow}No pods found{colors.reset}")
        print_section_footer(colors)
        return

    print(f"{colors.cyan}Total Pods: {len(all_pods)}{colors.reset}\n")

    # Count by phase
    phase_counts = {}
    restart_counts = {'0': 0, '1-5': 0, '>5': 0}

    for pod in all_pods:
        phase = pod.get('status', {}).get('phase', 'Unknown')
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

        # Count restarts
        containers = pod.get('status', {}).get('containerStatuses', [])
        total_restarts = sum(c.get('restartCount', 0) for c in containers)

        if total_restarts == 0:
            restart_counts['0'] += 1
        elif total_restarts <= 5:
            restart_counts['1-5'] += 1
        else:
            restart_counts['>5'] += 1

    print(f"{colors.cyan}Pods by Phase:{colors.reset}")
    for phase in sorted(phase_counts.keys()):
        count = phase_counts[phase]
        color = colors.green if phase == 'Running' else colors.yellow if phase == 'Pending' else colors.red
        print(f"  {color}{phase:15s}{colors.reset}: {count:4d}")

    print(f"\n{colors.cyan}Pods by Restart Count:{colors.reset}")
    print(f"  0 restarts   : {restart_counts['0']:4d}")
    print(f"  1-5 restarts : {restart_counts['1-5']:4d}")
    print(f"  >5 restarts  : {restart_counts['>5']:4d}")

    # Show detailed list if requested
    if hasattr(options, 'detail') and options.detail:
        print(f"\n{colors.cyan}{'Pod Name':<50} {'Namespace':<20} {'Phase':<12} {'Restarts':<8}{colors.reset}")
        print("-" * 100)

        limit = options.limit if hasattr(options, 'limit') and options.limit else len(all_pods)
        count = 0

        for pod in all_pods:
            if count >= limit:
                remaining = len(all_pods) - count
                print(f"\n{colors.yellow}... and {remaining} more pods{colors.reset}")
                break

            name = pod.get('metadata', {}).get('name', 'Unknown')[:49]
            namespace = pod.get('_namespace', 'Unknown')[:19]
            phase = pod.get('status', {}).get('phase', 'Unknown')

            # Calculate total restarts
            containers = pod.get('status', {}).get('containerStatuses', [])
            total_restarts = sum(c.get('restartCount', 0) for c in containers)

            # Color based on phase
            phase_color = colors.green if phase == 'Running' else colors.yellow if phase == 'Pending' else colors.red

            print(f"{name:<50} {namespace:<20} {phase_color}{phase:<12}{colors.reset} {total_restarts:<8}")
            count += 1

    print_section_footer(colors)


def show_inspect_logs(inspect_root, options, colors):
    """Show available pod logs from inspect data or display log content"""

    # Check if user wants to view log content
    show_content = hasattr(options, 'show_logs') and options.show_logs

    if show_content:
        # Show log content mode
        show_inspect_log_content(inspect_root, options, colors)
        return

    # List available logs mode
    print_section_header("Available Pod Logs", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    # Filter by pod name if specified
    pod_filter = options.filter.lower() if hasattr(options, 'filter') and options.filter else None

    total_logs = 0

    for ns in namespaces:
        pods_dir = paths.pods_dir(ns)

        if not os.path.isdir(pods_dir):
            continue

        try:
            pod_names = os.listdir(pods_dir)
        except (IOError, OSError):
            continue

        # Filter pod names
        if pod_filter:
            pod_names = [p for p in pod_names if pod_filter in p.lower()]

        for pod_name in sorted(pod_names):
            pod_dir = os.path.join(pods_dir, pod_name)
            if not os.path.isdir(pod_dir):
                continue

            # Find container directories
            try:
                containers = os.listdir(pod_dir)
            except (IOError, OSError):
                continue

            pod_has_logs = False

            for container in sorted(containers):
                logs_dir = paths.pod_logs_dir(ns, pod_name, container)

                if not os.path.isdir(logs_dir):
                    continue

                # Check for log files
                try:
                    log_files = os.listdir(logs_dir)
                except (IOError, OSError):
                    continue

                if not log_files:
                    continue

                # Print pod header once
                if not pod_has_logs:
                    print(f"{colors.green}Pod: {pod_name}{colors.reset} (ns: {ns})")
                    pod_has_logs = True

                print(f"  {colors.cyan}Container: {container}{colors.reset}")

                for log_file in sorted(log_files):
                    log_path = os.path.join(logs_dir, log_file)
                    if os.path.isfile(log_path):
                        size = os.path.getsize(log_path)
                        print(f"    ✓ {log_file} ({format_bytes(size, precision=1)})")
                        total_logs += 1

            if pod_has_logs:
                print()

    if total_logs == 0:
        print(f"{colors.yellow}No log files found{colors.reset}")
    else:
        print(f"{colors.cyan}Total log files: {total_logs}{colors.reset}")
        print()
        print(f"{colors.cyan}Tip: Use --show to view log content{colors.reset}")
        print(f"  Example: ocpinfo --logs -f <pod-name> --show")

    print_section_footer(colors)


def show_inspect_log_content(inspect_root, options, colors):
    """Display actual log content for a pod"""

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    # Pod filter is required for --show
    pod_filter = options.filter.lower() if hasattr(options, 'filter') and options.filter else None

    if not pod_filter:
        print(f"{colors.red}Error: Pod name filter required with --show{colors.reset}")
        print()
        print(f"{colors.yellow}Usage:{colors.reset}")
        print(f"  ocpinfo --logs -f <pod-name> --show")
        print(f"  ocpinfo --logs -f <pod-name> --show --container <container>")
        print(f"  ocpinfo --logs -f <pod-name> --show --tail 200")
        print(f"  ocpinfo --logs -f <pod-name> --show --previous")
        return

    # Find matching pods
    matching_pods = []

    for ns in namespaces:
        pods_dir = paths.pods_dir(ns)
        if not os.path.isdir(pods_dir):
            continue

        try:
            pod_names = os.listdir(pods_dir)
        except (IOError, OSError):
            continue

        # Filter pod names
        for pod_name in pod_names:
            if pod_filter in pod_name.lower():
                matching_pods.append((ns, pod_name))

    if not matching_pods:
        print(f"{colors.red}Error: No pods found matching '{options.filter}'{colors.reset}")
        return

    # If multiple pods match and no exact match, list them
    exact_matches = [p for p in matching_pods if p[1].lower() == pod_filter]
    if len(matching_pods) > 1 and not exact_matches:
        print(f"{colors.yellow}Multiple pods match '{options.filter}':{colors.reset}")
        print()
        for ns, pod_name in matching_pods:
            print(f"  - {pod_name} (ns: {ns})")
        print()
        print(f"{colors.cyan}Please be more specific or use exact pod name{colors.reset}")
        return

    # Use exact match if found, otherwise use the single match
    if exact_matches:
        ns, pod_name = exact_matches[0]
    else:
        ns, pod_name = matching_pods[0]

    # Get container filter if specified
    container_filter = options.container.lower() if hasattr(options, 'container') and options.container else None

    # Determine log file to show
    log_filename = "previous.log" if hasattr(options, 'previous_log') and options.previous_log else "current.log"

    # Get tail lines
    tail_lines = options.tail_lines if hasattr(options, 'tail_lines') and options.tail_lines else 100

    # Find containers for this pod
    pod_dir = os.path.join(paths.pods_dir(ns), pod_name)
    try:
        containers = os.listdir(pod_dir)
    except (IOError, OSError):
        print(f"{colors.red}Error: Cannot read pod directory{colors.reset}")
        return

    # Filter containers if specified
    if container_filter:
        containers = [c for c in containers if container_filter in c.lower()]

    if not containers:
        if container_filter:
            print(f"{colors.red}Error: No container found matching '{options.container}'{colors.reset}")
        else:
            print(f"{colors.red}Error: No containers found in pod{colors.reset}")
        return

    # If multiple containers and no filter, list them
    if len(containers) > 1 and not container_filter:
        print(f"{colors.yellow}Multiple containers in pod '{pod_name}':{colors.reset}")
        print()
        for container in sorted(containers):
            logs_dir = paths.pod_logs_dir(ns, pod_name, container)
            if os.path.isdir(logs_dir):
                log_path = os.path.join(logs_dir, log_filename)
                size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
                print(f"  - {container} ({log_filename}: {format_bytes(size, precision=1)})")
        print()
        print(f"{colors.cyan}Specify container with --container option:{colors.reset}")
        print(f"  ocpinfo --logs -f {pod_name} --show --container <container-name>")
        return

    # Show log content for the container
    container = containers[0]
    logs_dir = paths.pod_logs_dir(ns, pod_name, container)
    log_path = os.path.join(logs_dir, log_filename)

    if not os.path.exists(log_path):
        print(f"{colors.red}Error: Log file not found: {log_filename}{colors.reset}")
        print(f"  Pod: {pod_name}")
        print(f"  Container: {container}")
        return

    log_size = os.path.getsize(log_path)

    if log_size == 0:
        print(f"{colors.yellow}Log file is empty{colors.reset}")
        print(f"  Pod: {pod_name}")
        print(f"  Namespace: {ns}")
        print(f"  Container: {container}")
        print(f"  File: {log_filename}")
        return

    # Display log header
    print_section_header(f"Pod Log: {pod_name}", colors)
    print(f"{colors.cyan}Namespace:{colors.reset} {ns}")
    print(f"{colors.cyan}Container:{colors.reset} {container}")
    print(f"{colors.cyan}Log File:{colors.reset} {log_filename}")
    print(f"{colors.cyan}Size:{colors.reset} {format_bytes(log_size, precision=1)}")
    print(f"{colors.cyan}Showing:{colors.reset} Last {tail_lines} lines")
    print(f"{colors.blue}{'=' * 80}{colors.reset}\n")

    # Read and display log content
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Get last N lines
        if tail_lines > 0 and len(lines) > tail_lines:
            display_lines = lines[-tail_lines:]
            skipped = len(lines) - tail_lines
            print(f"{colors.yellow}... (skipped {skipped} earlier lines) ...{colors.reset}\n")
        else:
            display_lines = lines

        # Display lines
        for line in display_lines:
            line = line.rstrip('\n')

            # Color code based on log level
            line_lower = line.lower()
            if 'error' in line_lower or 'fail' in line_lower or 'fatal' in line_lower:
                print(f"{colors.red}{line}{colors.reset}")
            elif 'warn' in line_lower:
                print(f"{colors.yellow}{line}{colors.reset}")
            elif 'info' in line_lower:
                print(f"{colors.cyan}{line}{colors.reset}")
            else:
                print(line)

    except (IOError, OSError) as e:
        print(f"{colors.red}Error reading log file: {e}{colors.reset}")
        return

    print_section_footer(colors)


def show_inspect_deployments(inspect_root, options, colors):
    """Show deployments and statefulsets from inspect data"""
    print_section_header("Deployments and StatefulSets", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    all_workloads = []

    # Load deployments and statefulsets from all namespaces
    for ns in namespaces:
        # Load deployments
        deploy_file = paths.namespace_file(ns, "apps", "deployments.yaml")
        deployments = load_yaml_resources(deploy_file)
        for d in deployments:
            if d.get('kind') == 'Deployment':
                d['_namespace'] = ns
                d['_type'] = 'Deployment'
                all_workloads.append(d)

        # Load statefulsets
        sts_file = paths.namespace_file(ns, "apps", "statefulsets.yaml")
        statefulsets = load_yaml_resources(sts_file)
        for s in statefulsets:
            if s.get('kind') == 'StatefulSet':
                s['_namespace'] = ns
                s['_type'] = 'StatefulSet'
                all_workloads.append(s)

        # Load daemonsets
        ds_file = paths.namespace_file(ns, "apps", "daemonsets.yaml")
        daemonsets = load_yaml_resources(ds_file)
        for ds in daemonsets:
            if ds.get('kind') == 'DaemonSet':
                ds['_namespace'] = ns
                ds['_type'] = 'DaemonSet'
                all_workloads.append(ds)

    # Filter by pattern if specified
    if hasattr(options, 'filter') and options.filter:
        filter_lower = options.filter.lower()
        all_workloads = [w for w in all_workloads if
                        filter_lower in w.get('metadata', {}).get('name', '').lower() or
                        filter_lower in w.get('_namespace', '').lower()]

    if not all_workloads:
        print(f"{colors.yellow}No deployments or statefulsets found{colors.reset}")
        print_section_footer(colors)
        return

    print(f"{colors.cyan}Total Workloads: {len(all_workloads)}{colors.reset}\n")

    # Count by type
    type_counts = {}
    for w in all_workloads:
        wtype = w.get('_type', 'Unknown')
        type_counts[wtype] = type_counts.get(wtype, 0) + 1

    print(f"{colors.cyan}Workloads by Type:{colors.reset}")
    for wtype in sorted(type_counts.keys()):
        print(f"  {wtype:15s}: {type_counts[wtype]:4d}")

    # Show detailed list
    print(f"\n{colors.cyan}{'Type':<15} {'Name':<40} {'Namespace':<20} {'Replicas':<10}{colors.reset}")
    print("-" * 100)

    limit = options.limit if hasattr(options, 'limit') and options.limit else len(all_workloads)
    count = 0

    for workload in all_workloads:
        if count >= limit:
            remaining = len(all_workloads) - count
            print(f"\n{colors.yellow}... and {remaining} more workloads{colors.reset}")
            break

        wtype = workload.get('_type', 'Unknown')
        name = workload.get('metadata', {}).get('name', 'Unknown')[:39]
        namespace = workload.get('_namespace', 'Unknown')[:19]

        # Get replica info
        spec = workload.get('spec', {})
        desired = spec.get('replicas', 0)
        status = workload.get('status', {})
        ready = status.get('readyReplicas', 0)

        replicas_str = f"{ready}/{desired}"
        replicas_color = colors.green if ready == desired else colors.yellow

        print(f"{wtype:<15} {name:<40} {namespace:<20} {replicas_color}{replicas_str:<10}{colors.reset}")
        count += 1

    print_section_footer(colors)


def show_inspect_services(inspect_root, options, colors):
    """Show services and routes from inspect data"""
    print_section_header("Services and Routes", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    all_services = []

    # Load services from all namespaces
    for ns in namespaces:
        # Load services
        svc_file = paths.namespace_file(ns, "core", "services.yaml")
        services = load_yaml_resources(svc_file)
        for s in services:
            if s.get('kind') == 'Service':
                s['_namespace'] = ns
                all_services.append(s)

    # Filter by pattern if specified
    if hasattr(options, 'filter') and options.filter:
        filter_lower = options.filter.lower()
        all_services = [s for s in all_services if
                       filter_lower in s.get('metadata', {}).get('name', '').lower() or
                       filter_lower in s.get('_namespace', '').lower()]

    if not all_services:
        print(f"{colors.yellow}No services found{colors.reset}")
        print_section_footer(colors)
        return

    print(f"{colors.cyan}Total Services: {len(all_services)}{colors.reset}\n")

    # Show detailed list
    print(f"{colors.cyan}{'Name':<40} {'Namespace':<20} {'Type':<15} {'ClusterIP':<20}{colors.reset}")
    print("-" * 100)

    limit = options.limit if hasattr(options, 'limit') and options.limit else len(all_services)
    count = 0

    for service in all_services:
        if count >= limit:
            remaining = len(all_services) - count
            print(f"\n{colors.yellow}... and {remaining} more services{colors.reset}")
            break

        name = service.get('metadata', {}).get('name', 'Unknown')[:39]
        namespace = service.get('_namespace', 'Unknown')[:19]
        spec = service.get('spec', {})
        svc_type = spec.get('type', 'Unknown')
        cluster_ip = spec.get('clusterIP', 'None')[:19]

        print(f"{name:<40} {namespace:<20} {svc_type:<15} {cluster_ip:<20}")
        count += 1

    print_section_footer(colors)


def show_inspect_resources(inspect_root, options, colors):
    """Show resource inventory from inspect data"""
    print_section_header("Resource Inventory", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    # Resource type to file mapping
    resource_types = {
        'Pods': ('core', 'pods.yaml'),
        'Services': ('core', 'services.yaml'),
        'Events': ('core', 'events.yaml'),
        'ConfigMaps': ('core', 'configmaps.yaml'),
        'Secrets': ('core', 'secrets.yaml'),
        'Endpoints': ('core', 'endpoints.yaml'),
        'PersistentVolumeClaims': ('core', 'persistentvolumeclaims.yaml'),
        'Deployments': ('apps', 'deployments.yaml'),
        'StatefulSets': ('apps', 'statefulsets.yaml'),
        'DaemonSets': ('apps', 'daemonsets.yaml'),
        'ReplicaSets': ('apps', 'replicasets.yaml'),
        'Jobs': ('batch', 'jobs.yaml'),
        'CronJobs': ('batch', 'cronjobs.yaml'),
        'Routes': ('route.openshift.io', 'routes.yaml'),
        'NetworkPolicies': ('networking.k8s.io', 'networkpolicies.yaml'),
    }

    # Count resources
    resource_counts = {rtype: 0 for rtype in resource_types.keys()}

    for ns in namespaces:
        for rtype, (res_dir, res_file) in resource_types.items():
            file_path = paths.namespace_file(ns, res_dir, res_file)
            resources = load_yaml_resources(file_path)
            resource_counts[rtype] += len([r for r in resources if r.get('kind') == rtype.rstrip('s') or
                                          r.get('kind') == rtype])

    print(f"{colors.cyan}{'Resource Type':<30} {'Count':<10}{colors.reset}")
    print("-" * 40)

    for rtype in sorted(resource_types.keys()):
        count = resource_counts[rtype]
        if count > 0:
            print(f"{rtype:<30} {count:<10}")

    print_section_footer(colors)


def show_inspect_pvc(inspect_root, options, colors):
    """Show PersistentVolumeClaims from inspect data"""
    print_section_header("PersistentVolumeClaims", colors)

    namespaces = get_inspect_namespaces(inspect_root)
    paths = InspectPaths(inspect_root)

    # Filter by namespace if specified
    if hasattr(options, 'namespace') and options.namespace:
        namespaces = [ns for ns in namespaces if ns == options.namespace]

    all_pvcs = []

    # Load PVCs from all namespaces
    for ns in namespaces:
        pvc_file = paths.namespace_file(ns, "core", "persistentvolumeclaims.yaml")
        pvcs = load_yaml_resources(pvc_file)
        for pvc in pvcs:
            if pvc.get('kind') == 'PersistentVolumeClaim':
                pvc['_namespace'] = ns
                all_pvcs.append(pvc)

    # Filter by pattern if specified
    if hasattr(options, 'filter') and options.filter:
        filter_lower = options.filter.lower()
        all_pvcs = [p for p in all_pvcs if
                   filter_lower in p.get('metadata', {}).get('name', '').lower() or
                   filter_lower in p.get('_namespace', '').lower()]

    if not all_pvcs:
        print(f"{colors.yellow}No PersistentVolumeClaims found{colors.reset}")
        print_section_footer(colors)
        return

    print(f"{colors.cyan}Total PVCs: {len(all_pvcs)}{colors.reset}\n")

    # Count by status
    status_counts = {}
    for pvc in all_pvcs:
        phase = pvc.get('status', {}).get('phase', 'Unknown')
        status_counts[phase] = status_counts.get(phase, 0) + 1

    print(f"{colors.cyan}PVCs by Status:{colors.reset}")
    for phase in sorted(status_counts.keys()):
        count = status_counts[phase]
        color = colors.green if phase == 'Bound' else colors.yellow
        print(f"  {color}{phase:15s}{colors.reset}: {count:4d}")

    # Show detailed list
    print(f"\n{colors.cyan}{'Name':<40} {'Namespace':<20} {'Status':<10} {'Capacity':<10}{colors.reset}")
    print("-" * 90)

    limit = options.limit if hasattr(options, 'limit') and options.limit else len(all_pvcs)
    count = 0

    for pvc in all_pvcs:
        if count >= limit:
            remaining = len(all_pvcs) - count
            print(f"\n{colors.yellow}... and {remaining} more PVCs{colors.reset}")
            break

        name = pvc.get('metadata', {}).get('name', 'Unknown')[:39]
        namespace = pvc.get('_namespace', 'Unknown')[:19]
        phase = pvc.get('status', {}).get('phase', 'Unknown')
        capacity = pvc.get('status', {}).get('capacity', {}).get('storage', 'Unknown')

        phase_color = colors.green if phase == 'Bound' else colors.yellow

        print(f"{name:<40} {namespace:<20} {phase_color}{phase:<10}{colors.reset} {capacity:<10}")
        count += 1

    print_section_footer(colors)


def print_help_msg(op, no_pipe, base_path=None):
    """Print help message following isos pattern - context-aware based on environment"""

    # Detect current environment
    if base_path is None:
        base_path = os.getcwd()

    sources = detect_data_sources(base_path)
    sosreport_available = sources.get('sosreport', False)
    must_gather_available = sources.get('must-gather', False)
    inspect_available = sources.get('inspect', False)

    # Determine which examples to show
    if sosreport_available:
        cmd_examples = '''
Examples (Sosreport):
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
    elif must_gather_available:
        cmd_examples = '''
Examples (Must-Gather):
    # Show cluster version (default)
    > ocpinfo

    # Show cluster version explicitly
    > ocpinfo --version

    # Show cluster operators status
    > ocpinfo --operators

    # Show detailed operators list
    > ocpinfo --operators -d

    # Filter degraded operators
    > ocpinfo --operators --state Degraded

    # Filter operators by name
    > ocpinfo --operators -f authentication -d

    # Show ETCD cluster health
    > ocpinfo --etcd

    # Show operators with limit
    > ocpinfo --operators -d -l 20
    '''
    elif inspect_available:
        cmd_examples = '''
Examples (Inspect):
    # List inspected namespaces (default)
    > ocpinfo

    # List namespaces explicitly
    > ocpinfo --namespaces

    # Show events (warnings and errors)
    > ocpinfo --events

    # Show only warnings
    > ocpinfo --events --type Warning

    # Show events in specific namespace
    > ocpinfo --events -n elastic-monitoring

    # Show events with limit
    > ocpinfo --events -l 20

    # Show pods from inspect data
    > ocpinfo --inspect-pods

    # Show pods with details
    > ocpinfo --inspect-pods -d

    # Filter pods by namespace
    > ocpinfo --inspect-pods -n elastic-monitoring

    # Filter pods by pattern
    > ocpinfo --inspect-pods -f monitoring

    # List available pod logs
    > ocpinfo --logs

    # List logs for specific pod
    > ocpinfo --logs -f stack-monitoring

    # View log content for a pod
    > ocpinfo --logs -f stack-monitoring-metric-0 --show

    # View log content for specific container
    > ocpinfo --logs -f stack-monitoring-es-default-0 --show --container elasticsearch

    # View last 200 lines of log
    > ocpinfo --logs -f stack-monitoring-kb --show --tail 200

    # View previous container log (from restart)
    > ocpinfo --logs -f stack-monitoring-es-default-1 --show --previous

    # Show deployments and statefulsets
    > ocpinfo --deployments

    # Show services and routes
    > ocpinfo --services

    # Show complete resource inventory
    > ocpinfo --resources

    # Show PersistentVolumeClaims
    > ocpinfo --pvc
    '''
    else:
        # No environment detected - show general help
        cmd_examples = '''
No OCP data detected in current directory.

This command requires one of:
  • A sosreport directory (contains 'sos_commands/' subdirectory)
  • A must-gather directory (contains 'quay-io-*' or 'must-gather*' subdirectory)
  • An inspect directory (contains 'namespaces/' subdirectory)

Please navigate to a valid OCP data directory and try again.

Examples by data type:

Sosreport (node-level):
    > ocpinfo -p           # Show pods
    > ocpinfo -c           # Show containers
    > ocpinfo -i           # Show images
    > ocpinfo -a           # Show all information

Must-Gather (cluster-level):
    > ocpinfo --version    # Show cluster version
    > ocpinfo --operators  # Show cluster operators
    > ocpinfo --etcd       # Show ETCD health

Inspect (namespace-level):
    > ocpinfo --namespaces # List namespaces
    > ocpinfo --events     # Show events
    > ocpinfo --inspect-pods  # Show pods
    > ocpinfo --logs       # List/view logs
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

    # Detect environment early for context-aware help
    base_path = os.getcwd()
    sources = detect_data_sources(base_path)
    sosreport_available = sources.get('sosreport', False)
    must_gather_available = sources.get('must-gather', False)
    inspect_available = sources.get('inspect', False)

    # Build usage message with environment info
    env_type = ""
    if sosreport_available:
        env_type = " (Sosreport detected)"
    elif must_gather_available:
        env_type = " (Must-Gather detected)"
    elif inspect_available:
        env_type = " (Inspect detected)"

    usage = "Usage: %s [options]%s" % (cmd_name, env_type)

    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

    # Common options (available in all environments)
    op.add_option("-d", "--detail", dest="detail", default=False,
                  action="store_true",
                  help="Show detailed information")
    op.add_option("-n", "--namespace", dest="namespace", default="",
                  type="string", action="store",
                  help="Filter by namespace")
    op.add_option("-l", "--limit", dest="limit", default=0,
                  type="int", action="store",
                  help="Limit number of items to display")
    op.add_option("-f", "--filter", dest="filter", default="",
                  type="string", action="store",
                  help="Filter lines containing pattern (case-insensitive)")

    # Sosreport-specific options
    if sosreport_available or not (must_gather_available or inspect_available):
        op.add_option("-p", "--pods", dest="pods", default=False,
                      action="store_true",
                      help="Show pod information (sosreport)")
        op.add_option("-c", "--containers", dest="containers", default=False,
                      action="store_true",
                      help="Show container information (sosreport)")
        op.add_option("-i", "--images", dest="images", default=False,
                      action="store_true",
                      help="Show container images (sosreport)")
        op.add_option("-s", "--stats", dest="stats", default=False,
                      action="store_true",
                      help="Show resource statistics (sosreport)")
        op.add_option("-a", "--all", dest="all", default=False,
                      action="store_true",
                      help="Show all information (sosreport)")
        op.add_option("--state", dest="state", default="",
                      type="string", action="store",
                      help="Filter by state (Ready, NotReady, Running, etc.)")

    # Must-gather-specific options
    if must_gather_available or not (sosreport_available or inspect_available):
        op.add_option("--version", dest="show_version", default=False,
                      action="store_true",
                      help="Show cluster version (must-gather)")
        op.add_option("--operators", dest="operators", default=False,
                      action="store_true",
                      help="Show cluster operators status (must-gather)")
        op.add_option("--etcd", dest="etcd", default=False,
                      action="store_true",
                      help="Show ETCD cluster health (must-gather)")
        if not sosreport_available:  # Only add --state for must-gather if no sosreport
            op.add_option("--state", dest="state", default="",
                          type="string", action="store",
                          help="Filter by state (Available, Degraded, etc.)")

    # Inspect-specific options
    if inspect_available or not (sosreport_available or must_gather_available):
        op.add_option("--namespaces", dest="namespaces", default=False,
                      action="store_true",
                      help="List namespaces (inspect)")
        op.add_option("--events", dest="events", default=False,
                      action="store_true",
                      help="Show events (inspect)")
        op.add_option("--inspect-pods", dest="inspect_pods", default=False,
                      action="store_true",
                      help="Show pods from inspect data (inspect)")
        op.add_option("--logs", dest="logs", default=False,
                      action="store_true",
                      help="List/view pod logs (inspect)")
        op.add_option("--deployments", dest="deployments", default=False,
                      action="store_true",
                      help="Show deployments and statefulsets (inspect)")
        op.add_option("--services", dest="services", default=False,
                      action="store_true",
                      help="Show services and routes (inspect)")
        op.add_option("--resources", dest="resources", default=False,
                      action="store_true",
                      help="Show resource inventory (inspect)")
        op.add_option("--pvc", dest="pvc", default=False,
                      action="store_true",
                      help="Show PersistentVolumeClaims (inspect)")
        op.add_option("--type", dest="event_type", default="",
                      type="string", action="store",
                      help="Filter events by type (Warning, Normal)")
        op.add_option("--show", dest="show_logs", default=False,
                      action="store_true",
                      help="Show log content (use with --logs)")
        op.add_option("--tail", dest="tail_lines", default=100,
                      type="int", action="store",
                      help="Number of lines to show from end of log (default: 100)")
        op.add_option("--previous", dest="previous_log", default=False,
                      action="store_true",
                      help="Show previous container log instead of current")
        op.add_option("--container", dest="container", default="",
                      type="string", action="store",
                      help="Specific container name (use with --logs --show)")
        if not sosreport_available and not must_gather_available:  # Only if no other env
            op.add_option("--state", dest="state", default="",
                          type="string", action="store",
                          help="Filter by state/phase")

    try:
        (o, args) = op.parse_args(input_str.split())
    except:
        return ""

    if o.help or show_help == True:
        return print_help_msg(op, no_pipe, base_path)

    # Create color manager
    colors = ColorManager(no_pipe)

    # Data sources already detected at the beginning of function
    # Get the roots
    must_gather_root = sources.get('must-gather-root')
    inspect_root = sources.get('inspect-root')

    # Handle must-gather specific options (use getattr for safety)
    if getattr(o, 'show_version', False) or getattr(o, 'operators', False) or getattr(o, 'etcd', False):
        if not must_gather_available:
            # Determine what's available and provide helpful message
            print(f"{colors.red}Error: Must-gather options not available{colors.reset}")
            print()

            # Build list of requested options
            requested = []
            if getattr(o, 'show_version', False):
                requested.append("--version")
            if getattr(o, 'operators', False):
                requested.append("--operators")
            if getattr(o, 'etcd', False):
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
        if getattr(o, 'show_version', False):
            show_cluster_version(must_gather_root, colors)

        if getattr(o, 'operators', False):
            show_cluster_operators(must_gather_root, o, colors)

        if getattr(o, 'etcd', False):
            show_etcd_health(must_gather_root, colors)

        return ""

    # Handle inspect options (use getattr for safety)
    if (getattr(o, 'namespaces', False) or getattr(o, 'events', False) or
        getattr(o, 'inspect_pods', False) or getattr(o, 'logs', False) or
        getattr(o, 'deployments', False) or getattr(o, 'services', False) or
        getattr(o, 'resources', False) or getattr(o, 'pvc', False)):
        if not inspect_available:
            # Determine what's available and provide helpful message
            print(f"{colors.red}Error: Inspect options not available{colors.reset}")
            print()

            # Build list of requested options
            requested = []
            if getattr(o, 'namespaces', False):
                requested.append("--namespaces")
            if getattr(o, 'events', False):
                requested.append("--events")
            if getattr(o, 'inspect_pods', False):
                requested.append("--inspect-pods")
            if getattr(o, 'logs', False):
                requested.append("--logs")
            if getattr(o, 'deployments', False):
                requested.append("--deployments")
            if getattr(o, 'services', False):
                requested.append("--services")
            if getattr(o, 'resources', False):
                requested.append("--resources")
            if getattr(o, 'pvc', False):
                requested.append("--pvc")

            print(f"Requested option(s): {', '.join(requested)}")
            print(f"{colors.yellow}These options require an inspect archive{colors.reset}")
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
            elif must_gather_available:
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
                print("Please run this command from within an inspect archive directory")

            return ""

        # Show requested inspect information
        if getattr(o, 'namespaces', False):
            show_inspect_namespaces(inspect_root, colors)

        if getattr(o, 'events', False):
            show_inspect_events(inspect_root, o, colors)

        if getattr(o, 'inspect_pods', False):
            show_inspect_pods(inspect_root, o, colors)

        if getattr(o, 'logs', False):
            show_inspect_logs(inspect_root, o, colors)

        if getattr(o, 'deployments', False):
            show_inspect_deployments(inspect_root, o, colors)

        if getattr(o, 'services', False):
            show_inspect_services(inspect_root, o, colors)

        if getattr(o, 'resources', False):
            show_inspect_resources(inspect_root, o, colors)

        if getattr(o, 'pvc', False):
            show_inspect_pvc(inspect_root, o, colors)

        return ""

    # Handle sosreport options (pods, containers, images, stats) - use getattr for safety
    if (getattr(o, 'pods', False) or getattr(o, 'containers', False) or
        getattr(o, 'images', False) or getattr(o, 'stats', False) or getattr(o, 'all', False)):
        if not sosreport_available:
            # Determine what's available and provide helpful message
            print(f"{colors.red}Error: Sosreport options not available{colors.reset}")
            print()

            # Build list of requested options
            requested = []
            if getattr(o, 'pods', False):
                requested.append("-p/--pods")
            if getattr(o, 'containers', False):
                requested.append("-c/--containers")
            if getattr(o, 'images', False):
                requested.append("-i/--images")
            if getattr(o, 'stats', False):
                requested.append("-s/--stats")
            if getattr(o, 'all', False):
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
        if getattr(o, 'all', False):
            show_cluster_info(sosreport_path, colors)
            show_pods_info(sosreport_path, o, colors)
            show_containers_info(sosreport_path, o, colors)
            show_images_info(sosreport_path, o, colors)
            show_resource_stats(sosreport_path, colors)
            return ""

        # Show specific information
        if getattr(o, 'pods', False):
            show_pods_info(sosreport_path, o, colors)

        if getattr(o, 'containers', False):
            show_containers_info(sosreport_path, o, colors)

        if getattr(o, 'images', False):
            show_images_info(sosreport_path, o, colors)

        if getattr(o, 'stats', False):
            show_resource_stats(sosreport_path, colors)

        return ""

    # No specific option - show cluster overview
    # Prefer must-gather if available, then inspect, then sosreport
    if must_gather_available:
        show_cluster_version(must_gather_root, colors)
    elif inspect_available:
        # For inspect, show namespaces as default overview
        show_inspect_namespaces(inspect_root, colors)
    elif sosreport_available:
        show_cluster_info(base_path, colors)
    else:
        print(f"{colors.red}Error: No OCP data found{colors.reset}")
        print()
        print(f"{colors.yellow}Current directory:{colors.reset} {base_path}")
        print()
        print("This command requires one of:")
        print(f"  {colors.cyan}• A sosreport directory{colors.reset} (contains 'sos_commands/' subdirectory)")
        print(f"  {colors.cyan}• A must-gather directory{colors.reset} (contains 'quay-io-*' or 'must-gather*' subdirectory)")
        print(f"  {colors.cyan}• An inspect directory{colors.reset} (contains 'namespaces/' subdirectory)")
        print()
        print("Please navigate to a valid OCP data directory and try again.")

    return ""


if __name__ == "__main__":
    # For testing
    def dummy_is_stopped():
        return False
    run_ocpinfo(" ".join(sys.argv[1:]), {}, dummy_is_stopped, False, True)
