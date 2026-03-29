"""
soscompare command for isos — compares two sosreports side-by-side.

Usage:
    soscompare <path-to-second-sosreport>
    soscompare -t <topic>
    soscompare -l
    soscompare --no-fzf <path-to-second-sosreport>
"""

import os
import shutil
import subprocess
import tempfile
from optparse import OptionParser
from os.path import basename, exists

from cmds.compare_topics import TOPICS, get_topic


sos_home = ""
is_cmd_stopped = None

cmd_name = "soscompare"


def description():
    return "Compares two sosreports side-by-side with fzf interactive UI"


def add_command():
    return True


def get_command_info():
    return {cmd_name: run_compare}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_and_write(topics, sos1_path, sos2_path, output_dir):
    """Phase 1: collect data for all topics and write pre-computed result files."""
    for topic in topics:
        try:
            data1 = topic.collector(sos1_path)
            data2 = topic.collector(sos2_path)
            diff_lines = topic.formatter(data1, data2)
        except Exception as exc:
            diff_lines = ["[ERROR] Failed to collect %s: %s" % (topic.key, exc)]

        out_path = os.path.join(output_dir, topic.key + ".txt")
        with open(out_path, 'w') as f:
            f.write('\n'.join(diff_lines) + '\n')


def _write_topics_file(topics, output_dir):
    """Write the topic list to a file for fzf input."""
    topics_file = os.path.join(output_dir, "_topics.txt")
    with open(topics_file, 'w') as f:
        for t in topics:
            f.write("%-12s  %s\n" % (t.key, t.display_name))
    return topics_file


def _run_fzf(topics, sos1_path, sos2_path, output_dir):
    """Phase 2: launch fzf with pre-computed topic result files."""
    sos1_label = basename(sos1_path.rstrip('/'))
    sos2_label = basename(sos2_path.rstrip('/'))

    topics_file = _write_topics_file(topics, output_dir)

    print("Launching interactive comparison...")

    # {1} in fzf refers to the first field (the topic key) of the selected line.
    # {{1}} in Python format string escapes to literal {1} after .format().
    # Use $'...' for multi-line header with newlines
    fzf_cmd = (
        "cat {topics_file} | fzf "
        "--ansi "
        "--preview 'cat {output_dir}/{{1}}.txt 2>/dev/null || echo \"(no data)\"' "
        "--preview-window 'right:70%:wrap' "
        "--layout reverse "
        "--header $'SOS1: {sos1_label}\\nSOS2: {sos2_label}\\n\\nKeys: ↑/↓=navigate  Esc=exit' "
        "--prompt 'Topic> ' "
        "--bind 'enter:ignore' "
        "--height 100%"
    ).format(
        topics_file=topics_file,
        output_dir=output_dir,
        sos1_label=sos1_label,
        sos2_label=sos2_label,
    )

    subprocess.call(fzf_cmd, shell=True)
    return ""  # Return empty string instead of None


def _print_topic(topic, sos1_path, sos2_path):
    """Collect and print a single topic's diff to stdout."""
    try:
        data1 = topic.collector(sos1_path)
        data2 = topic.collector(sos2_path)
        diff_lines = topic.formatter(data1, data2)
    except Exception as exc:
        diff_lines = ["[ERROR] %s" % exc]
    print('\n'.join(diff_lines))


def _print_all_plain(topics, sos1_path, sos2_path):
    """Print all topics sequentially (--no-fzf / fzf-unavailable fallback)."""
    sos1_label = basename(sos1_path.rstrip('/'))
    sos2_label = basename(sos2_path.rstrip('/'))
    print("SOS1: %s  |  SOS2: %s\n" % (sos1_label, sos2_label))
    for topic in topics:
        _print_topic(topic, sos1_path, sos2_path)
        print()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_compare(input_str, env_vars, is_cmd_stopped_func,
                show_help=False, no_pipe=True):
    global is_cmd_stopped, sos_home

    is_cmd_stopped = is_cmd_stopped_func
    sos_home = env_vars['sos_home']

    usage = "Usage: %s [options] <path-to-second-sosreport>" % cmd_name
    op = OptionParser(usage=usage, add_help_option=False)
    op.add_option('-h', '--help', dest='help', action='store_true',
                  help='Show this help message')
    op.add_option('-t', '--topic', dest='topic', default=None,
                  metavar='TOPIC',
                  help='Show specific topic(s) (comma-separated, skip fzf, print to stdout)')
    op.add_option('-l', '--list', dest='list_topics', action='store_true',
                  help='List available comparison topics')
    op.add_option('--no-fzf', dest='no_fzf', action='store_true',
                  help='Plain text output, no interactive UI')
    op.add_option('--no-color', dest='no_color', action='store_true',
                  help='Disable color output')

    args = input_str.split() if input_str else []
    # Skip first word (command name) - isos.py passes full input including command
    if args and args[0] == cmd_name:
        args = args[1:]
    opts, remaining = op.parse_args(args)

    if show_help or opts.help:
        op.print_help()
        print("\nAvailable topics:")
        for t in TOPICS:
            print("  %-12s  %s" % (t.key, t.display_name))
        return ""

    if opts.list_topics:
        for t in TOPICS:
            print("  %-12s  %s" % (t.key, t.display_name))
        return ""

    if not remaining:
        print("Error: second sosreport path required.")
        op.print_help()
        return ""

    sos2_path = remaining[0]
    sos1_path = sos_home

    # Resolve relative paths from WORK_DIR (original launch directory)
    # This handles symlink cases where sos_home is the resolved path
    if not os.path.isabs(sos2_path):
        work_dir = env_vars.get('WORK_DIR', os.getcwd())
        sos2_path = os.path.abspath(os.path.join(work_dir, sos2_path))

    if not exists(sos2_path):
        print("Error: path not found: %s" % sos2_path)
        return ""

    # Topic mode (-t) - supports comma-separated topics
    if opts.topic:
        topic_keys = [t.strip() for t in opts.topic.split(',')]
        for topic_key in topic_keys:
            topic = get_topic(topic_key)
            if topic is None:
                print("Error: unknown topic '%s'. Use -l to list topics." % topic_key)
                return ""
            _print_topic(topic, sos1_path, sos2_path)
            if len(topic_keys) > 1:
                print()  # Blank line between topics
        return ""

    # Plain text fallback (--no-fzf or fzf not installed)
    if opts.no_fzf or not shutil.which('fzf'):
        if not opts.no_fzf:
            print("Note: fzf not found, falling back to plain text output.")
        _print_all_plain(TOPICS, sos1_path, sos2_path)
        return ""

    # Interactive fzf mode
    output_dir = tempfile.mkdtemp(prefix='isos_compare_')
    try:
        print("Collecting comparison data...")
        _collect_and_write(TOPICS, sos1_path, sos2_path, output_dir)
        _run_fzf(TOPICS, sos1_path, sos2_path, output_dir)
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)

    return ""
