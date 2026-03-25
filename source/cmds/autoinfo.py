"""
Configuration Management Tools Detection and Analysis

Detects and analyzes configuration management tools in sosreports:
- Puppet: Configuration, logs, service status
- Ansible: Configuration, inventory, execution logs
- Chef: Client/server config, logs, cookbook information

Provides comprehensive overview of automated system management tools.
"""

import os
from os.path import exists, isfile, isdir, join
from optparse import OptionParser
from io import StringIO

from cmd_helpers import (
    ColorManager, OutputBuilder, get_sos_file_path
)


def description():
    return "Shows configuration management tools information (puppet/ansible/chef)"


def add_command():
    return True


def get_command_info():
    return {"autoinfo": run_autoinfo}


def detect_tool_by_packages(sos_home, tool_name):
    """
    Detect tool presence via installed_rpms.

    Args:
        sos_home: Root of sosreport
        tool_name: Tool name to search for (case-insensitive)

    Returns:
        List of matching package names, empty if not found
    """
    rpm_path = get_sos_file_path(sos_home, "installed_rpms")
    if not exists(rpm_path):
        return []

    packages = []
    try:
        with open(rpm_path, 'r') as f:
            for line in f:
                if is_cmd_stopped():
                    return packages
                if tool_name.lower() in line.lower():
                    packages.append(line.strip())
    except (IOError, OSError):
        pass

    return packages


def get_recent_log_lines(log_path, max_lines=20, filter_keywords=None):
    """
    Read recent lines from log file with optional keyword filtering.

    Args:
        log_path: Path to log file
        max_lines: Maximum lines to return (from end)
        filter_keywords: List of keywords to filter for (OR logic)

    Returns:
        List of log lines
    """
    if not exists(log_path):
        return []

    try:
        with open(log_path, 'r') as f:
            lines = []
            for line in f:
                if is_cmd_stopped():
                    return []
                lines.append(line)

            if filter_keywords:
                lines = [l for l in lines
                        if any(kw in l for kw in filter_keywords)]

            # Return last N lines
            return [l.rstrip() for l in lines[-max_lines:]]
    except (IOError, OSError):
        return []


def check_systemd_service(sos_home, service_name):
    """
    Check if systemd service exists.

    Args:
        sos_home: Root of sosreport
        service_name: Service name (e.g., 'puppet.service')

    Returns:
        True if service unit file found
    """
    paths = [
        get_sos_file_path(sos_home, "etc", "systemd", "system", service_name),
        get_sos_file_path(sos_home, "usr", "lib", "systemd", "system", service_name),
    ]

    for path in paths:
        if exists(path):
            return True

    # Also check in list-unit-files output
    unit_list_path = get_sos_file_path(sos_home, "sos_commands", "systemd",
                                       "systemctl_list-unit-files")
    if exists(unit_list_path):
        try:
            with open(unit_list_path, 'r') as f:
                for line in f:
                    if is_cmd_stopped():
                        return False
                    if service_name in line:
                        return True
        except (IOError, OSError):
            pass

    return False


def analyze_puppet(sos_home, colors, output):
    """
    Analyze Puppet installation and configuration.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance

    Returns:
        True if Puppet detected, False otherwise
    """
    # Check for Puppet presence
    puppet_dirs = [
        get_sos_file_path(sos_home, "etc", "puppet"),
        get_sos_file_path(sos_home, "var", "lib", "puppet"),
        get_sos_file_path(sos_home, "var", "log", "puppet")
    ]

    if not any(isdir(d) for d in puppet_dirs):
        return False

    output.add_colored_line("=== Puppet Configuration Management ===",
                           colors.cyan, colors.reset)
    output.add_line("")

    # Package information
    packages = detect_tool_by_packages(sos_home, "puppet")
    if packages:
        output.add_colored_line("Installed Packages:", colors.yellow, colors.reset)
        for pkg in packages[:5]:  # Limit to first 5
            output.add_line("  " + pkg)
        if len(packages) > 5:
            output.add_line("  ... and %d more packages" % (len(packages) - 5))
        output.add_line("")

    # Configuration file
    puppet_conf = get_sos_file_path(sos_home, "etc", "puppet", "puppet.conf")
    if exists(puppet_conf):
        output.add_colored_line("Configuration:", colors.yellow, colors.reset)
        output.add_line("  Config file: /etc/puppet/puppet.conf")

        # Parse key settings
        try:
            with open(puppet_conf, 'r') as f:
                current_section = None
                for line in f:
                    if is_cmd_stopped():
                        break
                    line = line.strip()
                    if line.startswith('['):
                        current_section = line
                    elif '=' in line and current_section:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key in ['server', 'certname', 'environment']:
                            output.add_line("  %s [%s]: %s" %
                                          (key, current_section, value))
        except (IOError, OSError):
            pass
        output.add_line("")

    # Manifests
    manifests_dir = get_sos_file_path(sos_home, "etc", "puppet", "manifests")
    if isdir(manifests_dir):
        try:
            manifest_files = []
            for f in os.listdir(manifests_dir):
                if is_cmd_stopped():
                    break
                if f.endswith('.pp'):
                    manifest_files.append(f)
            if manifest_files:
                output.add_colored_line("Manifests:", colors.yellow, colors.reset)
                output.add_line("  Directory: /etc/puppet/manifests/")
                output.add_line("  Files: %d manifest(s)" % len(manifest_files))
                output.add_line("")
        except OSError:
            pass

    # Service status
    has_service = (check_systemd_service(sos_home, "puppet.service") or
                   check_systemd_service(sos_home, "puppetd.service"))
    if has_service:
        output.add_colored_line("Service:", colors.yellow, colors.reset)
        output.add_line("  Systemd unit: Detected")
        output.add_line("")

    # Recent logs
    log_paths = [
        get_sos_file_path(sos_home, "var", "log", "puppet", "puppet-agent.log"),
        get_sos_file_path(sos_home, "var", "log", "puppet", "puppet.log"),
    ]

    for log_path in log_paths:
        if exists(log_path):
            recent_logs = get_recent_log_lines(log_path, max_lines=10)
            if recent_logs:
                output.add_colored_line("Recent Log Activity:", colors.yellow, colors.reset)
                output.add_line("  Log file: %s" % log_path.replace(sos_home, ""))
                output.add_line("  Last %d entries:" % len(recent_logs))
                for log_line in recent_logs:
                    output.add_line("    " + log_line[:100])
                break

    output.add_line("")
    return True


def analyze_ansible(sos_home, colors, output):
    """
    Analyze Ansible installation and configuration.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance

    Returns:
        True if Ansible detected, False otherwise
    """
    # Check for Ansible presence
    ansible_dirs = [
        get_sos_file_path(sos_home, "etc", "ansible"),
        get_sos_file_path(sos_home, "var", "log", "ansible")
    ]

    if not any(isdir(d) for d in ansible_dirs):
        return False

    output.add_colored_line("=== Ansible Configuration Management ===",
                           colors.cyan, colors.reset)
    output.add_line("")

    # Package information
    packages = detect_tool_by_packages(sos_home, "ansible")
    if packages:
        output.add_colored_line("Installed Packages:", colors.yellow, colors.reset)
        for pkg in packages[:5]:
            output.add_line("  " + pkg)
        if len(packages) > 5:
            output.add_line("  ... and %d more packages" % (len(packages) - 5))
        output.add_line("")

    # Configuration file
    ansible_cfg = get_sos_file_path(sos_home, "etc", "ansible", "ansible.cfg")
    if exists(ansible_cfg):
        output.add_colored_line("Configuration:", colors.yellow, colors.reset)
        output.add_line("  Config file: /etc/ansible/ansible.cfg")

        # Parse key settings
        try:
            with open(ansible_cfg, 'r') as f:
                current_section = None
                for line in f:
                    if is_cmd_stopped():
                        break
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith('['):
                        current_section = line
                    elif '=' in line and current_section:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key in ['inventory', 'remote_user', 'forks', 'host_key_checking']:
                            output.add_line("  %s: %s" % (key, value))
        except (IOError, OSError):
            pass
        output.add_line("")

    # Inventory/hosts file
    inventory_paths = [
        get_sos_file_path(sos_home, "etc", "ansible", "hosts"),
        get_sos_file_path(sos_home, "etc", "ansible", "inventory"),
    ]

    for inv_path in inventory_paths:
        if exists(inv_path):
            output.add_colored_line("Inventory:", colors.yellow, colors.reset)
            output.add_line("  File: %s" % inv_path.replace(sos_home, ""))

            # Count hosts/groups
            try:
                with open(inv_path, 'r') as f:
                    lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
                    groups = [l for l in lines if l.startswith('[')]
                    output.add_line("  Groups: %d" % len(groups))
            except (IOError, OSError):
                pass
            output.add_line("")
            break

    # Roles directory
    roles_dir = get_sos_file_path(sos_home, "etc", "ansible", "roles")
    if isdir(roles_dir):
        try:
            role_dirs = []
            for d in os.listdir(roles_dir):
                if is_cmd_stopped():
                    break
                if isdir(join(roles_dir, d)):
                    role_dirs.append(d)
            if role_dirs:
                output.add_colored_line("Roles:", colors.yellow, colors.reset)
                output.add_line("  Directory: /etc/ansible/roles/")
                output.add_line("  Roles: %d" % len(role_dirs))
                output.add_line("")
        except OSError:
            pass

    # Recent logs (if available)
    log_dir = get_sos_file_path(sos_home, "var", "log", "ansible")
    if isdir(log_dir):
        try:
            log_files = []
            for f in os.listdir(log_dir):
                if is_cmd_stopped():
                    break
                if isfile(join(log_dir, f)):
                    log_files.append(f)
            if log_files:
                output.add_colored_line("Log Files:", colors.yellow, colors.reset)
                output.add_line("  Directory: /var/log/ansible/")
                output.add_line("  Files: %d log file(s)" % len(log_files))
                output.add_line("")
        except OSError:
            pass

    output.add_line("")
    return True


def analyze_chef(sos_home, colors, output):
    """
    Analyze Chef installation and configuration.

    Args:
        sos_home: Root of sosreport
        colors: ColorManager instance
        output: OutputBuilder instance

    Returns:
        True if Chef detected, False otherwise
    """
    # Check for Chef presence
    chef_dirs = [
        get_sos_file_path(sos_home, "etc", "chef"),
        get_sos_file_path(sos_home, "var", "lib", "chef"),
        get_sos_file_path(sos_home, "var", "log", "chef")
    ]

    if not any(isdir(d) for d in chef_dirs):
        return False

    output.add_colored_line("=== Chef Configuration Management ===",
                           colors.cyan, colors.reset)
    output.add_line("")

    # Package information
    packages = detect_tool_by_packages(sos_home, "chef")
    if packages:
        output.add_colored_line("Installed Packages:", colors.yellow, colors.reset)
        for pkg in packages[:5]:
            output.add_line("  " + pkg)
        if len(packages) > 5:
            output.add_line("  ... and %d more packages" % (len(packages) - 5))
        output.add_line("")

    # Configuration files
    config_files = [
        ("Client Config", get_sos_file_path(sos_home, "etc", "chef", "client.rb")),
        ("Solo Config", get_sos_file_path(sos_home, "etc", "chef", "solo.rb")),
        ("Server Config", get_sos_file_path(sos_home, "etc", "chef", "server.rb")),
    ]

    found_config = False
    for config_name, config_path in config_files:
        if exists(config_path):
            if not found_config:
                output.add_colored_line("Configuration:", colors.yellow, colors.reset)
                found_config = True

            output.add_line("  %s: %s" % (config_name, config_path.replace(sos_home, "")))

            # Parse key settings
            try:
                with open(config_path, 'r') as f:
                    for line in f:
                        if is_cmd_stopped():
                            break
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        # Look for key settings (Ruby syntax)
                        for key in ['chef_server_url', 'node_name', 'log_level', 'cookbook_path']:
                            if line.startswith(key):
                                output.add_line("    %s" % line)
                                break
            except (IOError, OSError):
                pass

    if found_config:
        output.add_line("")

    # Cookbooks
    cookbook_paths = [
        get_sos_file_path(sos_home, "var", "lib", "chef", "cookbooks"),
        get_sos_file_path(sos_home, "var", "chef", "cookbooks"),
    ]

    for cookbook_path in cookbook_paths:
        if isdir(cookbook_path):
            try:
                cookbooks = []
                for d in os.listdir(cookbook_path):
                    if is_cmd_stopped():
                        break
                    if isdir(join(cookbook_path, d)):
                        cookbooks.append(d)
                if cookbooks:
                    output.add_colored_line("Cookbooks:", colors.yellow, colors.reset)
                    output.add_line("  Directory: %s" % cookbook_path.replace(sos_home, ""))
                    output.add_line("  Cookbooks: %d" % len(cookbooks))
                    output.add_line("")
                    break
            except OSError:
                pass

    # Service status
    has_service = (check_systemd_service(sos_home, "chef-client.service") or
                   check_systemd_service(sos_home, "chef-server.service"))
    if has_service:
        output.add_colored_line("Service:", colors.yellow, colors.reset)
        output.add_line("  Systemd unit: Detected")
        output.add_line("")

    # Recent logs
    log_path = get_sos_file_path(sos_home, "var", "log", "chef", "client.log")
    if exists(log_path):
        recent_logs = get_recent_log_lines(log_path, max_lines=10)
        if recent_logs:
            output.add_colored_line("Recent Log Activity:", colors.yellow, colors.reset)
            output.add_line("  Log file: /var/log/chef/client.log")
            output.add_line("  Last %d entries:" % len(recent_logs))
            for log_line in recent_logs:
                output.add_line("    " + log_line[:100])
            output.add_line("")

    output.add_line("")
    return True


def print_help_msg(op, no_pipe):
    """Generate help message."""
    cmd_examples = '''
Detects and analyzes configuration management tools in the sosreport.

Automatically detects:
  - Puppet: Agent/master configuration, manifests, logs
  - Ansible: Configuration, inventory, roles, playbooks
  - Chef: Client/server/solo configuration, cookbooks, logs

For each detected tool, displays:
  - Installed packages and versions
  - Configuration files and key settings
  - Managed resources (manifests/roles/cookbooks)
  - Service status (systemd units)
  - Recent log activity

Examples:
  autoinfo           Show all detected configuration management tools
  autoinfo | grep -i puppet    Filter for Puppet-specific information
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


def run_autoinfo(input_str, env_vars, is_cmd_stopped_func,
                 show_help=False, no_pipe=True):
    """
    Main entry point for autoinfo command.

    Args:
        input_str: Command arguments
        env_vars: Environment variables dict (requires 'sos_home')
        is_cmd_stopped_func: Function to check if command should stop
        show_help: Show help message
        no_pipe: True if output goes to terminal

    Returns:
        Result string (empty if output went to terminal)
    """
    global is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func

    # Parse command line options
    usage = "Usage: autoinfo [options]"
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')

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

    # Analyze each tool
    detected_count = 0

    try:
        if analyze_puppet(sos_home, colors, output):
            detected_count += 1

        if analyze_ansible(sos_home, colors, output):
            detected_count += 1

        if analyze_chef(sos_home, colors, output):
            detected_count += 1

        # Summary if nothing detected
        if detected_count == 0:
            output.add_colored_line("=== Configuration Management Tools ===",
                                   colors.cyan, colors.reset)
            output.add_line("")
            output.add_line("No configuration management tools detected.")
            output.add_line("")
            output.add_line("Checked for: Puppet, Ansible, Chef")

    except Exception as e:
        output.add_line("Unexpected error: %s" % str(e))

    return output.get_result()
