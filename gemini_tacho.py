"""Gemini-Tacho: shows how full the context of the active Antigravity chat is.

After every step Antigravity writes the token counts to
~/.gemini/antigravity/brain/<chat>/.system_generated/logs/transcript.jsonl
(input_tokens, cache_read_tokens, output_tokens). Active chat = most recently
modified file. Only the end of the file and only the number fields are read,
never the chat content.

Start: pythonw gemini_tacho.py   (small window, always on top)
"""
import glob
import json
import os
import time
import tkinter as tk

BRAIN = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "brain")
PATTERN = os.path.join(BRAIN, "*", ".system_generated", "logs", "transcript.jsonl")
# Antigravity compacts automatically around ~256 Ki (262,144); measured Oct 2026
# (9 cases) the last value before compaction was between 243,696 and 265,166 - probably
# the next request including the new input counts. Red therefore starts before the earliest case.
WINDOW = 262_144
YELLOW_FROM = 0.70   # from ~183k yellow: save what matters
RED_FROM = 0.85      # from ~223k red: compaction can happen any moment
TICK_MS = 5000
TAIL_BYTES = 256 * 1024
# If the count drops below 60 % within the same chat, a compaction happened (manual
# or automatic in the background) -> one line in the log, to learn the threshold.
DROP_FACTOR = 0.6
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compactions.txt")


def active_chat():
    files = glob.glob(PATTERN)
    return max(files, key=os.path.getmtime) if files else None


def last_count(path):
    """(tokens, mtime) from the last entry with count fields, otherwise None."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        if '"input_tokens"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue  # first line, cut in half
        if isinstance(o, dict) and "input_tokens" in o:
            total = sum(int(o.get(k) or 0) for k in
                        ("input_tokens", "cache_read_tokens", "output_tokens"))
            return total, os.path.getmtime(path)
    return None


def main():
    root = tk.Tk()
    root.title("Gemini-Tacho")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    number = tk.Label(root, font=("Segoe UI", 20, "bold"), width=12)
    number.pack(padx=12, pady=(10, 0))
    info = tk.Label(root, font=("Segoe UI", 9), fg="#666")
    info.pack(padx=12, pady=(0, 10))

    previous = {}  # chat path -> last count

    def remember_drop(path, tokens):
        before = previous.get(path)
        previous[path] = tokens
        if before and tokens < before * DROP_FACTOR:
            chat = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))[:8]
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  chat {chat}  "
                        f"{before:,} -> {tokens:,}\n")

    def tick():
        try:
            path = active_chat()
            count = last_count(path) if path else None
            if count is not None:
                remember_drop(path, count[0])
            if count is None:
                number.config(text="–", fg="#666")
                info.config(text="no Antigravity chat found")
            else:
                tokens, mtime = count
                share = tokens / WINDOW
                color = "#c0392b" if share >= RED_FROM else "#d68910" if share >= YELLOW_FROM else "#1e8449"
                number.config(text=f"{tokens:,}", fg=color)
                age = int(time.time() - mtime)
                age_txt = f"{age} s ago" if age < 120 else f"{age // 60} min ago"
                info.config(text=f"{share:.0%} of compaction limit · chat {os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))[:8]} · {age_txt}")
        except Exception as exc:  # the tacho must never crash
            number.config(text="?", fg="#666")
            info.config(text=type(exc).__name__)
        root.after(TICK_MS, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
