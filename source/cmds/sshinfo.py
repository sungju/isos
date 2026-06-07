"""
 Written by Daniel Sungju Kwon
"""

import os
import glob
from io import StringIO
from optparse import OptionParser

import screen

cmd_name = "sshinfo"
sos_home = ""
is_cmd_stopped = None


def description():
    return "Shows SSH/sshd configuration and connection startup chain"


def add_command():
    return True


def get_command_info():
    return {cmd_name: run_sshinfo}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return None


def _file_exists(path):
    return os.path.isfile(path)


def _section(title, no_pipe):
    line = "=" * 60
    screen.get_pipe_aware_line(line)
    if no_pipe:
        print(screen.COLOR_TITLE + title + screen.COLOR_RESET)
        print(line)
    else:
        return line + "\n" + title + "\n" + line + "\n"
    return ""


# ---------------------------------------------------------------------------
# sshd_config parsing
# ---------------------------------------------------------------------------

SECURITY_KEYS = {
    "Port", "ListenAddress", "Protocol",
    "PermitRootLogin", "PasswordAuthentication", "PubkeyAuthentication",
    "ChallengeResponseAuthentication", "KbdInteractiveAuthentication",
    "GSSAPIAuthentication", "UsePAM",
    "AllowUsers", "DenyUsers", "AllowGroups", "DenyGroups",
    "MaxAuthTries", "MaxSessions", "LoginGraceTime",
    "PermitEmptyPasswords", "X11Forwarding", "AllowTcpForwarding",
    "AuthorizedKeysFile", "AuthorizedKeysCommand",
    "ForceCommand", "Subsystem",
    "Banner", "PrintMotd", "PrintLastLog",
    "ClientAliveInterval", "ClientAliveCountMax",
    "HostbasedAuthentication", "IgnoreUserKnownHosts",
    "Match",
}

RISK_FLAGS = {
    "PermitRootLogin":        lambda v: v.lower() not in ("no", "prohibit-password", "forced-commands-only"),
    "PasswordAuthentication": lambda v: v.lower() == "yes",
    "PermitEmptyPasswords":   lambda v: v.lower() == "yes",
    "X11Forwarding":          lambda v: v.lower() == "yes",
    "Protocol":               lambda v: "1" in v,
}


def parse_sshd_config(sos_home):
    cfg = {}
    path = sos_home + "/etc/ssh/sshd_config"
    content = _read_file(path)
    if content is None:
        return None, path
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2:
            key, val = parts
            if key in cfg:
                if isinstance(cfg[key], list):
                    cfg[key].append(val)
                else:
                    cfg[key] = [cfg[key], val]
            else:
                cfg[key] = val
    return cfg, path


def show_sshd_config(no_pipe):
    result = ""
    cfg, path = parse_sshd_config(sos_home)

    header = "\n[SSH Server Configuration]  (%s)\n" % path
    if no_pipe:
        print(screen.COLOR_TITLE + header.strip() + screen.COLOR_RESET)
        print("-" * 60)
    else:
        result += header + "-" * 60 + "\n"

    if cfg is None:
        msg = "  sshd_config not found at %s\n" % path
        if no_pipe:
            print(msg)
        else:
            result += msg
        return result

    for key in sorted(SECURITY_KEYS):
        val = cfg.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            display = ", ".join(val)
        else:
            display = val

        # Color-code risky settings
        risk_fn = RISK_FLAGS.get(key)
        is_risky = risk_fn and risk_fn(val if isinstance(val, str) else val[0])
        color = screen.COLOR_CRITICAL if is_risky else ""
        reset = screen.COLOR_RESET if is_risky else ""

        line = "  %-35s %s%s%s\n" % (key + ":", color, display, reset)
        if no_pipe:
            print(line, end="")
        else:
            result += line

    # Connection summary
    auth_methods = []
    if cfg.get("PubkeyAuthentication", "yes").lower() != "no":
        auth_methods.append("PublicKey")
    if cfg.get("PasswordAuthentication", "yes").lower() != "no":
        auth_methods.append("Password")
    if cfg.get("GSSAPIAuthentication", "no").lower() == "yes":
        auth_methods.append("GSSAPI/Kerberos")
    if cfg.get("KbdInteractiveAuthentication",
               cfg.get("ChallengeResponseAuthentication", "yes")).lower() != "no":
        auth_methods.append("KbdInteractive")

    force_cmd = cfg.get("ForceCommand")
    summary = "\n  Auth methods enabled : %s\n" % ", ".join(auth_methods)
    if force_cmd:
        summary += "  ForceCommand         : %s\n" % force_cmd

    if no_pipe:
        print(summary)
    else:
        result += summary

    return result


# ---------------------------------------------------------------------------
# PAM chain
# ---------------------------------------------------------------------------

def _parse_pam_file(pam_path, pam_dir, visited=None):
    """Return list of (type, control, module, args) tuples, following includes."""
    if visited is None:
        visited = set()
    if pam_path in visited:
        return []
    visited.add(pam_path)

    entries = []
    content = _read_file(pam_path)
    if content is None:
        return entries

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue

        pam_type = parts[0]
        if pam_type in ("@include", "include"):
            included = pam_dir + "/" + parts[1]
            entries += _parse_pam_file(included, pam_dir, visited)
            continue

        if len(parts) < 3:
            continue
        control = parts[1]
        module = parts[2]
        args = " ".join(parts[3:]) if len(parts) > 3 else ""

        if control in ("include", "substack"):
            # control field IS the keyword, module is the file
            included = pam_dir + "/" + module
            entries += _parse_pam_file(included, pam_dir, visited)
        else:
            entries.append((pam_type, control, module, args))

    return entries


def show_pam_chain(no_pipe):
    result = ""
    pam_dir = sos_home + "/etc/pam.d"
    pam_path = pam_dir + "/sshd"

    header = "\n[PAM Chain for sshd]  (%s)\n" % pam_path
    if no_pipe:
        print(screen.COLOR_TITLE + header.strip() + screen.COLOR_RESET)
        print("-" * 60)
    else:
        result += header + "-" * 60 + "\n"

    if not _file_exists(pam_path):
        msg = "  %s not found\n" % pam_path
        if no_pipe:
            print(msg)
        else:
            result += msg
        return result

    entries = _parse_pam_file(pam_path, pam_dir)

    current_type = None
    for pam_type, control, module, args in entries:
        if pam_type != current_type:
            section_hdr = "\n  [%s]\n" % pam_type.upper()
            if no_pipe:
                print(screen.COLOR_INFO + section_hdr.strip() + screen.COLOR_RESET)
            else:
                result += section_hdr
            current_type = pam_type

        mod_name = os.path.basename(module)
        line = "    %-12s %-30s %s\n" % (control, mod_name, args)
        if no_pipe:
            print(line, end="")
        else:
            result += line

    if no_pipe:
        print("")
    else:
        result += "\n"

    return result


# ---------------------------------------------------------------------------
# Shell startup chain
# ---------------------------------------------------------------------------

STARTUP_FILES = [
    ("/etc/profile",          "System-wide login shell profile"),
    ("/etc/profile.d/",       "Profile drop-ins (sourced by /etc/profile)"),
    ("/etc/bashrc",           "System-wide bash config (non-login shells)"),
    ("/etc/bash.bashrc",      "System-wide bash config (Debian variant)"),
    ("/etc/environment",      "PAM environment variables (pam_env)"),
    ("/etc/security/limits.conf", "Resource limits (pam_limits)"),
    ("/etc/security/access.conf", "Login access control (pam_access)"),
    ("/etc/motd",             "Message of the day"),
    ("/etc/issue.net",        "Pre-login banner (Banner in sshd_config)"),
]


def _show_file_contents(rel_path, label, no_pipe, max_lines=20):
    result = ""
    full = sos_home + rel_path

    if rel_path.endswith("/"):
        # Directory — list files
        try:
            files = sorted(glob.glob(full + "*.sh") + glob.glob(full + "*"))
            files = [f for f in files if os.path.isfile(f)]
        except Exception:
            files = []
        if files:
            line = "\n  %s  [%s — %d file(s)]\n" % (
                screen.COLOR_INFO if no_pipe else "",
                label,
                len(files))
            if no_pipe:
                print(line.strip() + (screen.COLOR_RESET if no_pipe else ""))
            else:
                result += "  [%s — %d file(s)]\n" % (label, len(files))
            for f in files:
                entry = "    • %s\n" % f.replace(sos_home, "")
                if no_pipe:
                    print(entry, end="")
                else:
                    result += entry
    else:
        content = _read_file(full)
        if content is None:
            return result
        lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not lines:
            return result
        hdr = "\n  [%s — %s]\n" % (label, rel_path)
        if no_pipe:
            print(screen.COLOR_INFO + hdr.strip() + screen.COLOR_RESET)
        else:
            result += hdr
        for line in lines[:max_lines]:
            entry = "    %s\n" % line
            if no_pipe:
                print(entry, end="")
            else:
                result += entry
        if len(lines) > max_lines:
            more = "    ... (%d more lines)\n" % (len(lines) - max_lines)
            if no_pipe:
                print(more, end="")
            else:
                result += more

    return result


def show_startup_chain(no_pipe):
    result = ""
    cfg, _ = parse_sshd_config(sos_home)

    header = "\n[SSH Connection Startup Chain]\n"
    if no_pipe:
        print(screen.COLOR_TITLE + header.strip() + screen.COLOR_RESET)
        print("-" * 60)
    else:
        result += header + "-" * 60 + "\n"

    # Step 1: ForceCommand overrides everything
    if cfg:
        force_cmd = cfg.get("ForceCommand")
        if force_cmd:
            msg = "\n  ForceCommand is set — shell startup files are bypassed:\n  $ %s\n" % force_cmd
            if no_pipe:
                print(screen.COLOR_CRITICAL + msg.strip() + screen.COLOR_RESET)
            else:
                result += msg
            return result

    # Step 2: Connection flow
    flow = [
        "1. sshd accepts TCP connection",
        "2. sshd performs authentication (auth methods per sshd_config)",
        "3. PAM session opens  (pam.d/sshd: session stack)",
        "4. pam_env loads      /etc/environment",
        "5. pam_limits loads   /etc/security/limits.conf",
        "6. User shell starts  (from /etc/passwd or sshd_config)",
        "7. Login shell sources /etc/profile  →  /etc/profile.d/*.sh",
        "8. Login shell sources ~/.bash_profile (or ~/.profile)",
        "9. ~/.bash_profile may source ~/.bashrc",
    ]

    flow_hdr = "\n  Connection flow:\n"
    if no_pipe:
        print(screen.COLOR_INFO + "  Connection flow:" + screen.COLOR_RESET)
    else:
        result += flow_hdr

    for step in flow:
        line = "    %s\n" % step
        if no_pipe:
            print(line, end="")
        else:
            result += line

    # Step 3: System-wide startup files
    hdr2 = "\n  System startup files (present in sosreport):\n"
    if no_pipe:
        print(screen.COLOR_INFO + "\n  System startup files (present in sosreport):" + screen.COLOR_RESET)
    else:
        result += hdr2

    for rel_path, label in STARTUP_FILES:
        result += _show_file_contents(rel_path, label, no_pipe)

    # Step 4: subsystem/sftp
    if cfg:
        subsystem = cfg.get("Subsystem")
        if subsystem:
            sftp_msg = "\n  Subsystem: %s\n" % subsystem
            if no_pipe:
                print(screen.COLOR_INFO + "  Subsystem:" + screen.COLOR_RESET + " %s" % subsystem)
            else:
                result += sftp_msg

    return result


# ---------------------------------------------------------------------------
# Help messages
# ---------------------------------------------------------------------------

def print_config_help_msg(no_pipe):
    msg = '''sshinfo  --  SSH Server Configuration

SYNOPSIS
    sshinfo [OPTIONS]

DESCRIPTION
    Parses /etc/ssh/sshd_config and displays key security settings,
    enabled authentication methods, and any ForceCommand or Subsystem
    directives.  Risk flags (PermitRootLogin yes, PasswordAuthentication
    yes, etc.) are highlighted in red.

OPTIONS
    (no flag)   Show sshd_config summary (default)
    -p, --pam   Show PAM chain for sshd
    -s, --startup
                Show shell startup file chain
    -a, --all   Show all of the above

    -h, --help  Show this help message.

EXAMPLES
    example.com> sshinfo
    example.com> sshinfo -a
    example.com> sshinfo -p
    example.com> sshinfo -s
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_pam_help_msg(no_pipe):
    msg = '''sshinfo -p  --  PAM Chain for sshd

SYNOPSIS
    sshinfo -p

DESCRIPTION
    Parses /etc/pam.d/sshd (following all include/substack directives)
    and lists every PAM module in the auth, account, session, and
    password stacks, in order of execution.

    Useful for understanding what authentication backends, MFA modules,
    access controls, and session setup modules run on every SSH login.

OPTIONS
    -p, --pam   Enable PAM chain mode.
    -h, --help  Show this help message.

EXAMPLES
    example.com> sshinfo -p
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_startup_help_msg(no_pipe):
    msg = '''sshinfo -s  --  SSH Session Startup Chain

SYNOPSIS
    sshinfo -s

DESCRIPTION
    Shows what runs when a user connects via SSH:

    1. Connection and auth flow (from sshd_config settings)
    2. PAM session modules (pam_env, pam_limits, etc.)
    3. System-wide shell startup files present in the sosreport:
         /etc/environment, /etc/profile, /etc/profile.d/*.sh,
         /etc/bashrc, /etc/security/limits.conf, /etc/security/access.conf
    4. ForceCommand (if set — bypasses normal shell startup)
    5. Subsystem (e.g. sftp-server)

OPTIONS
    -s, --startup   Enable startup chain mode.
    -h, --help      Show this help message.

EXAMPLES
    example.com> sshinfo -s
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Examples:
    sshinfo          # sshd_config key settings
    sshinfo -p       # PAM chain (what auth/session modules run)
    sshinfo -s       # shell startup file chain
    sshinfo -a       # everything
    '''
    if not no_pipe:
        output = StringIO()
        op.print_help(file=output)
        contents = output.getvalue()
        output.close()
        return contents + "\n" + cmd_examples
    else:
        op.print_help()
        print(cmd_examples)
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_sshinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    global sos_home, is_cmd_stopped
    is_cmd_stopped = is_cmd_stopped_func
    sos_home = env_vars["sos_home"]

    screen.init_data(no_pipe, 1, is_cmd_stopped)

    usage = "Usage: %s [options]" % cmd_name
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option("-h", "--help", dest="help", action="store_true",
                  help="Show this help message and exit")
    op.add_option("-p", "--pam", dest="pam", action="store_true",
                  default=False, help="Show PAM chain for sshd")
    op.add_option("-s", "--startup", dest="startup", action="store_true",
                  default=False, help="Show shell startup chain on SSH connect")
    op.add_option("-a", "--all", dest="all", action="store_true",
                  default=False, help="Show all SSH information")

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except Exception:
        return ""

    if o.help or show_help:
        if o.pam:
            return print_pam_help_msg(no_pipe)
        if o.startup:
            return print_startup_help_msg(no_pipe)
        return print_config_help_msg(no_pipe)

    result = ""
    if o.all or not (o.pam or o.startup):
        result += show_sshd_config(no_pipe)
    if o.all or o.pam:
        result += show_pam_chain(no_pipe)
    if o.all or o.startup:
        result += show_startup_chain(no_pipe)

    return result
