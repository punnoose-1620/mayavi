"""Standalone USB chat window. Copy this folder next to the GGUFs."""

from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import committee
import formatter
import jobapp
import profiledoc
import usbchat


class _HoverTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

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
        self.notes_file = usbchat.notes_path(self.data_root)
        self.profile_file = usbchat.profile_path(self.data_root)
        self.profile_json = profiledoc.profile_json_path(self.data_root)
        self.n_ctx = args.n_ctx

        self.choices: list[usbchat.ModelChoice] = []
        self.engine = None
        self.loaded_path: Path | None = None
        self.busy = False
        self.stop_event = threading.Event()
        self.session_path = usbchat.new_session_path(self.log_root)
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
        self.github_var = tk.StringVar(value="")
        self.seed_dir: Path | None = None
        self.seed_var = tk.StringVar(value="No project folder")
        self._turn_prompt_tokens = 0
        self._turn_completion_tokens = 0
        self._spin_angle = 0
        self._spin_after: str | None = None

        usbchat.purge_old_logs(self.log_root)
        self._build()
        self.refresh_models()
        self._status(
            f"Session {self.session_path.name}  ·  models {self.models_root}  ·  notes {self.notes_file.name}"
        )

    def _build(self) -> None:
        self.root.title("USB chat")
        self.root.geometry("920x700")
        self.root.minsize(420, 360)

        pad, gap = 16, 8
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = ttk.Frame(self.root)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self._canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0)
        page_scroll = ttk.Scrollbar(shell, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=page_scroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        page_scroll.grid(row=0, column=1, sticky="ns")

        self._page = ttk.Frame(self._canvas)
        self._page_id = self._canvas.create_window((0, 0), window=self._page, anchor="nw")
        self._page.columnconfigure(0, weight=1)
        self._page.rowconfigure(2, weight=1)

        top = ttk.Frame(self._page, padding=(pad, 12, pad, gap))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Model").pack(side="left")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(top, textvariable=self.model_var, state="readonly", width=52)
        self.model_box.pack(side="left", padx=(gap, gap), fill="x", expand=True)
        ttk.Button(top, text="Reload", command=self.refresh_models).pack(side="left")

        ttk.Label(self._page, text="History", font=self._title_font, padding=(pad, 12, pad, 6)).grid(
            row=1, column=0, sticky="w"
        )

        mid = ttk.Frame(self._page, padding=(pad, 0, pad, 0))
        mid.grid(row=2, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        self.transcript = tk.Text(
            mid,
            wrap="word",
            height=12,
            state="disabled",
            font=self._ui_font,
            padx=16,
            pady=12,
            background="#f7f7f7",
        )
        scroll = ttk.Scrollbar(mid, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=self._on_scroll(scroll))
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.transcript.tag_configure("user", foreground="#0b57d0", spacing3=4)
        self.transcript.tag_configure("assistant", foreground="#1a7f37", spacing3=4)
        self.transcript.tag_configure("system", foreground="#5f6368", spacing1=6, spacing3=4)
        self.transcript.tag_configure("title_user", foreground="#0b57d0", font=self._title_font)
        self.transcript.tag_configure("title_assistant", foreground="#1a7f37", font=self._title_font)
        self.transcript.tag_configure("title_system", foreground="#5f6368", font=self._title_font)
        self.transcript.tag_configure("heading1", foreground="#1a7f37", font=(self._ui_font[0], 16, "bold"), spacing1=8, spacing3=4)
        self.transcript.tag_configure("heading2", foreground="#1a7f37", font=(self._ui_font[0], 13, "bold"), spacing1=6, spacing3=4)
        self.transcript.tag_configure("heading3", foreground="#1a7f37", font=self._title_font, spacing1=4, spacing3=2)
        self.transcript.tag_configure("empty", foreground="#8a8a8a", font=(self._ui_font[0], 11, "italic"))
        self.transcript.bind("<Button-3>", self._reply_menu)
        self.transcript.bind("<Control-c>", lambda e: None)
        self._show_history_empty()

        self.quote_row = ttk.Frame(self._page, padding=(pad, gap, pad, 0))
        self.quote_var = tk.StringVar(value="")
        ttk.Label(self.quote_row, textvariable=self.quote_var, foreground="#5f6368").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(self.quote_row, text="Clear quote", command=self.clear_quote).pack(side="right")

        self.attach_row = ttk.Frame(self._page, padding=(pad, gap, pad, 0))
        self.attach_row.grid(row=4, column=0, sticky="ew")
        self.attach_var = tk.StringVar(value="No document attached")
        ttk.Label(self.attach_row, textvariable=self.attach_var).pack(side="left", fill="x", expand=True)
        folder_attach = ttk.Button(self.attach_row, text="Attach folder…", command=self.attach_folder)
        folder_attach.pack(side="right", padx=(gap, 0))
        _HoverTip(
            folder_attach,
            "Read pdf, docx, xlsx, txt, md, and csv in this folder before the model starts. "
            "Other files are skipped. A long folder is read in parts so it fits the context window.",
        )
        ttk.Button(self.attach_row, text="Attach…", command=self.attach).pack(side="right", padx=(gap, 0))
        ttk.Button(self.attach_row, text="Clear", command=self.clear_attach).pack(side="right")

        self.coding_row = ttk.Frame(self._page, padding=(pad, gap, pad, 0))
        self.coding_row.grid(row=5, column=0, sticky="ew")
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
            "from Profile… only, then a short match summary.",
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

        self.github_row = ttk.Frame(self._page, padding=(pad, gap, pad, 0))
        ttk.Label(self.github_row, text="GitHub URL").pack(side="left")
        self.github_entry = ttk.Entry(self.github_row, textvariable=self.github_var)
        self.github_entry.pack(side="left", fill="x", expand=True, padx=(10, 8))
        _HoverTip(
            self.github_entry,
            "Optional public https://github.com/owner/repo. Used only while Coding is on. "
            "Leave empty if you pick a local folder.",
        )
        ttk.Label(self.github_row, textvariable=self.seed_var, foreground="#5f6368").pack(
            side="left", padx=(0, 8)
        )
        folder_btn = ttk.Button(self.github_row, text="Folder…", command=self.pick_seed_folder)
        folder_btn.pack(side="right")
        _HoverTip(
            folder_btn,
            "Pick a local folder. Files are copied into a new work folder on the stick; "
            "your original folder is not edited. Cannot be used with a GitHub URL.",
        )
        ttk.Button(self.github_row, text="Clear folder", command=self.clear_seed_folder).pack(
            side="right", padx=(0, 8)
        )
        self.github_var.trace_add("write", self._on_github_edit)

        self.web_row = ttk.Frame(self._page, padding=(pad, gap, pad, 0))
        self.web_search_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.web_row,
            text="Web Search",
            variable=self.web_search_var,
            command=self._on_web,
        ).pack(side="left")
        star = ttk.Label(self.web_row, text="*", foreground="#5f6368")
        star.pack(side="left", padx=(2, 0))
        _HoverTip(
            star,
            "Web Search takes extra time and model passes. Use it only when you need live internet.",
        )

        ttk.Label(self._page, text="Message", font=self._title_font, padding=(pad, 16, pad, 6)).grid(
            row=8, column=0, sticky="w"
        )
        input_row = ttk.Frame(self._page, padding=(pad, 0, pad, 16))
        input_row.grid(row=9, column=0, sticky="ew")
        self.input = tk.Text(
            input_row,
            height=4,
            wrap="word",
            font=self._ui_font,
            background="#ffffff",
            padx=12,
            pady=10,
        )
        self.input.pack(side="left", fill="x", expand=True)
        self.send_btn = ttk.Button(input_row, text="Send", command=self.send)
        self.send_btn.pack(side="right", padx=(12, 0), fill="y")
        self.spin_host = ttk.Frame(input_row)
        self.spin = tk.Canvas(
            self.spin_host,
            width=36,
            height=36,
            highlightthickness=0,
            borderwidth=0,
            background=self.root.cget("background"),
        )
        self.spin.pack(expand=True)
        self.input.bind("<Control-Return>", self._send_shortcut)
        self.input.bind("<FocusIn>", self._clear_input_hint)
        self.input.bind("<FocusOut>", self._restore_input_hint)
        self._restore_input_hint()

        buttons = ttk.Frame(self._page, padding=(pad, 0, pad, 12))
        buttons.grid(row=10, column=0, sticky="ew")
        ttk.Button(buttons, text="Stop", command=self.stop).pack(side="left")
        ttk.Button(buttons, text="New session", command=self.new_session).pack(side="left", padx=(gap, 0))
        ttk.Button(buttons, text="Save transcript PDF", command=self.save_pdf).pack(side="right")
        ttk.Button(buttons, text="Print", command=self.print_pdf).pack(side="right", padx=(0, gap))
        ttk.Button(buttons, text="Notes…", command=self.notes_dialog).pack(side="right", padx=(0, gap))
        ttk.Button(buttons, text="View profile", command=self.profile_dialog).pack(side="right", padx=(0, gap))
        ttk.Button(buttons, text="Profile…", command=self.profile_dialog).pack(side="right", padx=(0, gap))

        self.status_var = tk.StringVar(value="")
        ttk.Label(self._page, textvariable=self.status_var, padding=(pad, 0, pad, 16)).grid(
            row=11, column=0, sticky="ew"
        )

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
        while widget is not None:
            if widget in {self.transcript, self.input}:
                return None
            if widget.winfo_toplevel() is not self.root:
                return None
            widget = getattr(widget, "master", None)
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self._canvas.yview_scroll(-1, "units")
        else:
            self._canvas.yview_scroll(1, "units")
        return "break"

    def _on_scroll(self, scrollbar: ttk.Scrollbar):
        def set_view(*args):
            scrollbar.set(*args)
            if self._pin_bottom:
                return None
            if args and float(args[0]) <= 0.001:
                self.root.after(50, self.load_older)
            return None

        return set_view

    def _status(self, text: str) -> None:
        self.status_var.set(text)

    def _ui_status(self, text: str) -> None:
        self.root.after(0, lambda t=text: self._begin_step(t))

    def _begin_step(self, step: str) -> None:
        self._step = step
        self._step_chars = 0
        self._step_got_text = False
        self._step_tick = 0
        self._status(step)
        self._schedule_step_tail()

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
        tails = ("", " · still working", " · this can take a while on a large model")
        self._status(self._step + tails[self._step_tick])
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
            label = self._step or "Writing the answer"
            self._status(f"{label} · {self._step_chars} chars")

        self.root.after(0, apply)

    def _set_web_row(self, online: bool) -> None:
        if online:
            self.web_row.grid(row=7, column=0, sticky="ew")
            self.web_visible = True
        elif not self.web_search_var.get():
            self.web_row.grid_remove()
            self.web_visible = False
        self._sync_page()

    def _on_coding(self) -> None:
        if self.coding_var.get():
            self.job_var.set(False)
            self.update_var.set(False)
            self.github_row.grid(row=6, column=0, sticky="ew")
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

    def _show_no_earlier_history(self) -> None:
        if self._history_empty or self._end_of_history:
            return
        self._end_of_history = True
        self.transcript.configure(state="normal")
        self.transcript.insert(
            "1.0",
            "No earlier history. Nothing is stored before this, or older logs were deleted.\n\n",
            "empty",
        )
        self.transcript.configure(state="disabled")

    def _show_history_empty(self) -> None:
        self._history_empty = True
        self._end_of_history = False
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.insert(
            "1.0",
            "No messages yet. Type below and press Send.",
            "empty",
        )
        self.transcript.configure(state="disabled")

    def _clear_history_empty(self) -> None:
        if not self._history_empty:
            return
        self._history_empty = False
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

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
            return
        if self._spin_after is not None:
            self.root.after_cancel(self._spin_after)
            self._spin_after = None
        if self._step_after is not None:
            self.root.after_cancel(self._step_after)
            self._step_after = None
        self.spin_host.pack_forget()
        self.send_btn.pack(side="right", padx=(12, 0), fill="y")
        self.input.configure(state="normal", background="#ffffff")
        self._restore_input_hint()

    def _role_look(self, role: str) -> tuple[str, str, str]:
        if role == "user":
            return "👤", "You", "title_user"
        if role == "assistant":
            return "🤖", "Model", "title_assistant"
        return "•", "System", "title_system"

    def _quote_button(self, body: str) -> ttk.Button:
        holder = {"text": body}

        def quote() -> None:
            self._set_quote(holder["text"])

        btn = ttk.Button(self.transcript, text="↩", width=3, command=quote)
        btn.holder = holder  # type: ignore[attr-defined]
        _HoverTip(btn, "Reply to this message")
        return btn

    def _action_bar(self, body: str, extras: dict | None) -> ttk.Frame:
        extras = extras or {}
        pages = extras.get("html_pages")
        if pages is None:
            pages = formatter.html_pages(formatter.format_blocks(body))
        pdfs = [p for p in (extras.get("pdf_paths") or []) if p]
        profile = extras.get("profile_update") or {}
        record = extras.get("profile_record")
        frame = ttk.Frame(self.transcript)
        if record:
            save = ttk.Button(
                frame,
                text="Save to profile",
                command=lambda rec=record: self._save_profile_record(rec),
            )
            save.pack(side="left")
            _HoverTip(save, "Merge these checked details into profile.json")
        else:
            save = ttk.Button(
                frame,
                text="Save to notes",
                command=lambda b=body, p=profile: self._save_turn_notes(b, p),
            )
            save.pack(side="left")
            _HoverTip(save, "Append this reply, or the saved personal details, to notes.md")
        if pages:
            view = ttk.Button(frame, text="View HTML", command=lambda ps=pages: self._view_html(ps))
            view.pack(side="left", padx=(8, 0))
        saves = [item for item in (extras.get("pdf_saves") or []) if item.get("path")]
        if saves:
            for item in saves:
                path = str(item["path"])
                label = str(item.get("label") or "Save PDF")
                pdf_btn = ttk.Button(frame, text=label, command=lambda p=path: self._save_turn_pdf([p]))
                pdf_btn.pack(side="left", padx=(8, 0))
        elif pdfs:
            pdf_btn = ttk.Button(frame, text="Save PDF", command=lambda paths=pdfs: self._save_turn_pdf(paths))
            pdf_btn.pack(side="left", padx=(8, 0))
        return frame

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

    def _insert_blocks(self, index: str, text: str) -> None:
        blocks = formatter.format_blocks(text)
        if index == "end":
            for block in blocks:
                self._write_block("end", block)
            return
        for block in reversed(blocks):
            self._write_block(index, block)

    def _write_block(self, index: str, block) -> None:
        kind = block.kind
        if kind == "heading":
            level = 3 if block.level > 3 else max(1, block.level)
            self.transcript.insert(index, block.text + "\n", f"heading{level}")
            return
        if kind == "code":
            lines = max(2, min(14, block.text.count("\n") + 1))
            mono = ("Consolas", 10) if sys.platform == "win32" else ("monospace", 10)
            box = tk.Text(
                self.transcript,
                height=lines,
                wrap="word",
                font=mono,
                background="#ececec",
                padx=8,
                pady=6,
                highlightthickness=0,
                borderwidth=0,
            )
            box.insert("1.0", block.text)
            box.configure(state="disabled")
            if index == "end":
                self.transcript.window_create("end", window=box)
                self.transcript.insert("end", "\n")
            else:
                self.transcript.insert(index, "\n")
                self.transcript.window_create(index, window=box)
            return
        if kind == "list":
            rows = [
                (f"{i}. " if block.ordered else "• ") + item
                for i, item in enumerate(block.items, 1)
            ]
            self.transcript.insert(index, "\n".join(rows) + "\n", "assistant")
            return
        if kind == "quote":
            self.transcript.insert(index, block.text + "\n", "system")
            return
        if kind == "rule":
            self.transcript.insert(index, "—\n", "system")
            return
        if kind == "html_doc":
            self.transcript.insert(index, f"HTML page: {block.name}\n", "system")
            return
        self.transcript.insert(index, (block.text or "") + "\n", "assistant")

    def _embed_actions(self, index: str, body: str, extras: dict | None) -> None:
        bar = self._action_bar(body, extras)
        if index == "end":
            self.transcript.insert("end", "\n")
            self.transcript.window_create("end", window=bar)
            self.transcript.insert("end", "\n")
            return
        self.transcript.insert(index, "\n")
        self.transcript.window_create(index, window=bar)
        self.transcript.insert(index, "\n")

    def _insert_header(self, role: str, body: str) -> dict:
        icon, title, title_tag = self._role_look(role)
        holder = {"text": body}
        self.transcript.configure(state="normal")
        if self.transcript.get("1.0", "end-1c").strip():
            self.transcript.insert("end", "\n")
        if role in {"user", "assistant"}:
            btn = self._quote_button(body)
            holder = btn.holder  # type: ignore[attr-defined]
            self.transcript.window_create("end", window=btn)
            self.transcript.insert("end", "  ")
        self.transcript.insert("end", f"{icon}  {title}\n", title_tag)
        self.transcript.configure(state="disabled")
        return holder

    def _append(self, role: str, text: str, *, remember: bool = True, extras: dict | None = None) -> None:
        self._clear_history_empty()
        holder = self._insert_header(role, text)
        self.transcript.configure(state="normal")
        if role == "assistant":
            self._insert_blocks("end", text)
            self._embed_actions("end", text, extras)
        else:
            self.transcript.insert("end", f"{text}\n", role)
        self.transcript.configure(state="disabled")
        if remember:
            self.messages.append((role, text))
        self.transcript.see("end")
        holder["text"] = text

    def refresh_models(self) -> None:
        free = usbchat.free_ram()
        self.choices = usbchat.pickable_models(self.models_root, free)
        labels = [c.label for c in self.choices]
        self.model_box["values"] = labels
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
        self.attach_var.set(f"{usbchat.attach_label(resolved)} ({len(text)} chars, read-only)")

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
        suffixes = ", ".join(sorted({path.suffix.lower().lstrip(".") for path in files}))
        extra = f" First {usbchat.FOLDER_MAX_FILES} only." if truncated else ""
        self.attach_var.set(
            f"{usbchat.FOLDER_ICON} {folder}  ·  {len(files)} document(s): {suffixes}, read-only.{extra}"
        )

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
            self.quote_row.grid(row=3, column=0, sticky="ew")
            self._sync_page()

    def reply_selection(self) -> None:
        try:
            text = self.transcript.get("sel.first", "sel.last").strip()
        except tk.TclError:
            text = ""
        if not text:
            return
        self._set_quote(text)

    def _reply_menu(self, event) -> None:
        try:
            if self.transcript.tag_ranges("sel"):
                self.reply_selection()
        except tk.TclError:
            pass

    def new_session(self) -> None:
        if self.busy:
            return
        self.session_path = usbchat.new_session_path(self.log_root)
        self.session_turns = []
        self.older_turns = []
        self.older_files = []
        self.messages = []
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.clear_quote()
        self._show_history_empty()
        self._status(f"New session {self.session_path.name}")

    def _show_latest(self) -> None:
        self.transcript.see("end")
        self._pin_bottom = False

    def load_older(self) -> None:
        if self.loading_older or self.busy:
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
                    self._prepend_message("assistant", str(turn["response"]), extras)
                    self.messages.insert(0, ("assistant", str(turn["response"])))
                user_line = usbchat.display_user_prompt(turn)
                if user_line:
                    self._prepend_message("user", user_line)
                    self.messages.insert(0, ("user", user_line))
            self.transcript.configure(state="normal")
            self.transcript.insert("1.0", f"— earlier session {nxt.name} —\n", "system")
            self.transcript.configure(state="disabled")
        self.loading_older = False
        if initial:
            self.transcript.see("end")
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
                    "Open Profile… and write your professional background first.",
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
            self._begin_step(f"Loading {choice.label}")
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

    def _complete(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        parts: list[str] = []
        for piece in self.engine.stream(messages, self.stop_event, max_tokens=max_tokens):
            parts.append(piece)
            self._add_step_chars(len(piece))
            if self.stop_event.is_set():
                break
        if self.engine is not None:
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

    def _structure_saved_profile(self, state: dict, reply_parts: list[str]) -> None:
        notes = "\n\n".join(str(note) for note in (state.get("notes") or []) if str(note).strip())
        source = str(state.get("source_text") or notes)
        self._ui_status("Update profile: structuring the profile")
        result = profiledoc.build_update(
            self._complete,
            notes or source,
            str(state.get("instruction") or ""),
            source,
        )
        reply_parts.append(str(result.get("reply") or "").strip())
        if result.get("profile_record"):
            self._profile_turn = {"profile_record": result["profile_record"]}

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
        self._ui_status("Update profile: structuring the profile")
        result = profiledoc.build_update(self._complete, model_text, user_text, source)
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
            self._structure_saved_profile(state, reply_parts)
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
                result = jobapp.run_job_application(
                    complete=self._complete,
                    job_text=user_text,
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
                result = committee.run_coding(
                    complete=self._coding_complete,
                    user_text=run_text,
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
                result = committee.run_review(
                    complete=self._coding_complete,
                    user_text=run_text,
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
                self.root.after(0, self._begin_assistant)
                streamed = True
                for piece in self.engine.stream(messages, self.stop_event):
                    reply_parts.append(piece)
                    self._add_step_chars(len(piece))
                    self.root.after(0, lambda p=piece: self._stream_piece(p))
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
        if err and not reply:
            reply = "Stopped." if err == "stopped" else f"(error: {err})"
        elif not doc_answer and not job and not coding and not stakes and not reply.startswith("(error:"):
            reply = committee.finish_off_coding(user_text, reply)

        def finish() -> None:
            self._set_busy(False)
            if err and not reply_parts:
                self._append("system", reply)
            elif reply:
                if streamed:
                    self._finish_stream(reply, extras)
                else:
                    self._append("assistant", reply, extras=extras)
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
                "time": usbchat.utc_now(),
                "model": choice.label,
                "prompt": user_text,
                "shown": shown,
                "response": reply,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
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
            self.prompt_tokens_total += prompt_tokens
            self.completion_tokens_total += completion_tokens
            self._status(
                f"{choice.label}  ·  this turn {prompt_tokens}+{completion_tokens} tok  ·  "
                f"session {self.prompt_tokens_total}+{self.completion_tokens_total} tok"
            )

        self.root.after(0, finish)

    def _prepend_message(self, role: str, text: str, extras: dict | None = None) -> None:
        self.transcript.configure(state="normal")
        if role == "assistant":
            self._embed_actions("1.0", text, extras)
            self._insert_blocks("1.0", text)
        else:
            self.transcript.insert("1.0", f"{text}\n\n", role)
        icon, title, title_tag = self._role_look(role)
        self.transcript.insert("1.0", f"{icon}  {title}\n", title_tag)
        if role in {"user", "assistant"}:
            self.transcript.insert("1.0", "  ")
            self.transcript.window_create("1.0", window=self._quote_button(text))
        self.transcript.configure(state="disabled")

    def _begin_assistant(self) -> None:
        self._clear_history_empty()
        self._stream_holder = self._insert_header("assistant", "")
        self.transcript.configure(state="normal")
        self.transcript.mark_set("stream_start", "end")
        self.transcript.mark_gravity("stream_start", "left")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _finish_stream(self, reply: str, extras: dict | None) -> None:
        self.transcript.configure(state="normal")
        try:
            self.transcript.delete("stream_start", "end")
        except tk.TclError:
            pass
        self._insert_blocks("end", reply)
        self._embed_actions("end", reply, extras)
        self.transcript.configure(state="disabled")
        if self._stream_holder is not None:
            self._stream_holder["text"] = reply
        self.messages.append(("assistant", reply))
        self._stream_holder = None
        self.transcript.see("end")

    def _stream_piece(self, piece: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", piece, "assistant")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

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


class ProfileWindow:
    """Editable profile cards. Profile… and View profile open this same window."""

    _PAGE = "#f7f7f7"
    _CARD = "#ffffff"
    _GREEN = "#1a7f37"
    _GRAY = "#5f6368"
    _MUTED = "#8a8a8a"
    _CHIP = "#e7f5ec"
    _LINE = "#dadce0"

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
        self.skills: list[str] = list(self.profile["skills"])
        self._cards = 0

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
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", self._wheel)
        self.canvas.bind("<Button-5>", self._wheel)

        self._build_header()
        self._build_summary()
        self._build_experience()
        self._build_skills()
        self._build_education()

        bar = tk.Frame(self.win, bg=self._PAGE, padx=16, pady=12)
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.close).pack(side="right")
        ttk.Button(bar, text="Save profile", command=self.save).pack(side="right", padx=(0, 8))
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._loading = False
        self.dirty = False
        self.win.after_idle(self._place_skills)

    def _fit_width(self, event) -> None:
        self.canvas.itemconfigure(self.page_id, width=max(event.width, 1))

    def _wheel(self, event) -> str:
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-1, "units")
        else:
            self.canvas.yview_scroll(1, "units")
        return "break"

    def _touch(self, *_args) -> None:
        if not self._loading:
            self.dirty = True

    def _card(self, title: str) -> tk.Frame:
        outer = tk.Frame(self.page, bg=self._PAGE, padx=16)
        outer.pack(fill="x", pady=(12 if self._cards == 0 else 0, 0))
        self._cards += 1
        box = tk.Frame(outer, bg=self._CARD, padx=16, pady=14, highlightbackground=self._LINE, highlightthickness=1)
        box.pack(fill="x", pady=(0, 12))
        tk.Label(box, text=title, bg=self._CARD, fg=self._GRAY, font=self.small).pack(anchor="w")
        return box

    def _entry(self, parent, value: str, font=None, fg=None) -> tk.Entry:
        field = tk.Entry(
            parent,
            font=font or self.font,
            fg=fg or "#202124",
            bg=self._CARD,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
        )
        field.insert(0, value)
        field.bind("<KeyRelease>", self._touch)
        field.pack(fill="x", pady=(6, 0))
        return field

    def _text(self, parent, value: str, height: int) -> tk.Text:
        field = tk.Text(
            parent,
            height=height,
            wrap="word",
            font=self.font,
            bg=self._CARD,
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            padx=6,
            pady=4,
        )
        if value:
            field.insert("1.0", value)
        field.bind("<KeyRelease>", self._touch)
        field.pack(fill="x", pady=(6, 0))
        return field

    def _empty(self, parent, shown: bool) -> None:
        if shown:
            tk.Label(
                parent,
                text="Nothing saved in this section.",
                bg=self._CARD,
                fg=self._MUTED,
                font=(self.font[0], 11, "italic"),
            ).pack(anchor="w", pady=(8, 0))

    def _build_header(self) -> None:
        box = self._card("CONTACT")
        contact = self.profile["contact"]
        self.name = self._entry(box, contact["name"], font=self.name_font, fg=self._GREEN)
        self.email = self._entry(box, contact["email"])
        self.phone = self._entry(box, contact["phone"])
        self.location = self._entry(box, contact["location"])
        tk.Label(box, text="Links, one per line", bg=self._CARD, fg=self._GRAY, font=self.small).pack(anchor="w", pady=(8, 0))
        self.links = self._text(box, "\n".join(contact["links"]), 3)
        if usbchat.read_profile(self.app.profile_file).strip() and profiledoc.profile_is_empty(self.profile):
            tk.Label(
                box,
                text="profile.md is still on the stick. Saving writes profile.json, which the job committee uses.",
                bg=self._CARD,
                fg=self._GRAY,
                font=self.small,
                wraplength=620,
                justify="left",
            ).pack(anchor="w", pady=(8, 0))

    def _build_summary(self) -> None:
        box = self._card("SUMMARY")
        self.summary = self._text(box, self.profile["summary"], 4)
        self._empty(box, not self.profile["summary"])

    def _build_experience(self) -> None:
        self.exp_box = self._card("EXPERIENCE")
        self.exp_host = tk.Frame(self.exp_box, bg=self._CARD)
        self.exp_host.pack(fill="x")
        ttk.Button(self.exp_box, text="Add role", command=self._add_role).pack(anchor="w", pady=(8, 0))
        self._render_roles()

    def _render_roles(self) -> None:
        for child in self.exp_host.winfo_children():
            child.destroy()
        self.role_rows = []
        roles = self.profile["experience"]
        self._empty(self.exp_host, not roles)
        for role in roles:
            block = tk.Frame(self.exp_host, bg=self._CARD, pady=8)
            block.pack(fill="x")
            title = self._entry(block, role.get("title") or "")
            employer = self._entry(block, role.get("employer") or "")
            dates = tk.Frame(block, bg=self._CARD)
            dates.pack(fill="x")
            start = self._entry(dates, role.get("start") or "")
            end = self._entry(dates, role.get("end") or "")
            start.pack_forget()
            end.pack_forget()
            start.pack(in_=dates, side="left", fill="x", expand=True, pady=(6, 0))
            end.pack(in_=dates, side="left", fill="x", expand=True, padx=(8, 0), pady=(6, 0))
            highlights = self._text(block, "\n".join(role.get("highlights") or []), 3)
            row = {"title": title, "employer": employer, "start": start, "end": end, "highlights": highlights}
            self.role_rows.append(row)
            ttk.Button(block, text="Remove", command=lambda item=row: self._remove_role(item)).pack(anchor="w", pady=(6, 0))

    def _read_roles(self) -> list[dict]:
        roles = []
        for row in self.role_rows:
            highlights = [line.strip() for line in row["highlights"].get("1.0", "end").splitlines() if line.strip()]
            roles.append(
                {
                    "title": row["title"].get().strip(),
                    "employer": row["employer"].get().strip(),
                    "start": row["start"].get().strip(),
                    "end": row["end"].get().strip(),
                    "highlights": highlights,
                }
            )
        return roles

    def _add_role(self) -> None:
        self.profile["experience"] = self._read_roles() + [
            {"title": "", "employer": "", "start": "", "end": "", "highlights": []}
        ]
        self._touch()
        self._render_roles()

    def _remove_role(self, item: dict) -> None:
        roles = self._read_roles()
        index = self.role_rows.index(item)
        del roles[index]
        self.profile["experience"] = roles
        self._touch()
        self._render_roles()

    def _build_skills(self) -> None:
        self.skill_box = self._card("SKILLS")
        self.skill_host = tk.Frame(self.skill_box, bg=self._CARD)
        self.skill_host.pack(fill="x", pady=(8, 0))
        self.skill_host.bind("<Configure>", lambda _e: self._place_skills())
        add = tk.Frame(self.skill_box, bg=self._CARD)
        add.pack(fill="x", pady=(8, 0))
        self.skill_entry = tk.Entry(add, font=self.font)
        self.skill_entry.pack(side="left", fill="x", expand=True)
        self.skill_entry.bind("<Return>", lambda _e: self._add_skill())
        ttk.Button(add, text="Add skill", command=self._add_skill).pack(side="left", padx=(8, 0))
        self._place_skills()

    def _place_skills(self) -> None:
        for child in self.skill_host.winfo_children():
            child.destroy()
        if not self.skills:
            self._empty(self.skill_host, True)
            self.skill_host.configure(height=28)
            return
        width = max(self.skill_host.winfo_width(), 560)
        x = y = row_h = 0
        for index, skill in enumerate(self.skills):
            chip = tk.Frame(self.skill_host, bg=self._CHIP, padx=8, pady=3)
            tk.Label(chip, text=skill, bg=self._CHIP, fg=self._GREEN, font=self.font).pack(side="left")
            tk.Button(
                chip,
                text="×",
                relief="flat",
                bg=self._CHIP,
                fg=self._GREEN,
                command=lambda n=index: self._remove_skill(n),
                padx=2,
                pady=0,
            ).pack(side="left")
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
        self.edu_box = self._card("EDUCATION")
        self.edu_host = tk.Frame(self.edu_box, bg=self._CARD)
        self.edu_host.pack(fill="x")
        ttk.Button(self.edu_box, text="Add education", command=self._add_school).pack(anchor="w", pady=(8, 0))
        self._render_schools()

    def _render_schools(self) -> None:
        for child in self.edu_host.winfo_children():
            child.destroy()
        self.school_rows = []
        schools = self.profile["education"]
        self._empty(self.edu_host, not schools)
        for school in schools:
            block = tk.Frame(self.edu_host, bg=self._CARD, pady=8)
            block.pack(fill="x")
            degree = self._entry(block, school.get("degree") or "")
            name = self._entry(block, school.get("school") or "")
            year = self._entry(block, school.get("year") or "")
            row = {"degree": degree, "school": name, "year": year}
            self.school_rows.append(row)
            ttk.Button(block, text="Remove", command=lambda item=row: self._remove_school(item)).pack(anchor="w", pady=(6, 0))

    def _read_schools(self) -> list[dict]:
        return [
            {
                "degree": row["degree"].get().strip(),
                "school": row["school"].get().strip(),
                "year": row["year"].get().strip(),
            }
            for row in self.school_rows
        ]

    def _add_school(self) -> None:
        self.profile["education"] = self._read_schools() + [{"degree": "", "school": "", "year": ""}]
        self._touch()
        self._render_schools()

    def _remove_school(self, item: dict) -> None:
        schools = self._read_schools()
        del schools[self.school_rows.index(item)]
        self.profile["education"] = schools
        self._touch()
        self._render_schools()

    def _collect(self) -> dict:
        links = [line.strip() for line in self.links.get("1.0", "end").splitlines() if line.strip()]
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
                "skills": list(self.skills),
                "education": self._read_schools(),
            }
        )

    def save(self) -> None:
        record = self._collect()
        if not messagebox.askyesno("profile.json", "Save these details to profile.json?"):
            return
        profiledoc.save_profile(self.app.profile_json, record)
        self.profile = record
        self.dirty = False
        self.app._status("Saved profile.json")

    def close(self) -> None:
        if self.dirty and not messagebox.askyesno("Profile", "Close without saving these edits?"):
            return
        self.win.destroy()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone USB GGUF chat")
    parser.add_argument("--models", help="Folder of GGUF files (USB root)")
    parser.add_argument("--n-ctx", type=int, default=usbchat.N_CTX_DEFAULT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = tk.Tk()
    UsbChatApp(root, args)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
