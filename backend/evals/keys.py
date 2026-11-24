"""One keypress at a time for the labelling CLIs (falls back to a line of input)."""

import sys


def read_key(prompt: str) -> str:
    print(prompt, end=" ", flush=True)
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            key = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print(key)
        return key
    except (ImportError, OSError, ValueError):  # Windows, or not a terminal
        return (input() or " ")[0]
