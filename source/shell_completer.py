"""
Shell File and Executable Completion Module

Provides file system path completion for the isos interactive shell.
Integrates with prompt_toolkit's completion system to offer:
- File and directory name completion
- Executable command completion from PATH
- Prefix-based filtering
- Customizable file filtering

This module is adapted from prompt_toolkit's PathCompleter with
modifications for shell-like completion behavior suitable for the
isos command-line interface.

Example:
    # Create completer for files and directories
    file_completer = ShellCompleter(
        only_directories=False,
        get_paths=lambda: ["."],
        expanduser=True
    )

    # Create completer for executables only
    exec_completer = ExecutableCompleter()
"""

from __future__ import annotations

import os
from typing import Callable, Iterable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

__all__ = [
    "ShellCompleter",
    "ExecutableCompleter",
]


class ShellCompleter(Completer):
    """
    File system path completer for shell-like interfaces.

    Provides completion for file and directory names with configurable
    filtering and path resolution. Supports tilde expansion and relative
    path completion.

    Args:
        only_directories: If True, only complete directory names (default False)
        get_paths: Callable returning list of base directories for relative paths.
                   Default returns ["."] for current directory.
        file_filter: Optional callable(filename) -> bool to filter results.
                     Return True to include file, False to exclude.
        min_input_len: Minimum input length before triggering completion.
                       Prevents excessive results on empty input (default 0).
        expanduser: If True, expand ~ to user's home directory (default False)

    Example:
        # Complete only Python files
        completer = ShellCompleter(
            file_filter=lambda f: f.endswith('.py'),
            min_input_len=2
        )

        # Complete only directories
        dir_completer = ShellCompleter(only_directories=True)
    """

    def __init__(
        self,
        only_directories: bool = False,
        get_paths: Callable[[], list[str]] | None = None,
        file_filter: Callable[[str], bool] | None = None,
        min_input_len: int = 0,
        expanduser: bool = False,
    ) -> None:
        self.only_directories = only_directories
        self.get_paths = get_paths or (lambda: ["."])
        self.file_filter = file_filter or (lambda _: True)
        self.min_input_len = min_input_len
        self.expanduser = expanduser

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        """
        Generate completions for the current document state.

        Args:
            document: Current document state from prompt_toolkit
            complete_event: Completion event triggering this call

        Yields:
            Completion objects for matching files/directories

        Note:
            Silently handles OSError (permission denied, directory not found)
        """
        # Get word before cursor (using WORD mode for shell-like behavior)
        text = document.get_word_before_cursor(WORD=True)

        # Skip completion if input too short (prevents overwhelming output)
        if len(text) < self.min_input_len:
            return

        try:
            # Expand tilde if requested
            if self.expanduser:
                text = os.path.expanduser(text)

            # Determine search directories
            dirname = os.path.dirname(text)
            if dirname:
                # User typed path with directory component
                directories = [
                    os.path.dirname(os.path.join(p, text)) for p in self.get_paths()
                ]
            else:
                # No directory component, search base paths
                directories = self.get_paths()

            # Extract filename prefix for matching
            prefix = os.path.basename(text)

            # Collect matching filenames from all directories
            filenames = []
            for directory in directories:
                # Skip non-existent directories
                if os.path.isdir(directory):
                    for filename in os.listdir(directory):
                        # Match files starting with prefix
                        if filename.startswith(prefix):
                            filenames.append((directory, filename))

            # Sort by filename for consistent ordering
            filenames = sorted(filenames, key=lambda k: k[1])

            # Yield completion objects
            for directory, filename in filenames:
                # Calculate completion text (suffix to add)
                completion = filename[len(prefix) :]
                full_name = os.path.join(directory, filename)

                if os.path.isdir(full_name):
                    # Add trailing slash for directories
                    filename += "/"
                    completion += "/"
                elif self.only_directories:
                    # Skip files if only_directories=True
                    continue

                # Apply custom filter
                if not self.file_filter(full_name):
                    continue

                yield Completion(
                    text=completion,
                    start_position=0,
                    display=filename,
                )
        except OSError:
            # Silently handle permission errors, missing directories, etc.
            pass


class ExecutableCompleter(ShellCompleter):
    """
    Complete only executable files from system PATH.

    Specialized completer for shell commands. Searches all directories
    in the PATH environment variable for executable files.

    Note:
        Requires minimum input length of 1 to avoid listing all executables.
        Automatically expands ~ in paths.

    Example:
        exec_completer = ExecutableCompleter()
        # Will complete 'py' to 'python', 'python3', 'pytest', etc.
    """

    def __init__(self) -> None:
        """
        Initialize executable completer.

        Configuration:
            - Searches PATH directories
            - Filters for executable permission
            - Expands ~ in paths
            - Requires at least 1 character input
        """
        super().__init__(
            only_directories=False,
            min_input_len=1,
            get_paths=lambda: os.environ.get("PATH", "").split(os.pathsep),
            file_filter=lambda name: os.access(name, os.X_OK),
            expanduser=True,
        )
