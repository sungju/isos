"""
Common helper functions for isos command modules.

This module provides reusable utilities for:
- Color management
- Size formatting
- File parsing
- Error handling
- Table formatting (new pattern using TableFormatter)
"""

import ansicolor
from table_formatter import TableFormatter, create_table


# Constants for size formatting
SIZE_KB = 1024
SIZE_MB = 1048576
SIZE_GB = 1073741824
SIZE_TB = 1099511627776
SIZE_PB = 1125899906842624

# Constants for thresholds
THRESHOLD_CRITICAL = 90  # % usage for critical warning
THRESHOLD_WARNING = 80   # % usage for warning
THRESHOLD_VG_CRITICAL = 10  # % free for VG critical
THRESHOLD_VG_WARNING = 20   # % free for VG warning


class ColorManager(object):
    """
    Manages color output based on pipe status.

    Usage:
        colors = ColorManager(no_pipe)
        print(colors.cyan + "Header" + colors.reset)
    """

    def __init__(self, no_pipe):
        """Initialize color manager based on output destination."""
        if no_pipe:
            self.black = ansicolor.get_color(ansicolor.BLACK)
            self.red = ansicolor.get_color(ansicolor.RED)
            self.green = ansicolor.get_color(ansicolor.GREEN)
            self.yellow = ansicolor.get_color(ansicolor.YELLOW)
            self.blue = ansicolor.get_color(ansicolor.BLUE)
            self.magenta = ansicolor.get_color(ansicolor.MAGENTA)
            self.cyan = ansicolor.get_color(ansicolor.CYAN)
            self.lightred = ansicolor.get_color(ansicolor.LIGHTRED)
            self.lightgreen = ansicolor.get_color(ansicolor.LIGHTGREEN)
            self.lightyellow = ansicolor.get_color(ansicolor.LIGHTYELLOW)
            self.lightcyan = ansicolor.get_color(ansicolor.LIGHTCYAN)
            self.reset = ansicolor.get_color(ansicolor.RESET)
        else:
            self.black = ""
            self.red = ""
            self.green = ""
            self.yellow = ""
            self.blue = ""
            self.magenta = ""
            self.cyan = ""
            self.lightred = ""
            self.lightgreen = ""
            self.lightyellow = ""
            self.lightcyan = ""
            self.reset = ""

    def get_threshold_color(self, percentage, critical=THRESHOLD_CRITICAL, warning=THRESHOLD_WARNING):
        """
        Get color based on percentage threshold.

        Args:
            percentage: Value to check (0-100)
            critical: Critical threshold (default 90%)
            warning: Warning threshold (default 80%)

        Returns:
            Color code string
        """
        if percentage >= critical:
            return self.red
        elif percentage >= warning:
            return self.yellow
        else:
            return ""


def format_bytes(bytes_val, precision=2):
    """
    Format bytes into human readable format.

    Args:
        bytes_val: Number of bytes (int, float, or string)
        precision: Decimal places to show (default 2)

    Returns:
        Formatted string like "1.50 GB"
    """
    try:
        bytes_val = float(bytes_val)

        if bytes_val >= SIZE_TB:
            return "%.*f TB" % (precision, bytes_val / SIZE_TB)
        elif bytes_val >= SIZE_GB:
            return "%.*f GB" % (precision, bytes_val / SIZE_GB)
        elif bytes_val >= SIZE_MB:
            return "%.*f MB" % (precision, bytes_val / SIZE_MB)
        elif bytes_val >= SIZE_KB:
            return "%.*f KB" % (precision, bytes_val / SIZE_KB)
        else:
            return "%.0f B" % bytes_val
    except (ValueError, TypeError):
        return "N/A"


def parse_lvm_size(size_str):
    """
    Parse LVM size string to bytes.

    Args:
        size_str: String like '3.47t', '<99.00g', '1024.00m'

    Returns:
        Integer bytes value, or 0 on error
    """
    if not size_str:
        return 0

    # Remove '<' prefix and whitespace
    size_str = size_str.strip().lower().replace('<', '')

    # Size multipliers
    multipliers = {
        'b': 1,
        'k': SIZE_KB,
        'm': SIZE_MB,
        'g': SIZE_GB,
        't': SIZE_TB,
        'p': SIZE_PB
    }

    try:
        # Extract number and unit
        import re
        match = re.match(r'([\d.]+)\s*([bkmgtp])?', size_str)
        if match:
            num = float(match.group(1))
            unit = match.group(2) or 'b'
            return int(num * multipliers.get(unit, 1))
    except (ValueError, AttributeError):
        pass

    return 0


def safe_read_file(file_path, strip_lines=True):
    """
    Safely read file with error handling.

    Args:
        file_path: Path to file
        strip_lines: Whether to strip whitespace (default True)

    Returns:
        List of lines, or empty list on error
    """
    try:
        with open(file_path, 'r') as f:
            if strip_lines:
                return [line.strip() for line in f]
            else:
                return [line.rstrip('\n') for line in f]
    except (IOError, OSError):
        return []


def safe_read_single_value(file_path):
    """
    Read single value from file (like /sys files).

    Args:
        file_path: Path to file

    Returns:
        Stripped content, or None on error
    """
    try:
        with open(file_path, 'r') as f:
            return f.read().strip()
    except (IOError, OSError):
        return None


def skip_header_lines(line, headers=None):
    """
    Check if line should be skipped as header or noise.

    Args:
        line: Line to check
        headers: List of header keywords (default uses common ones)

    Returns:
        True if line should be skipped
    """
    if not line.strip():
        return True

    if headers is None:
        headers = ["WARNING:", "Reloading", "Loading config", "not found in config",
                   "Using cached", "Obtaining the complete", "Processing",
                   "Adding", "Running command", "/dev/sd"]

    for header in headers:
        if header in line:
            return True

    return False


def format_table_line(columns, widths, separator=" "):
    """
    Format a table line with fixed column widths.

    Args:
        columns: List of column values
        widths: List of column widths (negative for left-align)
        separator: Column separator (default " ")

    Returns:
        Formatted line string
    """
    parts = []
    for i, col in enumerate(columns):
        if i < len(widths):
            width = widths[i]
            if width < 0:
                # Left align
                parts.append(str(col).ljust(-width))
            else:
                # Right align
                parts.append(str(col).rjust(width))
        else:
            parts.append(str(col))

    return separator.join(parts)


def make_separator(width, char="-"):
    """
    Create separator line.

    Args:
        width: Total width
        char: Character to use (default "-")

    Returns:
        Separator string
    """
    return char * width


class OutputBuilder(object):
    """
    Helper to build command output with automatic pipe handling.

    Usage:
        builder = OutputBuilder(no_pipe)
        builder.add_line("Hello")
        return builder.get_result()

    New table support:
        builder = OutputBuilder(no_pipe)
        table = create_table(no_pipe)
        table.add_column("NAME", width=20, color='cyan')
        table.add_row("value")
        builder.add_table(table)
        return builder.get_result()
    """

    def __init__(self, no_pipe):
        """Initialize output builder."""
        self.no_pipe = no_pipe
        self.buffer = []

    def add_line(self, line=""):
        """Add a line to output."""
        if self.no_pipe:
            print(line)
        else:
            self.buffer.append(line)

    def add_colored_line(self, text, color="", reset=""):
        """Add colored line (handles pipe automatically)."""
        if self.no_pipe and color:
            print(color + text + reset)
        else:
            if self.no_pipe:
                print(text)
            else:
                self.buffer.append(text)

    def add_table(self, table_formatter):
        """
        Add a formatted table to output.

        Args:
            table_formatter: TableFormatter instance with data

        Example:
            table = create_table(no_pipe)
            table.add_column("PID", width=8, color='cyan')
            table.add_row("1234")
            builder.add_table(table)
        """
        if table_formatter:
            formatted = table_formatter.format()
            if formatted:
                if self.no_pipe:
                    print(formatted)
                else:
                    self.buffer.append(formatted)

    def get_result(self):
        """Get final result string."""
        if self.no_pipe:
            return ""
        else:
            return "\n".join(self.buffer)


def calculate_percentage(used, total):
    """
    Calculate percentage with error handling.

    Args:
        used: Used amount
        total: Total amount

    Returns:
        Float percentage (0-100), or 0.0 on error
    """
    try:
        used = float(used)
        total = float(total)
        if total > 0:
            return (used * 100.0) / total
    except (ValueError, TypeError, ZeroDivisionError):
        pass

    return 0.0


def get_sos_file_path(sos_home, *path_components):
    """
    Build path to file in sosreport.

    Args:
        sos_home: Root of sosreport
        *path_components: Path components to join

    Returns:
        Complete file path
    """
    import os.path
    return os.path.join(sos_home, *path_components)


# ============================================================================
# Table Formatting Utilities (New Pattern)
# ============================================================================

def format_table_row(values, widths, colors=None, no_pipe=True, align='left'):
    """
    Format a single table row with colors.

    Helper function for manual table formatting when not using TableFormatter.

    Args:
        values: List of column values
        widths: List of column widths
        colors: List of color names (optional)
        no_pipe: True if outputting to terminal
        align: Default alignment ('left', 'right', 'center')

    Returns:
        Formatted row string

    Example:
        row = format_table_row(
            ["eth0", "up", "192.168.1.1"],
            [12, 6, 15],
            ["cyan", "green", "yellow"],
            no_pipe=True
        )
    """
    parts = []
    for i, value in enumerate(values):
        if i >= len(widths):
            parts.append(str(value))
            continue

        width = widths[i]
        text = str(value)

        # Apply alignment
        if width < 0:
            # Negative width means left align
            text = text.ljust(-width)
        else:
            # Positive width means right align
            if align == 'right':
                text = text.rjust(width)
            elif align == 'center':
                text = text.center(width)
            else:
                text = text.ljust(width)

        # Apply color if specified
        if no_pipe and colors and i < len(colors) and colors[i]:
            from table_formatter import ANSI_COLOR_MAP
            color_const = ANSI_COLOR_MAP.get(colors[i].lower())
            if color_const:
                color_code = ansicolor.get_color(color_const)
                reset_code = ansicolor.get_color(ansicolor.RESET)
                text = color_code + text + reset_code

        parts.append(text)

    return " ".join(parts)


# Pre-defined color schemes for common table types

SCHEME_PROCESS_TABLE = {
    'pid': 'cyan',
    'user': 'green',
    'cpu': 'yellow',
    'mem': 'yellow',
    'command': 'lightcyan'
}

SCHEME_NETWORK_TABLE = {
    'device': 'cyan',
    'state': 'green',
    'address': 'yellow',
    'speed': 'lightcyan'
}

SCHEME_MEMORY_TABLE = {
    'name': 'cyan',
    'size': 'yellow',
    'used': 'lightred',
    'free': 'lightgreen',
    'percent': 'lightyellow'
}

SCHEME_DISK_TABLE = {
    'device': 'cyan',
    'mount': 'green',
    'size': 'yellow',
    'used': 'lightred',
    'avail': 'lightgreen',
    'percent': 'lightyellow'
}

SCHEME_LVM_TABLE = {
    'name': 'cyan',
    'vg': 'green',
    'size': 'yellow',
    'free': 'lightgreen',
    'devices': 'lightcyan'
}


def create_process_table(no_pipe=True):
    """
    Create a table formatted for process information.

    Returns:
        TableFormatter configured for process display
    """
    table = create_table(no_pipe=no_pipe)
    table.add_column("PID", width=8, align='right', color=SCHEME_PROCESS_TABLE['pid'])
    table.add_column("USER", width=12, align='left', color=SCHEME_PROCESS_TABLE['user'])
    table.add_column("CPU%", width=6, align='right', color=SCHEME_PROCESS_TABLE['cpu'])
    table.add_column("MEM%", width=6, align='right', color=SCHEME_PROCESS_TABLE['mem'])
    table.add_column("COMMAND", width=40, align='left', color=SCHEME_PROCESS_TABLE['command'])
    return table


def create_network_table(no_pipe=True):
    """
    Create a table formatted for network device information.

    Returns:
        TableFormatter configured for network display
    """
    table = create_table(no_pipe=no_pipe)
    table.add_column("DEVICE", width=12, align='left', color=SCHEME_NETWORK_TABLE['device'])
    table.add_column("STATE", width=6, align='left', color=SCHEME_NETWORK_TABLE['state'])
    table.add_column("IP_ADDRESS", width=18, align='left', color=SCHEME_NETWORK_TABLE['address'])
    table.add_column("SPEED", width=10, align='right', color=SCHEME_NETWORK_TABLE['speed'])
    return table


def create_memory_table(no_pipe=True):
    """
    Create a table formatted for memory information.

    Returns:
        TableFormatter configured for memory display
    """
    table = create_table(no_pipe=no_pipe)
    table.add_column("NAME", width=20, align='left', color=SCHEME_MEMORY_TABLE['name'])
    table.add_column("SIZE", width=12, align='right', color=SCHEME_MEMORY_TABLE['size'])
    table.add_column("USED", width=12, align='right', color=SCHEME_MEMORY_TABLE['used'])
    table.add_column("FREE", width=12, align='right', color=SCHEME_MEMORY_TABLE['free'])
    table.add_column("USE%", width=6, align='right', color=SCHEME_MEMORY_TABLE['percent'])
    return table
