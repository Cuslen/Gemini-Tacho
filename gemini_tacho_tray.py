"""Gemini-Tacho as an icon next to the clock (Windows taskbar tray).

The ring fills up with the context usage of the active Antigravity chat,
same colors as the window tacho. Hover = number, click = details window.
Data and thresholds come from gemini_tacho.py (reads count fields only).

Start: pythonw gemini_tacho_tray.py
"""
import ctypes
import json
import os
import queue
import time
import tkinter as tk

import pystray
from PIL import Image, ImageDraw

try:  # pystray's Windows internals, only used to restore a lost tray icon
    from pystray._util import win32 as pw
except Exception:
    pw = None

import gemini_tacho as gt

GREY = (90, 90, 90, 255)
COLORS = {"green": (30, 132, 73, 255), "yellow": (214, 137, 16, 255),
          "red": (192, 57, 43, 255)}
STEPS_SHOWN = 8


def level(share):
    return "red" if share >= gt.RED_FROM else "yellow" if share >= gt.YELLOW_FROM else "green"


def ring(share, color):
    """64x64 ring: grey base, colored arc clockwise from 12 o'clock."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = (4, 4, 60, 60)
    d.ellipse(box, outline=GREY, width=10)
    if share > 0:
        d.arc(box, start=-90, end=-90 + max(8, 360 * min(share, 1.0)),
              fill=color, width=10)
    return img


def last_steps(path, n):
    """The last n entries with count fields (numbers only)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - gt.TAIL_BYTES))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
    out = []
    for line in reversed(lines):
        if '"input_tokens"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict) and "input_tokens" in o:
            out.append({k: int(o.get(k) or 0) for k in
                        ("step_index", "input_tokens", "cache_read_tokens", "output_tokens")})
            if len(out) >= n:
                break
    return list(reversed(out))


def fmt(z):
    return f"{z:,}"


def age_text(sec):
    if sec < 120:
        return f"{sec} s ago"
    if sec < 7200:
        return f"{sec // 60} min ago"
    return f"{sec // 3600} h ago"


def chat_id(path):
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))[:8]


class Tacho:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.jobs = queue.Queue()
        self.previous = {}
        self.warned = set()  # chats that already got the red alert
        self.alert = None
        self.detail = None
        self.icon = pystray.Icon(
            "gemini_tacho", ring(0, GREY), "Gemini-Tacho",
            menu=pystray.Menu(
                pystray.MenuItem("Details", lambda: self.jobs.put("details"), default=True),
                pystray.MenuItem("Quit", lambda: self.jobs.put("quit"))))

    # --- data ------------------------------------------------------------
    def remember_drop(self, path, tokens):
        before = self.previous.get(path)
        self.previous[path] = tokens
        if before and tokens < before * gt.DROP_FACTOR:
            with open(gt.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  chat {chat_id(path)}  "
                        f"{fmt(before)} -> {fmt(tokens)}\n")

    def red_alert(self, path, tokens, share):
        """Alert once per chat when the tacho turns red - the colour alone is
        easy to miss. After a compaction (back below red) it is armed again."""
        if level(share) != "red":
            self.warned.discard(path)
            return
        if path in self.warned:
            return
        self.warned.add(path)
        text = (f"{fmt(tokens)} tokens ({share:.0%}) – automatic compaction is coming soon. "
                f"Tell Gemini now to save what matters.")
        try:
            self.icon.notify(text, "Gemini-Tacho: red")
        except Exception:  # the balloon is a bonus, the tacho keeps running
            pass
        # The balloon does not stay in the Windows notification history -
        # this window stays on top until you click OK.
        self.alert_window(f"{text}\n\nAlert at {time.strftime('%H:%M')}")

    def alert_window(self, text):
        if self.alert is None or not self.alert.winfo_exists():
            self.alert = tk.Toplevel(self.root)
            self.alert.title("Gemini-Tacho: red")
            self.alert.attributes("-topmost", True)
            self.alert.resizable(False, False)
            self.alert_label = tk.Label(self.alert, font=("Segoe UI", 11), justify="left",
                                        wraplength=380, fg="white", bg="#C0392B", padx=16, pady=14)
            self.alert_label.pack(fill="both")
            tk.Button(self.alert, text="OK", width=10, command=self.alert.destroy).pack(pady=10)
        self.alert_label.config(text=text)
        self.alert.deiconify()
        self.alert.lift()

    def tick(self):
        try:
            path = gt.active_chat()
            count = gt.last_count(path) if path else None
            if count is None:
                self.icon.icon = ring(0, GREY)
                self.icon.title = "Gemini-Tacho: no Antigravity chat found"
            else:
                tokens, mtime = count
                self.remember_drop(path, tokens)
                share = tokens / gt.WINDOW
                self.icon.icon = ring(share, COLORS[level(share)])
                self.red_alert(path, tokens, share)
                age = int(time.time() - mtime)
                self.icon.title = f"Gemini: {fmt(tokens)} tokens ({share:.0%}) · {age_text(age)}"
        except Exception as exc:  # the tacho must never crash
            self.icon.title = f"Gemini-Tacho: {type(exc).__name__}"
        self.ensure_icon()
        self.root.after(gt.TICK_MS, self.tick)

    def ensure_icon(self):
        """Re-add the tray icon if Windows lost it. After monitor standby Windows
        may rebuild the taskbar; the icon vanished while the process kept running.
        NIM_MODIFY fails when the icon is missing - then NIM_ADD via pystray's _show()."""
        if pw is None or not self.icon.visible:
            return
        try:
            data = pw.NOTIFYICONDATAW(cbSize=ctypes.sizeof(pw.NOTIFYICONDATAW),
                                      hWnd=self.icon._hwnd, hID=id(self.icon),
                                      uFlags=pw.NIF_TIP, szTip=self.icon.title or "Gemini-Tacho")
            if not pw.Shell_NotifyIcon(pw.NIM_MODIFY, data):
                self.icon._show()
        except Exception:  # restoring is a bonus, never crash
            pass

    # --- details window --------------------------------------------------
    def details_text(self):
        path = gt.active_chat()
        if not path:
            return "No Antigravity chat found."
        steps = last_steps(path, STEPS_SHOWN)
        if not steps:
            return "No token counts in the active chat yet."
        s = steps[-1]
        total = s["input_tokens"] + s["cache_read_tokens"] + s["output_tokens"]
        age = int(time.time() - os.path.getmtime(path))
        lines = [
            f"Total:         {fmt(total):>10}   ({total / gt.WINDOW:.1%} of compaction limit {fmt(gt.WINDOW)})",
            f"  cache:       {fmt(s['cache_read_tokens']):>10}",
            f"  new input:   {fmt(s['input_tokens']):>10}",
            f"  output:      {fmt(s['output_tokens']):>10}",
            f"Chat {chat_id(path)} · last step {s['step_index']} · {age_text(age)}",
            f"Colors: yellow from {fmt(int(gt.YELLOW_FROM * gt.WINDOW))}, red from {fmt(int(gt.RED_FROM * gt.WINDOW))}",
            "",
            "Last steps (total / growth):",
        ]
        before = None
        for x in steps:
            g = x["input_tokens"] + x["cache_read_tokens"] + x["output_tokens"]
            growth = "" if before is None else f"{g - before:+,}"
            lines.append(f"  #{x['step_index']:<5} {fmt(g):>10}  {growth:>9}")
            before = g
        lines += ["", "Detected compactions:"]
        if os.path.isfile(gt.LOG_FILE):
            with open(gt.LOG_FILE, encoding="utf-8") as f:
                entries = [z.rstrip() for z in f if z.strip()][-5:]
            lines += [f"  {z}" for z in entries] or ["  none"]
        else:
            lines.append("  none yet")
        return "\n".join(lines)

    def show_details(self):
        if self.detail is None or not self.detail.winfo_exists():
            self.detail = tk.Toplevel(self.root)
            self.detail.title("Gemini-Tacho – Details")
            self.detail.attributes("-topmost", True)
            self.detail.resizable(False, False)
            self.detail_label = tk.Label(self.detail, font=("Consolas", 10),
                                         justify="left", anchor="w")
            self.detail_label.pack(padx=12, pady=10)
            tk.Button(self.detail, text="Refresh",
                      command=lambda: self.detail_label.config(text=self.details_text())
                      ).pack(pady=(0, 10))
        self.detail_label.config(text=self.details_text())
        self.detail.deiconify()
        self.detail.lift()

    # --- main loop -------------------------------------------------------
    def check_jobs(self):
        try:
            while True:
                job = self.jobs.get_nowait()
                if job == "details":
                    self.show_details()
                elif job == "quit":
                    self.icon.stop()
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(200, self.check_jobs)

    def start(self):
        self.icon.run_detached()
        self.tick()
        self.check_jobs()
        self.root.mainloop()


if __name__ == "__main__":
    Tacho().start()
