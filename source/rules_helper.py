
def get_file_content(path):
    try:
        with open(sos_home + path) as f:
            lines = "".join(f.readlines())
            return lines
    except:
        return "Error reading %s" % path


def get_data(basic_data, command):
    if basic_data == None:
        return ""
    env_vars = basic_data['env_vars']
    sos_home = env_vars['sos_home']


    if command == "log":
        return get_file_content(sos_home + "/var/log/messages")
    else:
        return ""



def get_symbol(symbol):
    return ""


def is_symbol_exists(symbol):
    return False


def get_size_str(size):
    size_str = ""
    if size > (1024 * 1024 * 1024): # GiB
        size_str = "%.1f GiB" % (size / (1024*1024*1024))
    elif size > (1024 * 1024): # MiB
        size_str = "%.1f MiB" % (size / (1024*1024))
    elif size > (1024): # KiB
        size_str = "%.1f KiB" % (size / (1024))
    else:
        size_str = "%.0f B" % (size)

    return size_str

