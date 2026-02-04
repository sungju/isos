import ansicolor
from prompt_toolkit import print_formatted_text, HTML

no_pipe = True
is_cmd_stopped = None
header_start_idx = 0

def init_data(l_no_pipe, l_header_start_idx, l_is_cmd_stopped):
    global header_start_idx
    global is_cmd_stopped
    global no_pipe

    no_pipe = l_no_pipe
    header_start_idx = l_header_start_idx
    is_cmd_stopped = l_is_cmd_stopped

    set_color_table()


# Color variables - initialized by set_color_table()
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

column_color = { }

def set_color_table():
    global COLOR_1, COLOR_2, COLOR_3, COLOR_4, COLOR_5, COLOR_6
    global COLOR_7, COLOR_8, COLOR_9, COLOR_10, COLOR_11, COLOR_12
    global COLOR_13, COLOR_14, COLOR_RESET
    global column_color
    global no_pipe

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
                1 : COLOR_1,
                2 : COLOR_2,
                3 : COLOR_3,
                4 : COLOR_4,
                5 : COLOR_5,
                6 : COLOR_6,
                7 : COLOR_7,
                8 : COLOR_8,
                9 : COLOR_9,
                10 : COLOR_10,
                11 : COLOR_11,
                12 : COLOR_12,
                13 : COLOR_13,
                14 : COLOR_14,
        }
    else:
        COLOR_1 = COLOR_2 = COLOR_3 = COLOR_4 = ""
        COLOR_5 = COLOR_6 = COLOR_7 = COLOR_8 = ""
        COLOR_9 = COLOR_10 = COLOR_11 = COLOR_12 = ""
        COLOR_13 = COLOR_14 = COLOR_RESET = ""

        column_color = {}


def get_colored_line(line):
    global header_start_idx, is_cmd_stopped, no_pipe, column_color, COLOR_RESET

    if not column_color or not line.strip():
        return line

    words = line.split()
    if not words:
        return line

    # Build result using list accumulation (O(n) instead of O(n²))
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
            result_parts.append(word)
            start_idx_count -= 1
        elif count in column_color:
            result_parts.append(column_color[count])
            result_parts.append(word)
            result_parts.append(COLOR_RESET)
            count += 1
        else:
            result_parts.append(word)
            count += 1

        pos = word_start + len(word)

    # Append trailing content
    if pos < len(line):
        result_parts.append(line[pos:])

    return ''.join(result_parts)


def get_pipe_aware_line(line):
    global header_start_idx
    global is_cmd_stopped
    global no_pipe

    if line is None:
        return ""

    line = get_colored_line(line)
    if no_pipe:
        print(line)
        line = ""
    else:
        line = line + "\n"

    return line


def get_pipe_color_line(line, color="normal", end="\n"):
    if line is None:
        return ""

    if no_pipe:
        print_formatted_text(HTML("<%s>%s</%s>" % (color, line, color)), end=end)
        line = ""
    else:
        line = line + end

    return line
