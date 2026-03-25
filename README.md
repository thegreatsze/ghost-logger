# 👻 Ghost Logger

A silent, automatic time tracker for legal professionals — and anyone else who wants honest logs of where their time actually goes.

Ghost Logger sits in your system tray, polls your active window every 60 seconds, and writes everything to a local CSV file. No pop-ups. No interruptions. No cloud.

---

## Why Ghost Logger?

Most time-tracking tools require you to remember to start and stop a timer. Ghost Logger flips that assumption: it runs continuously in the background and captures time automatically.

- **Billing by the hour?** Every window you touch is logged — documents, emails, research, calls — so nothing falls through the cracks.
- **Stepped away and forgot to pause?** Idle detection flags entries automatically after 2 minutes of no keyboard or mouse input, so idle time never sneaks into your billable hours.
- **Want full control?** The floating overlay lets you pause manually and add a reason — useful for off-screen work, client calls, or anything you want to note explicitly.

---

## Features

| Feature | Details |
|---|---|
| 🪟 Window tracking | Polls the active window every 60 seconds |
| 💤 Idle detection | Flags entries as `(Idle)` after 2 min of no input |
| ⏸ Pause / Resume overlay | Floating, draggable widget with optional reason field |
| 📊 Daily report | Time breakdown per window, copyable to clipboard |
| 📄 CSV log | Plain-text log at `~/.ghost_logger/activity_log.csv` |
| 🖥 Cross-platform | Windows, macOS, Linux |
| 🔒 Local only | No internet connection, no accounts, no telemetry |

---

## Requirements

- Python 3.9 or newer
- Dependencies (installed automatically by `setup.bat`):
  - [`pystray`](https://github.com/moses-palmer/pystray) ≥ 0.19.5
  - [`Pillow`](https://python-pillow.org/) ≥ 10.0.0
  - [`pywin32`](https://github.com/mhammond/pywin32) ≥ 306 *(Windows only)*

---

## Installation

### Windows (recommended)

1. Download or clone this repository.
2. Double-click **`setup.bat`**.
   It will check for Python, install dependencies, and offer to launch Ghost Logger immediately.
3. To start Ghost Logger on subsequent sessions, double-click **`run_ghost.vbs`**
   (runs silently — no console window).

### macOS / Linux

```bash
pip install -r requirements.txt
python ghost_logger.py
```

> **macOS note:** Idle detection uses `ioreg` (built-in). No extra packages needed.
> **Linux note:** Idle detection requires [`xprintidle`](https://github.com/lucianodato/xprintidle). Install with `sudo apt install xprintidle` or your distro's equivalent.

---

## Usage

Once running, Ghost Logger appears as a ghost icon in your system tray. Everything is automatic from that point.

### Tray menu

Right-click the tray icon to access:

- **View Today's Report** — opens a window showing time per document/app for today
- **Pause / Resume Tracking** — manual pause with optional reason
- **Open Log File (CSV)** — opens `activity_log.csv` directly
- **Open Log Folder** — opens `~/.ghost_logger/` in your file manager
- **Quit Ghost Logger** — flushes the current session and exits

### Floating overlay

A small widget sits in the top-right corner of your desktop (draggable to any position). It shows:

- A **Pause Tracking** button (maroon while tracking, green while paused)
- A **reason field** — optionally note why you're pausing

You can also access the full tray menu from the **⋮** button on the overlay.

### Idle detection

If Ghost Logger detects no keyboard or mouse input for **2 minutes**, it automatically appends `(Idle)` to the next log entry for that window. When you return and interact with the computer, normal tracking resumes — no action required.

This means:
- **Idle detection** is the automatic safeguard — it handles the cases you forget about.
- **Pause** is the precision tool — use it when you want to explicitly note why you're stepping away.

---

## Log format

All sessions are saved to `~/.ghost_logger/activity_log.csv`:

```
date,start_time,end_time,window_title,duration_seconds
2026-03-26,09:00:00,09:01:00,Contract_NDA_Acme.docx,60
2026-03-26,09:01:00,09:02:00,Gmail - Inbox,60
2026-03-26,09:15:00,09:16:00,Contract_NDA_Acme.docx (Idle),60
```

- Sessions shorter than **15 seconds** are discarded (configurable via `MIN_SESSION` in the source).
- Common app suffixes (e.g. ` - Microsoft Word`, ` - Google Chrome`) are stripped from window titles in reports so the document or site name is surfaced instead.
- Pause periods are logged as their own entries with a `⏸ Paused` prefix.

---

## Configuration

Open `ghost_logger.py` and edit the constants near the top:

```python
POLL_INTERVAL  = 60   # how often to check the active window (seconds)
MIN_SESSION    = 15   # discard sessions shorter than this (seconds)
IDLE_THRESHOLD = 120  # seconds of no input before flagging as (Idle)
```

---

## Files

```
ghost_logger.py   — main application
run_ghost.vbs     — silent launcher (Windows, no console window)
setup.bat         — one-time dependency installer (Windows)
requirements.txt  — Python dependencies
```

---

## Demo

A web-based interactive demo is available at `index.html` (also hosted on GitHub Pages). It simulates the window tracking, idle detection, and report view in a browser — no Python required.

---

## License

MIT License. Free to use, modify, and distribute.

---

*Built by Tan Sze Yao*
