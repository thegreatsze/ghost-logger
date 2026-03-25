#!/usr/bin/env python3
"""
Ghost Activity & Time Logger
Silently tracks active window time for billable hours logging.
Sits in your system tray, polls every 60 seconds, logs to a local CSV.
"""

import csv
import sys
import threading
import datetime
import collections
import os
import urllib.request
from pathlib import Path
from typing import Dict, Optional

# ── Require Python 3.9+ ───────────────────────────────────────────────────────
if sys.version_info < (3, 9):
    sys.exit("Ghost Logger requires Python 3.9 or newer.")

# ── Configuration ─────────────────────────────────────────────────────────────
POLL_INTERVAL  = 60         # seconds between window checks
MIN_SESSION    = 15         # ignore sessions shorter than this (seconds)
IDLE_THRESHOLD = 120        # seconds of no input before a session is marked (Idle)
LOG_DIR        = Path.home() / ".ghost_logger"
LOG_FILE       = LOG_DIR / "activity_log.csv"
CSV_HEADERS    = ["date", "start_time", "end_time", "window_title", "duration_seconds"]

# App name suffixes to strip from window titles
APP_SUFFIXES = [
    " - Microsoft Word", " - Word",
    " - Microsoft Excel", " - Excel",
    " - Microsoft PowerPoint", " - PowerPoint",
    " - Google Chrome", " - Chrome",
    " - Mozilla Firefox", " - Firefox",
    " - Microsoft Edge", " - Edge",
    " - Notepad", " - Notepad++",
    " - Adobe Acrobat Reader DC", " - Adobe Acrobat",
    " - Microsoft Outlook", " - Outlook",
    " - Visual Studio Code", " - Code",
]

# ── Platform window detection ─────────────────────────────────────────────────

def get_active_window() -> str:
    """Return the title of the currently focused window."""
    if sys.platform == "win32":
        try:
            import win32gui
            hwnd  = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return title or "Desktop"
        except Exception:
            return "Unknown"
    elif sys.platform == "darwin":
        try:
            import subprocess
            script = ('tell application "System Events" to get name of first '
                      'application process whose frontmost is true')
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=2)
            return r.stdout.strip() or "Unknown"
        except Exception:
            return "Unknown"
    else:  # Linux / X11
        try:
            import subprocess
            r = subprocess.run(["xdotool", "getwindowfocus", "getwindowname"],
                               capture_output=True, text=True, timeout=2)
            return r.stdout.strip() or "Unknown"
        except Exception:
            return "Unknown"


def get_idle_seconds() -> float:
    """Return the number of seconds since the last keyboard or mouse input."""
    if sys.platform == "win32":
        try:
            import ctypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(lii)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            elapsed_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return elapsed_ms / 1000.0
        except Exception:
            return 0.0
    elif sys.platform == "darwin":
        try:
            import subprocess
            r = subprocess.run(["ioreg", "-c", "IOHIDSystem"],
                               capture_output=True, text=True, timeout=2)
            for line in r.stdout.splitlines():
                if "HIDIdleTime" in line:
                    ns = int(line.split("=")[-1].strip())
                    return ns / 1_000_000_000.0
        except Exception:
            pass
        return 0.0
    else:  # Linux — requires xprintidle
        try:
            import subprocess
            r = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=2)
            return int(r.stdout.strip()) / 1000.0
        except Exception:
            return 0.0


def clean_title(title: str) -> str:
    """Strip common app name suffixes to surface the document/site name."""
    for suffix in APP_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title.strip() or "Unknown"


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m      = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


# ── CSV Activity Logger ───────────────────────────────────────────────────────

class ActivityLogger:
    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_HEADERS)
        self._lock         = threading.Lock()
        self.current       : Optional[str]               = None
        self.win_start     : Optional[datetime.datetime] = None
        self.running       = False
        self.paused        = False
        self._timer        : Optional[threading.Timer]   = None
        self._pause_start  : Optional[datetime.datetime] = None
        self._pause_reason : str                         = ""

    # ── internal ──────────────────────────────────────────────────────────────

    def _write_session(self, title: str, start: datetime.datetime,
                       end: datetime.datetime):
        duration = int((end - start).total_seconds())
        if duration < MIN_SESSION:
            return
        row = [
            start.strftime("%Y-%m-%d"),
            start.strftime("%H:%M:%S"),
            end.strftime("%H:%M:%S"),
            title,
            duration,
        ]
        with self._lock:
            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)

    def _effective_title(self) -> str:
        """Return the active window title, appending ' (Idle)' when the user is idle."""
        title = get_active_window()
        if get_idle_seconds() >= IDLE_THRESHOLD:
            return f"{title} (Idle)"
        return title

    def _poll(self):
        if self.running:
            if not self.paused:
                title = self._effective_title()
                now   = datetime.datetime.now()
                if self.current is None:
                    self.current   = title
                    self.win_start = now
                elif title != self.current:
                    self._write_session(self.current, self.win_start, now)
                    self.current   = title
                    self.win_start = now
            # Reschedule
            self._timer = threading.Timer(POLL_INTERVAL, self._poll)
            self._timer.daemon = True
            self._timer.start()

    # ── public ────────────────────────────────────────────────────────────────

    def start(self):
        self.running   = True
        self.current   = self._effective_title()
        self.win_start = datetime.datetime.now()
        self._timer = threading.Timer(POLL_INTERVAL, self._poll)
        self._timer.daemon = True
        self._timer.start()

    def flush(self):
        """Write the current in-progress session to disk (incrementally)."""
        if self.current and self.win_start:
            now = datetime.datetime.now()
            self._write_session(self.current, self.win_start, now)
            self.win_start = now   # reset so next flush is additive, not duplicate

    def stop(self):
        self.flush()
        self.running = False
        if self._timer:
            self._timer.cancel()

    def toggle_pause(self, reason: str = "") -> bool:
        """Pause or resume tracking. Returns True if now paused."""
        self.paused = not self.paused
        if self.paused:
            # Record when and why we paused
            self._pause_start  = datetime.datetime.now()
            self._pause_reason = reason
        else:
            # Log the pause as its own CSV entry, then restart tracking
            if self._pause_start:
                pause_end = datetime.datetime.now()
                label = (f"\u23f8 Paused \u2014 {self._pause_reason}"
                         if self._pause_reason else "\u23f8 Paused")
                self._write_session(label, self._pause_start, pause_end)
                self._pause_start  = None
                self._pause_reason = ""
            # Resuming: fresh start time so paused gap is not double-counted
            self.current   = get_active_window()
            self.win_start = datetime.datetime.now()
        return self.paused

    def get_report(self, date_str: Optional[str] = None) -> Dict[str, int]:
        """Return {cleaned_title: total_seconds} sorted by time desc."""
        if date_str is None:
            date_str = datetime.date.today().strftime("%Y-%m-%d")
        totals: Dict[str, int] = collections.defaultdict(int)
        with self._lock:
            with open(LOG_FILE, "r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row["date"] == date_str:
                        key = clean_title(row["window_title"])
                        totals[key] += int(row["duration_seconds"])
        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


# ── Pause / Resume Overlay Widget ────────────────────────────────────────────

class PauseOverlay:
    """
    Always-on-top frameless widget in the top-right corner of the desktop.
    Shows a large Pause / Resume button, a reason entry field, and a ⋮ menu
    button that replicates the system-tray context menu.
    Draggable so the user can reposition it anywhere on screen.
    """

    _TRACK_BG    = "#8B1A2E"   # maroon while tracking
    _TRACK_HOVER = "#a32235"
    _PAUSE_BG    = "#a6e3a1"   # green while paused
    _PAUSE_HOVER = "#94e2d5"
    _PLACEHOLDER = "Reason (optional)"

    def __init__(self, logger: "ActivityLogger", paused_state: list,
                 on_toggle_callback=None, on_quit_callback=None):
        """
        logger               – ActivityLogger instance
        paused_state         – shared [bool] mutated in-place
        on_toggle_callback   – called with (is_paused: bool) after each toggle
        on_quit_callback     – called when the user quits from the widget menu
        """
        self.logger       = logger
        self.paused_state = paused_state
        self._cb          = on_toggle_callback
        self._quit_cb     = on_quit_callback
        self._root        = None
        self._entry       = None
        self._btn         = None
        self._menu_btn    = None
        self._drag_x      = 0
        self._drag_y      = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self):
        """Blocking – run from a daemon thread."""
        import tkinter as tk

        root = tk.Tk()
        self._root = root

        root.overrideredirect(True)           # no title bar / border
        root.attributes("-topmost", True)     # always on top
        root.attributes("-alpha", 0.93)
        root.configure(bg="#313244")
        root.resizable(False, False)

        self._build_ui(root)
        root.update_idletasks()

        # Position: top-right corner with 24 px margin
        sw = root.winfo_screenwidth()
        w  = root.winfo_reqwidth()
        root.geometry(f"+{sw - w - 24}+24")

        # Allow dragging the widget to a new position
        root.bind("<ButtonPress-1>", self._drag_start)
        root.bind("<B1-Motion>",     self._drag_motion)

        root.mainloop()

    def _drag_start(self, event):
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _drag_motion(self, event):
        self._root.geometry(
            f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}"
        )

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, root):
        import tkinter as tk

        pad = tk.Frame(root, bg="#313244", padx=12, pady=10)
        pad.pack(fill="both", expand=True)

        # ── Top row: "Pause reason:" label  +  ⋮ menu button ─────────────────
        top = tk.Frame(pad, bg="#313244")
        top.pack(fill="x", pady=(0, 2))

        tk.Label(top, text="Pause reason:", bg="#313244", fg="#a6adc8",
                 font=("Segoe UI", 8)).pack(side="left")

        self._menu_btn = tk.Button(
            top, text="\u22ee",           # ⋮  vertical ellipsis
            command=self._show_context_menu,
            bg="#313244", fg="#a6adc8",
            font=("Segoe UI", 11), relief="flat",
            cursor="hand2", padx=4, pady=0, bd=0,
            activebackground="#45475a",
            activeforeground="#cdd6f4",
        )
        self._menu_btn.pack(side="right")

        # ── Reason entry ──────────────────────────────────────────────────────
        self._entry = tk.Entry(
            pad,
            bg="#1e1e2e", fg="#6c7086",
            insertbackground="#cdd6f4",
            relief="flat", font=("Segoe UI", 9),
            width=28, bd=4,
        )
        self._entry.insert(0, self._PLACEHOLDER)
        self._entry.bind("<FocusIn>",  self._on_focus_in)
        self._entry.bind("<FocusOut>", self._on_focus_out)
        self._entry.pack(fill="x", pady=(0, 8))

        # ── Pause / Resume button ─────────────────────────────────────────────
        self._btn = tk.Button(
            pad,
            text="\u23f8  Pause Tracking",
            command=self._toggle,
            bg=self._TRACK_BG, fg="#ffffff",
            font=("Segoe UI", 12),           # non-bold
            relief="flat", padx=10, pady=10,
            cursor="hand2",
            activebackground=self._TRACK_HOVER,
            activeforeground="#ffffff",
            bd=0,
        )
        self._btn.pack(fill="x")

    # ── Placeholder helpers ───────────────────────────────────────────────────

    def _on_focus_in(self, _):
        if self._entry.get() == self._PLACEHOLDER:
            self._entry.delete(0, "end")
            self._entry.config(fg="#cdd6f4")

    def _on_focus_out(self, _):
        if not self._entry.get().strip():
            self._entry.delete(0, "end")
            self._entry.insert(0, self._PLACEHOLDER)
            self._entry.config(fg="#6c7086")

    # ── Toggle logic ──────────────────────────────────────────────────────────

    def _toggle(self):
        raw    = self._entry.get().strip()
        reason = "" if raw == self._PLACEHOLDER else raw
        self.paused_state[0] = self.logger.toggle_pause(reason)
        self._apply_state(reason)
        if self._cb:
            self._cb(self.paused_state[0])

    def _apply_state(self, reason: str = ""):
        """Refresh the widget to match paused_state[0].  Must be on the Tk thread."""
        if self.paused_state[0]:
            self._btn.config(
                text="\u25b6  Resume Tracking",
                bg=self._PAUSE_BG,
                fg="#1e1e2e",
                activebackground=self._PAUSE_HOVER,
                activeforeground="#1e1e2e",
            )
            label = reason if reason else "Away from desk"
            self._entry.config(state="normal")
            self._entry.delete(0, "end")
            self._entry.insert(0, label)
            self._entry.config(
                state="disabled",
                disabledforeground="#f9e2af",
                disabledbackground="#1e1e2e",
            )
        else:
            self._btn.config(
                text="\u23f8  Pause Tracking",
                bg=self._TRACK_BG,
                fg="#ffffff",
                activebackground=self._TRACK_HOVER,
                activeforeground="#ffffff",
            )
            self._entry.config(state="normal", fg="#6c7086")
            self._entry.delete(0, "end")
            self._entry.insert(0, self._PLACEHOLDER)

    def sync_from_tray(self):
        """Thread-safe sync when the tray menu toggles pause independently."""
        if self._root:
            self._root.after(0, lambda: self._apply_state())

    # ── ⋮ Context menu ────────────────────────────────────────────────────────

    def _show_context_menu(self):
        import tkinter as tk

        menu = tk.Menu(
            self._root, tearoff=0,
            bg="#313244", fg="#cdd6f4",
            activebackground="#45475a", activeforeground="#cdd6f4",
            font=("Segoe UI", 9), bd=0, relief="flat",
        )
        menu.add_command(label="View Today's Report",
                         command=self._menu_report)
        menu.add_separator()
        menu.add_command(label="Open Log File (CSV)",
                         command=self._menu_open_log)
        menu.add_command(label="Open Log Folder",
                         command=self._menu_open_folder)
        menu.add_separator()
        menu.add_command(label="Quit Ghost Logger",
                         command=self._menu_quit)

        # Show below the ⋮ button
        btn = self._menu_btn
        menu.tk_popup(btn.winfo_rootx(),
                      btn.winfo_rooty() + btn.winfo_height())

    def _menu_report(self):
        self.logger.flush()
        report   = self.logger.get_report()
        date_str = datetime.date.today().strftime("%Y-%m-%d")
        threading.Thread(target=show_report_window,
                         args=(report, date_str), daemon=True).start()

    def _menu_open_log(self):
        if sys.platform == "win32":
            os.startfile(str(LOG_FILE))
        elif sys.platform == "darwin":
            os.system(f'open "{LOG_FILE}"')
        else:
            os.system(f'xdg-open "{LOG_FILE}"')

    def _menu_open_folder(self):
        folder = str(LOG_DIR)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}"')

    def _menu_quit(self):
        if self._quit_cb:
            self._quit_cb()
        if self._root:
            self._root.destroy()


# ── Report Window (Tkinter) ───────────────────────────────────────────────────

def show_report_window(report: Dict[str, int], date_str: str):
    """Open a styled Tkinter window showing today's activity breakdown."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"Ghost Logger — {date_str}")
    root.configure(bg="#1e1e2e")
    root.minsize(520, 340)

    # ── Header ────────────────────────────────────────────────────────────────
    tk.Label(root, text="Ghost Activity Report",
             font=("Segoe UI", 14, "bold"),
             bg="#1e1e2e", fg="#cdd6f4").pack(pady=(14, 2))
    tk.Label(root, text=date_str,
             font=("Segoe UI", 10),
             bg="#1e1e2e", fg="#6c7086").pack(pady=(0, 10))

    # ── Table ─────────────────────────────────────────────────────────────────
    frame = tk.Frame(root, bg="#1e1e2e")
    frame.pack(fill="both", expand=True, padx=16, pady=4)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Ghost.Treeview",
                    background="#313244", fieldbackground="#313244",
                    foreground="#cdd6f4", rowheight=28,
                    font=("Segoe UI", 10))
    style.configure("Ghost.Treeview.Heading",
                    background="#45475a", foreground="#cdd6f4",
                    font=("Segoe UI", 10, "bold"), relief="flat")
    style.map("Ghost.Treeview",
              background=[("selected", "#89b4fa")],
              foreground=[("selected", "#1e1e2e")])

    tree = ttk.Treeview(frame, columns=("window", "time"),
                        show="headings", style="Ghost.Treeview")
    tree.heading("window", text="Window / Document")
    tree.heading("time",   text="Time Spent")
    tree.column("window", width=400, anchor="w", stretch=True)
    tree.column("time",   width=100, anchor="center", stretch=False)

    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)

    total = 0
    for title, secs in report.items():
        tree.insert("", "end", values=(title, fmt_duration(secs)))
        total += secs

    if not report:
        tree.insert("", "end", values=("No activity logged today yet.", "—"))

    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    # ── Footer ────────────────────────────────────────────────────────────────
    tk.Label(root,
             text=f"Total tracked today:  {fmt_duration(total)}",
             font=("Segoe UI", 10, "bold"),
             bg="#1e1e2e", fg="#a6e3a1").pack(pady=(8, 4))

    def copy_report():
        lines = [f"Activity Report — {date_str}", "=" * 40]
        for t, s in report.items():
            lines.append(f"{fmt_duration(s):>8}   {t}")
        lines += ["", f"Total tracked: {fmt_duration(total)}"]
        root.clipboard_clear()
        root.clipboard_append("\n".join(lines))
        copy_btn.config(text="Copied!")
        root.after(2000, lambda: copy_btn.config(text="Copy to Clipboard"))

    copy_btn = tk.Button(root, text="Copy to Clipboard", command=copy_report,
                         bg="#89b4fa", fg="#1e1e2e",
                         font=("Segoe UI", 10, "bold"),
                         relief="flat", padx=14, pady=7, cursor="hand2",
                         activebackground="#74c7ec", activeforeground="#1e1e2e")
    copy_btn.pack(pady=(0, 14))

    root.mainloop()


# ── Tray Icon Builder ─────────────────────────────────────────────────────────

def build_icon():
    """Create a simple ghost-shaped tray icon using Pillow."""
    from PIL import Image, ImageDraw
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    blue = (100, 160, 255, 230)
    # Rounded head
    d.ellipse([8, 4, 56, 44], fill=blue)
    # Body
    d.rectangle([8, 24, 56, 52], fill=blue)
    # Wavy skirt (scalloped bottom)
    skirt_y = 46
    for x in (8, 20, 32, 44):
        d.ellipse([x, skirt_y, x + 14, skirt_y + 14], fill=(0, 0, 0, 0))
        d.ellipse([x - 1, skirt_y + 2, x + 13, skirt_y + 16], fill=blue)
    # Eyes
    d.ellipse([18, 19, 30, 33], fill="white")
    d.ellipse([34, 19, 46, 33], fill="white")
    d.ellipse([21, 22, 27, 30], fill=(20, 20, 60))
    d.ellipse([37, 22, 43, 30], fill=(20, 20, 60))
    return img


# ── Arcade Font Loader ────────────────────────────────────────────────────────

def _load_arcade_font() -> str:
    """
    Download Press Start 2P (TTF) to ~/.ghost_logger/ on first run and
    register it with Windows.  Returns the font family name on success,
    empty string on any failure (caller should fall back to a system font).
    """
    font_path = LOG_DIR / "PressStart2P.ttf"
    font_url  = ("https://github.com/google/fonts/raw/main/ofl/"
                 "pressstart2p/PressStart2P-Regular.ttf")

    if not font_path.exists():
        try:
            urllib.request.urlretrieve(font_url, font_path)
        except Exception:
            return ""

    if not font_path.exists():
        return ""

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.gdi32.AddFontResourceExW(str(font_path), 0x10, 0)
            # Broadcast WM_FONTCHANGE so the system (and new Tk instances) see it
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x001D, 0, 0)
        except Exception:
            return ""

    return "Press Start 2P"


# ── Launch Splash Screen ──────────────────────────────────────────────────────

def show_splash():
    """
    Display a small branded splash on startup.
    Auto-dismisses after 2.5 s; click anywhere to dismiss early.
    """
    import tkinter as tk
    import tkinter.font as tkfont
    from PIL import Image, ImageTk

    arcade_family = _load_arcade_font()

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#1e1e2e")

    w, h = 320, 240
    sw   = root.winfo_screenwidth()
    sh   = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # Ghost icon scaled up for the splash
    ghost_pil   = build_icon().resize((80, 80), Image.LANCZOS)
    ghost_photo = ImageTk.PhotoImage(ghost_pil)
    icon_lbl    = tk.Label(root, image=ghost_photo, bg="#1e1e2e")
    icon_lbl.image = ghost_photo   # prevent garbage collection
    icon_lbl.pack(pady=(28, 12))

    # "Ghost Logger" in arcade / Pac-Man font
    if arcade_family:
        title_font = tkfont.Font(family=arcade_family, size=16, weight="normal")
    else:
        title_font = tkfont.Font(family="Courier New", size=18, weight="bold")

    tk.Label(root, text="Ghost Logger", font=title_font,
             bg="#1e1e2e", fg="#89b4fa").pack()

    # Byline in the same style as the reason-entry text
    tk.Label(root, text="by Tan Sze Yao",
             font=("Segoe UI", 9), bg="#1e1e2e", fg="#6c7086").pack(pady=(10, 0))

    def dismiss(_=None):
        root.destroy()

    root.after(2500, dismiss)
    root.bind("<Button-1>", dismiss)
    root.mainloop()


# ── System Tray ───────────────────────────────────────────────────────────────

def run_tray(logger: ActivityLogger):
    import pystray

    paused_state = [False]   # shared mutable state
    icon_ref     = [None]    # filled after icon creation
    overlay_ref  = [None]    # filled after overlay starts

    # ── Tray menu callbacks ────────────────────────────────────────────────────

    def on_report(icon, item):
        logger.flush()
        report   = logger.get_report()
        date_str = datetime.date.today().strftime("%Y-%m-%d")
        threading.Thread(target=show_report_window,
                         args=(report, date_str), daemon=True).start()

    def on_toggle_pause(icon, item):
        paused_state[0] = logger.toggle_pause()
        icon.title = "Ghost Logger — Paused" if paused_state[0] else "Ghost Logger — Tracking"
        icon.menu  = _make_menu(paused_state[0])
        if overlay_ref[0]:
            overlay_ref[0].sync_from_tray()

    def on_open_log(icon, item):
        if sys.platform == "win32":
            os.startfile(str(LOG_FILE))
        elif sys.platform == "darwin":
            os.system(f'open "{LOG_FILE}"')
        else:
            os.system(f'xdg-open "{LOG_FILE}"')

    def on_open_folder(icon, item):
        folder = str(LOG_DIR)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}"')

    def on_quit(icon, item):
        logger.stop()
        icon.stop()

    def _make_menu(is_paused: bool):
        pause_label = "Resume Tracking" if is_paused else "Pause Tracking"
        return pystray.Menu(
            pystray.MenuItem("Ghost Logger", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("View Today's Report", on_report, default=True),
            pystray.MenuItem(pause_label, on_toggle_pause),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Log File (CSV)", on_open_log),
            pystray.MenuItem("Open Log Folder", on_open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Ghost Logger", on_quit),
        )

    # ── Overlay callback (called when user clicks the floating button) ─────────

    def on_overlay_toggle(is_paused: bool):
        """Keep the tray title and menu in sync when the overlay is used."""
        if icon_ref[0]:
            icon_ref[0].title = "Ghost Logger — Paused" if is_paused else "Ghost Logger — Tracking"
            icon_ref[0].menu  = _make_menu(is_paused)

    # ── Launch the floating overlay widget ─────────────────────────────────────

    def _overlay_quit():
        """Called when the user chooses Quit from the overlay's context menu."""
        logger.stop()
        if icon_ref[0]:
            icon_ref[0].stop()

    overlay = PauseOverlay(logger, paused_state,
                           on_toggle_callback=on_overlay_toggle,
                           on_quit_callback=_overlay_quit)
    overlay_ref[0] = overlay
    threading.Thread(target=overlay.run, daemon=True).start()

    # ── Create and run the tray icon ───────────────────────────────────────────

    icon = pystray.Icon(
        name  ="ghost_logger",
        icon  =build_icon(),
        title ="Ghost Logger — Tracking",
        menu  =_make_menu(False),
    )
    icon_ref[0] = icon
    icon.run()


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    # Verify dependencies are installed
    missing = []
    try:
        import pystray        # noqa: F401
    except ImportError:
        missing.append("pystray")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if sys.platform == "win32":
        try:
            import win32gui   # noqa: F401
        except ImportError:
            missing.append("pywin32")

    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print("Run setup.bat (Windows) or:  pip install -r requirements.txt")
        sys.exit(1)

    show_splash()              # brief branded intro, then continues

    logger = ActivityLogger()
    logger.start()
    run_tray(logger)           # blocks until the user clicks Quit


if __name__ == "__main__":
    main()
