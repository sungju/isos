#!/usr/bin/env/python
"""
ANSI Color and Terminal Control Module

Provides ANSI escape code functionality for terminal output including:
- Text coloring (foreground and background)
- Text formatting (bold, blink, underline, invert)
- Cursor manipulation (positioning, movement)
- Screen clearing (full screen, lines)
- TTY detection (no color output when piped)

This module manages ANSI escape sequences for rich terminal output
and automatically disables color codes when output is redirected to
a file or pipe (not a TTY).

Example:
    # Set text color
    set_color(RED | BOLD)
    print("Important message")
    set_color(RESET)

    # Get color code for manual formatting
    color_str = get_color(GREEN)
    message = color_str + "Success!" + get_color(RESET)

    # Clear screen
    clear_screen()

    # Move cursor
    cursor_up(3)
    set_cursor(10, 5)  # x=10, y=5
"""

# --------------------------------------------------------------------
# Author: Daniel Sungju Kwon
#
# This provides ANSI features such as color output and cursor manipulation.
#
# Contributors:
# --------------------------------------------------------------------
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import sys
import os


def run_ansi_code(ansi_code_str):
    """
    Output ANSI escape code to stdout.

    Args:
        ansi_code_str: ANSI escape sequence string

    Note:
        Uses print with end='' to avoid adding newline
    """
    print(ansi_code_str, end='')


#------------------------------------------------------------------------
# Color related constants and functions
#------------------------------------------------------------------------

# Color constants (0-16 for basic colors, 17 for reset)
BLACK = 1
RED = 2
GREEN = 3
YELLOW = 4
BLUE = 5
MAGENTA = 6
CYAN = 7
DARKGRAY = 8
LIGHTRED = 9
LIGHTGREEN = 10
LIGHTYELLOW = 11
LIGHTBLUE = 12
LIGHTMAGENTA = 13
LIGHTCYAN = 14
LIGHTGRAY = 15
WHITE = 16
RESET = 17

MAX_COLOR = WHITE

# Text formatting mode constants (can be combined with colors using |)
BOLD = 0x00100
BLINK = 0x00200
UNDERLINE = 0x00400
INVERT = 0x00800

MIN_MODE = BOLD
MAX_MODE = INVERT

# Masks for extracting color and mode from combined value
COLOR_MASK = 0x00ff
MODE_MASK = 0xff00

# ANSI background color escape codes
bg_color_list = {
    BLACK : u"\u001b[40m",
    RED : u"\u001b[41m",
    GREEN : u"\u001b[42m",
    YELLOW : u"\u001b[43m",
    BLUE : u"\u001b[44m",
    MAGENTA : u"\u001b[45m",
    CYAN : u"\u001b[46m",
    LIGHTGRAY : u"\u001b[47m",
    DARKGRAY : u"\u001b[40;1m",
    LIGHTRED : u"\u001b[41;1m",
    LIGHTGREEN : u"\u001b[42;1m",
    LIGHTYELLOW : u"\u001b[43;1m",
    LIGHTBLUE : u"\u001b[44;1m",
    LIGHTMAGENTA : u"\u001b[45;1m",
    LIGHTCYAN : u"\u001b[46;1m",
    WHITE : u"\u001b[47;1m",
    RESET : u"\u001b[0m",
}

# ANSI foreground color and formatting escape codes
color_list = {
    BLACK : u"\u001b[30m",
    RED : u"\u001b[31m",
    GREEN : u"\u001b[32m",
    YELLOW : u"\u001b[33m",
    BLUE : u"\u001b[34m",
    MAGENTA : u"\u001b[35m",
    CYAN : u"\u001b[36m",
    LIGHTGRAY : u"\u001b[37m",
    DARKGRAY : u"\u001b[30;1m",
    LIGHTRED : u"\u001b[31;1m",
    LIGHTGREEN : u"\u001b[32;1m",
    LIGHTYELLOW : u"\u001b[33;1m",
    LIGHTBLUE : u"\u001b[34;1m",
    LIGHTMAGENTA : u"\u001b[35;1m",
    LIGHTCYAN : u"\u001b[36;1m",
    WHITE : u"\u001b[37;1m",
    RESET : u"\u001b[0m",
    BOLD : u"\u001b[1m",
    BLINK : u"\u001b[5m",
    UNDERLINE : u"\u001b[4m",
    INVERT : u"\u001b[7m",
}

# Cache for color codes to avoid redundant lookups
_color_cache = {}


def set_bg_color(color):
    """
    Set terminal background color (deprecated - unused).

    Args:
        color: Background color constant (e.g., RED, BLUE)

    Note:
        Does nothing if output is not a TTY
        Function body is incomplete in original implementation
    """
    if not sys.stdout.isatty():
        return

    if color in bg_color_list:
        color_ansi_code = bg_color_list[color]


def set_color(color_mix):
    """
    Set terminal text color and formatting modes.

    Accepts a color constant optionally combined with formatting modes
    using bitwise OR (e.g., RED | BOLD | UNDERLINE).

    Args:
        color_mix: Color constant or combined with modes using |
                   Examples: RED, BLUE | BOLD, GREEN | UNDERLINE | BLINK

    Note:
        Does nothing if output is not a TTY.
        Use RESET to clear all formatting.

    Example:
        set_color(RED | BOLD)
        print("Error message")
        set_color(RESET)
    """
    if not sys.stdout.isatty():
        return

    color = color_mix & COLOR_MASK
    mode = color_mix & MODE_MASK

    color_ansi_code = ""
    # Set text color
    if color in color_list:
        color_ansi_code = color_list[color]

    # Set text mode (can combine multiple modes)
    for cur_mode in range(MIN_MODE, MAX_MODE, MIN_MODE):
        cur_color = mode & cur_mode
        if cur_color in color_list:
            color_ansi_code = color_ansi_code + color_list[cur_color]

    if len(color_ansi_code) > 0:
        run_ansi_code(color_ansi_code)


def get_color(color):
    """
    Get ANSI color code string without applying it.

    Returns the ANSI escape sequence for the specified color.
    Uses caching for performance. Returns empty string if not a TTY.

    Args:
        color: Color constant (RED, GREEN, etc.) or formatting mode

    Returns:
        ANSI escape sequence string, or empty string if not TTY

    Example:
        msg = get_color(RED) + "Error" + get_color(RESET)
        print(msg)
    """
    if not sys.stdout.isatty():
        return ""

    # Check cache first for performance
    if color in _color_cache:
        return _color_cache[color]

    # Generate and cache the color code
    if color in color_list:
        result = color_list[color]
        _color_cache[color] = result
        return result

    return ""


def get_bg_color(color):
    """
    Get ANSI background color code string without applying it.

    Args:
        color: Background color constant

    Returns:
        ANSI background color escape sequence, or empty string if not TTY

    Example:
        bg = get_bg_color(BLUE) + get_color(WHITE) + "Text" + get_color(RESET)
    """
    if not sys.stdout.isatty():
        return ""
    if color in bg_color_list:
        return bg_color_list[color]

    return ""


#------------------------------------------------------------------------
# Cursor related constants and functions
#------------------------------------------------------------------------

# Cursor movement constants
CURSOR_RESET = 0
CURSOR_UP = 1
CURSOR_DOWN = 2
CURSOR_RIGHT = 3
CURSOR_LEFT = 4

# ANSI cursor movement escape codes
cursor_code_list = {
    CURSOR_RESET : u"\u001b[1000D",
    CURSOR_UP : u"\u001b[%dA",
    CURSOR_DOWN : u"\u001b[%dB",
    CURSOR_RIGHT : u"\u001b[%dC",
    CURSOR_LEFT : u"\u001b[%dD",
}


def change_cursor(cursor_type, by=0):
    """
    Move cursor in specified direction by given amount.

    Args:
        cursor_type: Direction constant (CURSOR_UP, CURSOR_DOWN, etc.)
        by: Number of positions to move (default 0)

    Note:
        Does nothing if output is not a TTY
        CURSOR_RESET moves to beginning of line (ignores 'by' parameter)
    """
    if not sys.stdout.isatty():
        return

    if cursor_type in cursor_code_list:
        cursor_code = cursor_code_list[cursor_type]
        if cursor_type != CURSOR_RESET:
            cursor_code = cursor_code % (by)
        sys.stdout.flush()
        run_ansi_code(cursor_code)


def cursor_reset():
    """Move cursor to beginning of current line."""
    change_cursor(CURSOR_RESET)


def cursor_up(by=1):
    """
    Move cursor up by specified number of lines.

    Args:
        by: Number of lines to move up (default 1)
    """
    change_cursor(CURSOR_UP, by)


def cursor_down(by=1):
    """
    Move cursor down by specified number of lines.

    Args:
        by: Number of lines to move down (default 1)
    """
    change_cursor(CURSOR_DOWN, by)


def cursor_left(by=1):
    """
    Move cursor left by specified number of columns.

    Args:
        by: Number of columns to move left (default 1)
    """
    change_cursor(CURSOR_LEFT, by)


def cursor_right(by=1):
    """
    Move cursor right by specified number of columns.

    Args:
        by: Number of columns to move right (default 1)
    """
    change_cursor(CURSOR_RIGHT, by)


# ANSI cursor positioning escape code template
CURSOR_POS = u"\u001b[%d;%dH"


def set_cursor(xpos, ypos):
    """
    Set absolute cursor position on screen.

    Args:
        xpos: Column position (1-based)
        ypos: Row position (1-based)

    Note:
        Screen coordinates are 1-based, not 0-based

    Example:
        set_cursor(10, 5)  # Move to column 10, row 5
    """
    cursor_pos_str = CURSOR_POS % (ypos, xpos)
    run_ansi_code(cursor_pos_str)


#------------------------------------------------------------------------
# Clear related constants and functions
#------------------------------------------------------------------------

# Screen clearing mode constants
CLEAR_SCREEN_AFTER = 0
CLEAR_SCREEN_BEFORE = 1
CLEAR_SCREEN_ALL = 2

# ANSI screen clearing escape codes
clear_screen_list = {
    CLEAR_SCREEN_AFTER : u"\u001b[0J",
    CLEAR_SCREEN_BEFORE: u"\u001b[1J",
    CLEAR_SCREEN_ALL : u"\u001b[2J",
}

# Line clearing mode constants
CLEAR_LINE_AFTER = 0
CLEAR_LINE_BEFORE = 1
CLEAR_LINE_ALL = 2

# ANSI line clearing escape codes
clear_line_list = {
    CLEAR_LINE_AFTER : u"\u001b[0K",
    CLEAR_LINE_BEFORE : u"\u001b[1K",
    CLEAR_LINE_ALL : u"\u001b[2K",
}


def clear_screen_to(mode):
    """
    Clear screen according to specified mode.

    Args:
        mode: Clear mode (CLEAR_SCREEN_AFTER, CLEAR_SCREEN_BEFORE,
              or CLEAR_SCREEN_ALL)

    Note:
        Does nothing if output is not a TTY
    """
    if not sys.stdout.isatty():
        return

    if mode in clear_screen_list:
        clear_code = clear_screen_list[mode]
        run_ansi_code(clear_code)


def clear_screen_before():
    """Clear screen from cursor position to beginning of screen."""
    clear_screen_to(CLEAR_SCREEN_BEFORE)


def clear_screen_after():
    """Clear screen from cursor position to end of screen."""
    clear_screen_to(CLEAR_SCREEN_AFTER)


def clear_screen():
    """Clear entire screen."""
    clear_screen_to(CLEAR_SCREEN_ALL)


def clear_line_to(mode):
    """
    Clear current line according to specified mode.

    Args:
        mode: Clear mode (CLEAR_LINE_AFTER, CLEAR_LINE_BEFORE,
              or CLEAR_LINE_ALL)

    Note:
        Does nothing if output is not a TTY
    """
    if not sys.stdout.isatty():
        return

    if mode in clear_line_list:
        clear_code = clear_line_list[mode]
        run_ansi_code(clear_code)


def clear_line_before():
    """Clear current line from cursor position to beginning of line."""
    clear_line_to(CLEAR_LINE_BEFORE)


def clear_line_after():
    """Clear current line from cursor position to end of line."""
    clear_line_to(CLEAR_LINE_AFTER)


def clear_line():
    """Clear entire current line."""
    clear_line_to(CLEAR_LINE_ALL)
