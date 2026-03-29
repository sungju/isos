"""
Comparison Topics for the isos compare command.

This module defines all comparison topics (system, memory, processes, network,
cgroups, storage, cpu, hardware, logs, autocheck) including their data collectors
and diff formatters.

Each topic:
    - collector(sos_home) -> dict   : extracts raw data from sosreport files
    - formatter(data1, data2) -> list[str] : produces colored diff lines

Diff line convention:
    [=] field  : value       (same in both)
    [~] field  : v1  vs  v2  (changed)
    [1] field  : v1           (only in sos1)
    [2] field  : v2           (only in sos2)
"""

import os
import re
from os.path import exists, join


# ---------------------------------------------------------------------------
# ANSI codes for diff output (written to preview files; fzf uses --ansi)
# ---------------------------------------------------------------------------
_ANSI_GREY   = "\033[90m"
_ANSI_YELLOW = "\033[33m"
_ANSI_GREEN  = "\033[32m"
_ANSI_RED    = "\033[31m"
_ANSI_CYAN   = "\033[36m"
_ANSI_BOLD   = "\033[1m"
_ANSI_RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CompareTopic:
    """Represents a single comparison topic."""

    def __init__(self, key, display_name, collector, formatter):
        self.key = key
        self.display_name = display_name
        self.collector = collector    # fn(sos_home) -> dict
        self.formatter = formatter    # fn(data1, data2) -> list[str]


# ---------------------------------------------------------------------------
# Shared formatting helpers
# ---------------------------------------------------------------------------

def _read_first_line(path):
    """Return first stripped line of file, or '' on error."""
    try:
        with open(path) as f:
            return f.readline().strip()
    except Exception:
        return ''


def _read_lines(path):
    """Return list of rstripped lines, or [] on error."""
    try:
        with open(path) as f:
            return [line.rstrip() for line in f]
    except Exception:
        return []


def _section_header(title):
    return "%s%s--- %s ---%s" % (_ANSI_BOLD, _ANSI_CYAN, title, _ANSI_RESET)


def _diff_line_same(key, value):
    return "%s[=] %-30s : %s%s" % (_ANSI_GREY, key, value, _ANSI_RESET)


def _diff_line_changed(key, val1, val2):
    return "%s[~] %-30s : %s  vs  %s%s" % (_ANSI_YELLOW, key, val1, val2, _ANSI_RESET)


def _diff_line_only1(key, val1):
    return "%s[1] %-30s : %s%s" % (_ANSI_RED, key, val1, _ANSI_RESET)


def _diff_line_only2(key, val2):
    return "%s[2] %-30s : %s%s" % (_ANSI_GREEN, key, val2, _ANSI_RESET)


def _format_dict_diff(d1, d2, keys=None, key_label=None):
    """
    Compare two flat dicts and produce diff lines.

    Args:
        d1: dict from sos1
        d2: dict from sos2
        keys: ordered list of keys to compare (default: sorted union)
        key_label: optional dict mapping key -> display label

    Returns:
        list of colored diff strings
    """
    lines = []
    if keys is None:
        keys = sorted(set(list(d1.keys()) + list(d2.keys())))

    for k in keys:
        label = key_label.get(k, k) if key_label else k
        v1 = str(d1.get(k, '(missing)'))
        v2 = str(d2.get(k, '(missing)'))
        if v1 == '(missing)' and v2 == '(missing)':
            continue
        if v1 == v2:
            lines.append(_diff_line_same(label, v1))
        elif v1 == '(missing)':
            lines.append(_diff_line_only2(label, v2))
        elif v2 == '(missing)':
            lines.append(_diff_line_only1(label, v1))
        else:
            lines.append(_diff_line_changed(label, v1, v2))

    return lines


def _kb_to_str(kb_val):
    """Convert KB integer to human-readable string."""
    try:
        kb = int(kb_val)
    except (TypeError, ValueError):
        return str(kb_val)
    if kb >= 1048576:
        return "%.1f GiB" % (kb / 1048576.0)
    elif kb >= 1024:
        return "%.1f MiB" % (kb / 1024.0)
    else:
        return "%d KiB" % kb


# ---------------------------------------------------------------------------
# Topic: system
# ---------------------------------------------------------------------------

def collect_system(sos_home):
    """
    Collect system information: kernel, hostname, OS release, date, RPM count.

    Returns:
        {
          'hostname': str,
          'kernel': str,
          'os_release': str,
          'date': str,
          'installed_rpms': str,   # count as string
        }
    Returns {} on error.
    """
    data = {}
    try:
        uname = _read_first_line(join(sos_home, "uname"))
        if uname:
            parts = uname.split()
            if len(parts) >= 3:
                data['kernel'] = parts[2]
            if len(parts) >= 2:
                data['hostname'] = parts[1]

        hostname = _read_first_line(join(sos_home, "hostname"))
        if hostname:
            data['hostname'] = hostname

        for path in [join(sos_home, "etc", "os-release"),
                     join(sos_home, "etc", "redhat-release"),
                     join(sos_home, "etc", "system-release")]:
            if not exists(path):
                continue
            for line in _read_lines(path):
                if line.startswith("PRETTY_NAME="):
                    data['os_release'] = line.split("=", 1)[1].strip('"')
                    break
                if not line.startswith("#") and ("Red Hat" in line or "CentOS" in line
                                                  or "Fedora" in line):
                    data['os_release'] = line.strip()
                    break
            if 'os_release' in data:
                break

        date_line = _read_first_line(join(sos_home, "date"))
        if date_line:
            data['date'] = date_line

        rpm_path = join(sos_home, "installed-rpms")
        if exists(rpm_path):
            count = 0
            with open(rpm_path) as f:
                for line in f:
                    if line.strip() and not line.startswith("#"):
                        count += 1
            data['installed_rpms'] = str(count)

    except Exception:
        pass

    return data


def format_system(data1, data2):
    """Format system info diff lines."""
    lines = [_section_header("System Information")]
    keys = ['hostname', 'kernel', 'os_release', 'date', 'installed_rpms']
    key_labels = {
        'hostname':       'Hostname',
        'kernel':         'Kernel',
        'os_release':     'OS Release',
        'date':           'System Date',
        'installed_rpms': 'Installed RPMs',
    }
    lines += _format_dict_diff(data1, data2, keys=keys, key_label=key_labels)
    return lines


# ---------------------------------------------------------------------------
# Topic: memory
# ---------------------------------------------------------------------------

def collect_memory(sos_home):
    """
    Parse /proc/meminfo from sosreport.

    Returns:
        {
          'MemTotal_kb': int,
          'MemFree_kb': int,
          'MemAvailable_kb': int,
          'SwapTotal_kb': int,
          'SwapFree_kb': int,
          'Cached_kb': int,
          'Buffers_kb': int,
          'Slab_kb': int,
          'HugePages_Total': int,
        }
    Returns {} on error.
    """
    data = {}
    try:
        with open(join(sos_home, "proc", "meminfo")) as f:
            for line in f:
                if ':' not in line:
                    continue
                parts = line.split(':', 1)
                key = parts[0].strip()
                val_parts = parts[1].strip().split()
                if not val_parts:
                    continue
                try:
                    data[key] = int(val_parts[0])
                except ValueError:
                    data[key] = val_parts[0]
    except Exception:
        pass
    return data


def format_memory(data1, data2):
    """Format memory diff with human-readable sizes."""
    lines = [_section_header("Memory Usage")]

    keys = ['MemTotal', 'MemFree', 'MemAvailable', 'Buffers', 'Cached',
            'SwapTotal', 'SwapFree', 'Slab', 'HugePages_Total']
    key_labels = {
        'MemTotal':       'Total Memory',
        'MemFree':        'Free Memory',
        'MemAvailable':   'Available Memory',
        'Buffers':        'Buffers',
        'Cached':         'Cached',
        'SwapTotal':      'Swap Total',
        'SwapFree':       'Swap Free',
        'Slab':           'Slab Cache',
        'HugePages_Total':'HugePages Total',
    }

    for k in keys:
        label = key_labels.get(k, k)
        v1 = data1.get(k)
        v2 = data2.get(k)
        if v1 is None and v2 is None:
            continue
        # HugePages_Total is a page count, not KB
        if k == 'HugePages_Total':
            s1 = str(v1) if v1 is not None else '(missing)'
            s2 = str(v2) if v2 is not None else '(missing)'
        else:
            s1 = _kb_to_str(v1) if v1 is not None else '(missing)'
            s2 = _kb_to_str(v2) if v2 is not None else '(missing)'

        if s1 == s2:
            lines.append(_diff_line_same(label, s1))
        elif v1 is None:
            lines.append(_diff_line_only2(label, s2))
        elif v2 is None:
            lines.append(_diff_line_only1(label, s1))
        else:
            lines.append(_diff_line_changed(label, s1, s2))

    return lines


# ---------------------------------------------------------------------------
# Topic: cpu
# ---------------------------------------------------------------------------

def collect_cpu(sos_home):
    """
    Collect CPU count, model, and load averages.

    Returns:
        {
          'cpu_count': str,
          'cpu_model': str,
          'load_1m': str,
          'load_5m': str,
          'load_15m': str,
        }
    Returns {} on error.
    """
    data = {}
    try:
        cpu_count = 0
        model = ''
        with open(join(sos_home, "proc", "cpuinfo")) as f:
            for line in f:
                if line.startswith("processor"):
                    cpu_count += 1
                elif line.startswith("model name") and not model:
                    model = line.split(":", 1)[1].strip()
        data['cpu_count'] = str(cpu_count)
        if model:
            data['cpu_model'] = model
    except Exception:
        pass

    try:
        loadavg = _read_first_line(join(sos_home, "proc", "loadavg"))
        if loadavg:
            parts = loadavg.split()
            if len(parts) >= 3:
                data['load_1m']  = parts[0]
                data['load_5m']  = parts[1]
                data['load_15m'] = parts[2]
    except Exception:
        pass

    return data


def format_cpu(data1, data2):
    """Format CPU & load diff lines."""
    lines = [_section_header("CPU & Load")]
    keys = ['cpu_count', 'cpu_model', 'load_1m', 'load_5m', 'load_15m']
    key_labels = {
        'cpu_count':  'CPU Count',
        'cpu_model':  'CPU Model',
        'load_1m':    'Load Avg 1m',
        'load_5m':    'Load Avg 5m',
        'load_15m':   'Load Avg 15m',
    }
    lines += _format_dict_diff(data1, data2, keys=keys, key_label=key_labels)
    return lines


# ---------------------------------------------------------------------------
# Topic: processes
# ---------------------------------------------------------------------------

def collect_processes(sos_home):
    """
    Parse ps output to get top processes by RSS.

    Returns:
        {
          'top_procs': [(name, rss_kb), ...],   # top 10 by RSS
          'total_rss_kb': int,
          'proc_count': int,
        }
    Returns {} on error.
    """
    data = {'top_procs': [], 'total_rss_kb': 0, 'proc_count': 0}
    ps_file = join(sos_home, "ps")
    if not exists(ps_file):
        return data

    proc_rss = {}
    total = 0
    try:
        with open(ps_file) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 11:
                    continue
                if not parts[1].isdigit():
                    continue
                try:
                    rss = int(parts[5])
                    name = parts[10]
                    proc_rss[name] = proc_rss.get(name, 0) + rss
                    total += rss
                except (ValueError, IndexError):
                    continue
    except Exception:
        return data

    top10 = sorted(proc_rss.items(), key=lambda x: x[1], reverse=True)[:10]
    data['top_procs'] = top10
    data['total_rss_kb'] = total
    data['proc_count'] = len(proc_rss)
    return data


def format_processes(data1, data2):
    """Format processes diff lines."""
    lines = [_section_header("Top Processes by RSS")]

    # Overall stats
    for label, key in [("Total RSS", 'total_rss_kb'), ("Process Count", 'proc_count')]:
        v1 = data1.get(key)
        v2 = data2.get(key)
        if v1 is None and v2 is None:
            continue
        if key == 'total_rss_kb':
            s1 = _kb_to_str(v1 * 1024) if v1 else '(missing)'
            s2 = _kb_to_str(v2 * 1024) if v2 else '(missing)'
        else:
            s1 = str(v1) if v1 is not None else '(missing)'
            s2 = str(v2) if v2 is not None else '(missing)'
        if s1 == s2:
            lines.append(_diff_line_same(label, s1))
        else:
            lines.append(_diff_line_changed(label, s1, s2))

    lines.append("")
    lines.append(_section_header("Per-Process RSS"))

    procs1 = dict(data1.get('top_procs', []))
    procs2 = dict(data2.get('top_procs', []))
    all_procs = sorted(
        set(list(procs1.keys()) + list(procs2.keys())),
        key=lambda n: max(procs1.get(n, 0), procs2.get(n, 0)),
        reverse=True
    )[:15]

    for name in all_procs:
        r1 = procs1.get(name)
        r2 = procs2.get(name)
        s1 = _kb_to_str(r1 * 1024) if r1 is not None else '(missing)'
        s2 = _kb_to_str(r2 * 1024) if r2 is not None else '(missing)'
        label = name[:28]
        if s1 == s2:
            lines.append(_diff_line_same(label, s1))
        elif r1 is None:
            lines.append(_diff_line_only2(label, s2))
        elif r2 is None:
            lines.append(_diff_line_only1(label, s1))
        else:
            lines.append(_diff_line_changed(label, s1, s2))

    return lines


# ---------------------------------------------------------------------------
# Topic: network
# ---------------------------------------------------------------------------

def collect_network(sos_home):
    """
    Collect network interface names, states, and IP addresses.

    Returns:
        {
          'interfaces': {iface_name: {'state': str, 'ips': [str]}},
          'default_route': str,
        }
    Returns {} on error.
    """
    data = {'interfaces': {}, 'default_route': ''}

    # Try common file locations for ip address output
    addr_candidates = [
        join(sos_home, "sos_commands", "networking", "ip_-d_address"),
        join(sos_home, "sos_commands", "networking", "ip_address"),
    ]
    addr_path = next((p for p in addr_candidates if exists(p)), None)

    if addr_path:
        try:
            current = None
            with open(addr_path) as f:
                for line in f:
                    m = re.match(r'^\d+:\s+(\S+):\s+<([^>]+)>', line)
                    if m:
                        iface = re.sub(r'@.*$', '', m.group(1))
                        flags = m.group(2)
                        state = 'UP' if 'UP' in flags else 'DOWN'
                        current = iface
                        data['interfaces'][iface] = {'state': state, 'ips': []}
                    elif current:
                        m2 = re.search(r'inet6?\s+(\S+)', line)
                        if m2:
                            data['interfaces'][current]['ips'].append(m2.group(1))
        except Exception:
            pass

    # Default route
    route_candidates = [
        join(sos_home, "sos_commands", "networking", "ip_route_show_table_all"),
        join(sos_home, "sos_commands", "networking", "ip_route"),
        join(sos_home, "sos_commands", "networking", "route"),
    ]
    for rpath in route_candidates:
        if not exists(rpath):
            continue
        for line in _read_lines(rpath):
            if line.startswith("default") or "0.0.0.0" in line:
                data['default_route'] = line.strip()
                break
        if data['default_route']:
            break

    return data


def format_network(data1, data2):
    """Format network interfaces diff lines."""
    lines = [_section_header("Network Interfaces")]

    ifaces1 = data1.get('interfaces', {})
    ifaces2 = data2.get('interfaces', {})
    all_ifaces = sorted(set(list(ifaces1.keys()) + list(ifaces2.keys())))

    for iface in all_ifaces:
        i1 = ifaces1.get(iface)
        i2 = ifaces2.get(iface)
        if i1 is None:
            info = "state=%s ips=[%s]" % (i2['state'], ' '.join(i2['ips']) or 'none')
            lines.append(_diff_line_only2(iface, info))
        elif i2 is None:
            info = "state=%s ips=[%s]" % (i1['state'], ' '.join(i1['ips']) or 'none')
            lines.append(_diff_line_only1(iface, info))
        else:
            s1 = "state=%s ips=[%s]" % (i1['state'], ' '.join(i1['ips']) or 'none')
            s2 = "state=%s ips=[%s]" % (i2['state'], ' '.join(i2['ips']) or 'none')
            if s1 == s2:
                lines.append(_diff_line_same(iface, s1))
            else:
                lines.append(_diff_line_changed(iface, s1, s2))

    if not all_ifaces:
        lines.append(_ANSI_GREY + "  (no interface data available)" + _ANSI_RESET)

    # Default route
    lines.append("")
    r1 = data1.get('default_route', '')
    r2 = data2.get('default_route', '')
    if r1 or r2:
        if r1 == r2:
            lines.append(_diff_line_same("Default Route", r1 or '(none)'))
        else:
            lines.append(_diff_line_changed("Default Route",
                                            r1 or '(none)', r2 or '(none)'))

    return lines


# ---------------------------------------------------------------------------
# Topic: cgroups
# ---------------------------------------------------------------------------

def collect_cgroups(sos_home):
    """
    Detect cgroup version and list subsystems/controllers.

    Returns:
        {
          'cgroup_version': str,          # v1 / v2 / hybrid / unknown
          'cgroup_controllers': str,      # v2 controllers (space-separated)
          'subsystem_count': str,         # v1 subsystem directory count
          'subsystems': str,              # comma-separated subsystem names
        }
    Returns {} on error.
    """
    data = {}
    has_v1 = has_v2 = False

    try:
        with open(join(sos_home, "proc", "mounts")) as f:
            for line in f:
                if "cgroup2" in line:
                    has_v2 = True
                elif "cgroup " in line and "/sys/fs/cgroup/" in line:
                    has_v1 = True
    except Exception:
        pass

    if has_v1 and has_v2:
        data['cgroup_version'] = 'hybrid'
    elif has_v2:
        data['cgroup_version'] = 'v2'
    elif has_v1:
        data['cgroup_version'] = 'v1'
    else:
        data['cgroup_version'] = 'unknown'

    cgroup_dir = join(sos_home, "sys", "fs", "cgroup")
    if os.path.isdir(cgroup_dir):
        try:
            subsystems = sorted(
                d for d in os.listdir(cgroup_dir)
                if os.path.isdir(join(cgroup_dir, d))
            )
            data['subsystem_count'] = str(len(subsystems))
            data['subsystems'] = ','.join(subsystems[:10])
        except Exception:
            pass

    controllers_path = join(sos_home, "sys", "fs", "cgroup", "cgroup.controllers")
    if exists(controllers_path):
        data['cgroup_controllers'] = _read_first_line(controllers_path)

    return data


def format_cgroups(data1, data2):
    """Format cgroup status diff lines."""
    lines = [_section_header("Cgroup Status")]
    keys = ['cgroup_version', 'cgroup_controllers', 'subsystem_count', 'subsystems']
    key_labels = {
        'cgroup_version':     'Cgroup Version',
        'cgroup_controllers': 'Controllers (v2)',
        'subsystem_count':    'Subsystem Count',
        'subsystems':         'Subsystems',
    }
    lines += _format_dict_diff(data1, data2, keys=keys, key_label=key_labels)
    return lines


# ---------------------------------------------------------------------------
# Topic: storage
# ---------------------------------------------------------------------------

def collect_storage(sos_home):
    """
    Collect LVM volume group and logical volume info.

    Returns:
        {
          'vg_count': str,
          'lv_count': str,
          'vgs': [{'name', 'pv_count', 'lv_count', 'vsize', 'vfree'}],
          'lvs': [{'name', 'vg', 'size'}],
        }
    Returns {} on error.
    """
    data = {'vgs': [], 'lvs': [], 'vg_count': '0', 'lv_count': '0'}
    lvm2_dir = join(sos_home, "sos_commands", "lvm2")
    if not os.path.isdir(lvm2_dir):
        return data

    try:
        for fname in sorted(os.listdir(lvm2_dir)):
            if not fname.startswith("vgs"):
                continue
            with open(join(lvm2_dir, fname)) as f:
                for line in f:
                    line = line.strip()
                    parts = line.split()
                    if (not parts or parts[0] in ("VG", "WARNING", "Reloading")
                            or line.startswith("#")):
                        continue
                    if len(parts) >= 8:
                        data['vgs'].append({
                            'name':     parts[0],
                            'pv_count': parts[3],
                            'lv_count': parts[4],
                            'vsize':    parts[6],
                            'vfree':    parts[7],
                        })
            break
    except Exception:
        pass

    try:
        for fname in sorted(os.listdir(lvm2_dir)):
            if not fname.startswith("lvs"):
                continue
            with open(join(lvm2_dir, fname)) as f:
                for line in f:
                    line = line.strip()
                    parts = line.split()
                    if (not parts or parts[0] in ("LV", "WARNING", "Reloading")
                            or line.startswith("#")):
                        continue
                    if len(parts) >= 4:
                        data['lvs'].append({
                            'name': parts[0],
                            'vg':   parts[1],
                            'size': parts[3],
                        })
            break
    except Exception:
        pass

    data['vg_count'] = str(len(data['vgs']))
    data['lv_count'] = str(len(data['lvs']))
    return data


def format_storage(data1, data2):
    """Format storage/LVM diff lines."""
    lines = [_section_header("Storage / LVM")]

    for label, key in [("Volume Group Count", 'vg_count'),
                        ("Logical Volume Count", 'lv_count')]:
        v1 = data1.get(key, '(missing)')
        v2 = data2.get(key, '(missing)')
        if v1 == v2:
            lines.append(_diff_line_same(label, v1))
        else:
            lines.append(_diff_line_changed(label, v1, v2))

    lines.append("")
    lines.append(_section_header("Volume Groups"))
    vgs1 = {vg['name']: vg for vg in data1.get('vgs', [])}
    vgs2 = {vg['name']: vg for vg in data2.get('vgs', [])}
    all_vgs = sorted(set(list(vgs1.keys()) + list(vgs2.keys())))

    for vgname in all_vgs:
        vg1 = vgs1.get(vgname)
        vg2 = vgs2.get(vgname)
        if vg1 is None:
            lines.append(_diff_line_only2(
                vgname, "size=%s free=%s" % (vg2['vsize'], vg2['vfree'])))
        elif vg2 is None:
            lines.append(_diff_line_only1(
                vgname, "size=%s free=%s" % (vg1['vsize'], vg1['vfree'])))
        else:
            s1 = "size=%s free=%s" % (vg1['vsize'], vg1['vfree'])
            s2 = "size=%s free=%s" % (vg2['vsize'], vg2['vfree'])
            if s1 == s2:
                lines.append(_diff_line_same(vgname, s1))
            else:
                lines.append(_diff_line_changed(vgname, s1, s2))

    if not all_vgs:
        lines.append(_ANSI_GREY + "  (no LVM data available)" + _ANSI_RESET)

    return lines


# ---------------------------------------------------------------------------
# Topic: hardware
# ---------------------------------------------------------------------------

def collect_hardware(sos_home):
    """
    Collect hardware info from dmidecode: manufacturer, product, BIOS.

    Returns:
        {
          'manufacturer': str,
          'product': str,
          'serial': str,
          'bios_version': str,
          'bios_date': str,
        }
    Returns {} on error.
    """
    data = {}
    dmi_candidates = [
        join(sos_home, "sos_commands", "hardware", "dmidecode"),
        join(sos_home, "dmidecode"),
    ]
    dmi_path = next((p for p in dmi_candidates if exists(p)), None)
    if not dmi_path:
        return data

    try:
        current_section = None
        with open(dmi_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped == "System Information":
                    current_section = "system"
                elif stripped == "BIOS Information":
                    current_section = "bios"
                elif stripped.startswith("Handle ") and current_section:
                    current_section = None

                if current_section == "system":
                    if stripped.startswith("Manufacturer:"):
                        data['manufacturer'] = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("Product Name:"):
                        data['product'] = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("Serial Number:"):
                        data['serial'] = stripped.split(":", 1)[1].strip()
                elif current_section == "bios":
                    if stripped.startswith("Version:"):
                        data['bios_version'] = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("Release Date:"):
                        data['bios_date'] = stripped.split(":", 1)[1].strip()
    except Exception:
        pass

    return data


def format_hardware(data1, data2):
    """Format hardware info diff lines."""
    lines = [_section_header("Hardware Information")]
    keys = ['manufacturer', 'product', 'serial', 'bios_version', 'bios_date']
    key_labels = {
        'manufacturer': 'Manufacturer',
        'product':      'Product Name',
        'serial':       'Serial Number',
        'bios_version': 'BIOS Version',
        'bios_date':    'BIOS Date',
    }
    lines += _format_dict_diff(data1, data2, keys=keys, key_label=key_labels)
    return lines


# ---------------------------------------------------------------------------
# Topic: logs
# ---------------------------------------------------------------------------

def collect_logs(sos_home):
    """
    Scan system log files and count notable event types.

    Returns:
        {
          'error_count': str,
          'warn_count': str,
          'crit_count': str,
          'oom_count': str,
          'oops_count': str,
        }
    Returns {} on error.
    """
    counts = {
        'error_count': 0,
        'warn_count':  0,
        'crit_count':  0,
        'oom_count':   0,
        'oops_count':  0,
    }

    log_paths = []
    for rel in ["var/log/messages", "var/log/syslog"]:
        p = join(sos_home, rel)
        if exists(p):
            log_paths.append(p)

    journal_dir = join(sos_home, "sos_commands", "logs")
    if os.path.isdir(journal_dir):
        for fname in sorted(os.listdir(journal_dir)):
            if fname.startswith("journalctl"):
                log_paths.append(join(journal_dir, fname))
                break

    for log_path in log_paths:
        try:
            with open(log_path, errors='replace') as f:
                for line in f:
                    ll = line.lower()
                    if ' error ' in ll or ': error:' in ll:
                        counts['error_count'] += 1
                    if ' warning ' in ll or ': warning:' in ll:
                        counts['warn_count'] += 1
                    if 'critical' in ll:
                        counts['crit_count'] += 1
                    if 'invoked oom-killer' in ll:
                        counts['oom_count'] += 1
                    if 'kernel oops' in ll or 'oops:' in ll:
                        counts['oops_count'] += 1
        except Exception:
            continue

    return {k: str(v) for k, v in counts.items()}


def format_logs(data1, data2):
    """Format log diff lines."""
    lines = [_section_header("Critical Log Entries")]
    keys = ['error_count', 'warn_count', 'crit_count', 'oom_count', 'oops_count']
    key_labels = {
        'error_count': 'Error Count',
        'warn_count':  'Warning Count',
        'crit_count':  'Critical Count',
        'oom_count':   'OOM Killer Events',
        'oops_count':  'Kernel Oops',
    }
    lines += _format_dict_diff(data1, data2, keys=keys, key_label=key_labels)
    return lines


# ---------------------------------------------------------------------------
# Topic: autocheck
# ---------------------------------------------------------------------------

def collect_autocheck(sos_home):
    """
    Scan kernel logs for patterns that autocheck rules detect.

    Returns:
        {
          'rcu_stall': str,
          'hung_task': str,
          'softlockup': str,
          'hardlockup': str,
          'call_trace': str,
          'oom_kill': str,
          'panic': str,
          'mcelog': str,
        }
    Returns {} on error.
    """
    patterns = {
        'rcu_stall':  r'rcu.*stall',
        'hung_task':  r'INFO: task .* blocked for more than',
        'softlockup': r'soft lockup',
        'hardlockup': r'hard lockup',
        'call_trace': r'Call Trace:',
        'oom_kill':   r'Out of memory.*Killed process',
        'panic':      r'Kernel panic',
        'mcelog':     r'Machine Check Exception',
    }

    log_candidates = [
        join(sos_home, "var", "log", "messages"),
        join(sos_home, "var", "log", "dmesg"),
        join(sos_home, "sos_commands", "kernel", "dmesg"),
    ]
    log_paths = [p for p in log_candidates if exists(p)]

    counts = {k: 0 for k in patterns}
    for log_path in log_paths:
        try:
            with open(log_path, errors='replace') as f:
                for line in f:
                    for key, pattern in patterns.items():
                        if re.search(pattern, line, re.IGNORECASE):
                            counts[key] += 1
        except Exception:
            continue

    return {k: str(v) for k, v in counts.items()}


def format_autocheck(data1, data2):
    """Format autocheck findings diff lines."""
    lines = [_section_header("Autocheck Findings")]
    keys = ['rcu_stall', 'hung_task', 'softlockup', 'hardlockup',
            'call_trace', 'oom_kill', 'panic', 'mcelog']
    key_labels = {
        'rcu_stall':  'RCU Stall',
        'hung_task':  'Hung Task',
        'softlockup': 'Soft Lockup',
        'hardlockup': 'Hard Lockup',
        'call_trace': 'Call Traces',
        'oom_kill':   'OOM Kill Events',
        'panic':      'Kernel Panic',
        'mcelog':     'Machine Check Exceptions',
    }
    lines += _format_dict_diff(data1, data2, keys=keys, key_label=key_labels)
    return lines


# ---------------------------------------------------------------------------
# Topic registry
# ---------------------------------------------------------------------------

TOPICS = [
    CompareTopic("system",    "System Info",        collect_system,    format_system),
    CompareTopic("memory",    "Memory Usage",       collect_memory,    format_memory),
    CompareTopic("cpu",       "CPU & Load",         collect_cpu,       format_cpu),
    CompareTopic("processes", "Top Processes",      collect_processes, format_processes),
    CompareTopic("network",   "Network Interfaces", collect_network,   format_network),
    CompareTopic("cgroups",   "Cgroup Status",      collect_cgroups,   format_cgroups),
    CompareTopic("storage",   "Storage/LVM",        collect_storage,   format_storage),
    CompareTopic("hardware",  "Hardware Info",      collect_hardware,  format_hardware),
    CompareTopic("logs",      "Critical Logs",      collect_logs,      format_logs),
    CompareTopic("autocheck", "Autocheck Findings", collect_autocheck, format_autocheck),
]


def get_topic(key):
    """Return CompareTopic by key, or None if not found."""
    for t in TOPICS:
        if t.key == key:
            return t
    return None


# ---------------------------------------------------------------------------
# isos command interface (returns False so this module is not loaded as a command)
# ---------------------------------------------------------------------------

def add_command():
    """Do not load this module as a command - it's a library for compare.py."""
    return False
