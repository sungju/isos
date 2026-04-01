# isos — Interactive Sosreport Analysis Shell

An interactive shell for analyzing Red Hat sosreports. isos reduces the manual effort of navigating and extracting information from sosreport archives by providing smart file browsing, integrated commands, and automated issue detection.

---

## Features

- **Smart file access** — Type a filename to view it with color output; type a directory name to navigate into it
- **Command history with autocomplete** — Use the right arrow key to complete from history
- **Pipe support** — Pipe isos output to any system command (`free | grep Mem`)
- **Automated issue detection** — `autocheck` runs known-issue rules against the sosreport
- **Rich analysis commands** — Memory, process, network, cgroup, LVM, SAR, perf, trace, OCP analysis and more
- **Sosreport comparison** — Side-by-side diff of two sosreports with interactive fzf UI
- **Startup scripts** — Autorun commands at launch via `~/.isosrc`

---

## Requirements

- Python 3
- `fzf` (optional, for `soscompare` interactive UI)
- `tshark` or `tcpdump` (optional, for `pcapinfo`)
- `xsos` (optional, for extended sosreport analysis)

---

## Installation

```bash
cd ~/
git clone https://github.com/sungju/isos.git
```

Add an alias to your shell profile:

```bash
echo "alias is='~/isos/isos.sh'" >> ~/.bashrc
source ~/.bashrc
```

---

## Quick Start

```bash
cd /path/to/sosreport/
is
```

The prompt shows the hostname from the sosreport:

```
host0.example.com>
```

To get help:

```
host0.example.com> help
```

---

## Shell Behavior

### File and Directory Access

Type a filename to view it with colored output:

```
host0.example.com> free
               total        used        free      shared  buff/cache   available
Mem:       527523056     8424572   512957876       85568     9313436   519098484
Swap:              0           0           0
```

Type a directory name to navigate into it:

```
host0.example.com> sos_commands/kernel
host0.example.com/sos_commands/kernel>
```

### Prompt Navigation

The prompt tracks your location within the sosreport:

```
host0.example.com> cd sos_commands/kernel
host0.example.com/sos_commands/kernel> cd ~/
host0.example.com:/home/sungju>
```

### External Commands

If input doesn't match a file or directory in the sosreport, it runs as a system command:

```
host0.example.com> wc df
  258  1549 34520 df
```

To force execution as an external command (bypassing file match):

```
host0.example.com> !free
               total        used        free      shared  buff/cache   available
Mem:        64264044    58005292      806260    30627960    37372204     6258752
Swap:              0           0           0
```

To open a shell prompt directly:

```
host0.example.com> sh
sh-5.1$ date
Mon Oct 21 11:33:09 PM UTC 2024
sh-5.1$ exit
host0.example.com>
```

### Pipe Support

Pipe output to any system command:

```
host0.example.com> dmidecode | grep CPU
    Socket Designation: CPU1
    Version: Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz
    Socket Designation: CPU2
    Version: Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz
```

### History

View command history:

```
host0.example.com> h
[1] xsos
[2] ls
[3] cd sos_commands/kernel
[4] ls

host0.example.com> h -d
[1] xsos [~]
[2] ls [~]
[3] cd sos_commands/kernel [~]
[4] ls [~/sos_commands/kernel]
```

Re-execute a history entry with its original directory:

```
host0.example.com> !4
```

Re-execute a history entry in the current directory:

```
host0.example.com> ?4
```

---

## Built-in Commands

### `cat` — View Files with Color

```
host0.example.com> cat free
               total        used        free      shared  buff/cache   available
Mem:       527523056     8424572   512957876       85568     9313436   519098484
Swap:              0           0           0
```

View multiple files with glob patterns:

```
host0.example.com> cd sos_commands/memory
host0.example.com/sos_commands/memory> cat free*

========== < free > ==========
               total        used        free      shared  buff/cache   available
Mem:       527523056     8424572   512957876       85568     9313436   519098484
Swap:              0           0           0

========== < free_-m > ==========
               total        used        free      shared  buff/cache   available
Mem:          515159        8243      500918          83        9095      506915
Swap:              0           0           0
```

### `set` — View and Change Settings

The `sos_home` variable controls the root directory isos uses as home. Commands like `xsos` reference this path.

```
host0.example.com> set
Setting variables
=================
sos_home        : ~/sosreport-host0-2024-09-17-nvrqmth

host0.example.com> set sos_home /path/to/other/sosreport
```

### `man` / `help` — Get Help

```
host0.example.com> help
host0.example.com> help perf
```

### `cd`, `exit`, `sh`, `h` — Navigation and Shell

| Command | Description |
|---------|-------------|
| `cd <dir>` | Change directory |
| `exit` | Exit isos |
| `sh` | Open a system shell |
| `h` | Show history |
| `h -d` | Show history with directory context |

---

## Internal Commands

Internal commands are prefixed with `/`:

| Command | Description |
|---------|-------------|
| `/list` | List available analysis commands |
| `/reload` | Reload command modules without restarting |
| `/set` | Alias for `set` (view/change settings) |
| `/sethome` | Set sosreport home directory |

`/reload` is useful during development to pick up changes to command modules without restarting isos.

---

## Startup Configuration

Create `~/.isosrc` to run commands automatically at launch:

```bash
# ~/.isosrc — isos startup script
xsos
autocheck
```

---

## Analysis Commands

### `autocheck` — Automated Issue Detection

Runs known-issue detection rules against the sosreport. Rules check for kernel bugs, scheduler deadlocks, memory issues, and other known problems.

```
host0.example.com> autocheck
host0.example.com> autocheck -a          # Run all rules (not just major)
host0.example.com> autocheck -l          # List available rules
host0.example.com> autocheck -r          # Reload rules from disk
```

### `meminfo` — Memory Analysis

```
host0.example.com> meminfo               # Memory summary
host0.example.com> meminfo -p            # Top memory-consuming processes
host0.example.com> meminfo -o            # OOM killer events
host0.example.com> meminfo -s            # SLAB cache usage
host0.example.com> meminfo -g            # Bar graph visualization
host0.example.com> meminfo -p -g -m 20  # Top 20 processes with graph
```

### `psinfo` — Process Information

```
host0.example.com> psinfo                # Process list
host0.example.com> psinfo -t            # Process tree
host0.example.com> psinfo -s cpu        # Sort by CPU usage
host0.example.com> psinfo -f httpd      # Filter by process name
```

### `netinfo` — Network Information

```
host0.example.com> netinfo              # All network information
host0.example.com> netinfo -i           # Network interfaces
host0.example.com> netinfo -r           # Routing table
host0.example.com> netinfo -c           # Network connections
host0.example.com> netinfo -s ESTABLISHED  # Filter connections by state
```

### `sarinfo` — SAR System Activity

```
host0.example.com> sarinfo              # All SAR data
host0.example.com> sarinfo -d cpu       # CPU activity
host0.example.com> sarinfo -d mem       # Memory activity
host0.example.com> sarinfo -d disk      # Disk I/O activity
host0.example.com> sarinfo -g           # Graph visualization
```

### `cginfo` — Cgroup Information

```
host0.example.com> cginfo              # Cgroup summary
host0.example.com> cginfo -m           # Memory limits and usage
host0.example.com> cginfo -c           # CPU quotas and shares
host0.example.com> cginfo -o           # OOM events
```

### `loginfo` — System Logs

```
host0.example.com> loginfo             # All logs
host0.example.com> loginfo -b          # Boot log
host0.example.com> loginfo -s          # Secure/auth log
host0.example.com> loginfo -j          # Journalctl output
```

### `auditinfo` — Audit System

```
host0.example.com> auditinfo           # All audit information
host0.example.com> auditinfo -c        # Audit configuration
host0.example.com> auditinfo -r        # Audit rules
host0.example.com> auditinfo -s        # Audit status
host0.example.com> auditinfo -l        # Audit log entries
```

### `hwinfo` — Hardware Information

```
host0.example.com> hwinfo             # Full hardware summary
host0.example.com> hwinfo -s          # Summary only
host0.example.com> hwinfo -p          # PCI device details
```

### `lvminfo` — LVM Storage

```
host0.example.com> lvminfo            # LVM overview
host0.example.com> lvminfo -p         # Physical volumes
host0.example.com> lvminfo -l         # Logical volumes
host0.example.com> lvminfo -f         # Filesystem usage
```

### `croninfo` — Cron Configuration

```
host0.example.com> croninfo           # All cron information
host0.example.com> croninfo -c        # Cron configuration files
host0.example.com> croninfo -l        # Cron execution logs
host0.example.com> croninfo -s        # Cron statistics
```

### `modules` — Kernel Modules

```
host0.example.com> modules            # Module list
host0.example.com> modules -t         # Taint status and flags
host0.example.com> modules -l         # Detailed module list
```

### `ipcinfo` — SYSV IPC Resources

```
host0.example.com> ipcinfo            # All IPC resources
host0.example.com> ipcinfo -m         # Shared memory segments
host0.example.com> ipcinfo -s         # Semaphore sets
host0.example.com> ipcinfo -q         # Message queues
```

### `perf` — Performance Profiling Data

```
host0.example.com> perf <perf-data>          # Show perf report
host0.example.com> perf -s overhead <data>   # Sort by overhead
host0.example.com> perf -b <data>            # Use ~/.debug symbols
host0.example.com> perf -d 5 <data>          # Show only top 5 stack depth
host0.example.com> perf -l 100 <data>        # Show top 100 lines
```

### `trace` — Kernel Trace Data

```
host0.example.com> trace <trace.dat>         # Show trace data
host0.example.com> trace -p <trace.dat>      # Show profiling with overhead
host0.example.com> trace -t <trace.dat>      # Sort by time consumed
host0.example.com> trace -g <trace.dat>      # Convert to funcgraph format
host0.example.com> trace -r <trace.dat>      # Reverse order
host0.example.com> trace -o out.txt <data>   # Save output to file
```

### `page_owner_stat` — Memory Allocation Analysis

Analyzes `page_owner` kernel debug output to identify top memory-consuming call stacks.

```
host0.example.com> page_owner_stat <page_owner_file>
host0.example.com> page_owner_stat -t 20 <file>   # Show top 20 allocations
```

### `pcapinfo` — Packet Capture Analysis

Requires `tshark` or `tcpdump`:

```
host0.example.com> pcapinfo <file.pcap>        # Analyze packet capture
host0.example.com> pcapinfo -s <file.pcap>     # Summary only
host0.example.com> pcapinfo -t <file.pcap>     # Use tshark for analysis
```

### `autoinfo` — Configuration Management Detection

Detects Puppet, Ansible, and Chef installations and configuration:

```
host0.example.com> autoinfo
```

### `caseinfo` — Case and System Identification

```
host0.example.com> caseinfo           # System and case metadata
host0.example.com> caseinfo -t        # List available topics
host0.example.com> caseinfo -d        # Detailed information
```

### `ocpinfo` — OpenShift Container Platform Analysis

For OCP/Kubernetes sosreports:

```
host0.example.com> ocpinfo                    # Full cluster analysis
host0.example.com> ocpinfo -n my-namespace    # Specific namespace
host0.example.com> ocpinfo -p                 # Pod details
host0.example.com> ocpinfo -d                 # Deployment status
```

### `soscompare` — Compare Two Sosreports

Side-by-side comparison with interactive fzf UI (requires `fzf`):

```
host0.example.com> soscompare /path/to/other/sosreport
host0.example.com> soscompare -l /path/to/other           # List topics
host0.example.com> soscompare -t memory,cpu /path/to/other  # Specific topics
host0.example.com> soscompare --no-fzf /path/to/other     # Plain text output
```

Diff markers:

| Marker | Meaning |
|--------|---------|
| `[=]` | Same in both reports |
| `[~]` | Changed (shows both values) |
| `[1]` | Only in sosreport 1 |
| `[2]` | Only in sosreport 2 |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ISOS_RULES_PATH` | Colon-separated paths to additional autocheck rule directories |
| `ISOS_EDITOR` | Editor for file preview in soscompare (default: `less`) |

---

## Tips

- Use `/reload` after modifying command modules — no restart needed
- Set `sos_home` to switch analysis to a different sosreport without restarting
- Use `autocheck` first on any new sosreport to quickly surface known issues
- Combine `meminfo -p -g` and `psinfo -s cpu` for memory and CPU bottleneck analysis
- Use `soscompare` to isolate differences between a working and a broken system
