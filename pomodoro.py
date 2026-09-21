#!/usr/bin/env python3
"""Simple cross-platform Pomodoro / focus-sequence timer.

Single-file Tkinter application. Designed first for macOS 10.15+, while also
supporting Windows and Linux notifications.

Features:
- Arbitrary sequence of named blocks (e.g. Work 1 -> Work 2 -> Break)
- Each block has its own duration in minutes
- Sequence repeats for a configurable number of cycles, or indefinitely
- Add/remove/reorder blocks
- Start, pause, resume, skip, and reset
- Native notifications where practical
- No third-party packages required

Python 3.8+ recommended. Tkinter must be installed with the Python build.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import List, Optional


APP_TITLE = "Pomodoro Sequence"
TICK_MS = 200


@dataclass
class Block:
    name: str
    minutes: float

    @property
    def seconds(self) -> float:
        return max(1.0, self.minutes * 60.0)


class NotificationManager:
    """Small cross-platform notification wrapper with no dependencies."""

    @staticmethod
    def send(title: str, body: str) -> None:
        system = platform.system()

        try:
            if system == "Darwin":
                # AppleScript is available on macOS 10.15+ and gives us a
                # native Notification Center banner without third-party libs.
                script = (
                    'display notification '
                    f'{NotificationManager._quote_applescript(body)} '
                    'with title '
                    f'{NotificationManager._quote_applescript(title)}'
                )
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return

            if system == "Windows":
                # PowerShell fallback. This uses the Windows toast API through
                # a tiny in-process PowerShell script and requires no package.
                ps = (
                    '[Windows.UI.Notifications.ToastNotificationManager, '
                    'Windows.UI.Notifications, ContentType = WindowsRuntime]; '
                    '[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, '
                    'ContentType = WindowsRuntime]; '
                    f'$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; '
                    f'$xml.LoadXml(\'<toast><visual><binding template="ToastGeneric">'
                    f'<text>{NotificationManager._xml_escape(title)}</text>'
                    f'<text>{NotificationManager._xml_escape(body)}</text>'
                    f'</binding></visual></toast>\'); '
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

            # Linux / other Unix-like systems: use notify-send when present.
            notify_send = None
            for candidate in ("notify-send",):
                try:
                    subprocess.run(
                        [candidate, "--version"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1,
                        check=False,
                    )
                    notify_send = candidate
                    break
                except (FileNotFoundError, OSError):
                    pass

            if notify_send:
                subprocess.Popen(
                    [notify_send, title, body],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
        except Exception:
            # Notifications are a convenience, never a reason for the timer
            # itself to crash.
            pass

    @staticmethod
    def _quote_applescript(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _xml_escape(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )


class PomodoroApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(720, 540)
        self.geometry("820x650")
        self.configure(padx=18, pady=18)

        # The sequence shown in the editor is the source of truth.
        self.blocks: List[Block] = [
            Block("Work 1", 25),
            Block("Work 2", 25),
            Block("Break", 5),
        ]
        self.cycles_total = 0  # 0 = infinite
        self.cycle_number = 1
        self.block_index = 0
        self.remaining = self.blocks[0].seconds
        self.running = False
        self._last_tick = time.monotonic()
        self._after_id: Optional[str] = None
        self._last_completed_label = ""
        self._editing = False

        self._build_style()
        self._build_ui()
        self._refresh_editor()
        self._refresh_timer()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_tick()

    # ---------- UI ----------

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Title.TLabel", font=("Helvetica", 22, "bold"))
        style.configure("Block.TLabel", font=("Helvetica", 16, "bold"))
        style.configure("Timer.TLabel", font=("Helvetica", 62, "bold"))
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Primary.TButton", font=("Helvetica", 11, "bold"))
        style.configure("Treeview", rowheight=30, font=("Helvetica", 11))
        style.configure("Treeview.Heading", font=("Helvetica", 10, "bold"))

    def _build_ui(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="Pomodoro Sequence", style="Title.TLabel").pack(side="left")

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(header, textvariable=self.status_var, style="Muted.TLabel").pack(side="right", pady=6)

        timer_card = ttk.Frame(self, padding=(18, 16))
        timer_card.pack(fill="x", pady=(0, 18))

        self.current_block_var = tk.StringVar()
        ttk.Label(timer_card, textvariable=self.current_block_var, style="Block.TLabel").pack()

        self.timer_var = tk.StringVar(value="25:00")
        ttk.Label(timer_card, textvariable=self.timer_var, style="Timer.TLabel").pack(pady=(6, 4))

        self.cycle_var = tk.StringVar()
        ttk.Label(timer_card, textvariable=self.cycle_var, style="Muted.TLabel").pack()

        buttons = ttk.Frame(timer_card)
        buttons.pack(pady=(14, 2))
        self.start_button = ttk.Button(buttons, text="Start", style="Primary.TButton", command=self._toggle_running)
        self.start_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Skip", command=self._skip).pack(side="left", padx=4)
        ttk.Button(buttons, text="Reset", command=self._reset).pack(side="left", padx=4)

        editor = ttk.LabelFrame(self, text="Sequence", padding=12)
        editor.pack(fill="both", expand=True)

        # The editor is a real set of widgets rather than a Treeview, so each
        # block can be changed directly in the main window.
        self.sequence_frame = ttk.Frame(editor)
        self.sequence_frame.pack(side="left", fill="both", expand=True)

        self.sequence_canvas = tk.Canvas(self.sequence_frame, highlightthickness=0, borderwidth=0)
        self.sequence_scrollbar = ttk.Scrollbar(
            self.sequence_frame, orient="vertical", command=self.sequence_canvas.yview
        )
        self.sequence_rows = ttk.Frame(self.sequence_canvas)
        self.sequence_window = self.sequence_canvas.create_window(
            (0, 0), window=self.sequence_rows, anchor="nw"
        )
        self.sequence_canvas.configure(yscrollcommand=self.sequence_scrollbar.set)
        self.sequence_canvas.pack(side="left", fill="both", expand=True)
        self.sequence_scrollbar.pack(side="right", fill="y")
        self.sequence_rows.bind(
            "<Configure>",
            lambda _e: self.sequence_canvas.configure(scrollregion=self.sequence_canvas.bbox("all")),
        )
        self.sequence_canvas.bind(
            "<Configure>",
            lambda e: self.sequence_canvas.itemconfigure(self.sequence_window, width=e.width),
        )

        controls = ttk.Frame(editor)
        controls.pack(side="right", fill="y", padx=(12, 0))

        ttk.Button(controls, text="Add", command=self._add_block).pack(fill="x", pady=2)
        ttk.Button(controls, text="Delete", command=self._delete_selected).pack(fill="x", pady=2)
        ttk.Separator(controls).pack(fill="x", pady=7)
        ttk.Button(controls, text="Move ↑", command=lambda: self._move_selected(-1)).pack(fill="x", pady=2)
        ttk.Button(controls, text="Move ↓", command=lambda: self._move_selected(1)).pack(fill="x", pady=2)

        settings = ttk.Frame(self)
        settings.pack(fill="x", pady=(14, 0))

        ttk.Label(settings, text="Cycles:").pack(side="left")
        self.cycles_spin = tk.Spinbox(settings, from_=0, to=9999, width=7, command=self._update_cycles)
        self.cycles_spin.pack(side="left", padx=(7, 4))
        self.cycles_spin.delete(0, "end")
        self.cycles_spin.insert(0, "0")
        self.cycles_spin.bind("<Return>", lambda _e: self._update_cycles())
        self.cycles_spin.bind("<FocusOut>", lambda _e: self._update_cycles())
        ttk.Label(settings, text="0 = repeat forever", style="Muted.TLabel").pack(side="left")

        ttk.Label(settings, text="Edits save when you leave a field.", style="Muted.TLabel").pack(side="right")

    # ---------- Sequence editor ----------

    def _refresh_editor(self) -> None:
        for child in self.sequence_rows.winfo_children():
            child.destroy()

        header = ttk.Frame(self.sequence_rows)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Block", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Minutes", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        header.columnconfigure(0, weight=1)

        for index, block in enumerate(self.blocks):
            self._build_sequence_row(index, block)

    @staticmethod
    def _format_minutes(minutes: float) -> str:
        if float(minutes).is_integer():
            return str(int(minutes))
        return f"{minutes:g}"

    def _build_sequence_row(self, index: int, block: Block) -> None:
        row = ttk.Frame(self.sequence_rows)
        row.pack(fill="x", pady=2)
        row.columnconfigure(0, weight=1)

        position = ttk.Label(row, text=f"{index + 1}.", width=4, anchor="e")
        position.grid(row=0, column=0, sticky="w")

        name_var = tk.StringVar(value=block.name)
        name_entry = ttk.Entry(row, textvariable=name_var)
        name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))

        minutes_var = tk.StringVar(value=self._format_minutes(block.minutes))
        minutes_entry = ttk.Entry(row, textvariable=minutes_var, width=10)
        minutes_entry.grid(row=0, column=2, sticky="w")

        def save_name(_event=None) -> None:
            name = name_var.get().strip()
            if not name:
                name_var.set(block.name)
                return
            if name != block.name:
                self.blocks[index] = Block(name, block.minutes)
                block.name = name
                self._refresh_timer()

        def save_minutes(_event=None) -> None:
            try:
                minutes = float(minutes_var.get().strip())
            except ValueError:
                minutes_var.set(self._format_minutes(block.minutes))
                return
            if not 0 < minutes <= 24 * 60:
                minutes_var.set(self._format_minutes(block.minutes))
                return
            if minutes != block.minutes:
                self.blocks[index] = Block(block.name, minutes)
                block.minutes = minutes
                if index == self.block_index and not self.running:
                    self.remaining = block.seconds
                    self._refresh_timer()

        name_entry.bind("<FocusOut>", save_name)
        name_entry.bind("<Return>", save_name)
        minutes_entry.bind("<FocusOut>", save_minutes)
        minutes_entry.bind("<Return>", save_minutes)

    def _get_selected_index(self) -> Optional[int]:
        # Keep selection semantics for the buttons, using the row under focus.
        focused = self.focus_get()
        if focused is None:
            return None
        for index, row in enumerate(self.sequence_rows.winfo_children()[1:]):
            if self._widget_contains(row, focused):
                return index
        return None

    @staticmethod
    def _widget_contains(parent, widget) -> bool:
        current = widget
        while current is not None:
            if current == parent:
                return True
            current = current.master
        return False

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
        if not (0 <= new_index < len(self.blocks)):
            return

        self.blocks[index], self.blocks[new_index] = self.blocks[new_index], self.blocks[index]

        current = self._current_block_object()
        try:
            self.block_index = self.blocks.index(current)
        except ValueError:
            self.block_index = 0

        self._refresh_editor()
        self._refresh_timer()

    def _current_block_object(self) -> Block:
        if not self.blocks:
            self.blocks.append(Block("Work", 25))
        self.block_index = max(0, min(self.block_index, len(self.blocks) - 1))
        return self.blocks[self.block_index]

    def _keep_timer_valid(self) -> None:
        if not self.blocks:
            self.blocks.append(Block("Work", 25))
        self.block_index = max(0, min(self.block_index, len(self.blocks) - 1))
        if self.remaining <= 0:
            self.remaining = self._current_block_object().seconds

    # ---------- Timer ----------

    def _toggle_running(self) -> None:
        # Starting after a completed sequence begins a fresh run.
        if not self.running and self.remaining <= 0:
            self.cycle_number = 1
            self.block_index = 0
            self.remaining = self.blocks[0].seconds

        if self.running:
            self.running = False
            self.status_var.set("Paused")
            self.start_button.configure(text="Resume")
            self._last_tick = time.monotonic()
        else:
            self.running = True
            self._last_tick = time.monotonic()
            self.status_var.set("Running")
            self.start_button.configure(text="Pause")
            NotificationManager.send(
                APP_TITLE,
                f"Started: {self._current_block_object().name}",
            )

    def _skip(self) -> None:
        self._advance("Skipped")

    def _reset(self) -> None:
        self.running = False
        self.cycle_number = 1
        self.block_index = 0
        self.remaining = self.blocks[0].seconds
        self.status_var.set("Ready")
        self.start_button.configure(text="Start")
        self._refresh_timer()

    def _advance(self, reason: str = "Completed") -> None:
        old_block = self._current_block_object()
        NotificationManager.send(
            APP_TITLE,
            f"{old_block.name} {reason.lower()}.",
        )

        next_index = self.block_index + 1
        if next_index < len(self.blocks):
            self.block_index = next_index
        else:
            if self.cycles_total > 0 and self.cycle_number >= self.cycles_total:
                self.running = False
                self.status_var.set("Finished")
                self.start_button.configure(text="Start")
                self.remaining = 0
                NotificationManager.send(
                    APP_TITLE,
                    f"Sequence complete: {self.cycles_total} cycle(s).",
                )
                self._refresh_timer()
                return
            self.cycle_number += 1
            self.block_index = 0

        new_block = self._current_block_object()
        self.remaining = new_block.seconds
        self._last_tick = time.monotonic()
        self.status_var.set("Running" if self.running else "Ready")
        self._refresh_timer()
        NotificationManager.send(
            APP_TITLE,
            f"Next: {new_block.name} ({self._format_minutes(new_block.minutes)} min)",
        )

    def _schedule_tick(self) -> None:
        self._after_id = self.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        if self.running:
            now = time.monotonic()
            elapsed = now - self._last_tick
            self._last_tick = now
            self.remaining -= elapsed

            # Use a loop so that a badly delayed/suspended app cannot leave the
            # timer stuck in an already-finished block.
            while self.remaining <= 0 and self.running:
                overshoot = -self.remaining
                self._advance()
                if self.running:
                    self.remaining -= overshoot

            self._refresh_timer()

        self._schedule_tick()

    def _refresh_timer(self) -> None:
        block = self._current_block_object()
        shown = max(0, self.remaining)
        total_seconds = int(shown + 0.999999)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            timer_text = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            timer_text = f"{minutes:02d}:{seconds:02d}"

        self.current_block_var.set(block.name)
        self.timer_var.set(timer_text)

        if self.cycles_total:
            self.cycle_var.set(f"Cycle {min(self.cycle_number, self.cycles_total)} of {self.cycles_total}")
        else:
            self.cycle_var.set(f"Cycle {self.cycle_number} • repeating forever")

    def _update_cycles(self) -> None:
        try:
            value = int(self.cycles_spin.get())
        except ValueError:
            value = 0
        self.cycles_total = max(0, min(value, 9999))
        self._refresh_timer()

    # ---------- Lifecycle ----------

    def _on_close(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self.destroy()


if __name__ == "__main__":
    app = PomodoroApp()
    app.mainloop()
