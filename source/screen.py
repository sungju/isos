"""
Screen Display Module

Provides screen and terminal display utilities for isos:
- Color management for terminal output (Rich-based)
- Syntax highlighting for command output
- Pipe-aware output handling (terminal vs redirected)
- Column-based coloring (deprecated - use TableFormatter)

This module manages global state for color output configuration
and provides utilities to format text with Rich styles.

NEW: Rich Console Integration
- Uses Rich library for modern terminal output
- Automatic pipe detection and color suppression
- Semantic color styles for consistent theming
- Backward compatible with legacy ANSI code
"""

import sys
import ansicolor
from prompt_toolkit import print_formatted_text, HTML

# Rich library imports
try:
    from rich.console import Console
    from rich.style import Style
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None
    Style = None
    Text = None


# Global state variables
no_pipe = True
is_cmd_stopped = None
header_start_idx = 0

# Rich Console singleton (initialized in init_data)
_console = None

# Rich style definitions (semantic colors)
_rich_styles = {
    'title': 'bold bright_cyan',
    'header': 'bold cyan',
    'content': 'default',
    'important': 'bright_yellow',
    'warning': 'yellow',
    'critical': 'bright_red',
    'success': 'bright_green',
    'info': 'magenta',
    'highlight': 'bright_magenta',
}

# Legacy color constants - deprecated, use context colors instead
COLOR_1 = ""
COLOR_2 = ""
COLOR_3 = ""
COLOR_4 = ""
COLOR_5 = ""
COLOR_6 = ""
COLOR_7 = ""
COLOR_8 = ""
COLOR_9 = ""
COLOR_10 = ""
COLOR_11 = ""
COLOR_12 = ""
COLOR_13 = ""
COLOR_14 = ""
COLOR_RESET = ""

# Column color mapping (column number -> color code) - DEPRECATED
column_color = {}

# Context-based color constants (preferred approach)
COLOR_TITLE = ""        # Section titles and headers
COLOR_HEADER = ""       # Table/list headers
COLOR_CONTENT = ""      # Normal content (usually no color)
COLOR_IMPORTANT = ""    # Important values that need attention
COLOR_WARNING = ""      # Warning level issues
COLOR_CRITICAL = ""     # Critical/error level issues
COLOR_SUCCESS = ""      # Success/positive indicators
COLOR_INFO = ""         # Metadata and secondary information
COLOR_HIGHLIGHT = ""    # Highlighted/emphasized text


def init_data(l_no_pipe, l_header_start_idx, l_is_cmd_stopped):
    """
    Initialize screen module with display parameters.

    Args:
        l_no_pipe: True if output goes to terminal, False if piped
        l_header_start_idx: Column index where coloring should start
        l_is_cmd_stopped: Function that returns True if Ctrl-C was pressed

    Note:
        This function must be called before using get_colored_line()
        or other output functions.
    """
    global header_start_idx, is_cmd_stopped, no_pipe, _console

    no_pipe = l_no_pipe
    header_start_idx = l_header_start_idx
    is_cmd_stopped = l_is_cmd_stopped

    # Initialize Rich Console if available
    if RICH_AVAILABLE:
        _console = Console(
            force_terminal=no_pipe,
            force_interactive=False,
            no_color=not no_pipe,
            legacy_windows=False
        )
    else:
        _console = None

    set_color_table()


def set_color_table():
    """
    Set up color mapping based on pipe status.

    When output goes to terminal (no_pipe=True), initializes ANSI color
    codes for both legacy column colors and new context-based colors.
    When output is piped (no_pipe=False), sets all colors to empty strings.

    Sets global variables:
    - Legacy: COLOR_1 through COLOR_14, COLOR_RESET, column_color
    - Context-based: COLOR_TITLE, COLOR_HEADER, COLOR_CONTENT, etc.
    """
    global COLOR_1, COLOR_2, COLOR_3, COLOR_4, COLOR_5, COLOR_6
    global COLOR_7, COLOR_8, COLOR_9, COLOR_10, COLOR_11, COLOR_12
    global COLOR_13, COLOR_14, COLOR_RESET
    global COLOR_TITLE, COLOR_HEADER, COLOR_CONTENT, COLOR_IMPORTANT
    global COLOR_WARNING, COLOR_CRITICAL, COLOR_SUCCESS, COLOR_INFO, COLOR_HIGHLIGHT
    global column_color, no_pipe

    if no_pipe:
        # Legacy colors (deprecated)
        COLOR_1  = ansicolor.get_color(ansicolor.RED)
        COLOR_2  = ansicolor.get_color(ansicolor.GREEN)
        COLOR_3  = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_4  = ansicolor.get_color(ansicolor.BLUE)
        COLOR_5  = ansicolor.get_color(ansicolor.MAGENTA)
        COLOR_6  = ansicolor.get_color(ansicolor.CYAN)
        COLOR_7  = ansicolor.get_color(ansicolor.YELLOW)
        COLOR_8  = ansicolor.get_color(ansicolor.BLUE)
        COLOR_9  = ansicolor.get_color(ansicolor.LIGHTRED)
        COLOR_10 = ansicolor.get_color(ansicolor.LIGHTGREEN)
        COLOR_11 = ansicolor.get_color(ansicolor.LIGHTYELLOW)
        COLOR_12 = ansicolor.get_color(ansicolor.LIGHTBLUE)
        COLOR_13 = ansicolor.get_color(ansicolor.LIGHTMAGENTA)
        COLOR_14 = ansicolor.get_color(ansicolor.LIGHTCYAN)
        COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

        # Context-based colors (preferred)
        COLOR_TITLE = ansicolor.get_color(ansicolor.LIGHTCYAN)      # Section titles
        COLOR_HEADER = ansicolor.get_color(ansicolor.CYAN)          # Table headers
        COLOR_CONTENT = ""                                           # Normal text (no color)
        COLOR_IMPORTANT = ansicolor.get_color(ansicolor.LIGHTYELLOW) # Important values
        COLOR_WARNING = ansicolor.get_color(ansicolor.YELLOW)        # Warnings
        COLOR_CRITICAL = ansicolor.get_color(ansicolor.LIGHTRED)     # Critical/errors
        COLOR_SUCCESS = ansicolor.get_color(ansicolor.LIGHTGREEN)    # Success indicators
        COLOR_INFO = ansicolor.get_color(ansicolor.MAGENTA)          # Metadata/secondary info
        COLOR_HIGHLIGHT = ansicolor.get_color(ansicolor.LIGHTMAGENTA) # Emphasis

        column_color = {
            1: COLOR_1,   2: COLOR_2,   3: COLOR_3,   4: COLOR_4,
            5: COLOR_5,   6: COLOR_6,   7: COLOR_7,   8: COLOR_8,
            9: COLOR_9,   10: COLOR_10, 11: COLOR_11, 12: COLOR_12,
            13: COLOR_13, 14: COLOR_14
        }
    else:
        # Piped output - no colors
        COLOR_1 = COLOR_2 = COLOR_3 = COLOR_4 = ""
        COLOR_5 = COLOR_6 = COLOR_7 = COLOR_8 = ""
        COLOR_9 = COLOR_10 = COLOR_11 = COLOR_12 = ""
        COLOR_13 = COLOR_14 = COLOR_RESET = ""

        COLOR_TITLE = COLOR_HEADER = COLOR_CONTENT = ""
        COLOR_IMPORTANT = COLOR_WARNING = COLOR_CRITICAL = ""
        COLOR_SUCCESS = COLOR_INFO = COLOR_HIGHLIGHT = ""

        column_color = {}


def get_colored_line(line):
    """
    Apply column-based coloring to a line of text.

    DEPRECATED: This function has a fundamental design issue - it splits
    lines by whitespace and colors "words" by position, which breaks when
    fixed-width format strings create extra spaces. This causes colors to
    land on wrong columns or in the middle of values.

    RECOMMENDED: Use TableFormatter from table_formatter.py instead.
    TableFormatter handles formatting and coloring together, avoiding the
    split/color mismatch problem.

    Old pattern (problematic):
        screen.column_color = {1: screen.COLOR_3, 2: screen.COLOR_2}
        header = "%-12s %-6s" % ("COL1", "COL2")
        line = screen.get_colored_line(header)

    New pattern (recommended):
        from table_formatter import TableFormatter
        table = TableFormatter(no_pipe=no_pipe)
        table.add_column("COL1", width=12, color='cyan')
        table.add_column("COL2", width=6, color='green')
        table.add_row("value1", "value2")
        output = table.format()

    This function is kept functional for backward compatibility during
    the transition period, but new code should use TableFormatter.

    Colors each whitespace-separated word based on its column position.
    Skips the first N columns if header_start_idx is set.

    Args:
        line: String to colorize

    Returns:
        String with ANSI color codes applied (if no_pipe=True)
        or original string stripped of trailing whitespace

    Example:
        Input:  "PID  USER  CPU  MEM"
        Output: "\033[31mPID\033[0m  \033[32mUSER\033[0m  ..." (with colors)
    """
    global header_start_idx, is_cmd_stopped, no_pipe, column_color, COLOR_RESET

    line = line.rstrip()
    if not column_color or not line.strip():
        return line

    words = line.split()
    if not words:
        return line

    # Build result using list accumulation for efficiency
    result_parts = []
    pos = 0
    count = 1
    start_idx_count = header_start_idx - 1

    for word in words:
        if is_cmd_stopped():
            return ''.join(result_parts)

        # Find word position from current position
        word_start = line.find(word, pos)
        if word_start == -1:
            break

        # Preserve whitespace before word
        if word_start > pos:
            result_parts.append(line[pos:word_start])

        # Apply color or keep plain
        if start_idx_count > 0:
            # Skip coloring for header columns
            result_parts.append(word)
            start_idx_count -= 1
        elif count in column_color:
            # Apply column color
            result_parts.append(column_color[count])
            result_parts.append(word)
            result_parts.append(COLOR_RESET)
            count += 1
        else:
            # No color for this column
            result_parts.append(word)
            count += 1

        pos = word_start + len(word)

    # Append trailing content
    if pos < len(line):
        result_parts.append(line[pos:])

    return ''.join(result_parts).rstrip()


def get_pipe_aware_line(line):
    """
    Output line with color, aware of pipe status.

    When output goes to terminal, prints colored line directly.
    When output is piped, returns colored line as string.

    Args:
        line: String to output

    Returns:
        Empty string if printed to terminal (no_pipe=True)
        or line with newline if piped (no_pipe=False)
    """
    global header_start_idx, is_cmd_stopped, no_pipe

    if line is None:
        return ""

    line = get_colored_line(line)
    if no_pipe:
        print(line)
        return ""
    else:
        return line + "\n"


def get_pipe_color_line(line, color="normal", end="\n"):
    """
    Output HTML-formatted colored line, aware of pipe status.

    Uses prompt_toolkit's HTML formatting for rich terminal output.

    Args:
        line: String to output
        color: HTML color tag name (e.g., "red", "green", "ansired")
        end: Line ending (default newline)

    Returns:
        Empty string if printed to terminal (no_pipe=True)
        or line with ending if piped (no_pipe=False)

    Example:
        get_pipe_color_line("Error occurred", "red")
        # Terminal: prints "Error occurred" in red
        # Piped: returns "Error occurred\n"
    """
    global no_pipe

    if line is None:
        return ""

    if no_pipe:
        print_formatted_text(HTML("<%s>%s</%s>" % (color, line, color)), end=end)
        return ""
    else:
        return line + end


def should_use_table_formatter():
    """
    Check if TableFormatter is available and recommended.

    This helper function guides command authors to use the new TableFormatter
    pattern instead of the deprecated column_color + get_colored_line approach.

    The old pattern has a fundamental issue where splitting text by whitespace
    and coloring by position breaks when fixed-width formatting creates extra
    spaces. TableFormatter solves this by handling formatting and coloring
    together.

    Returns:
        True (always) - TableFormatter is available and recommended

    Example usage in command modules:
        if should_use_table_formatter():
            # Use new pattern
            from table_formatter import create_table
            table = create_table(no_pipe)
            table.add_column("NAME", width=20, color='cyan')
            table.add_row("value")
            output = table.format()
        else:
            # Use old pattern (deprecated)
            screen.column_color = {1: screen.COLOR_3}
            line = screen.get_colored_line(header)
    """
    return True


# ============================================================================
# Rich-based Color API (New)
# ============================================================================

def get_console():
    """
    Get the Rich Console instance.

    Returns:
        Rich Console instance, or None if Rich unavailable or piped output

    Example:
        console = get_console()
        if console:
            console.print("Hello", style="bold cyan")
    """
    return _console


def print_rich(text, style=None, end="\n"):
    """
    Print text using Rich with optional style.

    Automatically handles pipe detection - uses Rich for terminal,
    plain text for piped output.

    Args:
        text: Text to print
        style: Rich style string (e.g., "bold cyan", "bright_red")
        end: Line ending (default newline)

    Example:
        print_rich("Error occurred", style="bright_red")
        print_rich("Success", style="bright_green")
    """
    global _console, no_pipe

    if _console and no_pipe:
        _console.print(text, style=style, end=end)
    else:
        # Fallback to plain print
        print(text, end=end)


def print_semantic(text, semantic_type="content", end="\n"):
    """
    Print text using semantic color style.

    Uses predefined semantic styles for consistent theming across isos.

    Args:
        text: Text to print
        semantic_type: One of: title, header, content, important, warning,
                       critical, success, info, highlight
        end: Line ending (default newline)

    Example:
        print_semantic("System Overview", "title")
        print_semantic("WARNING: High memory usage", "warning")
        print_semantic("Operation completed", "success")
    """
    global _console, no_pipe, _rich_styles

    style = _rich_styles.get(semantic_type, 'default')

    if _console and no_pipe:
        _console.print(text, style=style, end=end)
    else:
        # Fallback to plain print
        print(text, end=end)


def get_semantic_style(semantic_type):
    """
    Get Rich style string for semantic type.

    Args:
        semantic_type: One of: title, header, content, important, warning,
                       critical, success, info, highlight

    Returns:
        Rich style string (e.g., "bold cyan")

    Example:
        style = get_semantic_style("critical")
        console.print("Error", style=style)
    """
    return _rich_styles.get(semantic_type, 'default')


def format_rich_text(text, style=None):
    """
    Format text with Rich style and return as string.

    Pipe-aware: returns styled text for terminal, plain text for pipes.

    Args:
        text: Text to format
        style: Rich style string or semantic type

    Returns:
        Formatted string

    Example:
        msg = format_rich_text("Error", "bright_red")
        print(msg)
    """
    global _console, no_pipe

    if not _console or not no_pipe:
        return text

    # Check if style is a semantic type
    if style in _rich_styles:
        style = _rich_styles[style]

    # Create Rich Text object and render
    if RICH_AVAILABLE:
        rich_text = Text(text, style=style)
        # Render to string using console
        from io import StringIO
        string_io = StringIO()
        temp_console = Console(file=string_io, force_terminal=True, legacy_windows=False)
        temp_console.print(rich_text, end='')
        return string_io.getvalue()
    else:
        return text


def print_header(text):
    """Print a header line using semantic header style."""
    print_semantic(text, "header")


def print_title(text):
    """Print a title line using semantic title style."""
    print_semantic(text, "title")


def print_warning(text):
    """Print a warning message using semantic warning style."""
    print_semantic(text, "warning")


def print_critical(text):
    """Print a critical/error message using semantic critical style."""
    print_semantic(text, "critical")


def print_success(text):
    """Print a success message using semantic success style."""
    print_semantic(text, "success")


def print_info(text):
    """Print an info message using semantic info style."""
    print_semantic(text, "info")
