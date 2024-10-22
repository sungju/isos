# isos
Interactive sos checker

## Usage

- It is convinent to make an alias like below.

```
$ cd ~/
$ git clone https://github.com/sungju/isos.git
$ alias is='~/isos/isos.sh'
```

- Move to the sosreport directory and start the command.

```
$ cd mysosreport/
$ is
```

- If you want to autostart some commands, you can use `~/.isosrc`. Below example executes `xsos` command as soon as `isos` started. `xsos` uses the sosreport directory as a home for further checking

```
$ cat ~/.isosrc
# isos startup script
# You can put commands to start during the application launch
xsos
```

- To get help, you can run `man` or `help`.

```
host0.example.com> help
Help
------------------------------
help       man        cd         eval       
set        xsos       reload     list       
exit       ps         cron       cat        
perf       mods       trace      audit      
powner     log        sar   
```

- Some commands are very simple and gives you a single line help.

```
host0.example.com> help cd
Change directory in the app
host0.example.com>
```

- Some are giving you option details.

```
host0.example.com> help perf
Usage: perf [options] <perf data>

Options:
  -h, --help            show this help message and exit
  -b, --debugsymbol     Use ~/.debug symbols instead of /proc/kallsyms
  -d DEPTH, --depth=DEPTH
                        Shows only specified stack depth <max-stack in perf>
  -l LINES, --lines=LINES
                        Shows only specified lines from the top
  -m, --meta            show cpu utilisation
  -s SORTBY, --sort=SORTBY
                        Show data with different options
  -q, --quiet           Do not show any warnings or messages.
host0.example.com> 
```

- Prompt: it shows hostname for the home directory in isos. Changing directory will shows the path after the hostname. If the directory is outside of the path, it'll show full path.

```
host0.example.com> cd sos_commands/kernel
host0.example.com/sos_commands/kernel> 
host0.example.com/sos_commands/kernel> cd ~/
host0.example.com:/home/sungju> 
```

- If you enter text, isos is checking if it is matching with the file in sosreport. If so, it will show you the content with `cat` command.

```
host0.example.com> free
               total        used        free      shared  buff/cache   available
Mem:       527523056     8424572   512957876       85568     9313436   519098484
Swap:              0           0           0
host0.example.com>
```

- If it doesn't match with a file in sosreport, it tries to execute that as a command from shell.

```
host0.example.com> wc df
  258  1549 34520 df
host0.example.com>
```

- If the command you want to run exists in the current directory, you can use `!` before the command to make sure it is external command.

```
host0.example.com> !free
               total        used        free      shared  buff/cache   available
Mem:        64264044    58005292      806260    30627960    37372204     6258752
Swap:              0           0           0
host0.example.com> 
```

- Other option to run shell commands is using `sh` to get shell prompt.

```
host0.example.com> sh
sh-5.1$ free
               total        used        free      shared  buff/cache   available
Mem:        64264044    57732852      680048    30627968    37436888     6531192
Swap:              0           0           0
sh-5.1$ date
Mon Oct 21 11:33:09 PM UTC 2024
sh-5.1$ exit
exit
host0.example.com> 
```

- sosreport home path is saved in `sos_home` variable in isos. You can see and change that with `set` command.

```
host0.example.com>  set
Setting variables
=================
sos_home        : ~/sosreport-host0-2024-09-17-nvrqmth
host0.example.com> set sos_home .
host0.example.com>
```

- `sos_home` is important as it is the home in isos and files are accessed by relative path from home. `xsos` is using this as home. If you need to check other sosreport, you may want to exit and start it again from that directory or you can set new sosreport directory to sos_home.


- You can use pipe ('|') to pass the result to other commands in the system.

```
host0.example.com> dmidecode | grep CPU
	Socket Designation: CPU1
	Version: Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz
	Socket Designation: CPU2
	Version: Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz
		CPU.Socket.1
		CPU.Socket.2
host0.example.com> 
```

- `cat` is the internal command that reads file(s) with colored output. It has same action as just type the file name, but it can be useful to see multiple files.

```
host0.example.com> cat free
               total        used        free      shared  buff/cache   available
Mem:       527523056     8424572   512957876       85568     9313436   519098484
Swap:              0           0           0
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
host0.example.com/sos_commands/memory>
```

