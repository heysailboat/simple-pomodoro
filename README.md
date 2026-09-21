# Pomodoro Sequence

A lightweight, cross-platform Pomodoro timer built in **Python + Tkinter**.

Instead of forcing the usual `work → break → work → break` pattern, Pomodoro Sequence lets you build **arbitrary repeating sequences of timed blocks**:

```text
Work 1 → Work 2 → Break → Work 1 → Work 2 → Break → ...
```

The project is deliberately small and transparent: every version is a standalone `pomodoro.py` file with no database, web stack, or heavy GUI framework.

## TLDR
Use `pomodoro_menubar.py`, the latest version. Download it and run it as a Python script. If you're on MacOS and want a menubar integration, install PyObjC:
```bash
python3 -m pip install pyobjc-framework-Cocoa
```

## Features

- Custom named timer blocks
- Individual duration for every block
- Arbitrary block sequences
- Fixed cycle counts or infinite repetition
- Start / pause / resume
- Skip and reset controls
- Inline editing of block names and durations
- Add, delete, and reorder blocks
- Desktop notifications
- Compact horizontal layouts
- Bento / Swiss-inspired UI in later versions
- Light / dark appearance support in the later versions
- Live appearance switching in the latest version
- Optional native macOS menu-bar integration in the latest version
- Core timer designed to remain portable across macOS, Windows, and Linux

## Version compatibility

The repository contains **five selected versions**. Earlier intermediate experiments and patches from development are not included as separate repository files; their useful changes are incorporated into the later versions where applicable.

| Feature | `pomodoro.py` | `pomodoro_compact.py` | `pomodoro_modern.py` | `pomodoro_bento.py` | `pomodoro_menubar.py` |
|---|:---:|:---:|:---:|:---:|:---:|
| Custom named blocks | ✓ | ✓ | ✓ | ✓ | ✓ |
| Per-block durations | ✓ | ✓ | ✓ | ✓ | ✓ |
| Arbitrary sequences | ✓ | ✓ | ✓ | ✓ | ✓ |
| Fixed / infinite cycles | ✓ | ✓ | ✓ | ✓ | ✓ |
| Start / pause / resume | ✓ | ✓ | ✓ | ✓ | ✓ |
| Skip / reset | ✓ | ✓ | ✓ | ✓ | ✓ |
| Inline block editing | — | ✓ | ✓ | ✓ | ✓ |
| Add / delete / reorder blocks | ✓ | ✓ | ✓ | ✓ | ✓ |
| Desktop notifications | ✓ | ✓ | ✓ | ✓ | ✓ |
| Compact UI | — | ✓ | ✓ | ✓ | ✓ |
| Horizontal Bento / Swiss layout | — | — | — | ✓ | ✓ |
| Dark appearance | — | — | — | ✓ | ✓ |
| Live theme switching | — | — | — | — | ✓ |
| Native macOS menu bar | — | — | — | — | ✓ |
| Reliable 1–2+ block editing | — | — | — | — | ✓ |
| Cross-platform core | ✓ | ✓ | ✓ | ✓ | ✓ |

`✓` means the feature is present in that version. `—` means it was not yet implemented in that version.

## Version history

### Version 1 — `pomodoro.py`

The original implementation and functional baseline.

It introduced the core timer: custom timed blocks, repeating cycles, start/pause/skip/reset controls, and desktop notifications. Block editing used the earlier editor workflow rather than the later inline editor.

### Version 2 — `pomodoro_compact.py`

The first substantial size reduction.

This version made the application feel more like a small utility than a full-sized productivity dashboard. It also introduced direct **inline editing** for block names and durations and tightened the sequence editor.

### Version 3 — `pomodoro_modern.py`

A visual refinement of the compact design.

The UI moved towards a cleaner **native Tk/Aqua** appearance, with simplified controls, tighter typography, and less visual clutter while keeping the same timer model.

### Version 4 — `pomodoro_bento.py`

The major layout redesign.

The interface was rebuilt around a **horizontal Bento / Swiss-inspired grid**, separating the timer, settings, and sequence editor into compact rectangular sections. The goal was to use the available width rather than stacking everything vertically.

### Version 5 — `pomodoro_menubar.py`

The current feature-complete version.

This version builds on the Bento layout and adds **live theme switching**, improved dark-mode handling, and an optional native **macOS menu-bar timer** with a live time/state indicator and quick controls. It also includes the later sequence-selection fix so one-, two-, and multi-block sequences can be edited reliably.

The menu-bar integration is macOS-specific; the main timer remains cross-platform.

## Requirements

### All platforms

- Python **3.8+**
- Tkinter

### macOS

The project is designed with **macOS 10.15.8 Catalina** in mind.

The latest version can optionally use PyObjC for its native menu-bar integration:

```bash
python3 -m pip install pyobjc-framework-Cocoa
```

Without PyObjC, the main application still works; only the native macOS menu-bar integration is unavailable.

### Windows

The core GUI, timer, sequences, and notifications are supported without third-party Python packages. Windows notifications use the platform's PowerShell / Toast facilities.

### Linux

The core GUI and timer work without third-party Python packages. Desktop notifications use `notify-send` when it is available.

## Running a version

Each version is self-contained:

```text
pomodoro-sequence/
├── README.md
├── pomodoro.py
├── pomodoro_compact.py
├── pomodoro_modern.py
├── pomodoro_bento.py
└── pomodoro_menubar.py
```

Run whichever version you want directly:

```bash
python3 pomodoro.py
```

or, for example:

```bash
python3 pomodoro_menubar.py
```

On Unix-like systems, the file can also be made executable:

```bash
chmod +x pomodoro_menubar.py
./pomodoro_menubar.py
```

## How sequences work

Each row in the sequence editor is one timed block.

For example:

| Block | Duration |
|---|---:|
| Work 1 | 25 min |
| Work 2 | 15 min |
| Break | 5 min |

With **Cycles = 0**, the complete sequence repeats forever.

With **Cycles = 4**, the complete sequence runs four times.

Sequences are not required to contain a traditional work/break pattern. You can make a sequence such as:

```text
Study → Practice → Review → Break
```

or a two-block loop:

```text
Work → Break
```

The latest version also supports a single repeating block.

## macOS menu bar

The latest version can create a native macOS status-bar item showing the current timer state and remaining time.

The menu provides quick controls such as:

- Open Pomodoro
- Start / Pause / Resume
- Skip
- Reset
- Quit

This allows the timer to remain visible without keeping the main window in front.

## Theme system

The latest version supports appearance switching without restarting the application.

The theme can be changed from within the app, while the automatic mode can follow the system appearance where supported.

## Design goals

- **Lightweight** — standard-library-first, with PyObjC as an optional macOS enhancement
- **Portable** — the core timer runs across macOS, Windows, and Linux
- **Compact** — designed as a small utility rather than a large productivity dashboard
- **Flexible** — user-defined sequences instead of one fixed Pomodoro formula
- **Readable** — straightforward Python and a simple Tkinter UI
- **Incremental** — each retained version shows a meaningful stage of the UI and feature evolution

## AI-assisted development disclaimer

This project was developed with assistance from **OpenAI's ChatGPT**. AI assistance was used for portions of the implementation, debugging, UI iteration, and documentation.

AI-generated code can contain mistakes, outdated assumptions, or platform-specific bugs. The code should therefore be reviewed, tested, and maintained by a human before being relied upon, especially when adapting it to newer operating-system versions or packaging it for distribution.
