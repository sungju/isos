"""
Screen Display Module

Provides screen and terminal display utilities for isos:
- Color management for terminal output
- Syntax highlighting for command output
- Pipe-aware output handling (terminal vs redirected)
- Column-based coloring

This module manages global state for color output configuration
and provides utilities to format text with ANSI color codes.
"""

import ansicolor
from prompt_toolkit import print_formatted_text, HTML


# Global state variables
no_pipe = True
is_cmd_stopped = None
header_start_idx = 0

# Color constants - initialized by set_color_table()
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

# Column color mapping (column number -> color code)
column_color = {}


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
    global header_start_idx, is_cmd_stopped, no_pipe

    no_pipe = l_no_pipe
    header_start_idx = l_header_start_idx
    is_cmd_stopped = l_is_cmd_stopped

    set_color_table()


def set_color_table():
    """
    Set up color mapping based on pipe status.

    When output goes to terminal (no_pipe=True), initializes ANSI color
    codes for 14 different colors. When output is piped (no_pipe=False),
    sets all colors to empty strings.

    Sets global variables: COLOR_1 through COLOR_14, COLOR_RESET, column_color
    """
    global COLOR_1, COLOR_2, COLOR_3, COLOR_4, COLOR_5, COLOR_6
    global COLOR_7, COLOR_8, COLOR_9, COLOR_10, COLOR_11, COLOR_12
    global COLOR_13, COLOR_14, COLOR_RESET
    global column_color, no_pipe

    if no_pipe:
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
        column_color = {}


def get_colored_line(line):
    """
    Apply column-based coloring to a line of text.

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
