"""Standalone USB chat window. Copy this folder next to the GGUFs."""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import committee
import formatter
import jobapp
import profiledoc
import usbchat


def _clock_label(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _elapsed_words(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts: list[str] = []
    if hours:
        parts.append("1 hr" if hours == 1 else f"{hours} hrs")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} sec")
    return ", ".join(parts)


def _turn_elapsed_seconds(turn: dict) -> int | None:
    """Seconds from the stored send time to the stored reply time."""
    started = turn.get("started")
    finished = turn.get("time")
    if isinstance(started, str) and isinstance(finished, str):
        try:
            begin = datetime.fromisoformat(started)
            end = datetime.fromisoformat(finished)
        except ValueError:
            begin = end = None
        if begin is not None and end is not None:
            return max(0, int((end - begin).total_seconds()))
    raw = turn.get("elapsed_s")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0, int(raw))
    return None


CHAT_PAGE = "#f7f7f7"
CHAT_WELL = "#ffffff"
CHAT_BUBBLE = "#e8eaed"
CHAT_LINE = "#d8dce3"


class _HoverTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip,
            text=self.text,
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=3,
            font=("Segoe UI", 9) if sys.platform == "win32" else ("sans-serif", 9),
        ).pack()
        self.tip = tip

    def _hide(self, _event=None) -> None:
        if self.tip is None:
            return
        self.tip.destroy()
        self.tip = None


class _ModelPicker(tk.Frame):
    """Closed row is the model name and size. Open rows add job tags in a smaller gray line."""

    _NAME = "#202124"
    _TAG = "#5f6368"
    _LINE = "#d8dce3"
    _FACE = "#ffffff"
    _HOVER = "#f1f3f4"
    _PICK = "#e8f0fe"

    def __init__(self, master, variable: tk.StringVar, font: tuple) -> None:
        super().__init__(master, bg=CHAT_PAGE)
        self.var = variable
        self.font = font
        self._tag_font = (font[0], 9)
        self.choices: list[usbchat.ModelChoice] = []
        self._popup: tk.Toplevel | None = None
        self._ignore = False
        self.face = tk.Frame(
            self,
            bg=self._FACE,
            highlightthickness=1,
            highlightbackground=self._LINE,
            cursor="hand2",
        )
        self.face.pack(fill="x", expand=True)
        self._text = tk.Frame(self.face, bg=self._FACE, cursor="hand2")
        self._text.pack(side="left", fill="x", expand=True)
        self._name = tk.Label(
            self._text,
            text="",
            bg=self._FACE,
            fg=self._NAME,
            font=self.font,
            anchor="w",
        )
        self._name.pack(fill="x", padx=(10, 4), pady=5)
        self._arrow = tk.Label(
            self.face,
            text="▾",
            bg=self._FACE,
            fg=self._TAG,
            font=self.font,
            cursor="hand2",
        )
        self._arrow.pack(side="right", padx=(0, 8))
        for widget in (self.face, self._text, self._name, self._arrow):
            widget.bind("<Button-1>", self._on_face)

    def set_choices(self, choices: list[usbchat.ModelChoice]) -> None:
        self.choices = list(choices)
        self._paint_closed()

    def dismiss_from(self, widget) -> None:
        if self._ignore or self._popup is None:
            return
        if self._contains(widget):
            return
        self.close()

    def close(self) -> None:
        if self._popup is not None:
            self._popup.destroy()
            self._popup = None

    def _on_face(self, _event=None) -> None:
        self._ignore = True
        if self._popup is None:
            self._open()
        else:
            self.close()
        self.after(80, self._clear_ignore)

    def _clear_ignore(self) -> None:
        self._ignore = False

    def _paint_closed(self) -> None:
        choice = self._current()
        self._name.configure(text=choice.label if choice is not None else "No model fits")

    def _current(self) -> usbchat.ModelChoice | None:
        label = self.var.get()
        for choice in self.choices:
            if choice.label == label:
                return choice
        return self.choices[0] if self.choices else None

    def _open(self) -> None:
        if not self.choices:
            return
        self.close()
        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=self._LINE)
        self._popup = popup
        width = max(self.winfo_width(), 280)
        inner = tk.Frame(popup, bg=self._FACE)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        for choice in self.choices:
            self._add_row(inner, choice, choice.label == self.var.get())
        popup.update_idletasks()
        height = inner.winfo_reqheight() + 2
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        if y + height > self.winfo_screenheight() - 8:
            y = max(0, self.winfo_rooty() - height)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.bind("<Escape>", lambda _e: self.close())

    def _add_row(self, parent, choice: usbchat.ModelChoice, selected: bool) -> None:
        bg = self._PICK if selected else self._FACE
        row = tk.Frame(parent, bg=bg, cursor="hand2")
        row.pack(fill="x")
        name = tk.Label(row, text=choice.label, bg=bg, fg=self._NAME, font=self.font, anchor="w", cursor="hand2")
        name.pack(fill="x", padx=(10, 8), pady=(6, 1 if choice.tags else 6))
        tags = tk.Label(row, text="", bg=bg, fg=self._TAG, font=self._tag_font, anchor="w", cursor="hand2")
        if choice.tags:
            tags.configure(text=", ".join(choice.tags))
            tags.pack(fill="x", padx=(18, 8), pady=(0, 6))
        widgets = (row, name, tags) if choice.tags else (row, name)

        def paint(color: str) -> None:
            row.configure(bg=color)
            name.configure(bg=color)
            tags.configure(bg=color)

        def enter(_event=None) -> None:
            paint(self._HOVER if not selected else self._PICK)

        def leave(_event=None) -> None:
            paint(bg)

        def choose(_event=None) -> None:
            self.select(choice.label)
            self.close()

        for widget in widgets:
            widget.bind("<Enter>", enter)
            widget.bind("<Leave>", leave)
            widget.bind("<Button-1>", choose)

    def select(self, label: str) -> None:
        self.var.set(label)
        self._paint_closed()

    def _contains(self, widget) -> bool:
        while widget is not None:
            if widget in (self, self.face, self._popup):
                return True
            widget = getattr(widget, "master", None)
        return False


class UsbChatApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.models_root = Path(args.models).resolve() if args.models else usbchat.default_models_root(HERE)
        self.data_root = usbchat.usb_root(self.models_root, HERE)
        try:
            usbchat.ensure_stick_dirs(self.data_root)
        except OSError:
            pass
        self.log_root = usbchat.logs_dir(self.data_root)
        self.board_name = str(getattr(args, "memory_board", "") or "").strip()
        self.notes_file = usbchat.notes_path(self.data_root)
        self.profile_file = usbchat.profile_path(self.data_root)
        self.profile_json = profiledoc.profile_json_path(self.data_root)
        self.n_ctx = args.n_ctx

        self.choices: list[usbchat.ModelChoice] = []
        self.engine = None
        self.loaded_path: Path | None = None
        self.busy = False
        self.stop_event = threading.Event()
        if self.board_name:
            self.session_path = usbchat.open_named_session(self.log_root, self.board_name)
        else:
            self.session_path = usbchat.new_session_path(self.log_root)
        self.memory = usbchat.load_board(self.session_path)
        self.session_turns: list[dict] = []
        self.older_turns: list[dict] = []
        self.older_files: list[Path] = []
        self.loading_older = False
        self._pin_bottom = False
        self._step = ""
        self._step_chars = 0
        self._step_got_text = False
        self._step_tick = 0
        self._step_after: str | None = None
        self._clock_after: str | None = None
        self._turn_started = 0.0
        self._turn_started_at = ""
        self.attach_truncated = False
        self._doc_resume: dict | None = None
        self.quote = ""
        self.attachment: dict | None = None
        self.attach_dir: Path | None = None
        self.attach_files: list[Path] = []
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.messages: list[tuple[str, str]] = []
        self._history_empty = True
        self._end_of_history = False
        self._input_hint = True
        self._stream_holder: dict | None = None
        self._ui_font = ("Segoe UI", 11) if sys.platform == "win32" else ("sans-serif", 11)
        self._title_font = (self._ui_font[0], 11, "bold")
        self.web_visible = False
        self.coding_var = tk.BooleanVar(value=False)
        self.job_var = tk.BooleanVar(value=False)
        self.update_var = tk.BooleanVar(value=False)
        self._profile_turn: dict | None = None
        self._profile_window = None
        self.github_var = tk.StringVar(value="")
        self.seed_dir: Path | None = None
        self.seed_var = tk.StringVar(value="No project folder")
        self._turn_prompt_tokens = 0
        self._turn_completion_tokens = 0
        self._spin_angle = 0
        self._spin_after: str | None = None

        usbchat.purge_old_logs(self.log_root)
        self._build()
        if self.board_name:
            self.root.title(f"USB chat — {self.board_name}")
            self._load_named_history()
        self.refresh_models()
        if self.board_name:
            self._status(f"Test board {self.board_name}  ·  models {self.models_root}")
        else:
            self._status(
                f"Session {self.session_path.name}  ·  models {self.models_root}  ·  notes {self.notes_file.name}"
            )

    def _build(self) -> None:
        self.root.title("USB chat")
        self.root.geometry("920x700")
        self.root.minsize(420, 360)
        self._page_bg = CHAT_PAGE
        self._bubble_bg = CHAT_BUBBLE
        self.root.configure(bg=CHAT_PAGE)

        pad, gap = 16, 8
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = tk.Frame(self.root, bg=CHAT_PAGE)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0, bg=CHAT_PAGE)
        page_scroll = ttk.Scrollbar(shell, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=page_scroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        page_scroll.grid(row=0, column=1, sticky="ns")

        self._page = tk.Frame(self._canvas, bg=CHAT_PAGE)
        self._page_id = self._canvas.create_window((0, 0), window=self._page, anchor="nw")
        self._page.columnconfigure(0, weight=1)
        self._page.rowconfigure(2, weight=1)

        top = tk.Frame(self._page, bg=CHAT_PAGE)
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(12, gap))
        tk.Label(top, text="Model", bg=CHAT_PAGE, fg="#202124", font=self._ui_font).pack(side="left")
        self.model_var = tk.StringVar()
        self.model_box = _ModelPicker(top, self.model_var, self._ui_font)
        self.model_box.pack(side="left", padx=(gap, gap), fill="x", expand=True)
        self.root.bind_all("<Button-1>", self._dismiss_model_menu, add="+")
        self._pill(top, "Reload", self.refresh_models).pack(side="left")

        tk.Label(self._page, text="History", bg=CHAT_PAGE, fg="#202124", font=self._title_font).grid(
            row=1, column=0, sticky="w", padx=pad, pady=(12, 6)
        )

        mid = tk.Frame(self._page, bg=CHAT_PAGE)
        mid.grid(row=2, column=0, sticky="nsew", padx=pad)
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        self.history_well = tk.Canvas(mid, bg=CHAT_PAGE, highlightthickness=0, borderwidth=0, height=180)
        self.history_well.grid(row=0, column=0, sticky="nsew")
        self.history_canvas = tk.Canvas(self.history_well, bg=CHAT_WELL, highlightthickness=0, borderwidth=0)
        self.history_scroll = ttk.Scrollbar(self.history_well, command=self.history_canvas.yview)
        self.history_canvas.configure(yscrollcommand=self._on_history_scroll)
        self.history = tk.Frame(self.history_canvas, bg=CHAT_WELL)
        self.history_window = self.history_canvas.create_window((0, 0), window=self.history, anchor="nw")
        self.history.bind("<Configure>", self._history_region)
        self.history_canvas.bind("<Configure>", self._layout_history)
        self.history_well.bind("<Configure>", self._paint_history_well)
        self._cover_history(self.history_well)
        self._show_history_empty()

        self.quote_row = tk.Frame(self._page, bg=CHAT_PAGE)
        self.quote_var = tk.StringVar(value="")
        tk.Label(self.quote_row, textvariable=self.quote_var, bg=CHAT_PAGE, fg="#5f6368", font=self._ui_font).pack(
            side="left", fill="x", expand=True
        )
        self._pill(self.quote_row, "Clear quote", self.clear_quote).pack(side="right")

        self.attach_row = tk.Frame(self._page, bg=CHAT_PAGE)
        self.attach_row.grid(row=4, column=0, sticky="ew", padx=pad, pady=(gap, 0))
        self.attach_var = tk.StringVar(value="No document attached")
        tk.Label(self.attach_row, textvariable=self.attach_var, bg=CHAT_PAGE, fg="#202124", font=self._ui_font).pack(
            side="left", fill="x", expand=True
        )
        folder_attach = self._pill(self.attach_row, "Attach folder…", self.attach_folder)
        folder_attach.pack(side="right", padx=(gap, 0))
        _HoverTip(
            folder_attach,
            "Read pdf, docx, xlsx, txt, md, and csv in this folder before the model starts. "
            "Other files are skipped. A long folder is read in parts so it fits the context window.",
        )
        self._pill(self.attach_row, "Attach…", self.attach).pack(side="right", padx=(gap, 0))
        self._pill(self.attach_row, "Clear", self.clear_attach).pack(side="right")

        self.coding_row = tk.Frame(self._page, bg=CHAT_PAGE)
        self.coding_row.grid(row=5, column=0, sticky="ew", padx=pad, pady=(gap, 0))
        coding_box = ttk.Checkbutton(
            self.coding_row,
            text="Coding",
            variable=self.coding_var,
            command=self._on_coding,
        )
        coding_box.pack(side="left", padx=(0, 10))
        _HoverTip(
            coding_box,
            "Runs a sequential coding committee and may execute Python in a local folder. "
            "Leave off for snippets (not tested).",
        )
        job_box = ttk.Checkbutton(
            self.coding_row,
            text="Job application",
            variable=self.job_var,
            command=self._on_job,
        )
        job_box.pack(side="left", padx=(0, 10))
        _HoverTip(
            job_box,
            "The message is the job description. Writes an English resume and cover letter "
            "from your profile only, then a short match summary.",
        )
        update_box = ttk.Checkbutton(
            self.coding_row,
            text="Update profile",
            variable=self.update_var,
            command=self._on_update,
        )
        update_box.pack(side="left")
        _HoverTip(
            update_box,
            "The attached resume is the source. The message is an optional instruction. "
            "Save to profile writes profile.json after you confirm.",
        )

        self.github_row = tk.Frame(self._page, bg=CHAT_PAGE)
        tk.Label(self.github_row, text="GitHub URL", bg=CHAT_PAGE, fg="#202124", font=self._ui_font).pack(side="left")
        self.github_entry = ttk.Entry(self.github_row, textvariable=self.github_var)
        self.github_entry.pack(side="left", fill="x", expand=True, padx=(10, 8))
        _HoverTip(
            self.github_entry,
            "Optional public https://github.com/owner/repo. Used only while Coding is on. "
            "Leave empty if you pick a local folder.",
        )
        tk.Label(self.github_row, textvariable=self.seed_var, bg=CHAT_PAGE, fg="#5f6368", font=self._ui_font).pack(
            side="left", padx=(0, 8)
        )
        folder_btn = self._pill(self.github_row, "Folder…", self.pick_seed_folder)
        folder_btn.pack(side="right")
        _HoverTip(
            folder_btn,
            "Pick a local folder. Files are copied into a new work folder on the stick; "
            "your original folder is not edited. Cannot be used with a GitHub URL.",
        )
        self._pill(self.github_row, "Clear folder", self.clear_seed_folder).pack(side="right", padx=(0, 8))
        self.github_var.trace_add("write", self._on_github_edit)

        self.web_row = tk.Frame(self._page, bg=CHAT_PAGE)
        self.web_row.grid(row=7, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.web_search_var = tk.BooleanVar(value=False)
        self.web_search_btn = ttk.Checkbutton(
            self.web_row,
            text="Web Search",
            variable=self.web_search_var,
            command=self._on_web,
        )
        self.web_star = ttk.Label(self.web_row, text="*", foreground="#5f6368")
        _HoverTip(
            self.web_star,
            "Web Search takes extra time and model passes. Use it only when you need live internet.",
        )
        self.retain_var = tk.BooleanVar(value=False)
        self.retain_btn = ttk.Checkbutton(
            self.web_row,
            text="Retain Selected Model",
            variable=self.retain_var,
        )
        self.retain_btn.pack(side="left")
        _HoverTip(
            self.retain_btn,
            "On: the model shown above answers. Off: the chat picks a tagged model for this message.",
        )

        tk.Label(self._page, text="Message", bg=CHAT_PAGE, fg="#202124", font=self._title_font).grid(
            row=8, column=0, sticky="w", padx=pad, pady=(16, 6)
        )
        input_row = tk.Frame(self._page, bg=CHAT_PAGE)
        input_row.grid(row=9, column=0, sticky="ew", padx=pad, pady=(0, 16))
        input_shell = _Round(
            input_row,
            fill="#ffffff",
            parent_bg=CHAT_PAGE,
            radius=14,
            padx=12,
            pady=8,
            outline=CHAT_LINE,
        )
        input_shell.pack(side="left", fill="x", expand=True)
        self.input = tk.Text(
            input_shell.body,
            height=4,
            wrap="word",
            font=self._ui_font,
            background="#ffffff",
            fg="#1a1a1a",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            insertbackground="#202124",
        )
        self.input.pack(fill="x")
        self.send_btn = _RoundButton(
            input_row,
            "Send",
            self.send,
            parent_bg=CHAT_PAGE,
            fill="#1a7f37",
            fg="#ffffff",
            outline="#1a7f37",
            hover="#176f31",
            radius=14,
            padx=18,
            pady=12,
            font=(self._ui_font[0], 11, "bold"),
        )
        self.send_btn.pack(side="right", padx=(12, 0))
        self.spin_host = tk.Frame(input_row, bg=CHAT_PAGE)
        self.spin = tk.Canvas(
            self.spin_host,
            width=36,
            height=36,
            highlightthickness=0,
            borderwidth=0,
            background=CHAT_PAGE,
        )
        self.spin.pack(expand=True)
        self.input.bind("<Control-Return>", self._send_shortcut)
        self.input.bind("<FocusIn>", self._clear_input_hint)
        self.input.bind("<FocusOut>", self._restore_input_hint)
        self._restore_input_hint()

        buttons = tk.Frame(self._page, bg=CHAT_PAGE)
        buttons.grid(row=10, column=0, sticky="ew", padx=pad, pady=(0, 12))
        self._pill(buttons, "Stop", self.stop).pack(side="left")
        self._pill(buttons, "New session", self.new_session).pack(side="left", padx=(gap, 0))
        self._pill(buttons, "Save transcript PDF", self.save_pdf).pack(side="right")
        self._pill(buttons, "Print", self.print_pdf).pack(side="right", padx=(0, gap))
        self._pill(buttons, "Notes…", self.notes_dialog).pack(side="right", padx=(0, gap))
        self._pill(buttons, "View profile", self.profile_dialog).pack(side="right", padx=(0, gap))

        self.status_var = tk.StringVar(value="")
        tk.Label(
            self._page,
            textvariable=self.status_var,
            bg=CHAT_PAGE,
            fg="#5f6368",
            font=self._ui_font,
            anchor="w",
            justify="left",
        ).grid(row=11, column=0, sticky="ew", padx=pad, pady=(0, 16))

        self._page.bind("<Configure>", self._sync_page)
        self._canvas.bind("<Configure>", self._sync_page)
        self.root.bind_all("<MouseWheel>", self._on_page_wheel)
        self.root.bind_all("<Button-4>", self._on_page_wheel)
        self.root.bind_all("<Button-5>", self._on_page_wheel)

        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self._schedule_web_probe()

    def _sync_page(self, _event=None) -> None:
        width = max(self._canvas.winfo_width(), 1)
        height = max(self._canvas.winfo_height(), 1)
        self._canvas.itemconfigure(self._page_id, width=width)
        self._page.update_idletasks()
        needed = max(self._page.winfo_reqheight(), height)
        self._canvas.itemconfigure(self._page_id, height=needed)
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_page_wheel(self, event) -> str | None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        profile = self._profile_window
        source = widget if widget is not None else getattr(event, "widget", None)
        if profile is not None and source is not None:
            try:
                top = source.winfo_toplevel()
            except tk.TclError:
                top = None
            if top is profile.win:
                return profile._wheel(event)
        while widget is not None:
            if widget in (self.history_well, self.history_canvas, self.history):
                return self._history_wheel(event)
            if widget is self.input:
                return None
            if widget.winfo_toplevel() is not self.root:
                return None
            widget = getattr(widget, "master", None)
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self._canvas.yview_scroll(-1, "units")
        else:
            self._canvas.yview_scroll(1, "units")
        return "break"

    def _pill(self, parent, text: str, command, **kwargs) -> _RoundButton:
        return _RoundButton(parent, text, command, parent_bg=CHAT_PAGE, font=self._ui_font, **kwargs)

    def _cover_history(self, widget) -> None:
        widget.bind("<MouseWheel>", self._history_wheel)
        widget.bind("<Button-4>", self._history_wheel)
        widget.bind("<Button-5>", self._history_wheel)
        for child in widget.winfo_children():
            self._cover_history(child)

    def _history_wheel(self, event) -> str:
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self.history_canvas.yview_scroll(-1, "units")
        else:
            self.history_canvas.yview_scroll(1, "units")
        return "break"

    def _on_history_scroll(self, first, last) -> None:
        self.history_scroll.set(first, last)
        if self._pin_bottom or self.loading_older:
            return
        if float(first) <= 0.001:
            self._queue_older()

    def _queue_older(self) -> None:
        job = getattr(self, "_older_job", None)
        if job is not None:
            self.root.after_cancel(job)
        self._older_job = self.root.after(80, self._run_older)

    def _run_older(self) -> None:
        self._older_job = None
        if self._pin_bottom or self.loading_older:
            return
        if self.history_canvas.yview()[0] > 0.001:
            return
        self.load_older()

    def _paint_history_well(self, _event=None) -> None:
        well = self.history_well
        width = well.winfo_width()
        height = well.winfo_height()
        if width < 40 or height < 40:
            return
        well.delete("edge")
        points = _round_points(1, 1, width - 2, height - 2, 14)
        well.create_polygon(points, fill=CHAT_WELL, outline=CHAT_LINE, width=1, tags="edge")
        well.tag_lower("edge")
        inset = 10
        bar = 16
        view = self.history_canvas.yview()
        self.history_canvas.place(x=inset, y=inset, width=max(40, width - inset * 2 - bar), height=max(40, height - inset * 2))
        self.history_scroll.place(x=width - inset - bar, y=inset + 4, height=max(20, height - inset * 2 - 8), width=bar)
        if self._pin_bottom:
            self.history_canvas.yview_moveto(1)
        elif view[0] > 0.001:
            self.history_canvas.yview_moveto(view[0])

    def _history_region(self, _event=None) -> None:
        bbox = self.history_canvas.bbox("all")
        if bbox:
            self.history_canvas.configure(scrollregion=bbox)

    def _layout_history(self, _event=None) -> None:
        width = self.history_canvas.winfo_width()
        if width < 40:
            return
        self.history_canvas.itemconfigure(self.history_window, width=width)
        self.history.update_idletasks()
        for child in self.history.winfo_children():
            bubble = getattr(child, "_bubble", None)
            if bubble is not None:
                bubble.layout(width)
            elif isinstance(child, tk.Label):
                child.configure(wraplength=max(200, width - 24))
        self.history.update_idletasks()
        self._history_region()

    def _history_see_end(self) -> None:
        self.history.update_idletasks()
        self._layout_history()
        self.history_canvas.yview_moveto(1)

    def _pack_history(self, widget, *, top: bool = False) -> None:
        # pack_slaves is visual order. winfo_children is creation order, so the
        # first child stays the last message and everything else stacks above it.
        slaves = [child for child in self.history.pack_slaves() if child is not widget]
        if top and slaves:
            widget.pack(fill="x", before=slaves[0])
            return
        widget.pack(fill="x")

    def _copy_reply(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._status("Copied the reply")

    def _status(self, text: str) -> None:
        self.status_var.set(text)

    def _ui_status(self, text: str) -> None:
        self.root.after(0, lambda t=text: self._begin_step(t))

    def _begin_step(self, step: str) -> None:
        self._step = step
        self._step_chars = 0
        self._step_got_text = False
        self._step_tick = 0
        self._paint_status()
        self._schedule_step_tail()

    def _elapsed_seconds(self) -> int:
        if not self._turn_started:
            return 0
        return max(0, int(time.monotonic() - self._turn_started))

    def _paint_status(self) -> None:
        if not self.busy or not self._step:
            return
        text = f"{_clock_label(self._elapsed_seconds())} · {self._step}"
        if self._step_got_text:
            text += f" · {self._step_chars} chars"
        else:
            tails = ("", " · still working", " · this can take a while on a large model")
            text += tails[self._step_tick]
        self._status(text)

    def _tick_clock(self) -> None:
        self._clock_after = None
        if not self.busy:
            return
        self._paint_status()
        self._clock_after = self.root.after(1000, self._tick_clock)

    def _schedule_step_tail(self) -> None:
        if self._step_after is not None:
            self.root.after_cancel(self._step_after)
            self._step_after = None
        if not self.busy or self._step_got_text or not self._step:
            return
        self._step_after = self.root.after(4000, self._advance_step_tail)

    def _advance_step_tail(self) -> None:
        self._step_after = None
        if not self.busy or self._step_got_text or not self._step:
            return
        self._step_tick = (self._step_tick + 1) % 3
        self._paint_status()
        self._schedule_step_tail()

    def _add_step_chars(self, count: int) -> None:
        if count <= 0:
            return

        def apply() -> None:
            self._step_chars += count
            self._step_got_text = True
            if self._step_after is not None:
                self.root.after_cancel(self._step_after)
                self._step_after = None
            self._paint_status()

        self.root.after(0, apply)

    def _set_web_row(self, online: bool) -> None:
        self.web_row.grid(row=7, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.web_search_btn.pack_forget()
        self.web_star.pack_forget()
        self.retain_btn.pack_forget()
        if online or self.web_search_var.get():
            self.web_search_btn.pack(side="left")
            self.web_star.pack(side="left", padx=(2, 16))
        if online:
            self.web_visible = True
        elif not self.web_search_var.get():
            self.web_visible = False
        self.retain_btn.pack(side="left")
        self._sync_page()

    def _on_coding(self) -> None:
        if self.coding_var.get():
            self.job_var.set(False)
            self.update_var.set(False)
            self.github_row.grid(row=6, column=0, sticky="ew", padx=16, pady=(8, 0))
        else:
            self.github_row.grid_remove()
        self._sync_page()

    def _on_job(self) -> None:
        if self.job_var.get():
            self.coding_var.set(False)
            self.update_var.set(False)
            self.web_search_var.set(False)
            self.github_row.grid_remove()
            self._sync_page()

    def _on_update(self) -> None:
        if self.update_var.get():
            self.coding_var.set(False)
            self.job_var.set(False)
            self.web_search_var.set(False)
            self.github_row.grid_remove()
            self._sync_page()

    def _on_web(self) -> None:
        if self.web_search_var.get():
            self.job_var.set(False)
            self.update_var.set(False)

    def _on_github_edit(self, *_args) -> None:
        if self.github_var.get().strip() and self.seed_dir is not None:
            self.clear_seed_folder()

    def _refresh_seed_ui(self) -> None:
        if self.seed_dir is None:
            self.seed_var.set("No project folder")
            self.github_entry.configure(state="normal")
        else:
            self.seed_var.set(self.seed_dir.name)
            self.github_entry.configure(state="disabled")
        self._sync_page()

    def pick_seed_folder(self) -> None:
        if self.busy:
            return
        picked = filedialog.askdirectory(
            title="Seed the coding folder (copied, not edited in place)",
            mustexist=True,
            initialdir=str(self.data_root if self.data_root.is_dir() else Path.home()),
        )
        if not picked:
            return
        folder = Path(picked).expanduser().resolve()
        if not folder.is_dir():
            messagebox.showerror("Folder", "Pick an existing folder.")
            return
        if committee.looks_like_usb_chat_app(folder):
            messagebox.showerror(
                "Folder",
                "That folder is USB chat itself. Pick a project folder with your code or test files.",
            )
            return
        self.seed_dir = folder
        if self.github_var.get().strip():
            self.github_var.set("")
        self._refresh_seed_ui()

    def clear_seed_folder(self) -> None:
        self.seed_dir = None
        self._refresh_seed_ui()

    def _probe_web_search(self) -> None:
        def work() -> None:
            online = False
            if usbchat.web_search_available():
                try:
                    import search

                    online = bool(search.check_internet_connectivity())
                except Exception:
                    online = False
            self.root.after(0, lambda: self._set_web_row(online))

        threading.Thread(target=work, daemon=True).start()

    def _schedule_web_probe(self) -> None:
        self._probe_web_search()
        self.root.after(60_000, self._schedule_web_probe)

    def _system_line(self, text: str, *, top: bool = False) -> None:
        label = tk.Label(
            self.history,
            text=text,
            bg=CHAT_WELL,
            fg="#6b7280",
            font=(self._ui_font[0], 11, "italic"),
            anchor="w",
            justify="left",
            wraplength=640,
        )
        self._pack_history(label, top=top)
        self._layout_history()

    def _show_no_earlier_history(self) -> None:
        if self._history_empty or self._end_of_history:
            return
        self._end_of_history = True
        self._system_line(
            "No earlier history. Nothing is stored before this, or older logs were deleted.",
            top=True,
        )

    def _show_history_empty(self) -> None:
        self._history_empty = True
        self._end_of_history = False
        for child in list(self.history.winfo_children()):
            child.destroy()
        self._system_line("No messages yet. Type below and press Send.")

    def _clear_history_empty(self) -> None:
        if not self._history_empty:
            return
        self._history_empty = False
        for child in list(self.history.winfo_children()):
            child.destroy()

    def _input_text(self) -> str:
        if self._input_hint:
            return ""
        return self.input.get("1.0", "end").strip()

    def _send_shortcut(self, _event=None):
        if self.busy:
            return "break"
        self.send()
        return "break"

    def _clear_input_hint(self, _event=None) -> None:
        if self.busy or not self._input_hint:
            return
        self._input_hint = False
        self.input.configure(state="normal")
        self.input.delete("1.0", "end")
        self.input.configure(foreground="#1a1a1a")

    def _restore_input_hint(self, _event=None) -> None:
        if self.busy:
            return
        current = self.input.get("1.0", "end").strip()
        if current and current != "Type a message…":
            self._input_hint = False
            return
        self._input_hint = True
        self.input.configure(state="normal")
        self.input.delete("1.0", "end")
        self.input.insert("1.0", "Type a message…")
        self.input.configure(foreground="#8a8a8a")

    def _draw_spinner(self) -> None:
        self.spin.delete("all")
        self.spin.create_arc(
            6,
            6,
            30,
            30,
            start=self._spin_angle,
            extent=80,
            style="arc",
            outline="#0b57d0",
            width=3,
        )

    def _tick_spinner(self) -> None:
        if not self.busy:
            self._spin_after = None
            return
        self._spin_angle = (self._spin_angle - 30) % 360
        self._draw_spinner()
        self._spin_after = self.root.after(50, self._tick_spinner)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.send_btn.pack_forget()
            self.spin_host.pack(side="right", padx=(12, 0), fill="y")
            self.input.configure(state="disabled", background="#f7f7f7")
            self._spin_angle = 0
            self._draw_spinner()
            if self._spin_after is None:
                self._spin_after = self.root.after(50, self._tick_spinner)
            self._turn_started = time.monotonic()
            self._turn_started_at = usbchat.utc_now()
            if self._clock_after is None:
                self._clock_after = self.root.after(1000, self._tick_clock)
            return
        if self._clock_after is not None:
            self.root.after_cancel(self._clock_after)
            self._clock_after = None
        if self._spin_after is not None:
            self.root.after_cancel(self._spin_after)
            self._spin_after = None
        if self._step_after is not None:
            self.root.after_cancel(self._step_after)
            self._step_after = None
        self.spin_host.pack_forget()
        self.send_btn.pack(side="right", padx=(12, 0))
        self.input.configure(state="normal", background="#ffffff")
        self._restore_input_hint()

    def _role_look(self, role: str) -> tuple[str, str, str]:
        if role == "user":
            return "👤", "You", "#0b57d0"
        if role == "assistant":
            return "🤖", "Model", "#1a7f37"
        return "•", "System", "#5f6368"

    def _save_turn_notes(self, body: str, profile: dict | None) -> None:
        snippet = committee.profile_snippet(profile or {}) or str(body or "").strip()
        if not snippet:
            messagebox.showinfo("notes.md", "Nothing to save from this reply.")
            return
        if not messagebox.askyesno("notes.md", "Append this to notes.md?"):
            return
        usbchat.append_notes(self.notes_file, snippet)
        self._status("Saved to notes.md")

    def _save_profile_record(self, record: dict) -> None:
        if profiledoc.profile_is_empty(record):
            messagebox.showinfo("profile.json", "Nothing checked from the resume can be saved.")
            return
        current = profiledoc.load_profile(self.profile_json)
        merged, conflicts = profiledoc.merge_profile(current, record)
        message = "Save these details to profile.json?"
        if conflicts:
            message += "\n\nExisting values kept:\n" + "\n".join(conflicts)
        if not messagebox.askyesno("profile.json", message):
            return
        profiledoc.save_profile(self.profile_json, merged)
        self._status("Saved profile.json")

    def _view_html(self, pages: list) -> None:
        if not pages:
            return
        try:
            usbchat.open_html_document(pages[0].html)
            extra = f" ({len(pages)} pages)" if len(pages) > 1 else ""
            self._status("Opened HTML in the browser" + extra)
        except Exception as exc:
            messagebox.showerror("View HTML", str(exc))

    def _save_turn_pdf(self, paths: list[str]) -> None:
        src = Path(paths[0])
        if not src.is_file():
            messagebox.showerror("Save PDF", "That PDF is no longer on this stick.")
            return
        dest = filedialog.asksaveasfilename(
            title="Save this PDF",
            defaultextension=".pdf",
            initialfile=src.name,
            filetypes=[("PDF", "*.pdf")],
        )
        if not dest:
            return
        Path(dest).write_bytes(src.read_bytes())
        self._status(f"Saved {dest}")

    def _place_card(self, card: _ChatCard, *, top: bool = False) -> None:
        self._pack_history(card.row, top=top)
        card.layout(max(self.history_canvas.winfo_width(), 320))
        self._history_region()

    def _append(self, role: str, text: str, *, remember: bool = True, extras: dict | None = None, elapsed: int | None = None) -> None:
        self._clear_history_empty()
        if role == "system":
            self._system_line(text)
        else:
            card = _ChatCard(self, role, text, extras=extras, elapsed=elapsed if role == "assistant" else None)
            self._place_card(card)
        if remember:
            self.messages.append((role, text))
        self._history_see_end()

    def _dismiss_model_menu(self, event) -> None:
        self.model_box.dismiss_from(event.widget)

    def refresh_models(self) -> None:
        free = usbchat.free_ram()
        self.choices = usbchat.pickable_models(self.models_root, free)
        labels = [c.label for c in self.choices]
        self.model_box.set_choices(self.choices)
        if labels:
            current = self.model_var.get()
            self.model_var.set(current if current in labels else labels[0])
            free_txt = f"{free / (1024**3):.1f} GB free" if free is not None else "free RAM unknown"
            self._status(f"{len(labels)} model(s) fit  ·  {free_txt}  ·  default is largest")
        else:
            self.model_var.set("")
            self._status("No GGUF on this stick fits free RAM (need file × 1.2 + 2 GB).")

    def _selected(self) -> usbchat.ModelChoice | None:
        label = self.model_var.get()
        for choice in self.choices:
            if choice.label == label:
                return choice
        return None

    def attach(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Attach a document (read-only)",
            filetypes=[
                ("Documents", "*.pdf *.docx *.xlsx *.txt *.md *.csv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        file_path = Path(path)
        if file_path.suffix.lower() not in usbchat.ALLOWED_ATTACH:
            messagebox.showerror("Attach", "Use pdf, docx, xlsx, txt, md, or csv.")
            return
        try:
            text = usbchat.extract_document(file_path)
        except Exception as exc:
            messagebox.showerror("Attach", str(exc))
            return
        resolved = str(file_path.resolve())
        self.attach_dir = None
        self.attach_files = []
        self.attach_truncated = False
        self.attachment = {"name": file_path.name, "path": resolved, "text": text}
        self.attach_var.set(usbchat.attach_row_file(file_path.name, text))

    def attach_folder(self) -> None:
        if self.busy:
            return
        picked = filedialog.askdirectory(
            title="Attach a folder of documents (read-only)",
            mustexist=True,
        )
        if not picked:
            return
        folder = Path(picked).expanduser().resolve()
        if not folder.is_dir():
            messagebox.showerror("Attach folder", "Pick an existing folder.")
            return
        files, truncated = usbchat.list_attach_files(folder)
        if not files:
            messagebox.showerror(
                "Attach folder",
                "No pdf, docx, xlsx, txt, md, or csv files in that folder.",
            )
            return
        self.attachment = None
        self.attach_dir = folder
        self.attach_files = files
        self.attach_truncated = truncated
        self._status("Reading the folder…")
        self.root.update_idletasks()
        tokens = usbchat.folder_extracted_tokens(files)
        self.attach_var.set(usbchat.attach_row_folder(folder.name, len(files), tokens, truncated))
        self._status("")

    def clear_attach(self) -> None:
        self.attachment = None
        self.attach_dir = None
        self.attach_files = []
        self.attach_truncated = False
        self.attach_var.set("No document attached")

    def clear_quote(self) -> None:
        self.quote = ""
        self.quote_var.set("")
        self.quote_row.grid_remove()
        self._sync_page()

    def _set_quote(self, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            return
        self.quote = text
        shown = text if len(text) <= 80 else text[:77] + "…"
        self.quote_var.set(f"Replying to: {shown}")
        if not self.quote_row.winfo_ismapped():
            self.quote_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
            self._sync_page()

    def reply_selection(self) -> None:
        return

    def _reply_menu(self, _event=None) -> None:
        return

    def new_session(self) -> None:
        if self.busy:
            return
        if self.board_name:
            self.session_path.write_text("", encoding="utf-8")
            usbchat.board_path(self.session_path).unlink(missing_ok=True)
            self.memory = usbchat.empty_board()
            label = f"Cleared test board {self.board_name}"
        else:
            self.session_path = usbchat.new_session_path(self.log_root)
            self.memory = usbchat.empty_board()
            label = f"New session {self.session_path.name}"
        self.session_turns = []
        self.older_turns = []
        self.older_files = []
        self.messages = []
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.clear_quote()
        self._show_history_empty()
        self._status(label)

    def _load_named_history(self) -> None:
        turns = usbchat.load_turns(self.session_path)
        if not turns:
            return
        self.session_turns = list(turns)
        self._clear_history_empty()
        for turn in turns:
            user_line = usbchat.display_user_prompt(turn)
            if user_line:
                self._append("user", user_line)
            if turn.get("response"):
                extras = {
                    "pdf_paths": list(turn.get("pdf_paths") or []),
                    "pdf_saves": list(turn.get("pdf_saves") or []),
                    "profile_update": turn.get("profile_update") or {},
                    "profile_record": turn.get("profile_record"),
                }
                self._append("assistant", str(turn["response"]), extras=extras, elapsed=_turn_elapsed_seconds(turn))
        self._history_see_end()

    def _show_latest(self) -> None:
        self._history_see_end()
        self._pin_bottom = False

    def load_older(self) -> None:
        if self.loading_older or self.busy:
            return
        if self.board_name:
            self._show_no_earlier_history()
            return
        sessions = [p for p in usbchat.list_sessions(self.log_root) if p != self.session_path]
        already = {p.resolve() for p in self.older_files}
        nxt = next((p for p in sessions if p.resolve() not in already), None)
        if nxt is None:
            self._show_no_earlier_history()
            return
        initial = self._history_empty
        self.loading_older = True
        if initial:
            self._pin_bottom = True
        turns = usbchat.load_turns(nxt)
        self.older_files.append(nxt)
        self.older_turns = turns + self.older_turns
        if turns:
            self._clear_history_empty()
            for turn in reversed(turns):
                if turn.get("response"):
                    extras = {
                        "pdf_paths": list(turn.get("pdf_paths") or []),
                        "pdf_saves": list(turn.get("pdf_saves") or []),
                        "profile_update": turn.get("profile_update") or {},
                        "profile_record": turn.get("profile_record"),
                    }
                    elapsed = _turn_elapsed_seconds(turn)
                    self._prepend_message(
                        "assistant",
                        str(turn["response"]),
                        extras,
                        elapsed,
                    )
                    self.messages.insert(0, ("assistant", str(turn["response"])))
                user_line = usbchat.display_user_prompt(turn)
                if user_line:
                    self._prepend_message("user", user_line)
                    self.messages.insert(0, ("user", user_line))
            self._system_line(f"— earlier session {nxt.name} —", top=True)
        self.loading_older = False
        if initial:
            self._history_see_end()
            self.root.after_idle(self._show_latest)
        self._status(f"Loaded older log {nxt.name} as earlier turns")
        loaded = {p.resolve() for p in self.older_files}
        if not any(p.resolve() not in loaded for p in sessions):
            self._show_no_earlier_history()

    def _send_doc_continue(self, text: str) -> None:
        if not text.strip():
            messagebox.showerror("Continue", "Answer yes or no to continue reading the folder.")
            return
        choice = self._selected()
        if choice is None and not self.choices:
            messagebox.showerror("Send", "Pick a model that fits RAM.")
            return
        if choice is None:
            choice = self.choices[0]
        self._append("user", text.strip())
        self.input.delete("1.0", "end")
        self._input_hint = False
        self._restore_input_hint()
        self.clear_quote()
        self._set_busy(True)
        self.stop_event.clear()
        self._begin_step("Checking whether to continue")
        threading.Thread(
            target=self._generate,
            args=(choice, [], text.strip(), [], "", False, False, "", None, "", False, "", False, True),
            daemon=True,
        ).start()

    def _choice_by_path(self, path_str: str, fallback):
        for item in self.choices:
            if str(item.path) == path_str:
                return item
        return fallback

    def _load_choice(self, picked) -> None:
        if self.loaded_path != picked.path:
            self._ui_status(f"Loading {picked.label}")
        self._ensure_engine(picked)

    def _stream_reply(self, messages: list[dict], reply_parts: list[str]) -> None:
        if usbchat.messages_tokens(messages) > usbchat.token_budget(self.n_ctx) and messages:
            last = dict(messages[-1])
            cap = usbchat._blob_char_budget(self.n_ctx, "", str((messages[0] or {}).get("content") or ""))
            last["content"] = str(last.get("content") or "")[:cap]
            messages = [dict(item) for item in messages[:-1]] + [last]
        self._ui_status("Writing the answer")
        self.root.after(0, self._begin_assistant)
        for piece in self.engine.stream(messages, self.stop_event):
            reply_parts.append(piece)
            self._add_step_chars(len(piece))
            self.root.after(0, lambda p=piece: self._stream_piece(p))
        if self.engine is not None:
            prompt_tokens, completion_tokens = self.engine.last_usage
            self._turn_prompt_tokens += prompt_tokens
            self._turn_completion_tokens += completion_tokens

    def send(self) -> None:
        if self.busy:
            return
        text = self._input_text()
        if self._doc_resume is not None:
            self._send_doc_continue(text)
            return
        coding = bool(self.coding_var.get())
        job = bool(self.job_var.get())
        update = bool(self.update_var.get())
        seed_dir = self.seed_dir if coding else None
        if job and coding:
            messagebox.showerror("Job application", "Use Job application or Coding, not both.")
            return
        if update and (not self.attachment and not self.attach_dir):
            messagebox.showerror("Update profile", "Attach a resume first.")
            return
        if update and self.web_search_var.get():
            messagebox.showerror(
                "Update profile",
                "Turn Web Search off. Profile updates do not search the web.",
            )
            return
        if job and not text.strip():
            messagebox.showerror("Job application", "Paste the job description in the message box.")
            return
        if not update and not text and not seed_dir and not self.attachment and not self.attach_dir:
            return
        user_text = text
        if not user_text:
            if update:
                user_text = "Update my profile from the attached resume."
            elif self.attachment or self.attach_dir:
                user_text = "Summarize the attached documents."
            else:
                user_text = f"(seed folder {seed_dir})"
        choice = self._selected()
        if choice is None:
            messagebox.showerror("Send", "Pick a model that fits RAM.")
            return
        use_web = bool(self.web_visible and self.web_search_var.get()) and not job and not update
        if job and self.web_search_var.get():
            messagebox.showerror(
                "Job application",
                "Turn Web Search off. The job committee does not search the web.",
            )
            return
        profile = ""
        if job:
            profile = profiledoc.job_profile_text(self.data_root)
            if not profile.strip():
                messagebox.showerror(
                    "Job application",
                    "Open View profile and write your professional background first.",
                )
                return
        if use_web:
            if not usbchat.web_search_available():
                messagebox.showerror(
                    "Web Search",
                    "Run setup.bat so the requests and beautifulsoup4 libraries are installed.",
                )
                return
            try:
                import search

                if not search.check_internet_connectivity():
                    messagebox.showerror(
                        "Web Search",
                        "No internet. Turn Web Search off or reconnect.",
                    )
                    self._set_web_row(False)
                    return
            except Exception as exc:
                messagebox.showerror("Web Search", str(exc))
                return
        if self.attach_dir:
            attachments = [
                {"name": path.name, "path": str(path.resolve()), "text": ""}
                for path in self.attach_files
            ]
        else:
            attachments = [self.attachment] if self.attachment else []
        attach_dir = str(self.attach_dir) if self.attach_dir else ""
        quote = self.quote
        github = ""
        if coding:
            github_raw = self.github_var.get().strip()
            if seed_dir and github_raw:
                messagebox.showerror(
                    "Coding",
                    "Use a GitHub URL or a local folder, not both.",
                )
                return
            if github_raw:
                github = committee.public_github_remote(github_raw) or ""
                if not github:
                    messagebox.showerror(
                        "GitHub",
                        "Use a public https://github.com/owner/repo URL, or leave the field empty.",
                    )
                    return
        routed_tag = ""
        if not self.retain_var.get() and not job and not update:
            picked, routed_tag = usbchat.route_model(
                self.choices,
                user_text,
                coding=coding,
                web=use_web,
            )
            if picked is not None:
                choice = picked
                self.model_box.select(choice.label)
        notes = usbchat.read_notes(self.notes_file)
        messages = usbchat.build_chat_messages(
            notes=notes,
            older_turns=self.older_turns,
            session_turns=self.session_turns,
            quote=quote,
            attachments=[self.attachment] if self.attachment else [],
            user_text=user_text,
        )
        shown = user_text
        if quote:
            shown = f"> {quote[: usbchat.QUOTE_CAP]}\n\n{user_text}"
        if self.attach_dir:
            shown = (
                usbchat.folder_attach_block(
                    str(self.attach_dir),
                    [str(path) for path in self.attach_files],
                    self.attach_truncated,
                )
                + "\n"
                + shown
            )
        elif self.attachment:
            shown = f"{usbchat.attach_label(self.attachment['path'])}\n{shown}"
        if seed_dir:
            shown = f"folder: {seed_dir}\n{shown}".strip()
        self._append("user", shown)
        self.input.delete("1.0", "end")
        self._input_hint = False
        self._restore_input_hint()
        self.clear_quote()
        self._set_busy(True)
        self.stop_event.clear()
        if update:
            self._begin_step("Update profile: reading the resume")
        elif job:
            self._begin_step("Job application: reading the job description")
        elif attach_dir and self.attach_files:
            first = self.attach_files[0].name
            self._begin_step(f"Reading 1/{len(self.attach_files)}: {first}")
        elif self.loaded_path != choice.path:
            loading = f"Loading {choice.label}"
            if routed_tag:
                loading = f"Loading {choice.label} for {routed_tag}"
            self._begin_step(loading)
        elif routed_tag:
            self._begin_step(f"Using {choice.label} for {routed_tag}")
        else:
            self._begin_step("Writing the answer")
        threading.Thread(
            target=self._generate,
            args=(
                choice,
                messages,
                user_text,
                attachments,
                quote,
                use_web,
                coding,
                github,
                seed_dir,
                attach_dir,
                job,
                profile,
                update,
            ),
            daemon=True,
        ).start()

    def _complete(self, messages: list[dict[str, str]], max_tokens: int | None = None, *, count: bool = True) -> str:
        parts: list[str] = []
        for piece in self.engine.stream(messages, self.stop_event, max_tokens=max_tokens):
            parts.append(piece)
            if count:
                self._add_step_chars(len(piece))
            if self.stop_event.is_set():
                break
        if count and self.engine is not None:
            prompt_tokens, completion_tokens = self.engine.last_usage
            self._turn_prompt_tokens += prompt_tokens
            self._turn_completion_tokens += completion_tokens
        return "".join(parts).strip()

    def _coding_complete(self, messages: list[dict[str, str]]) -> str:
        return self._complete(messages, max_tokens=usbchat.CODING_MAX_TOKENS)

    def _ensure_engine(self, choice) -> None:
        if self.engine is not None and self.loaded_path == choice.path:
            return
        self.engine = None
        self.loaded_path = None
        self.engine = usbchat.make_engine(choice.path, n_ctx=self.n_ctx, here=HERE)
        self.loaded_path = choice.path

    def _fold_doc_state(self, state: dict, stopped_early: bool):
        return usbchat.fold_notes_until_fit(
            complete=self._complete,
            chat_messages=list(state.get("chat_messages") or []),
            user_text=str(state.get("user_text") or ""),
            notes=list(state.get("notes") or []),
            n_ctx=self.n_ctx,
            stop_event=self.stop_event,
            status=self._ui_status,
            file_cut=bool(state.get("file_cut")),
            file_limit_note=str(state.get("file_limit_note") or ""),
            stopped_early=stopped_early,
        )

    def _structure_saved_profile(self, state: dict, reply_parts: list[str]) -> bool:
        notes = "\n\n".join(str(note) for note in (state.get("notes") or []) if str(note).strip())
        source = str(state.get("source_text") or notes)
        result = profiledoc.build_update(
            self._complete,
            notes or source,
            str(state.get("instruction") or ""),
            source,
            status=self._ui_status,
            stop_event=self.stop_event,
            n_ctx=self.n_ctx,
        )
        if result.get("stopped"):
            return True
        reply_parts.append(str(result.get("reply") or "").strip())
        if result.get("profile_record"):
            self._profile_turn = {"profile_record": result["profile_record"]}
        return False

    def _profile_board(self, attachments: list[dict]) -> tuple[str, list[dict]]:
        if self.attach_dir:
            def on_file(index: int, total: int, name: str) -> None:
                self._ui_status(f"Reading {index}/{total}: {name}")

            board, _truncated = usbchat.read_document_board(self.attach_dir, on_file=on_file)
            if not board:
                raise ValueError("No readable documents in that folder.")
            source = "\n\n".join(str(item.get("text") or "") for item in board).strip()
            return source, board
        if not attachments:
            raise ValueError("Attach a resume first.")
        path = Path(str(attachments[0].get("path") or ""))
        source = usbchat.extract_document(
            path,
            cap=usbchat.FOLDER_DOC_CAP,
            max_pages=usbchat.FOLDER_DOC_PAGES,
        )
        return source, [{"name": path.name or "resume", "path": str(path), "text": source}]

    def _run_profile_update(self, choice, user_text: str, attachments: list[dict], reply_parts: list[str]):
        picked = usbchat.job_model(self.choices) or choice
        self._load_choice(picked)
        source, board = self._profile_board(attachments)
        if not source.strip():
            raise ValueError("That resume did not contain readable text.")
        parts, file_cut = usbchat.split_document_board(board, self.n_ctx, user_text)
        if len(parts) > usbchat.DOC_BOARD_MAX_CHUNKS:
            batch, cursor, stopped = usbchat.take_document_notes(
                self._complete,
                self._ui_status,
                self.stop_event,
                parts,
                0,
                user_text,
                self.n_ctx,
            )
            if stopped:
                return "stopped", picked
            self._doc_resume = {
                "purpose": "profile",
                "parts": parts,
                "notes": batch,
                "cursor": cursor,
                "source_text": source,
                "instruction": user_text,
                "user_text": user_text,
                "chat_messages": [],
                "file_cut": file_cut,
                "file_limit_note": "",
                "choice_path": str(picked.path),
            }
            reply_parts.append(usbchat.CONTINUE_PROMPT)
            return "", picked
        model_text = source
        if not profiledoc.fits_structure_prompt(source, user_text, self.n_ctx):
            notes: list[str] = []
            cursor = 0
            while cursor < len(parts):
                batch, cursor, stopped = usbchat.take_document_notes(
                    self._complete,
                    self._ui_status,
                    self.stop_event,
                    parts,
                    cursor,
                    user_text,
                    self.n_ctx,
                    batch=len(parts),
                )
                if stopped:
                    return "stopped", picked
                notes.extend(batch)
            model_text = "\n\n".join(notes)
        result = profiledoc.build_update(
            self._complete,
            model_text,
            user_text,
            source,
            status=self._ui_status,
            stop_event=self.stop_event,
            n_ctx=self.n_ctx,
        )
        if result.get("stopped"):
            return "stopped", picked
        reply_parts.append(str(result.get("reply") or "").strip())
        if result.get("profile_record"):
            self._profile_turn = {"profile_record": result["profile_record"]}
        return "", picked

    def _run_doc_continue(self, choice, user_text: str, reply_parts: list[str]):
        state = self._doc_resume or {}
        parts = list(state.get("parts") or [])
        cursor = int(state.get("cursor") or 0)
        intent = usbchat.continue_intent(user_text)
        if intent is None:
            small = usbchat.smallest_model(self.choices)
            if small is None:
                return "No model is available to read that reply.", False, True, choice
            self._load_choice(small)
            choice = small
            intent = usbchat.classify_continue(self._complete, user_text)
        if intent is None:
            reply_parts.append(usbchat.CONTINUE_PROMPT)
            return "", False, True, choice
        picked = self._choice_by_path(str(state.get("choice_path") or ""), choice)
        choice = picked
        self._load_choice(picked)
        if intent == "yes" and cursor < len(parts):
            batch, cursor, stopped = usbchat.take_document_notes(
                self._complete,
                self._ui_status,
                self.stop_event,
                parts,
                cursor,
                str(state.get("user_text") or ""),
                self.n_ctx,
            )
            if stopped:
                return "stopped", False, True, choice
            state["notes"] = list(state.get("notes") or []) + batch
            state["cursor"] = cursor
            self._doc_resume = state
            if cursor < len(parts):
                reply_parts.append(usbchat.CONTINUE_PROMPT)
                return "", False, True, choice
        stopped_early = cursor < len(parts)
        self._doc_resume = None
        if str(state.get("purpose") or "") == "profile":
            if self._structure_saved_profile(state, reply_parts):
                return "stopped", False, True, choice
            return "", False, True, choice
        messages, _block, stopped = self._fold_doc_state(state, stopped_early)
        if stopped:
            return "stopped", False, True, choice
        self._stream_reply(messages, reply_parts)
        return "", True, True, choice

    def _read_document_board_turn(
        self,
        choice,
        messages,
        user_text: str,
        board: list[dict],
        file_limit_note: str,
        coding: bool,
        stakes: bool,
        reply_parts: list[str],
    ) -> dict:
        outcome: dict = {"hold": False, "doc_answer": False, "err": "", "messages": None, "block": ""}
        direct, _full = usbchat.document_board_fits(messages, board, self.n_ctx, file_limit_note)
        if direct is not None:
            outcome["messages"] = direct
            outcome["block"] = _full
            return outcome
        parts, file_cut = usbchat.split_document_board(board, self.n_ctx, user_text)
        notes: list[str] = []
        cursor = 0
        read_all = bool(coding or stakes)
        while cursor < len(parts):
            batch, cursor, stopped = usbchat.take_document_notes(
                self._complete,
                self._ui_status,
                self.stop_event,
                parts,
                cursor,
                user_text,
                self.n_ctx,
                batch=len(parts) if read_all else usbchat.DOC_BOARD_MAX_CHUNKS,
            )
            if stopped:
                outcome["err"] = "stopped"
                return outcome
            notes.extend(batch)
            if not read_all:
                break
        outcome["doc_answer"] = True
        if not read_all and cursor < len(parts):
            self._doc_resume = {
                "parts": parts,
                "notes": notes,
                "cursor": cursor,
                "user_text": user_text,
                "chat_messages": [dict(item) for item in messages],
                "file_cut": file_cut,
                "file_limit_note": file_limit_note,
                "choice_path": str(choice.path),
                "choice_label": choice.label,
            }
            reply_parts.append(usbchat.CONTINUE_PROMPT)
            outcome["hold"] = True
            return outcome
        fitted, block, stopped = usbchat.fold_notes_until_fit(
            complete=self._complete,
            chat_messages=messages,
            user_text=user_text,
            notes=notes,
            n_ctx=self.n_ctx,
            stop_event=self.stop_event,
            status=self._ui_status,
            file_cut=file_cut,
            file_limit_note=file_limit_note,
        )
        if stopped:
            outcome["err"] = "stopped"
            return outcome
        outcome["messages"] = fitted
        outcome["block"] = block
        return outcome

    def _pick_summarizer(self):
        loaded = self.loaded_path.stat().st_size if self.loaded_path and self.loaded_path.is_file() else 0
        return usbchat.summary_model(usbchat.models_after_unload(self.models_root, loaded))

    def _summary_slice(self) -> int:
        summarizer = self._pick_summarizer()
        if summarizer is None:
            return 0
        slice_tokens, _ceiling = usbchat.summary_limits(summarizer.path.name)
        return slice_tokens

    def _summarize_working(self, flag: str) -> bool:
        if not self.memory.get("working") or self.stop_event.is_set():
            return False
        self._ui_status("Summarizing chat history")
        summarizer = self._pick_summarizer()
        if summarizer is None:
            return False
        added = sum(
            usbchat.turn_tokens(str(row.get("prompt") or ""), str(row.get("response") or ""))
            for row in self.memory["working"]
        )
        continue_row = flag == "routine" and usbchat.routine_can_extend(self.memory, added, summarizer.path.name)
        previous = ""
        if continue_row:
            previous = str(self.memory["summaries"][-1].get("summary") or "")
        answer = self.loaded_path
        self._ensure_engine(summarizer)
        cap = 2048 if "qwen3" in summarizer.path.name.casefold() else 1024
        raw = self._complete(usbchat.summary_request(previous, self.memory["working"]), max_tokens=cap, count=False)
        if not usbchat.fold_working(self.memory, raw, flag, continue_row=continue_row):
            if answer is not None:
                match = next((item for item in self.choices if item.path == answer), None)
                if match is not None:
                    self._ensure_engine(match)
            return False
        usbchat.save_board(self.session_path, self.memory)
        return True

    def _prepare_memory(self, choice, user_text: str, quote: str, attachments: list[dict]) -> list[dict]:
        if usbchat.audit_board(self.memory, self.session_path):
            usbchat.save_board(self.session_path, self.memory)
        if self.memory.get("working") and user_text.strip() and not self.stop_event.is_set():
            self._ensure_engine(choice)
            cap = 1024 if "qwen3" in choice.path.name.casefold() else 256
            verdict = self._complete(usbchat.topic_messages(self.memory, user_text), max_tokens=cap, count=False)
            changed, intent = usbchat.topic_decision(self.memory, user_text, verdict)
            if changed and not self.stop_event.is_set():
                if self._summarize_working("model-generated"):
                    self.memory["topic"] = (intent or user_text).strip()[:120]
                    usbchat.save_board(self.session_path, self.memory)
                self._ensure_engine(choice)
        elif not str(self.memory.get("topic") or "").strip() and user_text.strip():
            self.memory["topic"] = user_text.strip()[:120]
            usbchat.save_board(self.session_path, self.memory)
        _retrieved, missing = usbchat.take_span(self.memory, self.session_path, user_text)
        retrieved = _retrieved
        if missing:
            usbchat.save_board(self.session_path, self.memory)
        elif retrieved:
            usbchat.save_board(self.session_path, self.memory)
        notes = usbchat.read_notes(self.notes_file)
        return usbchat.build_chat_messages(
            notes=notes,
            older_turns=self.older_turns,
            session_turns=usbchat.prompt_turns(retrieved, self.memory.get("working") or []),
            quote=quote,
            attachments=attachments,
            user_text=user_text,
            memory=usbchat.memory_text(self.memory),
        )

    def _maybe_routine_fold(self, user_text: str, reply: str) -> None:
        if not reply or reply.startswith("(error:") or reply == "Stopped." or self.stop_event.is_set():
            return
        if not usbchat.routine_due(self.memory, user_text, reply, self._summary_slice()):
            return
        self._summarize_working("routine")

    def _generate(
        self,
        choice,
        messages,
        user_text,
        attachments,
        quote,
        use_web,
        coding,
        github,
        seed_dir=None,
        attach_dir="",
        job=False,
        profile="",
        update=False,
        continuing=False,
    ) -> None:
        err = ""
        reply_parts: list[str] = []
        streamed = False
        self._turn_prompt_tokens = 0
        self._turn_completion_tokens = 0
        web_meta = {"used": False, "query": "", "urls": [], "log": "", "digest": ""}
        extras: dict = {"pdf_paths": [], "pdf_saves": [], "profile_update": {}, "keep_dir": ""}
        stakes = committee.looks_high_stakes(user_text)
        run_text = user_text
        board: list[dict] = []
        file_limit_note = ""
        folder_truncated = False
        doc_answer = False
        doc_hold = False
        skip_main = False
        try:
            if not continuing:
                messages = self._prepare_memory(choice, user_text, quote, attachments)
            if continuing and self._doc_resume:
                skip_main = True
                err, streamed, doc_answer, choice = self._run_doc_continue(choice, user_text, reply_parts)
            if not skip_main and update:
                skip_main = True
                doc_answer = True
                err, choice = self._run_profile_update(choice, user_text, attachments, reply_parts)
            if not skip_main and job:
                picked = usbchat.job_model(self.choices) or choice
                choice = picked
                if self.loaded_path != picked.path:
                    self._ui_status(f"Loading {picked.label}")
                self._ensure_engine(picked)
                keep = usbchat.new_keep_dir(self.data_root, "job")
                job_input = user_text
                note = usbchat.memory_text(self.memory)
                if note:
                    job_input = "Chat memory:\n" + note + "\n\nJob description:\n" + user_text
                result = jobapp.run_job_application(
                    complete=self._complete,
                    job_text=job_input,
                    profile_text=profile,
                    n_ctx=self.n_ctx,
                    stop_event=self.stop_event,
                    status=self._ui_status,
                    build_pdf=usbchat.build_text_pdf,
                    out_dir=keep,
                )
                reply_parts.append(str(result.get("reply") or "").strip())
                extras = {
                    "pdf_paths": list(result.get("pdf_paths") or []),
                    "pdf_saves": list(result.get("pdf_saves") or []),
                    "profile_update": {},
                    "keep_dir": str(keep),
                }
                if result.get("stopped"):
                    err = "stopped"
            if not skip_main and not job and attach_dir:
                def on_file(index: int, total: int, name: str) -> None:
                    self._ui_status(f"Reading {index}/{total}: {name}")

                board, truncated = usbchat.read_document_board(Path(attach_dir), on_file=on_file)
                if not board:
                    raise ValueError("No readable documents in that folder.")
                attachments = [
                    {
                        "name": str(item.get("name") or ""),
                        "path": str(item.get("path") or ""),
                        "text": str(item.get("text") or ""),
                    }
                    for item in board
                ]
                if truncated:
                    folder_truncated = True
                    file_limit_note = f"Only the first {usbchat.FOLDER_MAX_FILES} accepted files were read."
                noun = "document" if len(board) == 1 else "documents"
                self._ui_status(f"Read {len(board)} {noun}")
                if self.stop_event.is_set():
                    raise ValueError("stopped")
            if not skip_main and not job:
                if self.loaded_path != choice.path:
                    self._ui_status(f"Loading {choice.label}")
                self._ensure_engine(choice)
            if not skip_main and not job and use_web:
                web_path = usbchat.new_web_log_path(self.log_root)
                web_meta["log"] = web_path.name
                web = usbchat.run_web_search(
                    complete=self._complete,
                    messages=messages,
                    user_text=user_text,
                    stop_event=self.stop_event,
                    log_path=web_path,
                    status=self._ui_status,
                    n_ctx=self.n_ctx,
                )
                web_meta["query"] = str(web.get("query") or "")
                web_meta["urls"] = list(web.get("urls") or [])
                web_meta["used"] = bool(web.get("ok"))
                if web.get("ok"):
                    web_meta["digest"] = usbchat.format_web_excerpts(
                        web_meta["query"],
                        web.get("excerpts") or [],
                    )
                usbchat.append_web_event(
                    web_path,
                    {
                        "step": "summary",
                        "ok": web.get("ok"),
                        "error": web.get("error"),
                        "query": web_meta["query"],
                        "urls": web_meta["urls"],
                    },
                )
                if web.get("stopped"):
                    err = "stopped"
                elif web.get("ok") and not coding and not stakes:
                    messages, stopped = usbchat.fit_web_answer_messages(
                        complete=self._complete,
                        chat_messages=messages,
                        user_text=user_text,
                        query=web_meta["query"],
                        excerpts=web.get("excerpts") or [],
                        n_ctx=self.n_ctx,
                        stop_event=self.stop_event,
                        status=self._ui_status,
                        log=lambda event: usbchat.append_web_event(web_path, event),
                    )
                    if stopped:
                        err = "stopped"
                    else:
                        self._ui_status("Web Search: writing the answer…")
                elif not web.get("ok"):
                    self._ui_status("Search failed; answering without the web.")
            if not skip_main and not err and board:
                outcome = self._read_document_board_turn(
                    choice,
                    messages,
                    user_text,
                    board,
                    file_limit_note,
                    coding,
                    stakes,
                    reply_parts,
                )
                doc_hold = bool(outcome["hold"])
                doc_answer = bool(outcome["doc_answer"])
                if outcome["err"]:
                    err = str(outcome["err"])
                elif outcome["messages"] is not None:
                    messages = outcome["messages"]
                    if outcome["block"] and (coding or stakes):
                        clip = outcome["block"]
                        if len(clip) > 4000:
                            clip = clip[:4000] + "\n…[truncated]"
                        run_text = (user_text.rstrip() + "\n\nAttached documents (read-only):\n" + clip).strip()
            if not skip_main and not doc_hold and not job and not err and coding:
                slug = user_text or (Path(seed_dir).name if seed_dir else "run")
                keep = usbchat.new_keep_dir(self.data_root, slug)
                coding_log = usbchat.new_coding_log_path(self.data_root, keep.name)
                self._ui_status("Coding committee…")
                task = run_text
                note = usbchat.memory_text(self.memory)
                if note:
                    task = "Chat memory:\n" + note + "\n\nTask:\n" + run_text
                result = committee.run_coding(
                    complete=self._coding_complete,
                    user_text=task,
                    keep_dir=keep,
                    github_url=github or None,
                    seed_dir=Path(seed_dir) if seed_dir else None,
                    web_digest=str(web_meta.get("digest") or ""),
                    stop_event=self.stop_event,
                    status=self._ui_status,
                    build_pdf=usbchat.build_text_pdf,
                    coding_log=coding_log,
                )
                reply_parts.append(str(result.get("reply") or "").strip())
                extras = {
                    "pdf_paths": list(result.get("pdf_paths") or []),
                    "profile_update": result.get("profile_update") or {},
                    "keep_dir": str(result.get("keep_dir") or keep),
                    "coding_log": str(result.get("coding_log") or coding_log),
                    "coding_session": str(result.get("coding_session") or Path(coding_log).parent),
                }
                if result.get("stopped"):
                    err = "stopped"
            elif not skip_main and not doc_hold and not job and not err and stakes:
                keep = usbchat.new_keep_dir(self.data_root, user_text)
                coding_log = usbchat.new_coding_log_path(self.data_root, keep.name)
                self._ui_status("Review committee…")
                task = run_text
                note = usbchat.memory_text(self.memory)
                if note:
                    task = "Chat memory:\n" + note + "\n\nTask:\n" + run_text
                result = committee.run_review(
                    complete=self._coding_complete,
                    user_text=task,
                    keep_dir=keep,
                    web_digest=str(web_meta.get("digest") or ""),
                    stop_event=self.stop_event,
                    status=self._ui_status,
                    build_pdf=usbchat.build_text_pdf,
                    coding_log=coding_log,
                )
                reply_parts.append(str(result.get("reply") or "").strip())
                extras = {
                    "pdf_paths": list(result.get("pdf_paths") or []),
                    "profile_update": result.get("profile_update") or {},
                    "keep_dir": str(result.get("keep_dir") or keep),
                    "coding_log": str(result.get("coding_log") or coding_log),
                    "coding_session": str(result.get("coding_session") or Path(coding_log).parent),
                }
                if result.get("stopped"):
                    err = "stopped"
            elif not skip_main and not doc_hold and not job and not err:
                if usbchat.messages_tokens(messages) > usbchat.token_budget(self.n_ctx) and messages:
                    last = dict(messages[-1])
                    cap = usbchat._blob_char_budget(self.n_ctx, user_text, str((messages[0] or {}).get("content") or ""))
                    last["content"] = str(last.get("content") or "")[:cap]
                    messages = [dict(m) for m in messages[:-1]] + [last]
                self._ui_status("Writing the answer")
                for piece in self.engine.stream(messages, self.stop_event):
                    reply_parts.append(piece)
                    self._add_step_chars(len(piece))
                if self.engine is not None:
                    prompt_tokens, completion_tokens = self.engine.last_usage
                    self._turn_prompt_tokens += prompt_tokens
                    self._turn_completion_tokens += completion_tokens
        except Exception as exc:
            err = (
                "This turn still did not fit the local context window."
                if usbchat._context_overflow(exc)
                else str(exc)
            )
        if self._profile_turn:
            extras.update(self._profile_turn)
            self._profile_turn = None
        prompt_tokens = self._turn_prompt_tokens
        completion_tokens = self._turn_completion_tokens
        reply = "".join(reply_parts).strip()
        elapsed_s = self._elapsed_seconds()
        started_at = self._turn_started_at
        if err and not reply:
            reply = "Stopped." if err == "stopped" else f"(error: {err})"
        elif not doc_answer and not job and not coding and not stakes and not reply.startswith("(error:"):
            reply = committee.finish_off_coding(user_text, reply)
        if reply and err != "stopped":
            try:
                self._maybe_routine_fold(user_text, reply)
            except Exception:
                pass
        turn_id = usbchat.fresh_message_id(self.memory, self.session_turns)

        def finish() -> None:
            self._set_busy(False)
            if err and not reply_parts:
                self._append("system", reply)
            elif reply:
                if streamed:
                    self._finish_stream(reply, extras, elapsed_s)
                else:
                    self._append("assistant", reply, extras=extras, elapsed=elapsed_s)
            shown = user_text
            if quote:
                shown = f"> {quote[: usbchat.QUOTE_CAP]}\n\n{user_text}"
            if attach_dir:
                names = usbchat.folder_attach_block(
                    attach_dir,
                    [a.get("path") or a.get("name") or "" for a in attachments],
                    folder_truncated,
                )
                shown = f"{names}\n{shown}"
            elif attachments:
                names = "\n".join(usbchat.attach_label(a.get("path") or a["name"]) for a in attachments)
                shown = f"{names}\n{shown}"
            if seed_dir:
                shown = f"folder: {seed_dir}\n{shown}".strip()
            turn = {
                "id": turn_id,
                "time": usbchat.utc_now(),
                "started": started_at,
                "model": choice.label,
                "prompt": user_text,
                "shown": shown,
                "response": reply,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "elapsed_s": elapsed_s,
                "attached": [a.get("path") or a["name"] for a in attachments],
                "attach_dir": attach_dir,
                "quote": quote,
                "web_search": bool(web_meta["used"]),
                "web_query": web_meta["query"],
                "web_urls": web_meta["urls"],
                "web_log": web_meta["log"],
                "coding": bool(coding),
                "github": github,
                "seed_dir": str(seed_dir) if seed_dir else "",
                "pdf_paths": list(extras.get("pdf_paths") or []),
                "pdf_saves": list(extras.get("pdf_saves") or []),
                "profile_record": extras.get("profile_record"),
                "job": bool(job),
                "profile_update": extras.get("profile_update") or {},
                "keep_dir": extras.get("keep_dir") or "",
            }
            usbchat.append_turn(self.session_path, turn)
            self.session_turns.append(turn)
            if reply and reply != "Stopped." and not str(reply).startswith("(error:"):
                usbchat.remember_turn(self.memory, turn_id, user_text, reply)
                usbchat.save_board(self.session_path, self.memory)
            self.prompt_tokens_total += prompt_tokens
            self.completion_tokens_total += completion_tokens
            self._status(
                f"{choice.label}  ·  this turn {prompt_tokens}+{completion_tokens} tok  ·  "
                f"session {self.prompt_tokens_total}+{self.completion_tokens_total} tok"
            )

        self.root.after(0, finish)

    def _prepend_message(self, role: str, text: str, extras: dict | None = None, elapsed: int | None = None) -> None:
        card = _ChatCard(
            self,
            role,
            text,
            extras=extras,
            elapsed=elapsed if role == "assistant" else None,
        )
        self._place_card(card, top=True)

    def _begin_assistant(self) -> None:
        self._clear_history_empty()
        card = _ChatCard(self, "assistant", "", streaming=True)
        self._stream_card = card
        self._place_card(card)
        self._history_see_end()

    def _finish_stream(self, reply: str, extras: dict | None, elapsed: int | None = None) -> None:
        card = getattr(self, "_stream_card", None)
        if card is None:
            self._append("assistant", reply, extras=extras, elapsed=elapsed)
            return
        card.finish(reply, extras, elapsed)
        card.layout(max(self.history_canvas.winfo_width(), 320))
        self._history_region()
        self.messages.append(("assistant", reply))
        self._stream_card = None
        self._history_see_end()

    def _stream_piece(self, piece: str) -> None:
        card = getattr(self, "_stream_card", None)
        if card is None:
            return
        card.set_stream(card.text + piece)
        card.layout(max(self.history_canvas.winfo_width(), 320))
        self._history_region()
        self.history_canvas.yview_moveto(1)

    def stop(self) -> None:
        self.stop_event.set()

    def _pdf_bytes(self) -> bytes:
        blocks = [(role.capitalize(), body) for role, body in self.messages if body]
        return usbchat.build_transcript_pdf("USB chat", blocks)

    def save_pdf(self) -> None:
        data = self._pdf_bytes()
        path = filedialog.asksaveasfilename(
            title="Save transcript PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        Path(path).write_bytes(data)
        self._status(f"Saved {path}")

    def print_pdf(self) -> None:
        try:
            usbchat.print_or_open_pdf(self._pdf_bytes())
            self._status("Sent PDF to the printer or opened it.")
        except Exception as exc:
            messagebox.showerror("Print", str(exc))

    def notes_dialog(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("notes.md")
        win.geometry("560x420")
        body = tk.Text(win, wrap="word")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        current = usbchat.read_notes(self.notes_file, cap=200_000)
        if current:
            body.insert("1.0", current)
        hint = ttk.Label(win, text="The model only reads the first 4000 characters. Writes need your OK.")
        hint.pack(fill="x", padx=8)
        row = ttk.Frame(win, padding=8)
        row.pack(fill="x")

        def save() -> None:
            text = body.get("1.0", "end").rstrip() + "\n"
            if not messagebox.askyesno("notes.md", f"Write {len(text)} characters to {self.notes_file}?"):
                return
            self.notes_file.parent.mkdir(parents=True, exist_ok=True)
            self.notes_file.write_text(text, encoding="utf-8")
            win.destroy()
            self._status(f"Wrote {self.notes_file}")

        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(row, text="Save notes", command=save).pack(side="right", padx=(0, 6))

    def profile_dialog(self) -> None:
        ProfileWindow(self)


def _round_points(x1: float, y1: float, x2: float, y2: float, radius: float, steps: int = 8) -> list[float]:
    radius = min(radius, max(0.0, (x2 - x1) / 2), max(0.0, (y2 - y1) / 2))
    if radius <= 0:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    points: list[float] = []

    def arc(cx: float, cy: float, start: float, end: float) -> None:
        for step in range(steps + 1):
            angle = math.radians(start + (end - start) * step / steps)
            points.extend((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))

    arc(x1 + radius, y1 + radius, 90, 180)
    arc(x1 + radius, y2 - radius, 180, 270)
    arc(x2 - radius, y2 - radius, 270, 360)
    arc(x2 - radius, y1 + radius, 0, 90)
    return points


class _Round(tk.Canvas):
    """Full-width panel. Widgets go in ``body``; the canvas paints the rounded edge."""

    def __init__(
        self,
        parent,
        *,
        fill: str,
        parent_bg: str,
        radius: int = 12,
        padx: int = 12,
        pady: int = 10,
        outline: str = "",
    ) -> None:
        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0, height=pady * 2 + 8, takefocus=0)
        self.fill = fill
        self.radius = radius
        self.outline = outline
        self._padx = padx
        self._pady = pady
        self._height = pady * 2 + 8
        self.body = tk.Frame(self, bg=fill)
        self._window = self.create_window((padx, pady), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.bind("<Configure>", self._on_canvas)

    def _on_body(self, event) -> None:
        need = event.height + self._pady * 2
        if need > 1 and need != self._height:
            self._height = need
            self.configure(height=need)

    def _on_canvas(self, event) -> None:
        inner = max(event.width - self._padx * 2, 1)
        try:
            current = int(float(self.itemcget(self._window, "width")))
        except (TypeError, ValueError):
            current = -1
        if current != inner:
            self.itemconfigure(self._window, width=inner)
        self._redraw(event.width, max(event.height, self._height))

    def _redraw(self, width: int, height: int) -> None:
        self.delete("shape")
        if width < 4 or height < 4:
            return
        outer = _round_points(1, 1, width - 2, height - 2, self.radius)
        if self.outline:
            self.create_polygon(outer, smooth=False, fill=self.outline, outline="", tags="shape")
            inner = _round_points(2, 2, width - 3, height - 3, max(0, self.radius - 1))
            self.create_polygon(inner, smooth=False, fill=self.fill, outline="", tags="shape")
        else:
            self.create_polygon(outer, smooth=False, fill=self.fill, outline="", tags="shape")
        self.tag_lower("shape")


class _RoundButton(tk.Canvas):
    """Compact rounded button. The canvas background matches the parent so the corners disappear."""

    def __init__(
        self,
        parent,
        text: str,
        command,
        *,
        parent_bg: str,
        fill: str = "#ffffff",
        fg: str = "#202124",
        outline: str = CHAT_LINE,
        hover: str | None = None,
        radius: int = 12,
        padx: int = 14,
        pady: int = 7,
        font=None,
    ) -> None:
        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0, takefocus=0, cursor="hand2")
        self._text = text
        self._command = command
        self._fill = fill
        self._hover_fill = hover or "#eef1f4"
        self._fg = fg
        self._outline = outline
        self._radius = radius
        self._padx = padx
        self._pady = pady
        self._font = font or ("Segoe UI", 11)
        self._hot = False
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._paint()

    def _click(self, _event=None) -> None:
        if self._command:
            self._command()

    def _enter(self, _event=None) -> None:
        self._hot = True
        self._paint()

    def _leave(self, _event=None) -> None:
        self._hot = False
        self._paint()

    def _paint(self) -> None:
        self.delete("all")
        face = tkfont.Font(font=self._font)
        width = face.measure(self._text) + self._padx * 2
        height = face.metrics("linespace") + self._pady * 2
        self.configure(width=width, height=height)
        points = _round_points(1, 1, width - 2, height - 2, self._radius)
        self.create_polygon(
            points,
            smooth=False,
            fill=self._hover_fill if self._hot else self._fill,
            outline=self._outline,
        )
        self.create_text(width / 2, height / 2, text=self._text, fill=self._fg, font=self._font)


class _IconButton(tk.Canvas):
    """Small reply or copy mark, drawn rather than taken from a font."""

    def __init__(self, parent, kind: str, command, bg: str) -> None:
        super().__init__(
            parent,
            width=28,
            height=28,
            bg=bg,
            highlightthickness=0,
            bd=0,
            takefocus=0,
            cursor="hand2",
        )
        self.kind = kind
        self._command = command
        self._bg = bg
        self._fg = "#5f6368"
        self._hot = False
        self.bind("<Button-1>", lambda _e: command())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()

    def _enter(self, _event=None) -> None:
        self._hot = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self._hot = False
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        if self._hot:
            points = _round_points(1, 1, 27, 27, 8)
            self.create_polygon(points, smooth=False, fill="#dfe3e8", outline="")
        ink = self._fg
        plate = "#dfe3e8" if self._hot else self._bg
        if self.kind == "copy":
            self.create_rectangle(12, 5, 22, 15, outline=ink, width=1.4)
            self.create_rectangle(6, 9, 16, 19, outline=ink, width=1.4, fill=plate)
            return
        self.create_line(18, 10, 11, 10, 11, 18, fill=ink, width=1.6, smooth=True)
        self.create_line(11, 18, 16, 14, fill=ink, width=1.6)
        self.create_line(11, 18, 7, 14, fill=ink, width=1.6)


class _ChatCard:
    """One rounded message. Yours sits on the right; the model's sits on the left."""

    def __init__(self, app: "UsbChatApp", role: str, text: str, *, extras=None, elapsed: int | None = None, streaming: bool = False) -> None:
        self.app = app
        self.role = role
        self.text = text
        self.fill = CHAT_BUBBLE
        self.row = tk.Frame(app.history, bg=CHAT_WELL)
        self.row._bubble = self  # type: ignore[attr-defined]
        self.row.pack_propagate(False)
        self.canvas = tk.Canvas(self.row, bg=CHAT_WELL, highlightthickness=0, bd=0, takefocus=0)
        self.body = tk.Frame(self.canvas, bg=self.fill)
        self._win = self.canvas.create_window((14, 12), window=self.body, anchor="nw")
        _icon, title, color = app._role_look(role)
        tk.Label(
            self.body,
            text=f"{_icon}  {title}",
            bg=self.fill,
            fg=color,
            font=app._title_font,
        ).pack(anchor="w")
        self.content = tk.Frame(self.body, bg=self.fill)
        self.content.pack(anchor="w", fill="x", pady=(6, 0))
        self.footer = tk.Frame(self.body, bg=self.fill)
        self._labels: list[tk.Label] = []
        self._host_width = 640
        if streaming:
            self._add_label(text or "…")
        elif role == "assistant":
            self._render_blocks(text)
            self._render_footer(extras, elapsed)
        else:
            self._add_label(text)
            self._render_footer(None, None)
        app._cover_history(self.row)

    def _add_label(self, text: str, *, fg: str = "#202124", font=None, bg: str | None = None) -> tk.Label:
        label = tk.Label(
            self.content,
            text=text,
            bg=bg or self.fill,
            fg=fg,
            font=font or self.app._ui_font,
            justify="left",
            anchor="w",
            wraplength=320,
        )
        label.pack(anchor="w", pady=(2, 0))
        self._labels.append(label)
        return label

    def _render_blocks(self, text: str) -> None:
        family = self.app._ui_font[0]
        mono = ("Consolas", 10) if sys.platform == "win32" else ("monospace", 10)
        for block in formatter.format_blocks(text or ""):
            kind = block.kind
            if kind == "heading":
                size = 16 if block.level <= 1 else 13 if block.level == 2 else 11
                self._add_label(block.text, fg="#1a7f37", font=(family, size, "bold"))
            elif kind == "code":
                box = tk.Frame(self.content, bg="#dfe3e8")
                box.pack(anchor="w", pady=(4, 2))
                label = tk.Label(
                    box,
                    text=block.text,
                    bg="#dfe3e8",
                    fg="#202124",
                    font=mono,
                    justify="left",
                    anchor="w",
                    wraplength=320,
                )
                label.pack(padx=8, pady=6, anchor="w")
                self._labels.append(label)
            elif kind == "list":
                rows = [
                    (f"{i}. " if block.ordered else "• ") + item
                    for i, item in enumerate(block.items, 1)
                ]
                self._add_label("\n".join(rows))
            elif kind == "quote":
                self._add_label(block.text, fg="#5f6368")
            elif kind == "rule":
                self._add_label("—", fg="#8a8a8a")
            elif kind == "html_doc":
                self._add_label(f"HTML page: {block.name}", fg="#5f6368")
            else:
                self._add_label(block.text or "")

    def _render_footer(self, extras: dict | None, elapsed: int | None) -> None:
        for child in self.footer.winfo_children():
            child.destroy()
        if not self.footer.winfo_manager():
            self.footer.pack(fill="x", pady=(8, 0))
        left = tk.Frame(self.footer, bg=self.fill)
        right = tk.Frame(self.footer, bg=self.fill)
        left.pack(side="left")
        right.pack(side="right")
        reply = _IconButton(left, "reply", lambda: self.app._set_quote(self.text), self.fill)
        reply.pack(side="left")
        _HoverTip(reply, "Reply to this message")
        if self.role != "assistant":
            return
        copy = _IconButton(left, "copy", lambda: self.app._copy_reply(self.text), self.fill)
        copy.pack(side="left", padx=(2, 0))
        _HoverTip(copy, "Copy reply")
        save_pills, side_pills = self._footer_pills(extras or {})
        for label, command in save_pills:
            self._footer_pill(left, label, command).pack(side="left", padx=(6, 0))
        if elapsed is not None:
            tk.Label(
                left,
                text=_elapsed_words(elapsed),
                bg=self.fill,
                fg="#5f6368",
                font=(self.app._ui_font[0], 10),
            ).pack(side="left", padx=(8, 0))
        for label, command in side_pills:
            self._footer_pill(right, label, command).pack(side="right", padx=(6, 0))

    def _footer_pills(self, extras: dict) -> tuple[list[tuple[str, object]], list[tuple[str, object]]]:
        pages = extras.get("html_pages")
        if pages is None and self.text:
            pages = formatter.html_pages(formatter.format_blocks(self.text))
        pdfs = [p for p in (extras.get("pdf_paths") or []) if p]
        profile = extras.get("profile_update") or {}
        record = extras.get("profile_record")
        save: list[tuple[str, object]] = []
        side: list[tuple[str, object]] = []
        if record:
            save.append(("Save to profile", lambda rec=record: self.app._save_profile_record(rec)))
        else:
            save.append(("Save to notes", lambda body=self.text, prof=profile: self.app._save_turn_notes(body, prof)))
        saves = [item for item in (extras.get("pdf_saves") or []) if item.get("path")]
        if saves:
            for item in saves:
                path = str(item["path"])
                label = str(item.get("label") or "Save PDF")
                side.append((label, lambda p=path: self.app._save_turn_pdf([p])))
        elif pdfs:
            side.append(("Save PDF", lambda paths=list(pdfs): self.app._save_turn_pdf(paths)))
        if pages:
            side.append(("View HTML", lambda ps=pages: self.app._view_html(ps)))
        return save, side

    def _footer_pill(self, parent, label: str, command) -> _RoundButton:
        return _RoundButton(
            parent,
            label,
            command,
            parent_bg=self.fill,
            fill="#ffffff",
            fg="#1a7f37" if label == "Save to profile" else "#202124",
            radius=10,
            padx=10,
            pady=4,
            font=(self.app._ui_font[0], 10),
        )

    def set_stream(self, text: str) -> None:
        self.text = text
        if self._labels:
            self._labels[0].configure(text=text or "…")

    def finish(self, text: str, extras: dict | None, elapsed: int | None) -> None:
        self.text = text
        for child in list(self.content.winfo_children()):
            child.destroy()
        self._labels.clear()
        self._render_blocks(text)
        self._render_footer(extras, elapsed)
        self.app._cover_history(self.row)

    def layout(self, host_width: int) -> None:
        self._host_width = host_width
        edge = 12
        gutter = max(80, int(host_width * 0.20))
        max_outer = host_width - edge - gutter
        if max_outer < 180:
            gutter = max(16, host_width - edge - 180)
            max_outer = max(120, host_width - edge - gutter)
        inner = max(100, max_outer - 28)
        for label in self._labels:
            label.configure(wraplength=inner)
        self.body.update_idletasks()
        body_w = min(max(self.body.winfo_reqwidth(), 48), max_outer - 28)
        body_h = max(self.body.winfo_reqheight(), 24)
        outer_w = body_w + 28
        outer_h = body_h + 24
        self.canvas.configure(width=outer_w, height=outer_h)
        self.canvas.itemconfigure(self._win, width=body_w)
        self.canvas.delete("shape")
        points = _round_points(1, 1, outer_w - 2, outer_h - 2, 16)
        self.canvas.create_polygon(points, smooth=False, fill=self.fill, outline=CHAT_LINE, tags="shape")
        self.canvas.tag_lower("shape")
        self.row.configure(height=outer_h + 10)
        if self.role == "user":
            self.canvas.place(x=max(gutter, host_width - outer_w - edge), y=4, anchor="nw")
        else:
            self.canvas.place(x=edge, y=4, anchor="nw")


class ProfileWindow:
    """Editable profile cards. View profile opens this window."""

    _PAGE = "#f7f7f7"
    _FIELD = "#ffffff"
    _FIELD_LINE = "#d5d9e0"
    _GREEN = "#1a7f37"
    _GRAY = "#5f6368"
    _MUTED = "#8a8a8a"
    _TINTS = {
        "contact": {"base": "#ffffff", "light": "#ffffff", "dark": "#eef1f4", "line": "#e1e4e8"},
        "summary": {"base": "#fde8ef", "light": "#fff4f7", "dark": "#f8d4e0", "line": "#f3c6d4"},
        "experience": {"base": "#e3f0fc", "light": "#f4f9fe", "dark": "#d0e4f8", "line": "#c3daf2"},
        "projects": {"base": "#fff3cc", "light": "#fffdf4", "dark": "#ffe7a3", "line": "#f0d98a"},
        "skills": {"base": "#f2ebfe", "light": "#faf7ff", "dark": "#e4d8fc", "line": "#d9c8f6"},
        "education": {"base": "#e3f6ea", "light": "#f4fbf7", "dark": "#cfeeda", "line": "#bfe4cc"},
    }

    def __init__(self, app: UsbChatApp) -> None:
        self.app = app
        self.dirty = False
        self._loading = True
        family = app._ui_font[0]
        self.font = (family, 11)
        self.small = (family, 9)
        self.name_font = (family, 18, "bold")
        self.win = tk.Toplevel(app.root)
        self.win.title("Profile")
        self.win.geometry("720x640")
        self.win.minsize(480, 420)
        self.win.configure(bg=self._PAGE)
        self.profile = profiledoc.load_profile(app.profile_json)
        self.role_rows: list[dict] = []
        self.school_rows: list[dict] = []
        self.project_rows: list[dict] = []
        self.link_rows: list[dict] = []
        self.skills: list[str] = list(self.profile["skills"])
        self._cards = 0
        self._placing = False
        self.app._profile_window = self

        shell = tk.Frame(self.win, bg=self._PAGE)
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, bg=self._PAGE, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(shell, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.page = tk.Frame(self.canvas, bg=self._PAGE)
        self.page_id = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._fit_width)

        self._build_intro()
        self._build_header()
        self._build_summary()
        self._build_experience()
        self._build_projects()
        self._build_skills()
        self._build_education()

        bar = tk.Frame(self.win, bg=self._PAGE, padx=16, pady=12)
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.close).pack(side="right")
        self.save_btn = ttk.Button(bar, text="Save profile", command=self.save, state="disabled")
        self.save_btn.pack(side="right", padx=(0, 8))
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._loading = False
        self._saved_form = self._form_state()
        self.dirty = False
        self._cover_wheel(self.win)
        self.win.after_idle(self._place_skills)

    def _cover_wheel(self, widget) -> None:
        """One scroll handler for the profile window. Child cards do not keep their own."""
        widget.bind("<MouseWheel>", self._wheel)
        widget.bind("<Button-4>", self._wheel)
        widget.bind("<Button-5>", self._wheel)
        for child in widget.winfo_children():
            self._cover_wheel(child)

    def _fit_width(self, event) -> None:
        width = max(event.width, 1)
        self.canvas.itemconfigure(self.page_id, width=width)
        intro = getattr(self, "intro", None)
        if intro is not None:
            intro.configure(wraplength=max(200, width - 48))

    def _build_intro(self) -> None:
        self.intro = tk.Label(
            self.page,
            text=(
                "This is your professional background, saved on the stick. "
                "Job application writes the resume and cover letter only from what is saved here. "
                "Type it in yourself, or attach a resume in the chat with Update profile and save the result."
            ),
            bg=self._PAGE,
            fg=self._GRAY,
            font=self.font,
            wraplength=640,
            justify="left",
            anchor="w",
        )
        self.intro.pack(fill="x", padx=16, pady=(16, 4))

    def _wheel(self, event) -> str:
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-1, "units")
        else:
            self.canvas.yview_scroll(1, "units")
        return "break"

    def _touch(self, *_args) -> None:
        if self._loading:
            return
        try:
            changed = self._form_state() != getattr(self, "_saved_form", None)
        except tk.TclError:
            return
        self.dirty = changed
        if hasattr(self, "save_btn"):
            self.save_btn.configure(state="normal" if changed else "disabled")

    def _on_modified(self, event) -> None:
        widget = event.widget
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._touch()

    def _rerender(self, build) -> None:
        self._loading = True
        try:
            build()
        finally:
            self._loading = False
        self._touch()

    def _shade(self, kind: str, index: int) -> str:
        spec = self._TINTS[kind]
        return spec["light"] if index % 2 == 0 else spec["dark"]

    def _card(self, title: str, kind: str) -> tuple[tk.Frame, str]:
        spec = self._TINTS[kind]
        outer = tk.Frame(self.page, bg=self._PAGE)
        outer.pack(fill="x", padx=16, pady=(12 if self._cards == 0 else 0, 0))
        self._cards += 1
        panel = _Round(
            outer,
            fill=spec["base"],
            parent_bg=self._PAGE,
            radius=18,
            padx=18,
            pady=16,
            outline=spec["line"],
        )
        panel.pack(fill="x", pady=(0, 12))
        tk.Label(panel.body, text=title, bg=spec["base"], fg=self._GRAY, font=self.small).pack(anchor="w")
        return panel.body, spec["base"]

    def _subcard(self, parent, kind: str, index: int, parent_bg: str) -> tuple[tk.Frame, str]:
        bg = self._shade(kind, index)
        panel = _Round(
            parent,
            fill=bg,
            parent_bg=parent_bg,
            radius=14,
            padx=14,
            pady=12,
            outline=self._TINTS[kind]["line"],
        )
        panel.pack(fill="x", pady=(8, 0))
        return panel.body, bg

    def _entry(self, parent, value: str, bg: str, font=None, fg=None, watch: bool = True) -> tk.Entry:
        shell = _Round(
            parent,
            fill=self._FIELD,
            parent_bg=bg,
            radius=10,
            padx=10,
            pady=6,
            outline=self._FIELD_LINE,
        )
        shell.pack(fill="x", pady=(6, 0))
        var = tk.StringVar(value=value)
        field = tk.Entry(
            shell.body,
            textvariable=var,
            font=font or self.font,
            fg=fg or "#202124",
            bg=self._FIELD,
            insertbackground="#202124",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        field.pack(fill="x")
        field._var = var
        if watch:
            var.trace_add("write", self._touch)
        return field

    def _labeled(self, parent, label: str, value: str, bg: str) -> tk.Entry:
        tk.Label(parent, text=label, bg=bg, fg=self._GRAY, font=self.small).pack(anchor="w", pady=(8, 0))
        return self._entry(parent, value, bg)

    def _text(self, parent, value: str, height: int, bg: str) -> tk.Text:
        shell = _Round(
            parent,
            fill=self._FIELD,
            parent_bg=bg,
            radius=10,
            padx=10,
            pady=8,
            outline=self._FIELD_LINE,
        )
        shell.pack(fill="x", pady=(6, 0))
        field = tk.Text(
            shell.body,
            height=height,
            wrap="word",
            font=self.font,
            bg=self._FIELD,
            fg="#202124",
            insertbackground="#202124",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        if value:
            field.insert("1.0", value)
        field.bind("<<Modified>>", self._on_modified)
        field.edit_modified(False)
        field.pack(fill="x")
        return field

    def _empty(self, parent, shown: bool, bg: str) -> None:
        if shown:
            tk.Label(
                parent,
                text="Nothing saved in this section.",
                bg=bg,
                fg=self._MUTED,
                font=(self.font[0], 11, "italic"),
            ).pack(anchor="w", pady=(8, 0))

    def _build_header(self) -> None:
        box, tint = self._card("CONTACT", "contact")
        contact = self.profile["contact"]
        self.name = self._entry(box, contact["name"], tint, font=self.name_font, fg=self._GREEN)
        self.email = self._entry(box, contact["email"], tint)
        self.phone = self._entry(box, contact["phone"], tint)
        self.location = self._entry(box, contact["location"], tint)
        tk.Label(box, text="Links", bg=tint, fg=self._GRAY, font=self.small).pack(anchor="w", pady=(8, 0))
        self.link_host = tk.Frame(box, bg=tint)
        self.link_host.pack(fill="x")
        self._contact_tint = tint
        ttk.Button(box, text="Add link", command=self._add_link).pack(anchor="w", pady=(8, 0))
        self._render_links()
        if usbchat.read_profile(self.app.profile_file).strip() and profiledoc.profile_is_empty(self.profile):
            tk.Label(
                box,
                text="profile.md is still on the stick. Saving writes profile.json, which the job committee uses.",
                bg=tint,
                fg=self._GRAY,
                font=self.small,
                wraplength=620,
                justify="left",
            ).pack(anchor="w", pady=(8, 0))

    def _render_links(self) -> None:
        for child in self.link_host.winfo_children():
            child.destroy()
        self.link_rows = []
        links = self.profile["contact"]["links"]
        tint = self._contact_tint
        self._empty(self.link_host, not links, tint)
        for index, link in enumerate(links):
            block, bg = self._subcard(self.link_host, "contact", index, tint)
            fresh = bool(link.get("fresh"))
            title = link.get("title") or ""
            url = link.get("url") or ""
            if fresh:
                title_field = self._labeled(block, "Title", title, bg)
                value = self._labeled(block, "Address", url, bg)
            else:
                tk.Label(block, text=title or "Link", bg=bg, fg=self._GRAY, font=self.small).pack(anchor="w")
                title_field = title
                value = self._entry(block, url, bg)
            row = {"title": title_field, "value": value, "fresh": fresh}
            self.link_rows.append(row)
            ttk.Button(block, text="Remove", command=lambda item=row: self._remove_link(item)).pack(anchor="w", pady=(6, 0))
        self._cover_wheel(self.link_host)

    def _add_link(self) -> None:
        self.profile["contact"]["links"] = self._links_from_rows(strip=True) + [{"title": "", "url": "", "fresh": True}]
        self._rerender(self._render_links)

    def _remove_link(self, item: dict) -> None:
        links = self._links_from_rows(strip=True)
        del links[self.link_rows.index(item)]
        self.profile["contact"]["links"] = links
        self._rerender(self._render_links)

    def _build_summary(self) -> None:
        box, tint = self._card("SUMMARY", "summary")
        self.summary = self._text(box, self.profile["summary"], 4, tint)
        self._empty(box, not self.profile["summary"], tint)

    def _build_experience(self) -> None:
        self.exp_box, self._exp_tint = self._card("EXPERIENCE", "experience")
        self.exp_host = tk.Frame(self.exp_box, bg=self._exp_tint)
        self.exp_host.pack(fill="x")
        ttk.Button(self.exp_box, text="Add role", command=self._add_role).pack(anchor="w", pady=(8, 0))
        self._render_roles()

    def _render_roles(self) -> None:
        for child in self.exp_host.winfo_children():
            child.destroy()
        self.role_rows = []
        roles = self.profile["experience"]
        tint = self._exp_tint
        self._empty(self.exp_host, not roles, tint)
        for index, role in enumerate(roles):
            block, bg = self._subcard(self.exp_host, "experience", index, tint)
            position = self._labeled(block, "Position", role.get("position") or "", bg)
            company = self._labeled(block, "Company", role.get("company") or "", bg)
            location = self._labeled(block, "Location", role.get("location") or "", bg)
            dates = tk.Frame(block, bg=bg)
            dates.pack(fill="x")
            start_box = tk.Frame(dates, bg=bg)
            end_box = tk.Frame(dates, bg=bg)
            start_box.pack(side="left", fill="x", expand=True)
            end_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
            start = self._labeled(start_box, "Start", role.get("start") or "", bg)
            end = self._labeled(end_box, "End", role.get("end") or "", bg)
            tk.Label(block, text="Description", bg=bg, fg=self._GRAY, font=self.small).pack(anchor="w", pady=(8, 0))
            description = self._text(block, role.get("description") or "", 4, bg)
            row = {
                "position": position,
                "company": company,
                "location": location,
                "start": start,
                "end": end,
                "description": description,
            }
            self.role_rows.append(row)
            ttk.Button(block, text="Remove", command=lambda item=row: self._remove_role(item)).pack(anchor="w", pady=(6, 0))
        self._cover_wheel(self.exp_host)

    def _read_roles(self) -> list[dict]:
        return [
            {
                "position": row["position"].get().strip(),
                "company": row["company"].get().strip(),
                "location": row["location"].get().strip(),
                "start": row["start"].get().strip(),
                "end": row["end"].get().strip(),
                "description": row["description"].get("1.0", "end").strip(),
            }
            for row in self.role_rows
        ]

    def _add_role(self) -> None:
        self.profile["experience"] = self._read_roles() + [profiledoc.empty_role()]
        self._rerender(self._render_roles)

    def _remove_role(self, item: dict) -> None:
        roles = self._read_roles()
        index = self.role_rows.index(item)
        del roles[index]
        self.profile["experience"] = roles
        self._rerender(self._render_roles)

    def _build_skills(self) -> None:
        self.skill_box, self._skill_tint = self._card("SKILLS", "skills")
        self.skill_host = tk.Frame(self.skill_box, bg=self._skill_tint)
        self.skill_host.pack(fill="x", pady=(8, 0))
        self.skill_host.bind("<Configure>", self._place_skills)
        add = tk.Frame(self.skill_box, bg=self._skill_tint)
        add.pack(fill="x", pady=(8, 0))
        entry_host = tk.Frame(add, bg=self._skill_tint)
        entry_host.pack(side="left", fill="x", expand=True)
        self.skill_entry = self._entry(entry_host, "", self._skill_tint, watch=False)
        self.skill_entry.bind("<Return>", lambda _e: self._add_skill())
        ttk.Button(add, text="Add skill", command=self._add_skill).pack(side="left", padx=(8, 0), pady=(6, 0))
        self._place_skills()

    def _place_skills(self, _event=None) -> None:
        if self._placing:
            return
        self._placing = True
        self.skill_host.unbind("<Configure>")
        try:
            for child in self.skill_host.winfo_children():
                child.destroy()
            if not self.skills:
                self._empty(self.skill_host, True, self._skill_tint)
                self.skill_host.configure(height=28)
                self._cover_wheel(self.skill_host)
                return
            width = max(self.skill_host.winfo_width(), 560)
            x = y = row_h = 0
            for index, skill in enumerate(self.skills):
                chip = self._skill_chip(skill, index)
                chip.update_idletasks()
                w = chip.winfo_reqwidth()
                h = chip.winfo_reqheight()
                if x and x + w > width:
                    x = 0
                    y += row_h + 6
                    row_h = 0
                chip.place(x=x, y=y)
                x += w + 6
                row_h = max(row_h, h)
            self.skill_host.configure(height=y + row_h + 4)
            self._cover_wheel(self.skill_host)
        finally:
            self._placing = False
            self.skill_host.bind("<Configure>", self._place_skills)

    def _skill_chip(self, skill: str, index: int) -> tk.Canvas:
        fill = self._shade("skills", index)
        canvas = tk.Canvas(
            self.skill_host,
            bg=self._skill_tint,
            highlightthickness=0,
            bd=0,
            takefocus=0,
            height=1,
            width=1,
        )
        inner = tk.Frame(canvas, bg=fill)
        tk.Label(inner, text=skill, bg=fill, fg=self._GREEN, font=self.font).pack(side="left")
        tk.Button(
            inner,
            text="×",
            relief="flat",
            bd=0,
            bg=fill,
            fg=self._GREEN,
            activebackground=fill,
            activeforeground=self._GREEN,
            command=lambda n=index: self._remove_skill(n),
            padx=2,
            pady=0,
        ).pack(side="left")
        canvas.create_window((12, 8), window=inner, anchor="nw")
        inner.update_idletasks()
        width = inner.winfo_reqwidth() + 24
        height = inner.winfo_reqheight() + 16
        canvas.configure(width=width, height=height)
        points = _round_points(1, 1, width - 2, height - 2, 12)
        canvas.create_polygon(points, smooth=False, fill=fill, outline="", tags="shape")
        canvas.tag_lower("shape")
        return canvas

    def _add_skill(self) -> None:
        text = self.skill_entry.get().strip()
        if not text:
            return
        self.skills.append(text)
        self.skill_entry.delete(0, "end")
        self._touch()
        self._place_skills()

    def _remove_skill(self, index: int) -> None:
        if 0 <= index < len(self.skills):
            del self.skills[index]
            self._touch()
            self._place_skills()

    def _build_education(self) -> None:
        self.edu_box, self._edu_tint = self._card("EDUCATION", "education")
        self.edu_host = tk.Frame(self.edu_box, bg=self._edu_tint)
        self.edu_host.pack(fill="x")
        ttk.Button(self.edu_box, text="Add education", command=self._add_school).pack(anchor="w", pady=(8, 0))
        self._render_schools()

    def _render_schools(self) -> None:
        for child in self.edu_host.winfo_children():
            child.destroy()
        self.school_rows = []
        schools = self.profile["education"]
        tint = self._edu_tint
        self._empty(self.edu_host, not schools, tint)
        for index, school in enumerate(schools):
            block, bg = self._subcard(self.edu_host, "education", index, tint)
            school_name = self._labeled(block, "University / college", school.get("school") or "", bg)
            location = self._labeled(block, "Location", school.get("location") or "", bg)
            dates = tk.Frame(block, bg=bg)
            dates.pack(fill="x")
            start_box = tk.Frame(dates, bg=bg)
            end_box = tk.Frame(dates, bg=bg)
            start_box.pack(side="left", fill="x", expand=True)
            end_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
            start = self._labeled(start_box, "Start", school.get("start") or "", bg)
            end = self._labeled(end_box, "End", school.get("end") or "", bg)
            degree = self._labeled(block, "Degree / course", school.get("degree") or "", bg)
            specialization = self._labeled(block, "Specialization", school.get("specialization") or "", bg)
            tk.Label(block, text="Description", bg=bg, fg=self._GRAY, font=self.small).pack(anchor="w", pady=(8, 0))
            description = self._text(block, school.get("description") or "", 3, bg)
            row = {
                "school": school_name,
                "location": location,
                "start": start,
                "end": end,
                "degree": degree,
                "specialization": specialization,
                "description": description,
            }
            self.school_rows.append(row)
            ttk.Button(block, text="Remove", command=lambda item=row: self._remove_school(item)).pack(anchor="w", pady=(6, 0))
        self._cover_wheel(self.edu_host)

    def _read_schools(self) -> list[dict]:
        return [
            {
                "school": row["school"].get().strip(),
                "location": row["location"].get().strip(),
                "start": row["start"].get().strip(),
                "end": row["end"].get().strip(),
                "degree": row["degree"].get().strip(),
                "specialization": row["specialization"].get().strip(),
                "description": row["description"].get("1.0", "end").strip(),
            }
            for row in self.school_rows
        ]

    def _add_school(self) -> None:
        self.profile["education"] = self._read_schools() + [profiledoc.empty_school()]
        self._rerender(self._render_schools)

    def _remove_school(self, item: dict) -> None:
        schools = self._read_schools()
        del schools[self.school_rows.index(item)]
        self.profile["education"] = schools
        self._rerender(self._render_schools)

    def _build_projects(self) -> None:
        self.project_box, self._project_tint = self._card("PROJECTS", "projects")
        self.project_host = tk.Frame(self.project_box, bg=self._project_tint)
        self.project_host.pack(fill="x")
        ttk.Button(self.project_box, text="Add project", command=self._add_project).pack(anchor="w", pady=(8, 0))
        self._render_projects()

    def _render_projects(self) -> None:
        for child in self.project_host.winfo_children():
            child.destroy()
        self.project_rows = []
        projects = self.profile["projects"]
        tint = self._project_tint
        self._empty(self.project_host, not projects, tint)
        for index, project in enumerate(projects):
            block, bg = self._subcard(self.project_host, "projects", index, tint)
            title = self._labeled(block, "Title", project.get("title") or "", bg)
            tk.Label(block, text="Description", bg=bg, fg=self._GRAY, font=self.small).pack(anchor="w", pady=(8, 0))
            description = self._text(block, project.get("description") or "", 3, bg)
            row = {"title": title, "description": description}
            self.project_rows.append(row)
            ttk.Button(block, text="Remove", command=lambda item=row: self._remove_project(item)).pack(anchor="w", pady=(6, 0))
        self._cover_wheel(self.project_host)

    def _read_projects(self) -> list[dict]:
        return [
            {
                "title": row["title"].get().strip(),
                "description": row["description"].get("1.0", "end").strip(),
            }
            for row in self.project_rows
        ]

    def _add_project(self) -> None:
        self.profile["projects"] = self._read_projects() + [profiledoc.empty_project()]
        self._rerender(self._render_projects)

    def _remove_project(self, item: dict) -> None:
        projects = self._read_projects()
        del projects[self.project_rows.index(item)]
        self.profile["projects"] = projects
        self._rerender(self._render_projects)

    def _links_from_rows(self, strip: bool = False) -> list[dict]:
        rows = []
        for row in self.link_rows:
            title = row["title"].get() if row["fresh"] else str(row["title"] or "")
            url = row["value"].get()
            if strip:
                title = title.strip()
                url = url.strip()
            item = {"title": title, "url": url}
            if row["fresh"]:
                item["fresh"] = True
            rows.append(item)
        return rows

    def _form_state(self) -> tuple:
        return (
            self.name.get(),
            self.email.get(),
            self.phone.get(),
            self.location.get(),
            tuple((item["title"], item["url"]) for item in self._links_from_rows()),
            self.summary.get("1.0", "end-1c"),
            tuple(
                (
                    row["position"].get(),
                    row["company"].get(),
                    row["location"].get(),
                    row["start"].get(),
                    row["end"].get(),
                    row["description"].get("1.0", "end-1c"),
                )
                for row in self.role_rows
            ),
            tuple(
                (row["title"].get(), row["description"].get("1.0", "end-1c"))
                for row in self.project_rows
            ),
            tuple(self.skills),
            tuple(
                (
                    row["school"].get(),
                    row["location"].get(),
                    row["start"].get(),
                    row["end"].get(),
                    row["degree"].get(),
                    row["specialization"].get(),
                    row["description"].get("1.0", "end-1c"),
                )
                for row in self.school_rows
            ),
        )

    def _collect(self) -> dict:
        links = [
            {"title": item["title"], "url": item["url"]}
            for item in self._links_from_rows(strip=True)
            if item["title"] or item["url"]
        ]
        return profiledoc.normalize_profile(
            {
                "contact": {
                    "name": self.name.get().strip(),
                    "email": self.email.get().strip(),
                    "phone": self.phone.get().strip(),
                    "location": self.location.get().strip(),
                    "links": links,
                },
                "summary": self.summary.get("1.0", "end").strip(),
                "experience": self._read_roles(),
                "projects": self._read_projects(),
                "skills": list(self.skills),
                "education": self._read_schools(),
            }
        )

    def save(self) -> None:
        record = self._collect()
        if not messagebox.askyesno("profile.json", "Save these details to profile.json?"):
            return
        profiledoc.save_profile(self.app.profile_json, record)
        self._loading = True
        self.profile = record
        self._render_links()
        self._loading = False
        self._saved_form = self._form_state()
        self.dirty = False
        self.save_btn.configure(state="disabled")
        self.app._status("Saved profile.json")

    def close(self) -> None:
        if self.dirty and not messagebox.askyesno("Profile", "Close without saving these edits?"):
            return
        if self.app._profile_window is self:
            self.app._profile_window = None
        self.win.destroy()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone USB GGUF chat")
    parser.add_argument("--models", help="Folder of GGUF files (USB root)")
    parser.add_argument("--n-ctx", type=int, default=usbchat.N_CTX_DEFAULT)
    parser.add_argument(
        "--memory-board",
        default="",
        help="Open a named test board, such as library. The same name reopens that board. Omit this to use the chat board.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = tk.Tk()
    UsbChatApp(root, args)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
