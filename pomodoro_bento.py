#!/usr/bin/env python3
"""Compact cross-platform Pomodoro sequence timer.

Single-file Tkinter app, designed for macOS 10.15+ first, with notifications
for macOS, Windows, and Linux. No third-party packages required.
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

# Minimal Swiss-ish palette. Adapt to the macOS appearance so the UI does
# not end up with the classic "dark window + random white rectangle" problem.
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


DARK_MODE = _system_is_dark()

if DARK_MODE:
    BG = "#1d1d1f"
    CARD = "#272729"
    ENTRY = "#353537"
    TEXT = "#f2f2f2"
    MUTED = "#a5a5aa"
    LINE = "#55555a"
    ACCENT = "#e05a4f"
    ACCENT_DARK = "#c94c43"
else:
    BG = "#f2f2ef"
    CARD = "#ffffff"
    ENTRY = "#ffffff"
    TEXT = "#111111"
    MUTED = "#6f6f6a"
    LINE = "#d8d8d2"
    ACCENT = "#d94b3d"
    ACCENT_DARK = "#b93e32"


@dataclass
class Block:
    name: str
    minutes: float

    @property
    def seconds(self) -> float:
        return max(1.0, self.minutes * 60.0)


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
        self.configure(bg=BG)

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

        self._build_style()
        self._build_ui()
        self._refresh_editor()
        self._refresh_timer()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_tick()

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

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=self.font_ui)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=self.font_ui)
        style.configure("Small.Card.TLabel", background=CARD, foreground=MUTED, font=self.font_small)
        style.configure("Section.Card.TLabel", background=CARD, foreground=TEXT, font=("Helvetica", 9, "bold"))
        style.configure("Accent.TButton", font=("Helvetica", 9, "bold"), padding=(11, 4))
        style.configure("Compact.TButton", font=("Helvetica", 9), padding=(7, 3))
        style.configure("Card.TSeparator", background=LINE)

    # ---------- UI ----------

    def _card(self, parent: tk.Misc, **kwargs) -> ttk.Frame:
        outer = tk.Frame(parent, bg=LINE, bd=0, highlightthickness=0)
        inner = ttk.Frame(outer, style="Card.TFrame", **kwargs)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(10, 9), style="TFrame")
        root.pack(fill="both", expand=True)
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
        ttk.Label(main_timer, textvariable=self.timer_var, background=CARD, foreground=TEXT, font=self.font_timer).grid(
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
            bg=ENTRY,
            fg=TEXT,
            insertbackground=TEXT,
            buttonbackground=ENTRY,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
            justify="center",
        )
        self.cycles_spin.pack(side="right")
        self.cycles_spin.delete(0, "end")
        self.cycles_spin.insert(0, "0")
        self.cycles_spin.bind("<Return>", lambda _e: self._update_cycles())
        self.cycles_spin.bind("<FocusOut>", lambda _e: self._update_cycles())

        ttk.Label(settings, text="0 = repeat forever", style="Small.Card.TLabel").pack(anchor="w", padx=12)

        ttk.Label(
            settings,
            text="Edit sequence below.\nClick a field and type.",
            style="Small.Card.TLabel",
        ).pack(anchor="w", padx=12, pady=(22, 8))

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
            bg=CARD,
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

        ttk.Label(row, text=str(index + 1), style="Small.Card.TLabel", width=3).grid(row=0, column=0, sticky="w")
        name_var = tk.StringVar(value=block.name)
        name_entry = tk.Entry(
            row,
            textvariable=name_var,
            font=self.font_body,
            bg=ENTRY,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
        )
        name_entry.grid(row=0, column=1, sticky="ew", ipady=2)
        mins_var = tk.StringVar(value=self._format_minutes(block.minutes))
        mins_entry = tk.Entry(
            row,
            textvariable=mins_var,
            width=6,
            font=self.font_body,
            bg=ENTRY,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
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

    def _get_selected_index(self) -> Optional[int]:
        focused = self.focus_get()
        if focused is None:
            return None
        rows = self.sequence_rows.winfo_children()[1:]
        for index, row in enumerate(rows):
            current = focused
            while current is not None:
                if current == row:
                    return index
                current = current.master
        return None

    def _add_block(self) -> None:
        index = self._get_selected_index()
        insert_at = len(self.blocks) if index is None else index + 1
        self.blocks.insert(insert_at, Block("New block", 25))
        self._refresh_editor()
        self._keep_timer_valid()

    def _delete_selected(self) -> None:
        index = self._get_selected_index()
        if index is None:
            return
        if len(self.blocks) == 1:
            messagebox.showinfo(APP_TITLE, "Keep at least one block in the sequence.")
            return
        del self.blocks[index]
        if index < self.block_index:
            self.block_index -= 1
        elif index == self.block_index:
            self.block_index = min(self.block_index, len(self.blocks) - 1)
            if not self.running:
                self.remaining = self.blocks[self.block_index].seconds
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
        self._refresh_editor()
        self._refresh_timer()

    def _keep_timer_valid(self) -> None:
        if not self.blocks:
            self.blocks.append(Block("Work", 25))
        self.block_index = max(0, min(self.block_index, len(self.blocks) - 1))
        if self.remaining <= 0:
            self.remaining = self.blocks[self.block_index].seconds

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
        self.destroy()


if __name__ == "__main__":
    PomodoroApp().mainloop()
