"""
PCP (Performance Co-Pilot) data analyzer for isos.

Locates and parses PCP performance data from sosreports, extracting CPU,
memory, disk I/O, and network metrics. Supports text file output for
offline analysis and trend reporting.

PCP data locations in sosreports:
  - sos_commands/pcp/           : pmrep CSV/text output
  - var/log/pcp/pmlogger/<host>/: binary PCP archives (requires pmrep)
"""

import sys
import os
import glob
import csv
import re
import subprocess
import tempfile
import json
import gzip
import hashlib
from datetime import datetime
from optparse import OptionParser
from os.path import isfile, isdir, join, basename, dirname
from collections import defaultdict
from io import StringIO

import screen
from table_formatter import create_table
from cmd_helpers import ColorManager, OutputBuilder

# ---------------------------------------------------------------------------
# PCP metric name mappings (PCP metric -> short label)
# ---------------------------------------------------------------------------

CPU_METRICS = {
    'kernel.cpu.util.user':     'user',
    'kernel.cpu.util.sys':      'sys',
    'kernel.cpu.util.idle':     'idle',
    'kernel.cpu.util.wait':     'wait',
    'kernel.cpu.util.nice':     'nice',
    'kernel.cpu.util.steal':    'steal',
    'kernel.cpu.util.irq.hard': 'irqhard',
    'kernel.cpu.util.irq.soft': 'irqsoft',
}

MEM_METRICS = {
    'mem.util.used':      'used',
    'mem.util.free':      'free',
    'mem.util.available': 'available',
    'mem.util.cached':    'cached',
    'mem.util.bufmem':    'bufmem',
    'mem.util.swapFree':  'swap_free',
    'mem.util.swapTotal': 'swap_total',
    'mem.physmem':        'total',
}

DISK_METRICS = {
    'disk.all.read':        'read_iops',
    'disk.all.write':       'write_iops',
    'disk.all.read_bytes':  'read_bytes',
    'disk.all.write_bytes': 'write_bytes',
    'disk.all.avactive':    'avactive',
}

NET_METRICS = {
    'network.interface.in.bytes':    'in_bytes',
    'network.interface.out.bytes':   'out_bytes',
    'network.interface.in.packets':  'in_pkts',
    'network.interface.out.packets': 'out_pkts',
    'network.interface.in.errors':   'in_errors',
    'network.interface.out.errors':  'out_errors',
}

PROC_METRICS = {
    'proc.hog.cpu': 'cpu_util',
}

# All known metric names (flat set for lookup)
ALL_METRICS = {}
ALL_METRICS.update(CPU_METRICS)
ALL_METRICS.update(MEM_METRICS)
ALL_METRICS.update(DISK_METRICS)
ALL_METRICS.update(NET_METRICS)
ALL_METRICS.update(PROC_METRICS)

# Metric categories that are per-instance (e.g. per interface, per disk)
PER_INSTANCE_PREFIXES = ('network.interface.', 'proc.')

# ---------------------------------------------------------------------------
# Module globals
# ---------------------------------------------------------------------------

sos_home = ""
is_cmd_stopped = None


def description():
    return "Analyzes PCP (Performance Co-Pilot) performance data"


def add_command():
    return True


cmd_name = "pcpinfo"


def get_command_info():
    return {cmd_name: run_pcpinfo}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class PCPData:
    """Container for parsed PCP performance metrics."""

    def __init__(self):
        self.timestamps = []       # list of datetime objects
        self.cpu = defaultdict(list)   # label -> [float values]
        self.mem = defaultdict(list)   # label -> [float values]
        self.disk = defaultdict(list)  # label -> [float values]
        # network: {iface -> {label -> [float values]}}
        self.network = defaultdict(lambda: defaultdict(list))
        # process CPU: {pid_str -> [float values aligned with timestamps]}
        self.proc_cpu = defaultdict(list)
        self.source = ""           # data source description
        self.hostname = ""
        self.has_cpu = False
        self.has_mem = False
        self.has_disk = False
        self.has_network = False
        self.has_proc = False

    @property
    def start_time(self):
        return self.timestamps[0] if self.timestamps else None

    @property
    def end_time(self):
        return self.timestamps[-1] if self.timestamps else None

    @property
    def duration_minutes(self):
        if len(self.timestamps) >= 2:
            delta = self.timestamps[-1] - self.timestamps[0]
            return delta.total_seconds() / 60.0
        return 0.0

    def is_empty(self):
        return len(self.timestamps) == 0


# ---------------------------------------------------------------------------
# PCP data file locator
# ---------------------------------------------------------------------------

def find_pcp_files(sos_home_path):
    """
    Find PCP data files in the sosreport directory tree.

    Returns a dict with:
      'csv_files':    list of pmrep CSV text files
      'archive_dirs': list of pmlogger archive directories
      'pcp_cmd_dir':  path to sos_commands/pcp (or None)
    """
    result = {
        'csv_files':    [],
        'archive_dirs': [],
        'pcp_cmd_dir':  None,
    }

    # 1. sos_commands/pcp/ directory
    pcp_cmd_dir = join(sos_home_path, 'sos_commands', 'pcp')
    if isdir(pcp_cmd_dir):
        result['pcp_cmd_dir'] = pcp_cmd_dir
        # Find all files in the pcp command dir (pmrep outputs, etc.)
        for fname in os.listdir(pcp_cmd_dir):
            fpath = join(pcp_cmd_dir, fname)
            if isfile(fpath):
                result['csv_files'].append(fpath)

    # 2. var/log/pcp/pmlogger/<hostname>/ directories (binary archives)
    pmlogger_base = join(sos_home_path, 'var', 'log', 'pcp', 'pmlogger')
    if isdir(pmlogger_base):
        for entry in os.listdir(pmlogger_base):
            archive_dir = join(pmlogger_base, entry)
            if isdir(archive_dir):
                # Check for archive files — require both .index and .meta
                # (.index alone is not enough; pmrep needs the .meta file too)
                dir_files = os.listdir(archive_dir)
                has_archives = (
                    any(f.endswith('.index') for f in dir_files) and
                    any(f.endswith('.meta')  for f in dir_files)
                )
                if has_archives:
                    result['archive_dirs'].append(archive_dir)

    return result


# ---------------------------------------------------------------------------
# pmrep CSV parser
# ---------------------------------------------------------------------------

def _parse_timestamp(ts_str):
    """Parse timestamp from pmrep CSV. Tries multiple common formats."""
    ts_str = ts_str.strip()
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%a %b %d %H:%M:%S %Y',
        '%H:%M:%S',
        '%b %d %H:%M:%S %Y',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            pass
    return None


def _looks_like_csv(lines):
    """Return True if the file looks like a pmrep CSV output."""
    for line in lines[:20]:
        if line.startswith('#'):
            continue
        if ',' in line:
            return True
        break
    return False


def _classify_metric(col_header):
    """
    Given a CSV column header (possibly with instance suffix like
    'network.interface.in.bytes::eth0' or 'network.interface.in.bytes[eth0]'),
    return (category, pcp_name, instance).
    """
    # Instance metrics: "metric.name::instance" (pmrep >= 5.x)
    if '::' in col_header:
        pcp_name, instance = col_header.split('::', 1)
    # Instance metrics: "metric.name[instance]" (pmrep < 5.x)
    elif '[' in col_header and col_header.endswith(']'):
        bracket = col_header.index('[')
        pcp_name = col_header[:bracket]
        instance = col_header[bracket + 1:-1]
    # Instance metrics: "proc.hog.cpu-PID processname" format (pmrep 6.x)
    elif col_header.startswith('proc.hog.cpu-'):
        # Format: "proc.hog.cpu-000001 /usr/lib/systemd/systemd"
        parts = col_header.split(None, 1)  # Split on first whitespace
        if len(parts) >= 1:
            metric_instance = parts[0]  # "proc.hog.cpu-000001"
            pcp_name = 'proc.hog.cpu'
            instance = metric_instance[len('proc.hog.cpu-'):]  # Extract PID
            if len(parts) == 2:
                # Include process name in instance for better identification
                instance = parts[1]  # Use process name as instance
        else:
            pcp_name = col_header
            instance = None
    else:
        pcp_name = col_header
        instance = None

    pcp_name = pcp_name.strip()

    if pcp_name in CPU_METRICS:
        return 'cpu', pcp_name, instance
    if pcp_name in MEM_METRICS:
        return 'mem', pcp_name, instance
    if pcp_name in DISK_METRICS:
        return 'disk', pcp_name, instance
    if pcp_name in NET_METRICS:
        return 'net', pcp_name, instance
    if pcp_name in PROC_METRICS:
        return 'proc', pcp_name, instance

    # Prefix-based matching for partial metric names
    for known in CPU_METRICS:
        if pcp_name.startswith(known) or known.startswith(pcp_name):
            return 'cpu', known, instance
    for known in MEM_METRICS:
        if pcp_name.startswith(known) or known.startswith(pcp_name):
            return 'mem', known, instance
    for known in DISK_METRICS:
        if pcp_name.startswith(known) or known.startswith(pcp_name):
            return 'disk', known, instance
    for known in NET_METRICS:
        if pcp_name.startswith(known) or known.startswith(pcp_name):
            return 'net', known, instance
    for known in PROC_METRICS:
        if pcp_name.startswith(known) or known.startswith(pcp_name):
            return 'proc', known, instance

    return None, pcp_name, instance


def parse_pmrep_csv(filepath, data):
    """
    Parse a pmrep CSV output file into a PCPData object.
    Merges data into the provided PCPData instance.

    pmrep CSV format:
        # comment lines...
        Timestamp,kernel.cpu.util.user,kernel.cpu.util.sys,...
        2024-01-15 10:00:00,12.5,5.3,...
    """
    try:
        with open(filepath) as f:
            raw = f.readlines()
    except Exception:
        return False

    if not raw:
        return False

    # Skip comment lines to find header
    header_idx = None
    _metric_prefixes = ('kernel.', 'mem.', 'disk.', 'network.', 'proc.',
                        'Timestamp', 'timestamp', 'time')
    for i, line in enumerate(raw):
        stripped = line.strip()
        if stripped.startswith('#') or not stripped:
            continue
        if 'Timestamp' in stripped or stripped.startswith('time'):
            header_idx = i
            break
        # Accept as header only if it contains a known PCP metric prefix —
        # avoids misidentifying pmrep warning lines as the CSV header.
        if ',' in stripped and not stripped[0].isdigit():
            if any(p in stripped for p in _metric_prefixes):
                header_idx = i
                break

    if header_idx is None:
        return False

    # Parse header columns
    reader = csv.reader([raw[header_idx]])
    headers = [h.strip() for h in next(reader)]

    if len(headers) < 2:
        return False

    # Map column index -> (category, pcp_name, instance)
    col_map = {}
    ncpu_col = None  # column index for hinv.ncpu (CPU count metric)
    for idx, hdr in enumerate(headers):
        if idx == 0:
            continue  # timestamp column
        if hdr.strip() == 'hinv.ncpu':
            ncpu_col = idx
            continue
        cat, pcp_name, instance = _classify_metric(hdr)
        if cat:
            col_map[idx] = (cat, pcp_name, instance)

    if not col_map:
        return False

    # Remember starting position to normalize only newly-added CPU values
    start_idx = len(data.timestamps)

    # Parse data rows
    parsed_any = False
    ncpu = 0.0
    for line in raw[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        try:
            row = next(csv.reader([stripped]))
        except StopIteration:
            continue

        if len(row) < 2:
            continue

        ts = _parse_timestamp(row[0])
        if ts is None:
            continue

        data.timestamps.append(ts)
        parsed_any = True

        # Capture CPU count (constant value; take any valid reading)
        if ncpu_col is not None and ncpu_col < len(row):
            try:
                v = float(row[ncpu_col])
                if v > 0:
                    ncpu = v
            except (ValueError, TypeError):
                pass

        for idx, (cat, pcp_name, instance) in col_map.items():
            if idx >= len(row):
                continue
            try:
                val = float(row[idx])
            except (ValueError, TypeError):
                val = 0.0

            label = ALL_METRICS.get(pcp_name, pcp_name.split('.')[-1])

            if cat == 'cpu':
                data.cpu[label].append(val)
                data.has_cpu = True
            elif cat == 'mem':
                data.mem[label].append(val)
                data.has_mem = True
            elif cat == 'disk':
                data.disk[label].append(val)
                data.has_disk = True
            elif cat == 'net':
                iface = instance if instance else 'all'
                data.network[iface][label].append(val)
                data.has_network = True
            elif cat == 'proc':
                pid_str = instance if instance else 'unknown'
                data.proc_cpu[pid_str].append(val)
                data.has_proc = True

    # Normalize CPU series by CPU count to convert per-CPU sums to percentages
    if ncpu > 1 and parsed_any:
        for label in list(data.cpu.keys()):
            series = data.cpu[label]
            for i in range(start_idx, len(series)):
                series[i] /= ncpu

    return parsed_any


def parse_pmrep_text(filepath, data):
    """
    Parse pmrep columnar text output (non-CSV format).

    pmrep text format (space-aligned columns):
        #           kernel        kernel
        #              cpu           cpu
        #             util          util
        Timestamp    user          sys
        2024-01-15   12.50         5.30
    """
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except Exception:
        return False

    if not lines:
        return False

    # Find header line (contains 'Timestamp')
    header_idx = None
    for i, line in enumerate(lines):
        if 'Timestamp' in line and not line.strip().startswith('#'):
            header_idx = i
            break

    if header_idx is None:
        return False

    # Gather metric names from comment lines above header
    metric_comments = []
    for i in range(max(0, header_idx - 5), header_idx):
        if lines[i].strip().startswith('#'):
            metric_comments.append(lines[i].strip('#').strip())

    # Parse header to get column positions
    header = lines[header_idx]
    # Build column offsets from header tokens
    tokens = re.findall(r'\S+', header)
    if len(tokens) < 2:
        return False

    # For text format, we use a simple positional approach
    # Try to match column names against known metrics
    col_labels = []
    for token in tokens[1:]:  # skip 'Timestamp'
        cat, pcp_name, _ = _classify_metric(token)
        label = ALL_METRICS.get(pcp_name, token) if cat else token
        col_labels.append((cat, label))

    parsed_any = False
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        words = stripped.split()
        if len(words) < 2:
            continue

        ts = _parse_timestamp(words[0])
        if ts is None:
            continue

        data.timestamps.append(ts)
        parsed_any = True

        for i, (cat, label) in enumerate(col_labels):
            if i + 1 >= len(words):
                break
            try:
                val = float(words[i + 1])
            except (ValueError, TypeError):
                val = 0.0

            if cat == 'cpu':
                data.cpu[label].append(val)
                data.has_cpu = True
            elif cat == 'mem':
                data.mem[label].append(val)
                data.has_mem = True
            elif cat == 'disk':
                data.disk[label].append(val)
                data.has_disk = True
            elif cat == 'net':
                data.network['all'][label].append(val)
                data.has_network = True

    return parsed_any


# ---------------------------------------------------------------------------
# pmrep binary archive parser (via subprocess)
# ---------------------------------------------------------------------------

def _find_pmrep():
    """Return path to pmrep binary, or None if not found."""
    for candidate in ('pmrep', '/usr/bin/pmrep', '/usr/local/bin/pmrep'):
        try:
            result = subprocess.run(
                [candidate, '--version'],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    return None


def _run_pmrep_archive(pmrep, archive_path, include_proc=False):
    """Run pmrep on a single archive base path, return CSV text or None on failure.

    Retries with reduced metric list if pmrep reports unknown/unavailable metrics.
    """
    metrics = (['hinv.ncpu'] + list(CPU_METRICS.keys()) + list(MEM_METRICS.keys()) +
               list(DISK_METRICS.keys()) + list(NET_METRICS.keys()))
    if include_proc:
        metrics += list(PROC_METRICS.keys())

    # Try up to 3 times, removing failing metrics each iteration
    for attempt in range(3):
        # Use larger interval for proc metrics to avoid timeout with massive CSV
        interval = '300s' if include_proc else '60s'
        cmd = [
            pmrep, '-a', archive_path,
            '-t', interval,
            '-o', 'csv',
        ] + metrics

        try:
            # Proc metrics require longer timeout due to .xz decompression (6+ min per archive)
            proc_timeout = 900 if include_proc else 300
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=proc_timeout)
            if result.returncode == 0 and result.stdout:
                return result.stdout

            # Parse stderr for unavailable metrics (PM_ERR_NAME, "not in"/"unknown"/"invalid")
            if result.stderr:
                import re
                # pmrep 6.x format: "Invalid metric kernel.cpu.util.irq.hard (PM_ERR_NAME ...)"
                # pmrep 5.x format: "kernel.cpu.util.irq.hard: Unknown metric name"
                bad_metrics = re.findall(
                    r'(?:Invalid|Unknown) metric\s+([a-z][a-z0-9._]+(?:\.[a-z][a-z0-9._]+)*)'
                    r'|([a-z][a-z0-9._]+(?:\.[a-z][a-z0-9._]+)*)\s*[:\-]?\s*(?:Unknown|not in|Invalid|unavailable)',
                    result.stderr, re.IGNORECASE
                )
                # findall returns tuples when there are groups; flatten and filter empty strings
                bad_metrics = [m for tup in bad_metrics for m in tup if m]
                if bad_metrics:
                    # Remove the failing metrics and retry
                    metrics = [m for m in metrics if m not in bad_metrics]
                    if not metrics:
                        return None  # No metrics left to try
                    continue

            # No specific metrics identified, can't retry
            return None

        except (subprocess.TimeoutExpired, OSError):
            return None

    return None  # Max retries exhausted


def _sort_and_dedup_pcp_data(data):
    """
    Sort all time-series in data by timestamp (ascending) and remove
    duplicate timestamps that can occur when archive time ranges overlap.
    """
    n = len(data.timestamps)
    if n < 2:
        return

    # Build a sorted index permutation, deduplicate in one pass
    order = sorted(range(n), key=lambda i: data.timestamps[i])
    keep = []
    seen = None
    for i in order:
        ts = data.timestamps[i]
        if ts != seen:
            keep.append(i)
            seen = ts

    if len(keep) == n and all(keep[i] == i for i in range(n)):
        return  # Already sorted and no duplicates

    def _reorder(lst):
        return [lst[i] for i in keep if i < len(lst)]

    data.timestamps = _reorder(data.timestamps)
    for label in list(data.cpu.keys()):
        data.cpu[label] = _reorder(data.cpu[label])
    for label in list(data.mem.keys()):
        data.mem[label] = _reorder(data.mem[label])
    for label in list(data.disk.keys()):
        data.disk[label] = _reorder(data.disk[label])
    for iface in data.network:
        for label in list(data.network[iface].keys()):
            data.network[iface][label] = _reorder(data.network[iface][label])
    for pid_str in list(data.proc_cpu.keys()):
        data.proc_cpu[pid_str] = _reorder(data.proc_cpu[pid_str])


# ---------------------------------------------------------------------------
# Cache functions for PCP archive processing
# ---------------------------------------------------------------------------

def _cache_path(archive_dir):
    """Return path to cache file for the given archive directory."""
    cache_file = join(archive_dir, '.pcpinfo_cache.json.gz')
    # Check if writable
    if os.access(archive_dir, os.W_OK):
        return cache_file
    # Fallback to ~/.cache/isos/pcp/ if archive dir is read-only
    cache_dir = os.path.expanduser('~/.cache/isos/pcp')
    try:
        os.makedirs(cache_dir, exist_ok=True)
        # Use hash of absolute path to avoid collisions
        path_hash = hashlib.sha256(os.path.abspath(archive_dir).encode()).hexdigest()[:8]
        return join(cache_dir, '%s_%s.json.gz' % (basename(archive_dir), path_hash))
    except (OSError, IOError):
        return cache_file  # Return primary path even if fallback fails


def _build_manifest(archive_dir):
    """Build manifest of archive files with their mtimes."""
    manifest = {}
    for ext in ('*.index', '*.meta'):
        for fpath in glob.glob(join(archive_dir, ext)):
            fname = basename(fpath)
            try:
                mtime = os.path.getmtime(fpath)
                manifest[fname] = mtime
            except OSError:
                pass
    return manifest


def _is_cache_valid(cache_meta, archive_dir, include_proc, all_archives):
    """Check if cache is valid for current request."""
    # Version mismatch
    if cache_meta.get('cache_version') != 1:
        return False

    # Check archive manifest
    current_manifest = _build_manifest(archive_dir)
    cached_manifest = cache_meta.get('archive_manifest', {})
    if current_manifest != cached_manifest:
        return False

    # Check if cache has sufficient data for request
    cached_proc = cache_meta.get('include_proc', False)
    cached_all = cache_meta.get('all_archives', False)

    # If user wants proc but cache doesn't have it, invalid
    if include_proc and not cached_proc:
        return False

    # If user wants all archives but cache only has subset, invalid
    if all_archives and not cached_all:
        return False

    return True


def _load_cache(archive_dir, include_proc, all_archives, no_cache=False, refresh_cache=False):
    """Load cache if valid, return None if invalid or missing."""
    # Skip cache if user requested no-cache or refresh-cache
    if no_cache or refresh_cache:
        return None

    cache_file = _cache_path(archive_dir)
    if not os.path.exists(cache_file):
        return None

    try:
        with gzip.open(cache_file, 'rt', encoding='utf-8') as f:
            cache = json.load(f)

        meta = cache.get('meta', {})
        if not _is_cache_valid(meta, archive_dir, include_proc, all_archives):
            return None

        print("Using cached PCP data (processed %s)." % meta.get('created_at', 'unknown'),
              file=sys.stderr)
        return cache

    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        print("Note: PCP cache invalid (%s), reprocessing archives..." % str(e),
              file=sys.stderr)
        # Try to remove corrupt cache
        try:
            os.unlink(cache_file)
        except (OSError, IOError):
            pass
        return None


def _save_cache(archive_dir, data, include_proc, all_archives, index_files):
    """Save processed data to cache."""
    cache_file = _cache_path(archive_dir)

    try:
        # Build cache structure
        cache = {
            'meta': {
                'cache_version': 1,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'archive_manifest': _build_manifest(archive_dir),
                'include_proc': include_proc,
                'all_archives': all_archives,
                'archives_processed': [basename(f)[:-6] for f in index_files],  # Remove .index
                'source': archive_dir,
                'hostname': data.hostname or ''
            },
            'data': {
                'timestamps': [ts.strftime('%Y-%m-%dT%H:%M:%S') for ts in data.timestamps],
                'cpu': dict(data.cpu),
                'mem': dict(data.mem),
                'disk': dict(data.disk),
                'network': {iface: dict(labels) for iface, labels in data.network.items()},
                'proc_cpu': dict(data.proc_cpu),
                'has_cpu': data.has_cpu,
                'has_mem': data.has_mem,
                'has_disk': data.has_disk,
                'has_network': data.has_network,
                'has_proc': data.has_proc
            }
        }

        # Write atomically (write to temp, then rename)
        temp_file = cache_file + '.tmp'
        with gzip.open(temp_file, 'wt', encoding='utf-8', compresslevel=6) as f:
            json.dump(cache, f, indent=2)
        os.rename(temp_file, cache_file)

    except (IOError, OSError) as e:
        print("Note: Could not write PCP cache (%s), continuing without cache." % str(e),
              file=sys.stderr)
        # Clean up temp file if it exists
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
        except (OSError, IOError):
            pass


def _apply_cache_to_data(cache, data):
    """Populate PCPData object from cache dictionary."""
    cache_data = cache.get('data', {})
    cache_meta = cache.get('meta', {})

    # Parse timestamps
    data.timestamps = []
    for ts_str in cache_data.get('timestamps', []):
        try:
            data.timestamps.append(datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%S'))
        except ValueError:
            pass

    # Restore metrics
    for label, values in cache_data.get('cpu', {}).items():
        data.cpu[label] = list(values)
    for label, values in cache_data.get('mem', {}).items():
        data.mem[label] = list(values)
    for label, values in cache_data.get('disk', {}).items():
        data.disk[label] = list(values)
    for iface, labels in cache_data.get('network', {}).items():
        for label, values in labels.items():
            data.network[iface][label] = list(values)
    for pid_str, values in cache_data.get('proc_cpu', {}).items():
        data.proc_cpu[pid_str] = list(values)

    # Restore flags
    data.has_cpu = cache_data.get('has_cpu', False)
    data.has_mem = cache_data.get('has_mem', False)
    data.has_disk = cache_data.get('has_disk', False)
    data.has_network = cache_data.get('has_network', False)
    data.has_proc = cache_data.get('has_proc', False)

    # Restore metadata
    data.source = cache_meta.get('source', '')
    data.hostname = cache_meta.get('hostname', '')


def parse_binary_archive(archive_dir, data, include_proc=False, all_archives=False,
                         no_cache=False, refresh_cache=False):
    """
    Use pmrep to extract data from a PCP binary archive directory.
    Processes ALL archives found (not just the most recent), merging
    their time-series data chronologically into data.

    If include_proc=True and all_archives=False, limits to 3 most recent archives.
    If all_archives=True, processes all archives regardless (may take 90+ minutes).

    Returns True if any data was parsed.
    """
    # Try cache first
    cached = _load_cache(archive_dir, include_proc, all_archives, no_cache, refresh_cache)
    if cached is not None:
        _apply_cache_to_data(cached, data)
        return True

    pmrep = _find_pmrep()
    if not pmrep:
        return False

    # Collect all archive sets; sort by filename (date-named = chronological order)
    index_files = sorted(glob.glob(join(archive_dir, '*.index')))
    if not index_files:
        return False

    # For proc metrics, limit to most recent 3 archives to avoid excessive runtime
    # (6+ min per archive for proc.hog.cpu decompression)
    # Can be overridden with all_archives=True
    if include_proc and not all_archives and len(index_files) > 3:
        print("Note: Limiting process analysis to 3 most recent archives (out of %d total)."
              % len(index_files), file=sys.stderr)
        print("      Use --all-archives to process all archives (may take 90+ minutes).",
              file=sys.stderr)
        index_files = index_files[-3:]

    multi = len(index_files) > 1
    success_count = 0

    for i, idx_file in enumerate(index_files):
        if is_cmd_stopped and is_cmd_stopped():
            break

        archive_path = idx_file[:-6]  # Remove .index suffix
        archive_name = basename(archive_path)

        if multi:
            print("Processing archive %d/%d: %s..." % (i + 1, len(index_files), archive_name),
                  file=sys.stderr, flush=True)

        try:
            csv_text = _run_pmrep_archive(pmrep, archive_path, include_proc=include_proc)
            if csv_text is None:
                print("  Warning: archive %s returned no data, skipping." % archive_name,
                      file=sys.stderr, flush=True)
                continue

            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tf:
                tf.write(csv_text)
                tmp_path = tf.name

            try:
                ok = parse_pmrep_csv(tmp_path, data)
            finally:
                os.unlink(tmp_path)

            if ok:
                success_count += 1
        except Exception as e:
            print("  Warning: failed to process archive %s: %s" % (archive_name, e),
                  file=sys.stderr, flush=True)

    if multi and success_count > 0:
        print("Processed %d/%d archives successfully." % (success_count, len(index_files)),
              file=sys.stderr, flush=True)

    if data.timestamps:
        _sort_and_dedup_pcp_data(data)
        data.hostname = basename(archive_dir)
        # Save cache after successful processing (unless user disabled caching)
        if not no_cache and not refresh_cache:
            _save_cache(archive_dir, data, include_proc, all_archives, index_files)

    return success_count > 0


# ---------------------------------------------------------------------------
# Main data loading function
# ---------------------------------------------------------------------------

def _merge_pmstat_samples(samples, data):
    """Merge a list of PMStatData dicts (from parse_pmstat) into a PCPData instance."""
    for sample in samples:
        ts = _parse_timestamp(sample.get('timestamp', ''))
        if ts is None:
            continue
        data.timestamps.append(ts)

        cpu = sample.get('cpu', {})
        for label, key in [('user', 'user'), ('sys', 'sys'),
                            ('idle', 'idle'), ('wait', 'iowait')]:
            if cpu.get(key) is not None:
                data.cpu[label].append(cpu[key])
                data.has_cpu = True

        mem = sample.get('memory', {})
        for label, key in [('free', 'free'), ('cached', 'cache'), ('used', 'used')]:
            if mem.get(key) is not None:
                data.mem[label].append(mem[key])
                data.has_mem = True

        disk = sample.get('disk', {})
        for label, key in [('read_iops', 'reads'), ('write_iops', 'writes')]:
            if disk.get(key) is not None:
                data.disk[label].append(disk[key])
                data.has_disk = True


def load_pcp_data(sos_home_path, include_proc=False):
    """
    Locate and load PCP performance data from a sosreport directory.

    Returns PCPData instance (may be empty if no PCP data found).
    """
    data = PCPData()
    files_info = find_pcp_files(sos_home_path)

    # Try text/CSV files from sos_commands/pcp/ first
    for fpath in files_info['csv_files']:
        if is_cmd_stopped and is_cmd_stopped():
            break
        try:
            with open(fpath) as f:
                sample = f.read(1024)
        except Exception:
            continue

        if ',' in sample and ('Timestamp' in sample or
                               any(m in sample for m in ALL_METRICS)):
            success = parse_pmrep_csv(fpath, data)
            if success and not data.source:
                data.source = fpath
        elif 'Timestamp' in sample:
            success = parse_pmrep_text(fpath, data)
            if success and not data.source:
                data.source = fpath
        elif '@' in sample and any(kw in sample.lower() for kw in ('memory', 'swap', 'cpu')):
            # pmstat format: lines start with '@ <timestamp>'
            samples = parse_pmstat(fpath)
            if samples:
                _merge_pmstat_samples(samples, data)
                if not data.source:
                    data.source = fpath

    # Sort and deduplicate after CSV loading (os.listdir order is arbitrary)
    if not data.is_empty():
        _sort_and_dedup_pcp_data(data)

    # Try binary archives if no text data found
    if data.is_empty():
        for archive_dir in files_info['archive_dirs']:
            if is_cmd_stopped and is_cmd_stopped():
                break
            success = parse_binary_archive(archive_dir, data, include_proc=include_proc)
            if success:
                data.source = archive_dir
                break

    # Extract hostname from source path if not set
    if not data.hostname and data.source:
        # Try to find hostname from pmlogger path
        parts = data.source.split(os.sep)
        if 'pmlogger' in parts:
            idx = parts.index('pmlogger')
            if idx + 1 < len(parts):
                data.hostname = parts[idx + 1]

    return data


# ---------------------------------------------------------------------------
# Architecture contract interface (used by integration-dev for Task #4/#1)
# ---------------------------------------------------------------------------

def detect_pcp_data(sos_home_path):
    """
    Detect available PCP data in a sosreport directory.

    Returns PCPDataInfo dict:
      'available': bool - True if any PCP data found
      'text_files': {'pmstat': path|None, 'pmrep': path|None, 'pminfo': path|None}
      'archives':   list of archive directory paths (Phase 2)
      'message':    human-readable status string
    """
    files_info = find_pcp_files(sos_home_path)

    pmstat_path = pmrep_path = pminfo_path = None
    for fpath in files_info['csv_files']:
        fname = basename(fpath).lower()
        try:
            with open(fpath) as f:
                head = f.read(512)
        except Exception:
            continue
        if 'pmstat' in fname or ('memory' in head and 'swap' in head and 'cpu' in head):
            pmstat_path = pmstat_path or fpath
        elif 'pminfo' in fname:
            pminfo_path = pminfo_path or fpath
        elif 'pmrep' in fname or ('Timestamp' in head and ',' in head):
            pmrep_path = pmrep_path or fpath

    available = bool(pmstat_path or pmrep_path or pminfo_path or files_info['archive_dirs'])
    if available:
        sources = [s for s, p in [('pmstat', pmstat_path), ('pmrep', pmrep_path),
                                   ('pminfo', pminfo_path)] if p]
        if files_info['archive_dirs']:
            sources.append('archives')
        message = "PCP data found: %s" % ', '.join(sources)
    else:
        message = ("PCP data not found in this sosreport. "
                   "Enable the PCP sos plugin to collect performance data.")

    return {
        'available': available,
        'text_files': {'pmstat': pmstat_path, 'pmrep': pmrep_path, 'pminfo': pminfo_path},
        'archives':   files_info['archive_dirs'],
        'message':    message,
    }


def parse_pmstat(file_path):
    """
    Parse pmstat text output into a list of PMStatData dicts (one per sample).

    pmstat format (@ <timestamp> then header then data rows):
        @ Sat Jan 15 10:00:00 2024
                      memory      swap         io    system         cpu
                       free buff  cache   pi   po   bi   bo   in   cs us sy id wa
                        321m   2m  567m    0    0    1    3  678  890 12  5 82  1

    Returns list of dicts (empty list on failure):
      {'cpu': {'user', 'sys', 'idle', 'iowait'}, 'memory': {'free', 'cache', 'used'},
       'disk': {'iops', 'reads', 'writes'}, 'network': {'packets_in', 'packets_out'},
       'timestamp': str}
    All metric values are float|int|None (None = not available).
    """
    try:
        with open(file_path) as f:
            lines = f.readlines()
    except Exception:
        return []

    def _mem_to_kb(s):
        s = s.strip().lower()
        try:
            if s.endswith('g'): return int(float(s[:-1]) * 1024 * 1024)
            if s.endswith('m'): return int(float(s[:-1]) * 1024)
            if s.endswith('k'): return int(float(s[:-1]))
            return int(s)
        except (ValueError, TypeError):
            return None

    def _toint(s):
        try: return int(s.strip())
        except (ValueError, TypeError): return None

    def _tofloat(s):
        try: return float(s.strip())
        except (ValueError, TypeError): return None

    samples = []
    current_ts = None
    col_names = []
    in_data = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('@'):
            current_ts = stripped[1:].strip()
            # Keep col_names from prior block — pmstat repeats headers only periodically
            in_data = bool(col_names)
            continue
        # Section header lines (no data values)
        if any(kw in stripped.lower() for kw in ('memory', 'swap', 'system')):
            continue
        # Column name line: contains 'us'/'usr' or 'free'
        if re.search(r'\bus\b|\busr\b|\bfree\b', stripped.lower()) and not stripped[0].isdigit():
            col_names = stripped.lower().split()
            in_data = True
            continue
        # Data row
        if in_data and current_ts is not None:
            vals = stripped.split()
            if len(vals) < 4:
                continue
            col_map = {name: vals[i] for i, name in enumerate(col_names) if i < len(vals)}

            # CPU — handle us/usr/%usr naming variants
            user  = _tofloat(col_map.get('us',  col_map.get('usr',  col_map.get('%usr', ''))))
            sys_  = _tofloat(col_map.get('sy',  col_map.get('sys',  col_map.get('%sys', ''))))
            idle  = _tofloat(col_map.get('id',  col_map.get('idle', col_map.get('%idle', ''))))
            wait  = _tofloat(col_map.get('wa',  col_map.get('wait', col_map.get('%wait', ''))))
            # Positional fallback when column map is empty
            if user is None and len(vals) >= 4:
                try: user, sys_, idle, wait = (float(v) for v in vals[-4:])
                except (ValueError, TypeError): pass

            bi = _toint(col_map.get('bi', ''))
            bo = _toint(col_map.get('bo', ''))
            iops = (bi or 0) + (bo or 0) if (bi is not None or bo is not None) else None

            samples.append({
                'cpu':     {'user': user, 'sys': sys_, 'idle': idle, 'iowait': wait},
                'memory':  {'free': _mem_to_kb(col_map.get('free', '')),
                            'cache': _mem_to_kb(col_map.get('cache', col_map.get('buff', ''))),
                            'used': None},
                'disk':    {'iops': iops, 'reads': bi, 'writes': bo},
                'network': {'packets_in':  _toint(col_map.get('in', '')),
                            'packets_out': _toint(col_map.get('cs', ''))},
                'timestamp': current_ts,
            })

    return samples


def export_to_text(data_list, output_path, metric_type):
    """
    Export a list of PMStatData dicts to a formatted text file.

    Args:
        data_list:   List of PMStatData dicts (from parse_pmstat)
        output_path: File path for output
        metric_type: 'cpu', 'mem', 'disk', 'net', or 'all'
    """
    if not data_list:
        return False, "No data to export"

    # Convert PMStatData list into PCPData for reuse of existing output functions
    data = PCPData()
    data.source = output_path
    for sample in data_list:
        ts = _parse_timestamp(sample.get('timestamp', ''))
        data.timestamps.append(ts if ts else datetime.now())

        cpu = sample.get('cpu', {})
        for label, key in [('user', 'user'), ('sys', 'sys'), ('idle', 'idle'), ('wait', 'iowait')]:
            if cpu.get(key) is not None:
                data.cpu[label].append(cpu[key])
                data.has_cpu = True

        mem = sample.get('memory', {})
        for label, key in [('free', 'free'), ('cached', 'cache'), ('used', 'used')]:
            if mem.get(key) is not None:
                data.mem[label].append(mem[key])
                data.has_mem = True

        disk = sample.get('disk', {})
        for label, key in [('read_iops', 'reads'), ('write_iops', 'writes')]:
            if disk.get(key) is not None:
                data.disk[label].append(disk[key])
                data.has_disk = True

        net = sample.get('network', {})
        if net.get('packets_in') is not None:
            data.network['all']['in_pkts'].append(net['packets_in'])
            data.has_network = True
        if net.get('packets_out') is not None:
            data.network['all']['out_pkts'].append(net['packets_out'])
            data.has_network = True

    mt = metric_type.lower()
    if mt == 'cpu':
        return output_cpu(data, output_path)
    elif mt in ('mem', 'memory'):
        return output_mem(data, output_path)
    elif mt == 'disk':
        return output_disk(data, output_path)
    elif mt in ('net', 'network'):
        return output_network(data, output_path)
    else:
        results = output_all(data, output_path)
        return results[0] if results else (False, "No output generated")


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _stats(values):
    """Return (min, max, avg) for a list of floats, or (0,0,0) if empty."""
    if not values:
        return 0.0, 0.0, 0.0
    valid = [v for v in values if v is not None]
    if not valid:
        return 0.0, 0.0, 0.0
    return min(valid), max(valid), sum(valid) / len(valid)


def _trend(values):
    """Return 'rising', 'falling', 'stable', or 'unknown'."""
    if len(values) < 4:
        return 'unknown'
    # Compare first quarter vs last quarter average
    quarter = max(1, len(values) // 4)
    first_avg = sum(values[:quarter]) / quarter
    last_avg = sum(values[-quarter:]) / quarter
    diff = last_avg - first_avg
    if abs(diff) < 2.0:
        return 'stable'
    return 'rising' if diff > 0 else 'falling'


def _peak_times(timestamps, values, top_n=3):
    """Return list of (timestamp, value) for top N peak values."""
    if not timestamps or not values or len(timestamps) != len(values):
        return []
    pairs = sorted(zip(values, timestamps), reverse=True)
    return [(ts, val) for val, ts in pairs[:top_n]]


def _format_bytes(bytes_val):
    """Format byte count as human-readable string."""
    if bytes_val >= 1024 ** 3:
        return "%.2f GB" % (bytes_val / 1024 ** 3)
    if bytes_val >= 1024 ** 2:
        return "%.2f MB" % (bytes_val / 1024 ** 2)
    if bytes_val >= 1024:
        return "%.2f KB" % (bytes_val / 1024)
    return "%.0f B" % bytes_val


# ---------------------------------------------------------------------------
# Anomaly thresholds for highlighting
# ---------------------------------------------------------------------------

_CPU_USER_WARN   = 60.0   # avg user%  >= warn
_CPU_USER_CRIT   = 80.0   # avg user%  >= crit
_CPU_SYS_WARN    = 20.0
_CPU_SYS_CRIT    = 40.0
_CPU_WAIT_WARN   = 10.0   # iowait is very concerning
_CPU_WAIT_CRIT   = 30.0
_CPU_IDLE_WARN   = 30.0   # low idle = high load (check avg)
_CPU_IDLE_CRIT   = 10.0
_CPU_STEAL_WARN  =  5.0
_CPU_STEAL_CRIT  = 20.0
_NET_ERR_WARN    =  0.0   # any errors are notable
_NET_ERR_CRIT    = 100.0


def _cpu_row_color(label, mn, mx, avg):
    """Return row_color string for a CPU metric row based on its values."""
    if label in ('user', 'sys'):
        crit = _CPU_USER_CRIT if label == 'user' else _CPU_SYS_CRIT
        warn = _CPU_USER_WARN if label == 'user' else _CPU_SYS_WARN
        if avg >= crit:
            return 'lightred'
        if avg >= warn:
            return 'lightyellow'
    elif label == 'wait':
        if avg >= _CPU_WAIT_CRIT:
            return 'lightred'
        if avg >= _CPU_WAIT_WARN:
            return 'lightyellow'
    elif label == 'idle':
        if avg <= _CPU_IDLE_CRIT:
            return 'lightred'
        if avg <= _CPU_IDLE_WARN:
            return 'lightyellow'
    elif label == 'steal':
        if mx >= _CPU_STEAL_CRIT:
            return 'lightred'
        if mx >= _CPU_STEAL_WARN:
            return 'lightyellow'
    return None


def _trend_indicator(trend):
    """Return trend string with visual ASCII direction indicator."""
    return {
        'rising':  'rising  ^',
        'falling': 'falling v',
        'stable':  'stable  -',
        'unknown': 'unknown  ',
    }.get(trend, trend)


# ---------------------------------------------------------------------------
# Display functions (terminal output)
# ---------------------------------------------------------------------------

def _section_header(title, width=72):
    return "\n" + "=" * width + "\n" + title.center(width) + "\n" + "=" * width + "\n"


def show_cpu(data, no_pipe):
    """Display CPU utilization metrics using TableFormatter with anomaly highlighting."""
    builder = OutputBuilder(no_pipe)
    colors = ColorManager(no_pipe)

    if not data.has_cpu:
        builder.add_line("No CPU data available in PCP archives.")
        return builder.get_result()

    colors.print_header(_section_header("CPU UTILIZATION"))

    table = create_table(no_pipe)
    table.add_column("Metric",  width=12, align='left',  color='cyan')
    table.add_column("Min%",    width=9,  align='right', color='lightcyan')
    table.add_column("Max%",    width=9,  align='right', color='lightcyan')
    table.add_column("Avg%",    width=9,  align='right', color='lightcyan')
    table.add_column("Trend",   width=12, align='left',  color='white')

    important = ['user', 'sys', 'wait', 'idle', 'steal']
    seen = set()
    for label in important + sorted(data.cpu.keys()):
        if label in seen or label not in data.cpu:
            continue
        seen.add(label)
        vals = data.cpu[label]
        mn, mx, avg = _stats(vals)
        trend = _trend(vals)
        row_color = _cpu_row_color(label, mn, mx, avg)
        table.add_row(
            label,
            "%.2f" % mn,
            "%.2f" % mx,
            "%.2f" % avg,
            _trend_indicator(trend),
            row_color=row_color,
        )

    builder.add_table(table)

    # Peak usage times with inline anomaly coloring
    if 'user' in data.cpu and data.timestamps:
        builder.add_line("\nTop CPU peaks (user+sys):")
        combined = [
            (data.cpu['user'][i] if i < len(data.cpu['user']) else 0) +
            (data.cpu['sys'][i] if 'sys' in data.cpu and i < len(data.cpu['sys']) else 0)
            for i in range(len(data.timestamps))
        ]
        peaks = _peak_times(data.timestamps, combined)
        for ts, val in peaks:
            line = "  %s  %.2f%%" % (ts.strftime('%Y-%m-%d %H:%M:%S'), val)
            if val >= _CPU_USER_CRIT + _CPU_SYS_CRIT:
                colors.print_critical(line)
            elif val >= _CPU_USER_WARN + _CPU_SYS_WARN:
                colors.print_warning(line)
            else:
                builder.add_line(line)

    return builder.get_result()


def show_mem(data, no_pipe):
    """Display memory utilization metrics using TableFormatter."""
    builder = OutputBuilder(no_pipe)
    colors = ColorManager(no_pipe)

    if not data.has_mem:
        builder.add_line("No memory data available in PCP archives.")
        return builder.get_result()

    colors.print_header(_section_header("MEMORY UTILIZATION"))

    def fmt_mem(v):
        return _format_bytes(v if v > 1024 * 1024 else v * 1024)

    # Compute total for free% threshold (prefer 'total', fall back to used+free)
    mem_total_raw = 0.0
    if 'total' in data.mem and data.mem['total']:
        mem_total_raw = _stats(data.mem['total'])[2]  # avg total
    elif 'used' in data.mem and 'free' in data.mem:
        mem_total_raw = (_stats(data.mem['used'])[2] +
                         _stats(data.mem['free'])[2])

    table = create_table(no_pipe)
    table.add_column("Metric",  width=14, align='left',  color='cyan')
    table.add_column("Min",     width=14, align='right', color='lightcyan')
    table.add_column("Max",     width=14, align='right', color='lightcyan')
    table.add_column("Avg",     width=14, align='right', color='lightcyan')
    table.add_column("Trend",   width=12, align='left',  color='white')

    for label in ['used', 'free', 'available', 'cached', 'bufmem',
                  'swap_free', 'swap_total', 'total']:
        if label not in data.mem:
            continue
        vals = data.mem[label]
        mn, mx, avg = _stats(vals)
        trend = _trend(vals)

        # Anomaly highlight: free or available dropping critically low
        row_color = None
        if label in ('free', 'available') and mem_total_raw > 0:
            free_pct = (avg / mem_total_raw) * 100.0
            if free_pct <= 10.0:
                row_color = 'lightred'
            elif free_pct <= 20.0:
                row_color = 'lightyellow'
        # Rising swap usage is a warning
        elif label == 'swap_free' and mem_total_raw > 0:
            if _trend(vals) == 'falling':
                row_color = 'lightyellow'

        table.add_row(
            label,
            fmt_mem(mn),
            fmt_mem(mx),
            fmt_mem(avg),
            _trend_indicator(trend),
            row_color=row_color,
        )

    builder.add_table(table)

    # Peak memory pressure timestamps
    if 'used' in data.mem and data.timestamps:
        builder.add_line("\nPeak memory usage times:")
        peaks = _peak_times(data.timestamps, data.mem['used'])
        for ts, val in peaks:
            builder.add_line("  %s  %s" % (
                ts.strftime('%Y-%m-%d %H:%M:%S'), fmt_mem(val)
            ))

    return builder.get_result()


def show_disk(data, no_pipe):
    """Display disk I/O metrics using TableFormatter."""
    builder = OutputBuilder(no_pipe)
    colors = ColorManager(no_pipe)

    if not data.has_disk:
        builder.add_line("No disk I/O data available in PCP archives.")
        return builder.get_result()

    colors.print_header(_section_header("DISK I/O"))

    def fmt_disk(label, v):
        return _format_bytes(v) if 'bytes' in label else "%.2f/s" % v

    table = create_table(no_pipe)
    table.add_column("Metric",  width=14, align='left',  color='cyan')
    table.add_column("Min",     width=14, align='right', color='lightcyan')
    table.add_column("Max",     width=14, align='right', color='lightcyan')
    table.add_column("Avg",     width=14, align='right', color='lightcyan')
    table.add_column("Trend",   width=12, align='left',  color='white')

    for label in ['read_iops', 'write_iops', 'read_bytes', 'write_bytes', 'avactive']:
        if label not in data.disk:
            continue
        vals = data.disk[label]
        mn, mx, avg = _stats(vals)
        trend = _trend(vals)
        # Highlight heavy I/O: avactive (disk busy %) near 100 is concerning
        row_color = None
        if label == 'avactive':
            if avg >= 90.0:
                row_color = 'lightred'
            elif avg >= 70.0:
                row_color = 'lightyellow'
        table.add_row(
            label,
            fmt_disk(label, mn),
            fmt_disk(label, mx),
            fmt_disk(label, avg),
            _trend_indicator(trend),
            row_color=row_color,
        )

    builder.add_table(table)

    # Peak I/O throughput timestamps
    if 'read_bytes' in data.disk and data.timestamps:
        builder.add_line("\nPeak I/O throughput times:")
        peaks = _peak_times(data.timestamps, data.disk['read_bytes'])
        for ts, val in peaks:
            builder.add_line("  %s  read: %s" % (
                ts.strftime('%Y-%m-%d %H:%M:%S'), _format_bytes(val)
            ))

    return builder.get_result()


def show_network(data, no_pipe):
    """Display network statistics using TableFormatter with error highlighting."""
    builder = OutputBuilder(no_pipe)
    colors = ColorManager(no_pipe)

    if not data.has_network:
        builder.add_line("No network data available in PCP archives.")
        return builder.get_result()

    colors.print_header(_section_header("NETWORK STATISTICS"))

    def fmt_net(label, v):
        return _format_bytes(v) if 'bytes' in label else "%.2f/s" % v

    for iface in sorted(data.network.keys()):
        iface_data = data.network[iface]
        colors.print_info("\nInterface: %s" % iface)

        table = create_table(no_pipe)
        table.add_column("Metric",  width=14, align='left',  color='cyan')
        table.add_column("Min",     width=14, align='right', color='lightcyan')
        table.add_column("Max",     width=14, align='right', color='lightcyan')
        table.add_column("Avg",     width=14, align='right', color='lightcyan')
        table.add_column("Trend",   width=12, align='left',  color='white')

        for label in ['in_bytes', 'out_bytes', 'in_pkts', 'out_pkts',
                      'in_errors', 'out_errors']:
            if label not in iface_data:
                continue
            vals = iface_data[label]
            mn, mx, avg = _stats(vals)
            trend = _trend(vals)
            # Any non-zero errors are notable
            row_color = None
            if 'error' in label:
                if avg > _NET_ERR_CRIT:
                    row_color = 'lightred'
                elif avg > _NET_ERR_WARN:
                    row_color = 'lightyellow'
            table.add_row(
                label,
                fmt_net(label, mn),
                fmt_net(label, mx),
                fmt_net(label, avg),
                _trend_indicator(trend),
                row_color=row_color,
            )

        builder.add_table(table)

    return builder.get_result()


def show_top_procs(data, top_n, no_pipe):
    """Display top N CPU consuming processes ranked by average CPU usage."""
    builder = OutputBuilder(no_pipe)
    colors = ColorManager(no_pipe)

    if not data.has_proc:
        builder.add_line(
            "No process CPU data available.\n"
            "Use -p/--top-procs with PCP binary archives (requires pmrep).\n"
            "Ensure proc.hog.cpu metric is collected in PCP archives."
        )
        return builder.get_result()

    colors.print_header(_section_header("TOP %d CPU CONSUMERS" % top_n))

    # Compute stats per process; skip any that never had non-zero CPU
    proc_stats = {}
    n_ts = len(data.timestamps)
    for pid_str, vals in data.proc_cpu.items():
        if not any(v > 0 for v in vals):
            continue
        mn, mx, avg = _stats(vals)
        # Find peak timestamp
        peak_ts = None
        if data.timestamps and len(vals) >= 1:
            paired = sorted(zip(vals, range(len(vals))), reverse=True)
            peak_idx = paired[0][1]
            if peak_idx < n_ts:
                peak_ts = data.timestamps[peak_idx]
        proc_stats[pid_str] = (mn, mx, avg, peak_ts)

    if not proc_stats:
        builder.add_line("All processes reported zero CPU utilization.")
        return builder.get_result()

    top = sorted(proc_stats.items(), key=lambda x: x[1][2], reverse=True)[:top_n]

    table = create_table(no_pipe)
    table.add_column("Process",   width=32, align='left',  color='cyan')
    table.add_column("Min CPU%",  width=9,  align='right', color='lightcyan')
    table.add_column("Max CPU%",  width=9,  align='right', color='lightcyan')
    table.add_column("Avg CPU%",  width=9,  align='right', color='lightcyan')
    table.add_column("Peak At",   width=21, align='left',  color='white')

    for pid_str, (mn, mx, avg, peak_ts) in top:
        row_color = 'lightred' if avg >= 80 else ('lightyellow' if avg >= 40 else None)
        peak_str = peak_ts.strftime('%Y-%m-%d %H:%M:%S') if peak_ts else ""
        table.add_row(
            pid_str[:32],
            "%.2f" % mn,
            "%.2f" % mx,
            "%.2f" % avg,
            peak_str,
            row_color=row_color,
        )

    builder.add_table(table)

    # Peak snapshot: show top N at the single busiest timestamp
    if data.timestamps:
        builder.add_line("\nTop processes at peak CPU timestamp:")
        # Find timestamp where the sum of all proc CPU is highest
        peak_ts_idx = 0
        peak_sum = 0.0
        for ts_idx in range(n_ts):
            total = sum(
                vals[ts_idx] for vals in data.proc_cpu.values()
                if ts_idx < len(vals)
            )
            if total > peak_sum:
                peak_sum = total
                peak_ts_idx = ts_idx

        peak_snapshot = {
            pid_str: vals[peak_ts_idx]
            for pid_str, vals in data.proc_cpu.items()
            if peak_ts_idx < len(vals) and vals[peak_ts_idx] > 0
        }
        peak_top = sorted(peak_snapshot.items(), key=lambda x: x[1], reverse=True)[:top_n]
        peak_ts_str = data.timestamps[peak_ts_idx].strftime('%Y-%m-%d %H:%M:%S')
        builder.add_line("  Timestamp: %s" % peak_ts_str)
        for rank, (pid_str, cpu_val) in enumerate(peak_top, 1):
            builder.add_line("  %2d. %-32s  %.2f%%" % (rank, pid_str[:32], cpu_val))

    return builder.get_result()


def show_summary(data, no_pipe):
    """Display summary overview with TableFormatter and anomaly indicators."""
    builder = OutputBuilder(no_pipe)
    colors = ColorManager(no_pipe)

    colors.print_header(_section_header("PCP DATA SUMMARY"))

    if data.is_empty():
        colors.print_warning(
            "No PCP performance data found in this sosreport.\n"
            "PCP data is typically stored in:\n"
            "  sos_commands/pcp/\n"
            "  var/log/pcp/pmlogger/<hostname>/\n"
        )
        return builder.get_result()

    # Header info block
    if data.hostname:
        builder.add_line("Hostname  : %s" % data.hostname)
    if data.source:
        builder.add_line("Source    : %s" % data.source)
    if data.start_time:
        builder.add_line("Time range: %s -> %s (%.1f min)" % (
            data.start_time.strftime('%Y-%m-%d %H:%M:%S'),
            data.end_time.strftime('%Y-%m-%d %H:%M:%S'),
            data.duration_minutes,
        ))
    builder.add_line("Samples   : %d" % len(data.timestamps))

    avail = []
    if data.has_cpu:     avail.append("CPU")
    if data.has_mem:     avail.append("Memory")
    if data.has_disk:    avail.append("Disk I/O")
    if data.has_network: avail.append("Network")
    builder.add_line("Available : %s" % (", ".join(avail) if avail else "None"))

    # Aggregated anomaly summary table
    builder.add_line("")
    table = create_table(no_pipe)
    table.add_column("Metric",    width=26, align='left',  color='cyan')
    table.add_column("Avg",       width=14, align='right', color='lightcyan')
    table.add_column("Peak",      width=14, align='right', color='white')
    table.add_column("Trend",     width=12, align='left',  color='white')
    table.add_column("Status",    width=10, align='left',  color='white')

    if data.has_cpu and 'user' in data.cpu:
        mn, mx, avg = _stats(data.cpu['user'])
        trend = _trend(data.cpu['user'])
        row_color = _cpu_row_color('user', mn, mx, avg)
        status = "CRIT" if row_color == 'lightred' else ("WARN" if row_color == 'lightyellow' else "OK")
        table.add_row("CPU user%", "%.2f%%" % avg, "%.2f%%" % mx,
                      _trend_indicator(trend), status, row_color=row_color)

    if data.has_cpu and 'sys' in data.cpu:
        mn, mx, avg = _stats(data.cpu['sys'])
        trend = _trend(data.cpu['sys'])
        row_color = _cpu_row_color('sys', mn, mx, avg)
        status = "CRIT" if row_color == 'lightred' else ("WARN" if row_color == 'lightyellow' else "OK")
        table.add_row("CPU sys%", "%.2f%%" % avg, "%.2f%%" % mx,
                      _trend_indicator(trend), status, row_color=row_color)

    if data.has_cpu and 'wait' in data.cpu:
        mn, mx, avg = _stats(data.cpu['wait'])
        trend = _trend(data.cpu['wait'])
        row_color = _cpu_row_color('wait', mn, mx, avg)
        status = "CRIT" if row_color == 'lightred' else ("WARN" if row_color == 'lightyellow' else "OK")
        table.add_row("CPU iowait%", "%.2f%%" % avg, "%.2f%%" % mx,
                      _trend_indicator(trend), status, row_color=row_color)

    if data.has_cpu and 'idle' in data.cpu:
        mn, mx, avg = _stats(data.cpu['idle'])
        trend = _trend(data.cpu['idle'])
        row_color = _cpu_row_color('idle', mn, mx, avg)
        status = "CRIT" if row_color == 'lightred' else ("WARN" if row_color == 'lightyellow' else "OK")
        table.add_row("CPU idle%", "%.2f%%" % avg, "%.2f%%" % mn,
                      _trend_indicator(trend), status, row_color=row_color)

    if data.has_mem and 'used' in data.mem:
        mn, mx, avg = _stats(data.mem['used'])
        trend = _trend(data.mem['used'])
        def _fmb(v): return _format_bytes(v if v > 1024*1024 else v*1024)
        table.add_row("Memory used", _fmb(avg), _fmb(mx),
                      _trend_indicator(trend), "")

    if data.has_disk and 'read_bytes' in data.disk:
        mn, mx, avg = _stats(data.disk['read_bytes'])
        trend = _trend(data.disk['read_bytes'])
        table.add_row("Disk read", "%s/s" % _format_bytes(avg),
                      "%s/s" % _format_bytes(mx), _trend_indicator(trend), "")

    if data.has_disk and 'write_bytes' in data.disk:
        mn, mx, avg = _stats(data.disk['write_bytes'])
        trend = _trend(data.disk['write_bytes'])
        table.add_row("Disk write", "%s/s" % _format_bytes(avg),
                      "%s/s" % _format_bytes(mx), _trend_indicator(trend), "")

    builder.add_table(table)
    return builder.get_result()


# ---------------------------------------------------------------------------
# Text file output generators (Task #5)
# ---------------------------------------------------------------------------

def _write_header(f, title, data):
    """Write a standard header block to an output file."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    f.write("=" * 72 + "\n")
    f.write(("%s" % title).center(72) + "\n")
    f.write("=" * 72 + "\n")
    f.write("Generated : %s\n" % now)
    if data.hostname:
        f.write("Hostname  : %s\n" % data.hostname)
    if data.source:
        f.write("Source    : %s\n" % data.source)
    if data.start_time:
        f.write("Time range: %s -> %s\n" % (
            data.start_time.strftime('%Y-%m-%d %H:%M:%S'),
            data.end_time.strftime('%Y-%m-%d %H:%M:%S')
        ))
        f.write("Duration  : %.1f minutes\n" % data.duration_minutes)
    f.write("Samples   : %d\n" % len(data.timestamps))
    f.write("=" * 72 + "\n\n")


def _write_time_series(f, timestamps, series_dict, label_fmt, value_fmt):
    """Write a time-series table to the file."""
    if not timestamps:
        f.write("(no data)\n\n")
        return

    labels = [k for k in series_dict if series_dict[k]]
    if not labels:
        f.write("(no data)\n\n")
        return

    # Header
    header = "%-21s" % "Timestamp"
    for label in labels:
        header += "  " + label_fmt % label
    f.write(header + "\n")
    f.write("-" * len(header) + "\n")

    # Rows
    n = len(timestamps)
    for i in range(n):
        ts_str = timestamps[i].strftime('%Y-%m-%d %H:%M:%S')
        row = "%-21s" % ts_str
        for label in labels:
            vals = series_dict[label]
            val = vals[i] if i < len(vals) else 0.0
            row += "  " + value_fmt % val
        f.write(row + "\n")
    f.write("\n")


def _write_stats_section(f, series_dict, value_fmt, timestamps=None):
    """Write a statistics summary section."""
    f.write("\n--- Statistics Summary ---\n\n")
    header = "%-16s  %12s  %12s  %12s  %10s\n" % (
        "Metric", "Min", "Max", "Average", "Trend"
    )
    f.write(header)
    f.write("-" * 66 + "\n")

    for label, vals in sorted(series_dict.items()):
        if not vals:
            continue
        mn, mx, avg = _stats(vals)
        trend = _trend(vals)
        f.write("%-16s  " % label)
        f.write((value_fmt % mn) + "  ")
        f.write((value_fmt % mx) + "  ")
        f.write((value_fmt % avg) + "  ")
        f.write("%10s\n" % trend)

    # Peak timestamps
    if timestamps:
        f.write("\n--- Peak Events (Top 5) ---\n\n")
        for label, vals in sorted(series_dict.items()):
            if not vals or len(vals) < 2:
                continue
            peaks = _peak_times(timestamps, vals, top_n=5)
            if peaks:
                f.write("  %s:\n" % label)
                for ts, val in peaks:
                    f.write("    %s  " % ts.strftime('%Y-%m-%d %H:%M:%S'))
                    f.write((value_fmt % val) + "\n")
    f.write("\n")


def output_cpu(data, filepath):
    """Write CPU metrics to a text file."""
    if not data.has_cpu:
        return False, "No CPU data available"

    try:
        with open(filepath, 'w') as f:
            _write_header(f, "PCP CPU UTILIZATION REPORT", data)

            f.write("--- Time Series Data ---\n\n")
            # Format percentages
            _write_time_series(
                f, data.timestamps, dict(data.cpu),
                label_fmt="%8s",
                value_fmt="%7.2f%%"
            )

            _write_stats_section(
                f, dict(data.cpu),
                value_fmt="%11.2f%%",
                timestamps=data.timestamps
            )
    except Exception as e:
        return False, str(e)

    return True, filepath


def output_mem(data, filepath):
    """Write memory metrics to a text file."""
    if not data.has_mem:
        return False, "No memory data available"

    try:
        with open(filepath, 'w') as f:
            _write_header(f, "PCP MEMORY UTILIZATION REPORT", data)

            f.write("--- Time Series Data ---\n\n")

            def fmt_mem_val(v):
                return _format_bytes(v if v > 1024 * 1024 else v * 1024)

            # Write time series manually for memory (human-readable bytes)
            labels = [k for k in data.mem if data.mem[k]]
            if labels and data.timestamps:
                header = "%-21s" % "Timestamp"
                for label in labels:
                    header += "  %14s" % label
                f.write(header + "\n")
                f.write("-" * len(header) + "\n")

                for i, ts in enumerate(data.timestamps):
                    row = "%-21s" % ts.strftime('%Y-%m-%d %H:%M:%S')
                    for label in labels:
                        vals = data.mem[label]
                        val = vals[i] if i < len(vals) else 0.0
                        row += "  %14s" % fmt_mem_val(val)
                    f.write(row + "\n")
                f.write("\n")

            # Stats section
            f.write("\n--- Statistics Summary ---\n\n")
            header = "%-16s  %14s  %14s  %14s  %10s\n" % (
                "Metric", "Min", "Max", "Average", "Trend"
            )
            f.write(header)
            f.write("-" * 72 + "\n")
            for label in sorted(data.mem.keys()):
                vals = data.mem[label]
                if not vals:
                    continue
                mn, mx, avg = _stats(vals)
                trend = _trend(vals)
                f.write("%-16s  %14s  %14s  %14s  %10s\n" % (
                    label, fmt_mem_val(mn), fmt_mem_val(mx),
                    fmt_mem_val(avg), trend
                ))

            # Peak times
            if 'used' in data.mem and data.timestamps:
                f.write("\n--- Peak Memory Usage Times ---\n\n")
                peaks = _peak_times(data.timestamps, data.mem['used'], top_n=5)
                for ts, val in peaks:
                    f.write("  %s  %s\n" % (
                        ts.strftime('%Y-%m-%d %H:%M:%S'), fmt_mem_val(val)
                    ))
            f.write("\n")

    except Exception as e:
        return False, str(e)

    return True, filepath


def output_disk(data, filepath):
    """Write disk I/O metrics to a text file."""
    if not data.has_disk:
        return False, "No disk I/O data available"

    try:
        with open(filepath, 'w') as f:
            _write_header(f, "PCP DISK I/O REPORT", data)

            f.write("--- Time Series Data ---\n\n")

            def fmt_disk_val(label, v):
                if 'bytes' in label:
                    return "%12s" % _format_bytes(v)
                return "%12.2f" % v

            labels = [k for k in data.disk if data.disk[k]]
            if labels and data.timestamps:
                header = "%-21s" % "Timestamp"
                for label in labels:
                    header += "  %12s" % label
                f.write(header + "\n")
                f.write("-" * len(header) + "\n")

                for i, ts in enumerate(data.timestamps):
                    row = "%-21s" % ts.strftime('%Y-%m-%d %H:%M:%S')
                    for label in labels:
                        vals = data.disk[label]
                        val = vals[i] if i < len(vals) else 0.0
                        row += "  " + fmt_disk_val(label, val)
                    f.write(row + "\n")
                f.write("\n")

            # Stats
            f.write("\n--- Statistics Summary ---\n\n")
            f.write("%-16s  %14s  %14s  %14s  %10s\n" % (
                "Metric", "Min", "Max", "Average", "Trend"
            ))
            f.write("-" * 74 + "\n")
            for label in sorted(data.disk.keys()):
                vals = data.disk[label]
                if not vals:
                    continue
                mn, mx, avg = _stats(vals)
                trend = _trend(vals)
                if 'bytes' in label:
                    f.write("%-16s  %14s  %14s  %14s  %10s\n" % (
                        label, _format_bytes(mn), _format_bytes(mx),
                        _format_bytes(avg), trend
                    ))
                else:
                    f.write("%-16s  %14.2f  %14.2f  %14.2f  %10s\n" % (
                        label, mn, mx, avg, trend
                    ))

            # Highest throughput periods
            if 'read_bytes' in data.disk and data.timestamps:
                f.write("\n--- Peak I/O Times ---\n\n")
                for metric, label in [('read_bytes', 'Read'), ('write_bytes', 'Write')]:
                    if metric in data.disk:
                        f.write("  Top %s throughput:\n" % label)
                        peaks = _peak_times(data.timestamps, data.disk[metric], top_n=5)
                        for ts, val in peaks:
                            f.write("    %s  %s/s\n" % (
                                ts.strftime('%Y-%m-%d %H:%M:%S'), _format_bytes(val)
                            ))
            f.write("\n")

    except Exception as e:
        return False, str(e)

    return True, filepath


def output_network(data, filepath):
    """Write network statistics to a text file."""
    if not data.has_network:
        return False, "No network data available"

    try:
        with open(filepath, 'w') as f:
            _write_header(f, "PCP NETWORK STATISTICS REPORT", data)

            for iface in sorted(data.network.keys()):
                iface_data = data.network[iface]
                f.write("=" * 72 + "\n")
                f.write("Interface: %s\n" % iface)
                f.write("=" * 72 + "\n\n")

                f.write("--- Time Series Data ---\n\n")

                labels = [k for k in iface_data if iface_data[k]]
                if labels and data.timestamps:
                    header = "%-21s" % "Timestamp"
                    for label in labels:
                        header += "  %12s" % label
                    f.write(header + "\n")
                    f.write("-" * len(header) + "\n")

                    for i, ts in enumerate(data.timestamps):
                        row = "%-21s" % ts.strftime('%Y-%m-%d %H:%M:%S')
                        for label in labels:
                            vals = iface_data[label]
                            val = vals[i] if i < len(vals) else 0.0
                            if 'bytes' in label:
                                row += "  %12s" % _format_bytes(val)
                            else:
                                row += "  %12.2f" % val
                        f.write(row + "\n")
                    f.write("\n")

                # Stats per interface
                f.write("\n--- Statistics Summary (%s) ---\n\n" % iface)
                f.write("%-16s  %14s  %14s  %14s  %10s\n" % (
                    "Metric", "Min", "Max", "Average", "Trend"
                ))
                f.write("-" * 74 + "\n")
                for label in sorted(iface_data.keys()):
                    vals = iface_data[label]
                    if not vals:
                        continue
                    mn, mx, avg = _stats(vals)
                    trend = _trend(vals)
                    if 'bytes' in label:
                        f.write("%-16s  %14s  %14s  %14s  %10s\n" % (
                            label, _format_bytes(mn), _format_bytes(mx),
                            _format_bytes(avg), trend
                        ))
                    else:
                        f.write("%-16s  %14.2f  %14.2f  %14.2f  %10s\n" % (
                            label, mn, mx, avg, trend
                        ))
                f.write("\n")

    except Exception as e:
        return False, str(e)

    return True, filepath


def output_all(data, filepath_prefix):
    """
    Write a comprehensive report with all metrics to a single file,
    and individual metric files with prefix.

    Returns list of (success, filepath) tuples.
    """
    results = []

    # Comprehensive report
    all_file = filepath_prefix + "_all.txt" if not filepath_prefix.endswith('.txt') else filepath_prefix
    try:
        with open(all_file, 'w') as f:
            _write_header(f, "PCP COMPREHENSIVE PERFORMANCE REPORT", data)

            if data.is_empty():
                f.write("No PCP data found in this sosreport.\n")
            else:
                # CPU section
                if data.has_cpu:
                    f.write("\n" + "=" * 72 + "\n")
                    f.write("CPU UTILIZATION".center(72) + "\n")
                    f.write("=" * 72 + "\n\n")
                    _write_time_series(
                        f, data.timestamps, dict(data.cpu),
                        label_fmt="%8s", value_fmt="%7.2f%%"
                    )
                    _write_stats_section(
                        f, dict(data.cpu), value_fmt="%11.2f%%",
                        timestamps=data.timestamps
                    )

                # Memory section
                if data.has_mem:
                    f.write("\n" + "=" * 72 + "\n")
                    f.write("MEMORY UTILIZATION".center(72) + "\n")
                    f.write("=" * 72 + "\n\n")
                    labels = [k for k in data.mem if data.mem[k]]
                    if labels and data.timestamps:
                        header = "%-21s" % "Timestamp"
                        for label in labels:
                            header += "  %14s" % label
                        f.write(header + "\n")
                        f.write("-" * len(header) + "\n")
                        for i, ts in enumerate(data.timestamps):
                            row = "%-21s" % ts.strftime('%Y-%m-%d %H:%M:%S')
                            for label in labels:
                                vals = data.mem[label]
                                val = vals[i] if i < len(vals) else 0.0
                                v = val if val > 1024 * 1024 else val * 1024
                                row += "  %14s" % _format_bytes(v)
                            f.write(row + "\n")
                        f.write("\n")

                # Disk section
                if data.has_disk:
                    f.write("\n" + "=" * 72 + "\n")
                    f.write("DISK I/O".center(72) + "\n")
                    f.write("=" * 72 + "\n\n")
                    _write_time_series(
                        f, data.timestamps, dict(data.disk),
                        label_fmt="%14s", value_fmt="%14.2f"
                    )
                    _write_stats_section(
                        f, dict(data.disk), value_fmt="%14.2f",
                        timestamps=data.timestamps
                    )

                # Network section
                if data.has_network:
                    f.write("\n" + "=" * 72 + "\n")
                    f.write("NETWORK STATISTICS".center(72) + "\n")
                    f.write("=" * 72 + "\n\n")
                    for iface in sorted(data.network.keys()):
                        f.write("Interface: %s\n" % iface)
                        f.write("-" * 54 + "\n")
                        iface_data = data.network[iface]
                        _write_time_series(
                            f, data.timestamps, dict(iface_data),
                            label_fmt="%12s", value_fmt="%12.2f"
                        )

        results.append((True, all_file))
    except Exception as e:
        results.append((False, str(e)))

    # Individual files
    if data.has_cpu:
        ok, path = output_cpu(data, filepath_prefix + "_cpu.txt")
        results.append((ok, path))
    if data.has_mem:
        ok, path = output_mem(data, filepath_prefix + "_mem.txt")
        results.append((ok, path))
    if data.has_disk:
        ok, path = output_disk(data, filepath_prefix + "_disk.txt")
        results.append((ok, path))
    if data.has_network:
        ok, path = output_network(data, filepath_prefix + "_network.txt")
        results.append((ok, path))

    return results


# ---------------------------------------------------------------------------
# Help message
# ---------------------------------------------------------------------------

def print_cpu_help_msg(no_pipe):
    msg = '''pcpinfo -c  --  CPU utilization from PCP data

SYNOPSIS
    pcpinfo -c [OPTIONS]

DESCRIPTION
    Show CPU utilization metrics from PCP performance data in the
    sosreport.  Reads kernel.cpu.util.* metrics and displays min, max,
    and average percentages with trend indicators.  Highlights high user,
    sys, iowait, or steal values.

    PCP data is searched in:
      sos_commands/pcp/
      var/log/pcp/pmlogger/<hostname>/

OPTIONS
    -c, --cpu
        Enable CPU utilization mode.

    -f FILE, --file FILE
        Parse a specific pmrep CSV file instead of auto-discovering.

    -A DIR, --archive-dir DIR
        Analyze PCP binary archives from a standalone directory.

    --no-cache
        Skip cache, always process archives from scratch.

    --refresh-cache
        Force reprocess archives and update cache.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> pcpinfo -c
    example.com> pcpinfo -c -f /path/to/pmrep.csv
    example.com> pcpinfo -c -A /path/to/pcp_archives
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_mem_help_msg(no_pipe):
    msg = '''pcpinfo -m  --  Memory utilization from PCP data

SYNOPSIS
    pcpinfo -m [OPTIONS]

DESCRIPTION
    Show memory utilization metrics from PCP performance data in the
    sosreport.  Reads mem.util.* and mem.physmem metrics and displays
    min, max, and average values with trend indicators.  Highlights
    critically low free or available memory.

    PCP data is searched in:
      sos_commands/pcp/
      var/log/pcp/pmlogger/<hostname>/

OPTIONS
    -m, --mem
        Enable memory utilization mode.

    -f FILE, --file FILE
        Parse a specific pmrep CSV file instead of auto-discovering.

    -A DIR, --archive-dir DIR
        Analyze PCP binary archives from a standalone directory.

    --no-cache
        Skip cache, always process archives from scratch.

    --refresh-cache
        Force reprocess archives and update cache.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> pcpinfo -m
    example.com> pcpinfo -m -A /path/to/pcp_archives
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_disk_help_msg(no_pipe):
    msg = '''pcpinfo -d  --  Disk I/O statistics from PCP data

SYNOPSIS
    pcpinfo -d [OPTIONS]

DESCRIPTION
    Show disk I/O metrics from PCP performance data in the sosreport.
    Reads disk.all.* metrics (read/write IOPS, throughput, active time)
    and displays min, max, and average values with trend indicators.
    Highlights high disk busy (avactive) percentages.

    PCP data is searched in:
      sos_commands/pcp/
      var/log/pcp/pmlogger/<hostname>/

OPTIONS
    -d, --disk
        Enable disk I/O mode.

    -f FILE, --file FILE
        Parse a specific pmrep CSV file instead of auto-discovering.

    -A DIR, --archive-dir DIR
        Analyze PCP binary archives from a standalone directory.

    --no-cache
        Skip cache, always process archives from scratch.

    --refresh-cache
        Force reprocess archives and update cache.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> pcpinfo -d
    example.com> pcpinfo -d -A /path/to/pcp_archives
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_network_help_msg(no_pipe):
    msg = '''pcpinfo -n  --  Network statistics from PCP data

SYNOPSIS
    pcpinfo -n [OPTIONS]

DESCRIPTION
    Show network statistics from PCP performance data in the sosreport.
    Reads network.interface.* metrics per interface (bytes, packets,
    errors) and displays min, max, and average values with trend
    indicators.  Highlights interfaces with non-zero error rates.

    PCP data is searched in:
      sos_commands/pcp/
      var/log/pcp/pmlogger/<hostname>/

OPTIONS
    -n, --network
        Enable network statistics mode.

    -f FILE, --file FILE
        Parse a specific pmrep CSV file instead of auto-discovering.

    -A DIR, --archive-dir DIR
        Analyze PCP binary archives from a standalone directory.

    --no-cache
        Skip cache, always process archives from scratch.

    --refresh-cache
        Force reprocess archives and update cache.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> pcpinfo -n
    example.com> pcpinfo -n -A /path/to/pcp_archives
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_top_procs_help_msg(no_pipe):
    msg = '''pcpinfo -p N  --  Top CPU consuming processes from PCP data

SYNOPSIS
    pcpinfo -p N [OPTIONS]

DESCRIPTION
    Show the top N CPU consuming processes from PCP binary archives in
    the sosreport.  Reads the proc.hog.cpu metric, which is only
    available in binary archives (requires pmrep to be installed).

    By default, only the 3 most recent archives are processed to avoid
    excessive runtime.  Use --all-archives to process all of them.

    PCP archives are searched in:
      var/log/pcp/pmlogger/<hostname>/

OPTIONS
    -p N, --top-procs N
        Show top N CPU consuming processes.

    --all-archives
        Process all archives, not just the 3 most recent ones.
        May take 90+ minutes for large archive sets.

    -A DIR, --archive-dir DIR
        Analyze PCP binary archives from a standalone directory.

    --no-cache
        Skip cache, always process archives from scratch.

    --refresh-cache
        Force reprocess archives and update cache.

    -h, --help
        Show this help message.

EXAMPLES
    example.com> pcpinfo -p 5
    example.com> pcpinfo -p 10 -c
    example.com> pcpinfo -p 5 --all-archives
    example.com> pcpinfo -p 5 -A /path/to/pcp_archives
'''
    if no_pipe:
        print(msg)
        return ""
    return msg


def print_help_msg(op, no_pipe):
    cmd_examples = '''
Examples:
    # Show summary of available PCP data
    > pcpinfo

    # Show CPU utilization from PCP data
    > pcpinfo -c

    # Show memory utilization
    > pcpinfo -m

    # Show disk I/O statistics
    > pcpinfo -d

    # Show network statistics
    > pcpinfo -n

    # Show all metrics
    > pcpinfo -a

    # Write CPU metrics to a file
    > pcpinfo --output-cpu /tmp/pcp_cpu.txt

    # Write memory metrics to a file
    > pcpinfo --output-mem /tmp/pcp_mem.txt

    # Write disk I/O to a file
    > pcpinfo --output-disk /tmp/pcp_disk.txt

    # Write network stats to a file
    > pcpinfo --output-network /tmp/pcp_net.txt

    # Write comprehensive report (creates prefix_all.txt, prefix_cpu.txt, etc.)
    > pcpinfo --output-all /tmp/pcp_report

    # Show top 5 CPU consuming processes
    > pcpinfo -p 5

    # Show top 10 CPU consumers alongside CPU metrics
    > pcpinfo -p 10 -c

    # Show data from a specific pmrep CSV file
    > pcpinfo -f /path/to/pmrep_output.csv -c

    # Analyze a standalone PCP archive directory (e.g. collected from a remote server)
    > pcpinfo --archive-dir /path/to/pcp_archives -c
    > pcpinfo -A /path/to/pcp_archives --output-all /tmp/report

    # Standalone directories may contain compressed (.xz) or uncompressed archives
    > pcpinfo -A /path/to/archives.xz/ -m

PCP data is searched in:
    <sos_home>/sos_commands/pcp/
    <sos_home>/var/log/pcp/pmlogger/<hostname>/

If pmrep is installed on this system, binary archives will be converted
automatically.
'''
    if no_pipe:
        op.print_help()
        print(cmd_examples)
        return ""
    else:
        output = StringIO()
        op.print_help(file=output)
        return output.getvalue() + "\n" + cmd_examples


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pcpinfo(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    global is_cmd_stopped
    global sos_home
    is_cmd_stopped = is_cmd_stopped_func if is_cmd_stopped_func is not None else lambda: False
    sos_home = env_vars['sos_home']

    usage = "Usage: %s [options] [pmrep_csv_file ...]" % cmd_name
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='show this help message and exit')
    op.add_option('-a', '--all', dest='show_all', action='store_true',
                  help='show all available metrics')
    op.add_option('-c', '--cpu', dest='cpu', action='store_true',
                  help='show CPU utilization')
    op.add_option('-d', '--disk', dest='disk', action='store_true',
                  help='show disk I/O statistics')
    op.add_option('-f', '--file', dest='input_file', default="",
                  action='store', type='string',
                  help='parse a specific pmrep CSV file')
    op.add_option('-m', '--mem', dest='mem', action='store_true',
                  help='show memory utilization')
    op.add_option('-n', '--network', dest='network', action='store_true',
                  help='show network statistics')
    op.add_option('--output-cpu', dest='output_cpu', default="",
                  action='store', type='string',
                  help='write CPU metrics to file')
    op.add_option('--output-mem', dest='output_mem', default="",
                  action='store', type='string',
                  help='write memory metrics to file')
    op.add_option('--output-disk', dest='output_disk', default="",
                  action='store', type='string',
                  help='write disk I/O metrics to file')
    op.add_option('--output-network', dest='output_network', default="",
                  action='store', type='string',
                  help='write network statistics to file')
    op.add_option('--output-all', dest='output_all', default="",
                  action='store', type='string',
                  help='write comprehensive report (prefix for multiple files)')
    op.add_option('-A', '--archive-dir', dest='archive_dir', default="",
                  action='store', type='string',
                  help='analyze PCP archives from a standalone directory (supports .xz)')
    op.add_option('-p', '--top-procs', dest='top_procs', default=0,
                  action='store', type='int',
                  help='show top N CPU consuming processes (e.g. -p 5; requires PCP archives)')
    op.add_option('--all-archives', dest='all_archives', action='store_true',
                  help='process all archives (not just 3 most recent) for proc analysis; may take 90+ min')
    op.add_option('--no-cache', dest='no_cache', action='store_true',
                  help='skip cache, always process archives from scratch')
    op.add_option('--refresh-cache', dest='refresh_cache', action='store_true',
                  help='force reprocess archives and update cache')

    o = args = None
    try:
        (o, args) = op.parse_args(input_str.split())
    except Exception:
        return ""

    if o.help or show_help:
        if o.cpu:
            return print_cpu_help_msg(no_pipe)
        elif o.mem:
            return print_mem_help_msg(no_pipe)
        elif o.disk:
            return print_disk_help_msg(no_pipe)
        elif o.network:
            return print_network_help_msg(no_pipe)
        elif o.top_procs:
            return print_top_procs_help_msg(no_pipe)
        return print_help_msg(op, no_pipe)

    screen.init_data(no_pipe, 1, is_cmd_stopped)
    result_str = ""

    include_proc = o.top_procs > 0
    top_n = o.top_procs if o.top_procs > 0 else 5

    # Load PCP data
    data = PCPData()

    # Mutual exclusion: -A and -f cannot be used together
    if o.input_file and o.archive_dir:
        msg = "Options -A/--archive-dir and -f/--file are mutually exclusive.\n"
        if no_pipe:
            print(msg)
            return ""
        return msg

    # Specific file provided via -f
    if o.input_file:
        if not isfile(o.input_file):
            msg = "File not found: %s\n" % o.input_file
            if no_pipe:
                print(msg)
                return ""
            return msg
        parsed = parse_pmrep_csv(o.input_file, data)
        if not parsed:
            parsed = parse_pmrep_text(o.input_file, data)
        data.source = o.input_file
    elif o.archive_dir:
        if not isdir(o.archive_dir):
            msg = "Archive directory not found: %s\n" % o.archive_dir
            if no_pipe:
                print(msg)
                return ""
            return msg
        if not _find_pmrep():
            msg = ("pmrep is not installed on this system.\n"
                   "Install PCP tools to analyze binary archives: "
                   "dnf install pcp-system-tools\n")
            if no_pipe:
                print(msg)
                return ""
            return msg
        parse_binary_archive(o.archive_dir, data, include_proc=include_proc,
                             all_archives=o.all_archives, no_cache=o.no_cache,
                             refresh_cache=o.refresh_cache)
        if not data.timestamps:
            msg = ("No valid PCP archive data found in: %s\n"
                   "Ensure the directory contains .index/.meta archive files.\n"
                   "PCP 5.x+ handles .xz compressed archives natively.\n") % o.archive_dir
            if no_pipe:
                print(msg)
                return ""
            return msg
        data.source = o.archive_dir
    elif len(args) > 1:
        # File(s) provided as positional arguments
        for fpath in args[1:]:
            if not isfile(fpath):
                continue
            parsed = parse_pmrep_csv(fpath, data)
            if not parsed:
                parse_pmrep_text(fpath, data)
            if not data.source:
                data.source = fpath
    else:
        # Auto-discover from sosreport
        data = load_pcp_data(sos_home, include_proc=include_proc)

    # Handle output-to-file options
    any_output = False
    if o.output_cpu:
        any_output = True
        ok, path = output_cpu(data, o.output_cpu)
        if ok:
            msg = "CPU report written to: %s\n" % path
        else:
            msg = "Failed to write CPU report: %s\n" % path
        result_str += screen.get_pipe_aware_line(msg)

    if o.output_mem:
        any_output = True
        ok, path = output_mem(data, o.output_mem)
        if ok:
            msg = "Memory report written to: %s\n" % path
        else:
            msg = "Failed to write memory report: %s\n" % path
        result_str += screen.get_pipe_aware_line(msg)

    if o.output_disk:
        any_output = True
        ok, path = output_disk(data, o.output_disk)
        if ok:
            msg = "Disk I/O report written to: %s\n" % path
        else:
            msg = "Failed to write disk report: %s\n" % path
        result_str += screen.get_pipe_aware_line(msg)

    if o.output_network:
        any_output = True
        ok, path = output_network(data, o.output_network)
        if ok:
            msg = "Network report written to: %s\n" % path
        else:
            msg = "Failed to write network report: %s\n" % path
        result_str += screen.get_pipe_aware_line(msg)

    if o.output_all:
        any_output = True
        results = output_all(data, o.output_all)
        for ok, path in results:
            if ok:
                msg = "Report written to: %s\n" % path
            else:
                msg = "Failed to write report: %s\n" % path
            result_str += screen.get_pipe_aware_line(msg)

    if any_output:
        return result_str

    # Display to terminal
    show_any = o.cpu or o.mem or o.disk or o.network or o.show_all or include_proc

    if not show_any:
        # Default: show summary
        result_str += show_summary(data, no_pipe)
    else:
        if o.show_all or o.cpu:
            result_str += show_cpu(data, no_pipe)
        if o.show_all or o.mem:
            result_str += show_mem(data, no_pipe)
        if o.show_all or o.disk:
            result_str += show_disk(data, no_pipe)
        if o.show_all or o.network:
            result_str += show_network(data, no_pipe)
        if include_proc:
            result_str += show_top_procs(data, top_n, no_pipe)

    return result_str
