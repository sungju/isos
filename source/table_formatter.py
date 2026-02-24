"""
Table Formatter Module with Rich Integration

This module provides a unified table formatting system that fixes the
fundamental design issue in screen.py's column_color approach.

The old pattern (screen.py get_colored_line) splits text by whitespace
and colors "words" by position, which breaks when fixed-width format
strings create extra spaces. This causes colors to land on wrong columns.

Example of the old problem:
    header = "%-12s %-6s" % ("DEVICE", "STATE")
    # Result: "DEVICE       STATE "
    # get_colored_line splits: ["DEVICE", "STATE"]
    # But padding spaces are lost in the split!

TableFormatter solves this by handling formatting and coloring together
rather than splitting them into separate operations.

Usage:
    from table_formatter import TableFormatter

    table = TableFormatter(no_pipe=no_pipe)
    table.add_column("DEVICE", width=12, align='left', color='cyan')
    table.add_column("STATE", width=6, align='left', color='green')
    table.add_row("eth0", "up")
    table.add_row("eth1", "down")
    output = table.format()
"""

# --------------------------------------------------------------------
# Author: Daniel Sungju Kwon
#
# This provides table formatting with integrated coloring using Rich library
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
import ansicolor

# Try to import Rich library
try:
    from rich.console import Console
    from rich.table import Table as RichTable
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Map our color names to Rich style names
RICH_COLOR_MAP = {
    'black': 'black',
    'red': 'red',
    'green': 'green',
    'yellow': 'yellow',
    'blue': 'blue',
    'magenta': 'magenta',
    'cyan': 'cyan',
    'lightgray': 'white',
    'darkgray': 'bright_black',
    'lightred': 'bright_red',
    'lightgreen': 'bright_green',
    'lightyellow': 'bright_yellow',
    'lightblue': 'bright_blue',
    'lightmagenta': 'bright_magenta',
    'lightcyan': 'bright_cyan',
    'white': 'bright_white',
}

# Map our color names to ansicolor constants
ANSI_COLOR_MAP = {
    'black': ansicolor.BLACK,
    'red': ansicolor.RED,
    'green': ansicolor.GREEN,
    'yellow': ansicolor.YELLOW,
    'blue': ansicolor.BLUE,
    'magenta': ansicolor.MAGENTA,
    'cyan': ansicolor.CYAN,
    'lightgray': ansicolor.LIGHTGRAY,
    'darkgray': ansicolor.DARKGRAY,
    'lightred': ansicolor.LIGHTRED,
    'lightgreen': ansicolor.LIGHTGREEN,
    'lightyellow': ansicolor.LIGHTYELLOW,
    'lightblue': ansicolor.LIGHTBLUE,
    'lightmagenta': ansicolor.LIGHTMAGENTA,
    'lightcyan': ansicolor.LIGHTCYAN,
    'white': ansicolor.WHITE,
}


class ColumnDefinition(object):
    """
    Defines a single table column.

    Attributes:
        name: Column header text
        width: Column width (None for auto-sizing)
        align: Alignment ('left', 'right', 'center')
        color: Color name for this column's data
        header_color: Color name for this column's header (defaults to color)
    """

    def __init__(self, name, width=None, align='left', color=None, header_color=None):
        """
        Create a column definition.

        Args:
            name: Column header text
            width: Fixed width in characters (None for auto-sizing)
            align: 'left', 'right', or 'center'
            color: Color name string (e.g., 'cyan', 'red')
            header_color: Color for header (defaults to same as color)
        """
        self.name = name
        self.width = width
        self.align = align
        self.color = color
        self.header_color = header_color if header_color else color


class TableFormatter(object):
    """
    Table formatter with Rich integration and fallback mode.

    Handles table formatting and coloring together, fixing the fundamental
    issue in screen.py's column_color approach.

    Features:
    - Uses Rich library for advanced formatting when available
    - Falls back to basic formatting if Rich unavailable
    - Respects no_pipe flag to strip colors when piped
    - Supports flexible column definitions
    - Handles alignment, padding, and coloring together

    Usage:
        table = TableFormatter(no_pipe=True)
        table.add_column("NAME", width=20, align='left', color='cyan')
        table.add_column("VALUE", width=10, align='right', color='green')
        table.add_row("Item 1", "100")
        table.add_row("Item 2", "200")
        print(table.format())
    """

    def __init__(self, no_pipe=True, use_rich=True, show_header=True,
                 show_lines=False, padding=1):
        """
        Initialize table formatter.

        Args:
            no_pipe: True if outputting to terminal (colors enabled)
            use_rich: True to use Rich library, False for basic fallback
            show_header: Whether to show column headers
            show_lines: Whether to show row separator lines (Rich only)
            padding: Number of spaces for padding between columns (fallback mode)
        """
        self.no_pipe = no_pipe
        self.use_rich = use_rich and RICH_AVAILABLE
        self.show_header = show_header
        self.show_lines = show_lines
        self.padding = padding

        self.columns = []
        self.rows = []

        # For Rich mode
        self._rich_table = None
        self._rich_console = None

    def add_column(self, name, width=None, align='left', color=None, header_color=None):
        """
        Add a column definition to the table.

        Args:
            name: Column header text
            width: Fixed width in characters (None for auto-sizing)
            align: 'left', 'right', or 'center'
            color: Color name string (e.g., 'cyan', 'lightgreen')
            header_color: Color for header (defaults to same as color)

        Returns:
            Self for method chaining
        """
        col = ColumnDefinition(name, width, align, color, header_color)
        self.columns.append(col)
        return self

    def add_row(self, *values, **kwargs):
        """
        Add a data row to the table.

        Args:
            *values: Column values in order
            **kwargs: Optional parameters:
                - row_color: Color to override all column colors in this row
                - cell_colors: Dict mapping column index to color name
                               Example: {1: 'red', 3: 'green'}

        Returns:
            Self for method chaining

        Example:
            # Regular row with default column colors
            table.add_row("value1", "value2", "value3")

            # Row with custom color for entire row
            table.add_row("value1", "value2", "value3", row_color='red')

            # Row with custom colors for specific cells
            table.add_row("eth0", "DOWN", "1.2.3.4", cell_colors={1: 'red'})
        """
        row_color = kwargs.get('row_color', None)
        cell_colors = kwargs.get('cell_colors', None)
        self.rows.append({
            'values': list(values),
            'row_color': row_color,
            'cell_colors': cell_colors
        })
        return self

    def format(self):
        """
        Format the table and return as string.

        Returns:
            Formatted table as string
        """
        if not self.columns:
            return ""

        if self.use_rich and self.no_pipe:
            return self._format_with_rich()
        else:
            return self._format_basic()

    def _format_with_rich(self):
        """
        Format table using Rich library.

        Returns:
            Formatted table as string
        """
        # Create Rich console for string rendering
        from io import StringIO
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=200)

        # Create Rich table
        table = RichTable(
            show_header=self.show_header,
            header_style="bold",
            box=box.SIMPLE if self.show_lines else None,
            padding=(0, 1),
            collapse_padding=False
        )

        # Add columns
        for col in self.columns:
            # Map align to Rich justify
            justify_map = {
                'left': 'left',
                'right': 'right',
                'center': 'center'
            }
            justify = justify_map.get(col.align, 'left')

            # Get Rich style for column
            style = None
            if col.color:
                rich_color = RICH_COLOR_MAP.get(col.color.lower(), col.color)
                style = rich_color

            # Get Rich style for header
            header_style = "bold"
            if col.header_color:
                rich_color = RICH_COLOR_MAP.get(col.header_color.lower(), col.header_color)
                header_style = "bold " + rich_color
            elif col.color:
                rich_color = RICH_COLOR_MAP.get(col.color.lower(), col.color)
                header_style = "bold " + rich_color

            # Add column to Rich table
            table.add_column(
                col.name,
                justify=justify,
                style=style,
                header_style=header_style,
                width=col.width,
                no_wrap=True if col.width else False
            )

        # Add rows
        for row_data in self.rows:
            values = row_data['values']
            row_color = row_data.get('row_color')
            cell_colors = row_data.get('cell_colors', {})

            # Pad values to match column count
            while len(values) < len(self.columns):
                values.append("")

            # Convert all values to strings and apply colors
            str_values = []
            for i, v in enumerate(values[:len(self.columns)]):
                str_val = str(v)

                # Determine color: cell_colors > row_color > no color
                color_name = None
                if cell_colors and i in cell_colors:
                    color_name = cell_colors[i]
                elif row_color:
                    color_name = row_color

                # Apply Rich color markup if color specified
                if color_name:
                    rich_color = RICH_COLOR_MAP.get(color_name.lower(), color_name)
                    str_val = "[%s]%s[/%s]" % (rich_color, str_val, rich_color)

                str_values.append(str_val)

            table.add_row(*str_values)

        # Render to string
        console.print(table)
        result = string_io.getvalue()

        return result.rstrip()

    def _format_basic(self):
        """
        Format table using basic string formatting (fallback mode).

        Returns:
            Formatted table as string
        """
        if not self.rows and not self.show_header:
            return ""

        lines = []

        # Calculate column widths if not specified
        col_widths = []
        for i, col in enumerate(self.columns):
            if col.width:
                col_widths.append(col.width)
            else:
                # Auto-calculate width
                max_width = len(col.name) if self.show_header else 0
                for row_data in self.rows:
                    values = row_data['values']
                    if i < len(values):
                        max_width = max(max_width, len(str(values[i])))
                col_widths.append(max_width)

        # Format header
        if self.show_header:
            header_parts = []
            for i, col in enumerate(self.columns):
                width = col_widths[i]
                name = col.name

                # Apply alignment
                if col.align == 'right':
                    text = name.rjust(width)
                elif col.align == 'center':
                    text = name.center(width)
                else:
                    text = name.ljust(width)

                # Apply color if outputting to terminal
                if self.no_pipe and col.header_color:
                    color_code = self._get_ansi_color(col.header_color)
                    reset_code = ansicolor.get_color(ansicolor.RESET)
                    text = color_code + text + reset_code
                elif self.no_pipe and col.color:
                    color_code = self._get_ansi_color(col.color)
                    reset_code = ansicolor.get_color(ansicolor.RESET)
                    text = color_code + text + reset_code

                header_parts.append(text)

            header_line = (" " * self.padding).join(header_parts)
            lines.append(header_line)

        # Format rows
        for row_data in self.rows:
            values = row_data['values']
            row_color = row_data.get('row_color')
            cell_colors = row_data.get('cell_colors', {})

            row_parts = []
            for i, col in enumerate(self.columns):
                width = col_widths[i]

                # Get value
                if i < len(values):
                    value = str(values[i])
                else:
                    value = ""

                # Apply alignment
                if col.align == 'right':
                    text = value.rjust(width)
                elif col.align == 'center':
                    text = value.center(width)
                else:
                    text = value.ljust(width)

                # Apply color if outputting to terminal
                # Priority: cell_colors > row_color > column color
                if self.no_pipe:
                    color_name = None
                    if cell_colors and i in cell_colors:
                        # Per-cell color (highest priority)
                        color_name = cell_colors[i]
                    elif row_color:
                        # Whole row color (middle priority)
                        color_name = row_color
                    else:
                        # Column default color (lowest priority)
                        color_name = col.color

                    if color_name:
                        color_code = self._get_ansi_color(color_name)
                        reset_code = ansicolor.get_color(ansicolor.RESET)
                        text = color_code + text + reset_code

                row_parts.append(text)

            row_line = (" " * self.padding).join(row_parts)
            lines.append(row_line)

        return "\n".join(lines)

    def _get_ansi_color(self, color_name):
        """
        Get ANSI color code from color name.

        Args:
            color_name: Color name string

        Returns:
            ANSI color code string
        """
        color_const = ANSI_COLOR_MAP.get(color_name.lower())
        if color_const:
            return ansicolor.get_color(color_const)
        return ""


def create_table(no_pipe=True, show_header=True):
    """
    Factory function to create a TableFormatter instance.

    Args:
        no_pipe: True if outputting to terminal (colors enabled)
        show_header: Whether to show column headers

    Returns:
        TableFormatter instance

    Example:
        table = create_table(no_pipe=no_pipe)
        table.add_column("PID", width=8, align='right', color='cyan')
        table.add_column("USER", width=12, color='green')
        table.add_row("1234", "root")
        print(table.format())
    """
    return TableFormatter(no_pipe=no_pipe, show_header=show_header)
