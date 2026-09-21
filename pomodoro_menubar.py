#!/usr/bin/env python3
"""Compact cross-platform Pomodoro sequence timer.

Single-file Tkinter app, designed for macOS 10.15+ first, with notifications
for macOS, Windows, and Linux. Optional PyObjC enables the native macOS menu bar item.
"""

from __future__ import annotations

import html
import platform
import subprocess
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import List, Optional

APP_TITLE = "Pomodoro Sequence"
TICK_MS = 200
THEME_POLL_MS = 1500

# Theme palettes. The UI can switch between these without relaunching.
LIGHT_PALETTE = {
    "BG": "#f2f2ef",
    "CARD": "#ffffff",
    "ENTRY": "#ffffff",
    "TEXT": "#111111",
    "MUTED": "#6f6f6a",
    "LINE": "#d8d8d2",
    "ACCENT": "#d94b3d",
    "ACCENT_DARK": "#b93e32",
}

DARK_PALETTE = {
    "BG": "#1d1d1f",
    "CARD": "#272729",
    "ENTRY": "#353537",
    "TEXT": "#f2f2f2",
    "MUTED": "#a5a5aa",
    "LINE": "#55555a",
    "ACCENT": "#e05a4f",
    "ACCENT_DARK": "#c94c43",
}

def _system_is_dark() -> bool:
    if platform.system() != "Darwin":
        return False
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        return result.stdout.strip().lower() == "dark"
    except (OSError, subprocess.SubprocessError):
        return False




@dataclass
class Block:
    name: str
    minutes: float

    @property
    def seconds(self) -> float:
        return max(1.0, self.minutes * 60.0)



class MacMenubarController:
    """Small native NSStatusItem wrapper. Requires PyObjC on macOS."""

    def __init__(self, app: "PomodoroApp") -> None:
        self.available = False
        self.status_item = None
        self.menu = None
        self.start_item = None
        self.app = app
        self._NSObject = None
        self._controller = None

        if platform.system() != "Darwin":
            return

        try:
            import objc  # type: ignore
            from Cocoa import (  # type: ignore
                NSObject,
                NSMenu,
                NSMenuItem,
                NSStatusBar,
                NSVariableStatusItemLength,
            )
        except ImportError:
            return

        class Target(NSObject):
            def initWithApp_(self, owner):
                self = objc.super(Target, self).init()
                if self is not None:
                    self.owner = owner
                return self

            def menuAction_(self, sender):
                action = sender.action()
                if action == "openApp:":
                    self.owner.open_app()
                elif action == "toggle:":
                    self.owner.toggle_running()
                elif action == "skip:":
                    self.owner.skip()
                elif action == "reset:":
                    self.owner.reset()
                elif action == "quit:":
                    self.owner.close_app()

        self._NSObject = NSObject
        self._controller = Target.alloc().initWithApp_(self)
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("● 25:00")

        self.menu = NSMenu.alloc().initWithTitle_(APP_TITLE)
        self._add_menu_item(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open Pomodoro", "openApp:", "o"))
        self.start_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Start", "toggle:", " ")
        self._add_menu_item(self.start_item)
        self._add_menu_item(NSMenuItem.separatorItem())
        self._add_menu_item(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Skip", "skip:", "s"))
        self._add_menu_item(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Reset", "reset:", "r"))
        self._add_menu_item(NSMenuItem.separatorItem())
        self._add_menu_item(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "quit:", "q"))
        self.status_item.setMenu_(self.menu)
        self.available = True
        self.update()

    def _add_menu_item(self, item) -> None:
        if item.isSeparatorItem():
            self.menu.addItem_(item)
            return
        item.setTarget_(self._controller)
        self.menu.addItem_(item)

    def update(self) -> None:
        if not self.available or self.status_item is None:
            return
        block = self.app.blocks[self.app.block_index]
        shown = max(0.0, self.app.remaining)
        total = int(shown + 0.999999)
        hours, rem = divmod(total, 3600)
        mins, secs = divmod(rem, 60)
        timer_text = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"
        if self.app.running:
            indicator = "▶"
            menu_text = f"Pause  •  {block.name}"
        elif self.app.status_var.get() == "FINISHED":
            indicator = "✓"
            menu_text = "Finished"
        elif self.app.status_var.get() == "PAUSED":
            indicator = "Ⅱ"
            menu_text = "Resume"
        else:
            indicator = "●"
            menu_text = "Start"
        self.status_item.button().setTitle_(f"{indicator} {timer_text}")
        if self.start_item is not None:
            self.start_item.setTitle_(menu_text)

    def destroy(self) -> None:
        if not self.available or self.status_item is None:
            return
        try:
            from Cocoa import NSStatusBar  # type: ignore
            NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
        except Exception:
            pass
        self.available = False


class NotificationManager:
    @staticmethod
    def send(title: str, body: str) -> None:
        system = platform.system()
        try:
            if system == "Darwin":
                script = (
                    "display notification "
                    f'{NotificationManager._quote_applescript(body)} '
                    "with title "
                    f'{NotificationManager._quote_applescript(title)}'
                )
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return

            if system == "Windows":
                title_xml = html.escape(title, quote=True)
                body_xml = html.escape(body, quote=True)
                ps = (
                    '[Windows.UI.Notifications.ToastNotificationManager, '
                    'Windows.UI.Notifications, ContentType = WindowsRuntime]; '
                    '[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, '
                    'ContentType = WindowsRuntime]; '
                    '$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; '
                    f'$xml.LoadXml(\'<toast><visual><binding template="ToastGeneric">'
                    f'<text>{title_xml}</text><text>{body_xml}</text>'
                    '</binding></visual></toast>\'); '
                    '$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); '
                    '$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Pomodoro Sequence"); '
                    '$notifier.Show($toast);'
                )
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return

            try:
                subprocess.run(
                    ["notify-send", "--version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1,
                    check=False,
                )
                subprocess.Popen(
                    ["notify-send", title, body],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (FileNotFoundError, OSError):
                pass
        except Exception:
            pass

    @staticmethod
    def _quote_applescript(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class PomodoroApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("640x350")
        self.minsize(560, 310)

        self.theme_mode = "Auto" if platform.system() == "Darwin" else "Light"
        self._applied_dark = _system_is_dark() if self.theme_mode == "Auto" else self.theme_mode == "Dark"
        self._set_palette(self._applied_dark)
        self.configure(bg=self.BG)

        self.blocks: List[Block] = [
            Block("Work 1", 25),
            Block("Work 2", 25),
            Block("Break", 5),
        ]
        self.cycles_total = 0
        self.cycle_number = 1
        self.block_index = 0
        self.remaining = self.blocks[0].seconds
        self.running = False
        self._last_tick = time.monotonic()
        self._after_id: Optional[str] = None
        self.selected_index: Optional[int] = 0

        self._build_style()
        self._build_ui()
        self._refresh_editor()
        self._refresh_timer()
        self.menubar = MacMenubarController(self)
        self._update_menubar_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_tick()
        self._schedule_theme_poll()

    def _set_palette(self, dark: bool) -> None:
        palette = DARK_PALETTE if dark else LIGHT_PALETTE
        for key, value in palette.items():
            setattr(self, key, value)

    def _apply_theme(self, mode: str) -> None:
        if mode not in {"Auto", "Light", "Dark"}:
            return
        self.theme_mode = mode
        dark = _system_is_dark() if mode == "Auto" else mode == "Dark"
        if dark == self._applied_dark and hasattr(self, "theme_button"):
            self.theme_button.configure(text=f"Theme: {self.theme_mode}")
            return
        self._applied_dark = dark
        self._set_palette(dark)
        self.configure(bg=self.BG)
        if hasattr(self, "root_frame"):
            self.root_frame.destroy()
        self._build_style()
        self._build_ui()
        self._refresh_editor()
        self._refresh_timer()
        self._update_menubar_status()

    def _cycle_theme(self) -> None:
        order = ["Auto", "Light", "Dark"]
        self._apply_theme(order[(order.index(self.theme_mode) + 1) % len(order)])

    def _schedule_theme_poll(self) -> None:
        self.after(THEME_POLL_MS, self._poll_system_theme)

    def _poll_system_theme(self) -> None:
        if self.theme_mode == "Auto" and platform.system() == "Darwin":
            dark = _system_is_dark()
            if dark != self._applied_dark:
                self._apply_theme("Auto")
        self._schedule_theme_poll()

    def _update_menubar_status(self) -> None:
        active = bool(getattr(self, "menubar", None) and self.menubar.available)
        self.menubar_status = "Menu bar: active" if active else (
            "Menu bar: install PyObjC" if platform.system() == "Darwin" else "Menu bar: macOS only"
        )
        if hasattr(self, "menubar_hint"):
            self.menubar_hint.configure(text=("Menu bar enabled" if active else (
                "Install PyObjC for menu bar" if platform.system() == "Darwin" else "Menu bar: macOS only"
            )))
        if hasattr(self, "theme_button"):
            self.theme_button.configure(text=f"Theme: {self.theme_mode}")

    # ---------- styling ----------

    def _build_style(self) -> None:
        self.font_ui = ("Helvetica", 10)
        self.font_small = ("Helvetica", 8)
        self.font_body = ("Helvetica", 10)
        self.font_bold = ("Helvetica", 10, "bold")
        self.font_timer = ("Helvetica", 31, "bold")

        style = ttk.Style(self)
        if platform.system() == "Darwin":
            try:
                style.theme_use("aqua")
            except tk.TclError:
                pass
        else:
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.CARD)
        style.configure("SelectedRow.TFrame", background=self.CARD)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=self.font_ui)
        style.configure("Card.TLabel", background=self.CARD, foreground=self.TEXT, font=self.font_ui)
        style.configure("Small.Card.TLabel", background=self.CARD, foreground=self.MUTED, font=self.font_small)
        style.configure("Section.Card.TLabel", background=self.CARD, foreground=self.TEXT, font=("Helvetica", 9, "bold"))
        style.configure("Accent.TButton", font=("Helvetica", 9, "bold"), padding=(11, 4))
        style.configure("Compact.TButton", font=("Helvetica", 9), padding=(7, 3))
        style.configure("Card.TSeparator", background=self.LINE)

    # ---------- UI ----------

    def _card(self, parent: tk.Misc, **kwargs) -> ttk.Frame:
        outer = tk.Frame(parent, bg=self.LINE, bd=0, highlightthickness=0)
        inner = ttk.Frame(outer, style="Card.TFrame", **kwargs)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(10, 9), style="TFrame")
        root.pack(fill="both", expand=True)
        self.root_frame = root
        root.columnconfigure(0, weight=7)
        root.columnconfigure(1, weight=4)
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=2)

        # Top-left: large timer card.
        timer_outer = self._card(root)
        timer_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=(0, 5))
        timer = timer_outer.winfo_children()[0]
        timer.columnconfigure(0, weight=1)
        timer.rowconfigure(1, weight=1)

        top_line = ttk.Frame(timer, style="Card.TFrame")
        top_line.grid(row=0, column=0, sticky="ew", padx=13, pady=(10, 0))
        ttk.Label(top_line, text="POMODORO", style="Section.Card.TLabel").pack(side="left")
        self.status_var = tk.StringVar(value="READY")
        ttk.Label(top_line, textvariable=self.status_var, style="Small.Card.TLabel").pack(side="right")

        main_timer = ttk.Frame(timer, style="Card.TFrame")
        main_timer.grid(row=1, column=0, sticky="nsew", padx=13, pady=(2, 7))
        main_timer.columnconfigure(1, weight=1)

        self.current_block_var = tk.StringVar()
        ttk.Label(main_timer, textvariable=self.current_block_var, style="Small.Card.TLabel").grid(
            row=0, column=0, sticky="sw", padx=(0, 12), pady=(0, 3)
        )
        self.timer_var = tk.StringVar(value="25:00")
        ttk.Label(main_timer, textvariable=self.timer_var, background=self.CARD, foreground=self.TEXT, font=self.font_timer).grid(
            row=1, column=0, sticky="w"
        )
        self.cycle_var = tk.StringVar()
        ttk.Label(main_timer, textvariable=self.cycle_var, style="Small.Card.TLabel").grid(
            row=1, column=1, sticky="sw", pady=(0, 5)
        )

        controls = ttk.Frame(timer, style="Card.TFrame")
        controls.grid(row=2, column=0, sticky="ew", padx=13, pady=(0, 11))
        self.start_button = ttk.Button(controls, text="Start", style="Accent.TButton", command=self._toggle_running)
        self.start_button.pack(side="left")
        ttk.Button(controls, text="Skip", style="Compact.TButton", command=self._skip).pack(side="left", padx=4)
        ttk.Button(controls, text="Reset", style="Compact.TButton", command=self._reset).pack(side="left")

        # Top-right: controls/settings card.
        settings_outer = self._card(root)
        settings_outer.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=(0, 5))
        settings = settings_outer.winfo_children()[0]

        ttk.Label(settings, text="SETTINGS", style="Section.Card.TLabel").pack(anchor="w", padx=12, pady=(10, 7))
        ttk.Separator(settings, orient="horizontal", style="Card.TSeparator").pack(fill="x", padx=12)

        cycle_row = ttk.Frame(settings, style="Card.TFrame")
        cycle_row.pack(fill="x", padx=12, pady=(10, 5))
        ttk.Label(cycle_row, text="Cycles", style="Card.TLabel").pack(side="left")
        self.cycles_spin = tk.Spinbox(
            cycle_row,
            from_=0,
            to=9999,
            width=5,
            font=self.font_body,
            bg=self.ENTRY,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            buttonbackground=self.ENTRY,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.LINE,
            highlightcolor=self.ACCENT,
            justify="center",
        )
        self.cycles_spin.pack(side="right")
        self.cycles_spin.delete(0, "end")
        self.cycles_spin.insert(0, "0")
        self.cycles_spin.bind("<Return>", lambda _e: self._update_cycles())
        self.cycles_spin.bind("<FocusOut>", lambda _e: self._update_cycles())

        ttk.Label(settings, text="0 = repeat forever", style="Small.Card.TLabel").pack(anchor="w", padx=12)

        self.theme_button = ttk.Button(
            settings,
            text=f"Theme: {self.theme_mode}",
            style="Compact.TButton",
            command=self._cycle_theme,
        )
        self.theme_button.pack(anchor="w", padx=12, pady=(12, 5))

        menu_status = "Menu bar enabled" if platform.system() != "Darwin" else (
            "Menu bar enabled" if getattr(self, "menubar", None) and self.menubar.available else "Menu bar needs PyObjC"
        )
        self.menubar_hint = ttk.Label(settings, text=menu_status, style="Small.Card.TLabel")
        self.menubar_hint.pack(anchor="w", padx=12, pady=(0, 4))

        ttk.Label(
            settings,
            text="Edit sequence below. Click a field and type.",
            style="Small.Card.TLabel",
        ).pack(anchor="w", padx=12, pady=(6, 8))

        # Bottom: sequence card.
        seq_outer = self._card(root)
        seq_outer.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(5, 0))
        seq = seq_outer.winfo_children()[0]
        seq.rowconfigure(1, weight=1)
        seq.columnconfigure(0, weight=1)

        seq_head = ttk.Frame(seq, style="Card.TFrame")
        seq_head.grid(row=0, column=0, sticky="ew", padx=11, pady=(8, 5))
        ttk.Label(seq_head, text="SEQUENCE", style="Section.Card.TLabel").pack(side="left")
        actions = ttk.Frame(seq_head, style="Card.TFrame")
        actions.pack(side="right")
        ttk.Button(actions, text="+", width=2, style="Compact.TButton", command=self._add_block).pack(side="left", padx=1)
        ttk.Button(actions, text="−", width=2, style="Compact.TButton", command=self._delete_selected).pack(side="left", padx=1)
        ttk.Button(actions, text="↑", width=2, style="Compact.TButton", command=lambda: self._move_selected(-1)).pack(side="left", padx=1)
        ttk.Button(actions, text="↓", width=2, style="Compact.TButton", command=lambda: self._move_selected(1)).pack(side="left", padx=1)

        self.sequence_frame = ttk.Frame(seq, style="Card.TFrame")
        self.sequence_frame.grid(row=1, column=0, sticky="nsew", padx=11, pady=(0, 9))
        self.sequence_frame.columnconfigure(0, weight=1)

        # A canvas keeps arbitrary sequence lengths compact without imposing a
        # giant blank table on short sequences.
        self.sequence_canvas = tk.Canvas(
            self.sequence_frame,
            bg=self.CARD,
            highlightthickness=0,
            bd=0,
            height=76,
        )
        self.sequence_scrollbar = ttk.Scrollbar(self.sequence_frame, orient="vertical", command=self.sequence_canvas.yview)
        self.sequence_rows = ttk.Frame(self.sequence_canvas, style="Card.TFrame")
        self.sequence_window = self.sequence_canvas.create_window((0, 0), window=self.sequence_rows, anchor="nw")
        self.sequence_canvas.configure(yscrollcommand=self.sequence_scrollbar.set)
        self.sequence_canvas.grid(row=0, column=0, sticky="nsew")
        self.sequence_frame.columnconfigure(0, weight=1)
        self.sequence_frame.rowconfigure(0, weight=1)
        self.sequence_canvas.bind("<Configure>", lambda e: self.sequence_canvas.itemconfigure(self.sequence_window, width=e.width))
        self.sequence_rows.bind("<Configure>", lambda _e: self.sequence_canvas.configure(scrollregion=self.sequence_canvas.bbox("all")))

    # ---------- editor ----------

    @staticmethod
    def _format_minutes(minutes: float) -> str:
        return str(int(minutes)) if float(minutes).is_integer() else f"{minutes:g}"

    def _refresh_editor(self) -> None:
        for child in self.sequence_rows.winfo_children():
            child.destroy()

        header = ttk.Frame(self.sequence_rows, style="Card.TFrame")
        header.pack(fill="x", pady=(0, 2))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="#", style="Small.Card.TLabel", width=3).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Block", style="Small.Card.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Min", style="Small.Card.TLabel", width=5).grid(row=0, column=2, sticky="w", padx=(6, 0))
        for index, block in enumerate(self.blocks):
            self._build_sequence_row(index, block)

    def _build_sequence_row(self, index: int, block: Block) -> None:
        row = ttk.Frame(self.sequence_rows, style="Card.TFrame")
        row.pack(fill="x", pady=1)
        row.columnconfigure(1, weight=1)

        def select_row(_event=None) -> None:
            self.selected_index = index
            self._refresh_editor_selection()

        ttk.Label(row, text=str(index + 1), style="Small.Card.TLabel", width=3).grid(row=0, column=0, sticky="w")
        name_var = tk.StringVar(value=block.name)
        name_entry = tk.Entry(
            row,
            textvariable=name_var,
            font=self.font_body,
            bg=self.ENTRY,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.LINE,
            highlightcolor=self.ACCENT,
        )
        name_entry.grid(row=0, column=1, sticky="ew", ipady=2)
        mins_var = tk.StringVar(value=self._format_minutes(block.minutes))
        mins_entry = tk.Entry(
            row,
            textvariable=mins_var,
            width=6,
            font=self.font_body,
            bg=self.ENTRY,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.LINE,
            highlightcolor=self.ACCENT,
            justify="center",
        )
        mins_entry.grid(row=0, column=2, sticky="w", padx=(6, 0), ipady=2)

        def save_name(_event=None) -> None:
            value = name_var.get().strip()
            if value:
                block.name = value
                self._refresh_timer()
            else:
                name_var.set(block.name)

        def save_minutes(_event=None) -> None:
            try:
                value = float(mins_var.get().strip())
            except ValueError:
                mins_var.set(self._format_minutes(block.minutes))
                return
            if not 0 < value <= 24 * 60:
                mins_var.set(self._format_minutes(block.minutes))
                return
            block.minutes = value
            if index == self.block_index and not self.running:
                self.remaining = block.seconds
            self._refresh_timer()

        name_entry.bind("<FocusOut>", save_name)
        name_entry.bind("<Return>", save_name)
        mins_entry.bind("<FocusOut>", save_minutes)
        mins_entry.bind("<Return>", save_minutes)
        name_entry.bind("<Button-1>", select_row, add="+")
        mins_entry.bind("<Button-1>", select_row, add="+")
        row.bind("<Button-1>", select_row, add="+")
        row._sequence_index = index  # type: ignore[attr-defined]

    def _refresh_editor_selection(self) -> None:
        rows = self.sequence_rows.winfo_children()[1:]
        for index, row in enumerate(rows):
            bg = self.ACCENT if index == self.selected_index else self.CARD
            try:
                row.configure(style="SelectedRow.TFrame" if index == self.selected_index else "Card.TFrame")
            except tk.TclError:
                pass
            for child in row.winfo_children():
                if isinstance(child, ttk.Label):
                    try:
                        child.configure(background=bg)
                    except tk.TclError:
                        pass

    def _get_selected_index(self) -> Optional[int]:
        if self.selected_index is None:
            return None
        if 0 <= self.selected_index < len(self.blocks):
            return self.selected_index
        return None

    def _add_block(self) -> None:
        index = self._get_selected_index()
        insert_at = len(self.blocks) if index is None else index + 1
        self.blocks.insert(insert_at, Block("New block", 25))
        self.selected_index = insert_at
        self._refresh_editor()
        self._keep_timer_valid()

    def _delete_selected(self) -> None:
        index = self._get_selected_index()
        if index is None:
            return
        # One block is still the minimum valid timer sequence; two, one, etc. are all allowed.
        if len(self.blocks) <= 1:
            return
        del self.blocks[index]
        if index < self.block_index:
            self.block_index -= 1
        elif index == self.block_index:
            self.block_index = min(self.block_index, len(self.blocks) - 1)
            if not self.running:
                self.remaining = self.blocks[self.block_index].seconds
        self.selected_index = min(index, len(self.blocks) - 1)
        self._keep_timer_valid()
        self._refresh_editor()
        self._refresh_timer()

    def _move_selected(self, direction: int) -> None:
        index = self._get_selected_index()
        if index is None:
            return
        new_index = index + direction
        if not 0 <= new_index < len(self.blocks):
            return

        current = self.blocks[self.block_index]
        self.blocks[index], self.blocks[new_index] = self.blocks[new_index], self.blocks[index]
        self.block_index = self.blocks.index(current)
        self.selected_index = new_index
        self._refresh_editor()
        self._refresh_timer()

    def _keep_timer_valid(self) -> None:
        if not self.blocks:
            self.blocks.append(Block("Work", 25))
        self.block_index = max(0, min(self.block_index, len(self.blocks) - 1))
        if self.selected_index is not None:
            self.selected_index = max(0, min(self.selected_index, len(self.blocks) - 1))
        if self.remaining <= 0:
            self.remaining = self.blocks[self.block_index].seconds

    # ---------- menubar ----------

    def open_app(self) -> None:
        self.deiconify()
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def toggle_running(self) -> None:
        self._toggle_running()

    def skip(self) -> None:
        self._skip()

    def reset(self) -> None:
        self._reset()

    def close_app(self) -> None:
        self._on_close()

    # ---------- timer ----------

    def _toggle_running(self) -> None:
        if not self.running and self.remaining <= 0:
            self.cycle_number = 1
            self.block_index = 0
            self.remaining = self.blocks[0].seconds

        if self.running:
            self.running = False
            self.status_var.set("PAUSED")
            self.start_button.configure(text="Resume")
            self._last_tick = time.monotonic()
        else:
            self.running = True
            self._last_tick = time.monotonic()
            self.status_var.set("RUNNING")
            self.start_button.configure(text="Pause")
            NotificationManager.send(APP_TITLE, f"Started: {self.blocks[self.block_index].name}")

    def _skip(self) -> None:
        self._advance("Skipped")

    def _reset(self) -> None:
        self.running = False
        self.cycle_number = 1
        self.block_index = 0
        self.remaining = self.blocks[0].seconds
        self.status_var.set("READY")
        self.start_button.configure(text="Start")
        self._refresh_timer()

    def _advance(self, reason: str = "Completed") -> None:
        old = self.blocks[self.block_index]
        NotificationManager.send(APP_TITLE, f"{old.name} {reason.lower()}.")

        next_index = self.block_index + 1
        if next_index < len(self.blocks):
            self.block_index = next_index
        else:
            if self.cycles_total > 0 and self.cycle_number >= self.cycles_total:
                self.running = False
                self.remaining = 0
                self.status_var.set("FINISHED")
                self.start_button.configure(text="Start")
                NotificationManager.send(APP_TITLE, f"Sequence complete: {self.cycles_total} cycle(s).")
                self._refresh_timer()
                return
            self.cycle_number += 1
            self.block_index = 0

        new = self.blocks[self.block_index]
        self.remaining = new.seconds
        self._last_tick = time.monotonic()
        self._refresh_timer()
        NotificationManager.send(APP_TITLE, f"Next: {new.name} ({self._format_minutes(new.minutes)} min)")

    def _schedule_tick(self) -> None:
        self._after_id = self.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        if self.running:
            now = time.monotonic()
            elapsed = now - self._last_tick
            self._last_tick = now
            self.remaining -= elapsed

            while self.remaining <= 0 and self.running:
                overshoot = -self.remaining
                self._advance()
                if self.running:
                    self.remaining -= overshoot
            self._refresh_timer()
        self._schedule_tick()

    def _refresh_timer(self) -> None:
        block = self.blocks[self.block_index]
        shown = max(0.0, self.remaining)
        total = int(shown + 0.999999)
        hours, rem = divmod(total, 3600)
        mins, secs = divmod(rem, 60)
        text = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"
        self.current_block_var.set(block.name)
        self.timer_var.set(text)
        if self.cycles_total:
            self.cycle_var.set(f"Cycle {min(self.cycle_number, self.cycles_total)} / {self.cycles_total}")
        else:
            self.cycle_var.set(f"Cycle {self.cycle_number} / ∞")
        if getattr(self, "menubar", None):
            self.menubar.update()

    def _update_cycles(self) -> None:
        try:
            value = int(self.cycles_spin.get())
        except ValueError:
            value = 0
        self.cycles_total = max(0, min(value, 9999))
        self._refresh_timer()

    def _on_close(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        if getattr(self, "menubar", None):
            self.menubar.destroy()
        self.destroy()


if __name__ == "__main__":
    PomodoroApp().mainloop()
