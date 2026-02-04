#!/usr/bin/env python3
"""
Benchmark script to demonstrate the performance improvement
of the optimized get_colored_line() function.
"""

import sys
import time

# Add source directory to path
sys.path.insert(0, 'source')

import ansicolor
import screen

# Mock function for is_cmd_stopped
def mock_is_cmd_stopped():
    return False

# Old O(n²) implementation for comparison
def get_colored_line_old(line, column_color, COLOR_RESET):
    words = line.split()
    count = 1
    result_str = ""
    for word in words:
        colored_word = word
        if count in column_color:
            colored_word = column_color[count] + word + COLOR_RESET
        line = line.replace(word, colored_word, 1)
        mod_idx = line.find(colored_word) + len(colored_word)
        result_str = result_str + line[:mod_idx]
        line = line[mod_idx:]
        count = count + 1
    return result_str

# Test data - more realistic with longer lines and more columns
test_lines = [
    "PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND EXTRA1 EXTRA2 EXTRA3",
    "1 root 20 0 169588 13784 8804 S 0.0 0.1 0:05.12 systemd /usr/lib/systemd/systemd --system --deserialize",
    "2 root 20 0 0 0 0 S 0.0 0.0 0:00.01 kthreadd process_manager kernel_thread some_other_data",
    "12345 apache 20 0 1234567 234567 45678 R 95.3 12.5 123:45.67 httpd /usr/sbin/httpd -DFOREGROUND extended_arguments",
    "6789 mysql 20 0 9876543 876543 98765 S 45.2 25.3 456:78.90 mysqld /usr/sbin/mysqld --basedir=/usr very_long_command_line_argument",
    "4321 nginx 20 0 567890 67890 12345 S 12.3 4.5 12:34.56 nginx nginx: worker process extended data here and more text",
] * 50  # 300 lines total

# Setup colors
COLOR_1  = ansicolor.get_color(ansicolor.RED)
COLOR_2  = ansicolor.get_color(ansicolor.GREEN)
COLOR_3  = ansicolor.get_color(ansicolor.YELLOW)
COLOR_4  = ansicolor.get_color(ansicolor.BLUE)
COLOR_5  = ansicolor.get_color(ansicolor.MAGENTA)
COLOR_RESET = ansicolor.get_color(ansicolor.RESET)

column_color = {
    1: COLOR_1,
    2: COLOR_2,
    3: COLOR_3,
    4: COLOR_4,
    5: COLOR_5,
    6: COLOR_1,
    7: COLOR_2,
    8: COLOR_3,
    9: COLOR_4,
    10: COLOR_5,
}

# Initialize screen module
screen.init_data(True, 1, mock_is_cmd_stopped)
screen.column_color = column_color

print("=" * 60)
print("ANSI Color Output Performance Benchmark")
print("=" * 60)
print()
print(f"Test dataset: {len(test_lines)} lines")
avg_line_length = sum(len(line) for line in test_lines) / len(test_lines)
print(f"Average line length: {avg_line_length:.0f} characters")
print(f"Iterations: 100")
print()

# Benchmark old implementation
print("Benchmarking OLD O(n²) implementation...")
start_time = time.time()
for _ in range(100):
    for line in test_lines:
        result = get_colored_line_old(line, column_color, COLOR_RESET)
old_time = time.time() - start_time
print(f"  Time: {old_time:.4f} seconds")
print()

# Benchmark new implementation
print("Benchmarking NEW O(n) implementation...")
start_time = time.time()
for _ in range(100):
    for line in test_lines:
        result = screen.get_colored_line(line)
new_time = time.time() - start_time
print(f"  Time: {new_time:.4f} seconds")
print()

# Results
print("=" * 60)
print("RESULTS")
print("=" * 60)
print(f"Old implementation: {old_time:.4f}s")
print(f"New implementation: {new_time:.4f}s")
if new_time > 0:
    speedup = old_time / new_time
    print(f"Speedup: {speedup:.1f}x faster")
    improvement = ((old_time - new_time) / old_time) * 100
    print(f"Performance improvement: {improvement:.1f}%")
print()

# Verify correctness
print("Verifying output correctness...")
old_result = get_colored_line_old(test_lines[3], column_color, COLOR_RESET)
new_result = screen.get_colored_line(test_lines[3])
if old_result == new_result:
    print("✓ Output matches - optimization is correct!")
else:
    print("✗ Output differs - there may be an issue")
    print(f"Old: {repr(old_result[:100])}")
    print(f"New: {repr(new_result[:100])}")
