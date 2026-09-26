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
        self.log_root = usbchat.logs_dir(self.data_root)
        self.notes_file = usbchat.notes_path(self.data_root)
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
        self.quote = ""
        self.attachment: dict | None = None
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
        ttk.Button(self.attach_row, text="Attach…", command=self.attach).pack(side="right", padx=(gap, 0))
        ttk.Button(self.attach_row, text="Clear file", command=self.clear_attach).pack(side="right")

        self.web_row = ttk.Frame(self._page, padding=(pad, gap, pad, 0))
        self.web_search_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.web_row, text="Web Search", variable=self.web_search_var).pack(side="left")
        star = ttk.Label(self.web_row, text="*", foreground="#5f6368")
        star.pack(side="left", padx=(2, 0))
        _HoverTip(
            star,
            "Web Search takes extra time and model passes. Use it only when you need live internet.",
        )

        ttk.Label(self._page, text="Message", font=self._title_font, padding=(pad, 16, pad, 6)).grid(
            row=6, column=0, sticky="w"
        )
        input_row = ttk.Frame(self._page, padding=(pad, 0, pad, 16))
        input_row.grid(row=7, column=0, sticky="ew")
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
        buttons.grid(row=8, column=0, sticky="ew")
        ttk.Button(buttons, text="Stop", command=self.stop).pack(side="left")
        ttk.Button(buttons, text="New session", command=self.new_session).pack(side="left", padx=(gap, 0))
        ttk.Button(buttons, text="Save PDF", command=self.save_pdf).pack(side="right")
        ttk.Button(buttons, text="Print", command=self.print_pdf).pack(side="right", padx=(0, gap))
        ttk.Button(buttons, text="Notes…", command=self.notes_dialog).pack(side="right", padx=(0, gap))

        self.status_var = tk.StringVar(value="")
        ttk.Label(self._page, textvariable=self.status_var, padding=(pad, 0, pad, 16)).grid(
            row=9, column=0, sticky="ew"
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
            widget = getattr(widget, "master", None)
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self._canvas.yview_scroll(-1, "units")
        else:
            self._canvas.yview_scroll(1, "units")
        return "break"

    def _on_scroll(self, scrollbar: ttk.Scrollbar):
        def set_view(*args):
            scrollbar.set(*args)
            if args and float(args[0]) <= 0.001:
                self.root.after(50, self.load_older)
            return None

        return set_view

    def _status(self, text: str) -> None:
        self.status_var.set(text)

    def _ui_status(self, text: str) -> None:
        self.root.after(0, lambda t=text: self._status(t))

    def _set_web_row(self, online: bool) -> None:
        if online:
            self.web_row.grid(row=5, column=0, sticky="ew")
            self.web_visible = True
        elif not self.web_search_var.get():
            self.web_row.grid_remove()
            self.web_visible = False
        self._sync_page()

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

    def _append(self, role: str, text: str, *, remember: bool = True) -> None:
        self._clear_history_empty()
        holder = self._insert_header(role, text)
        self.transcript.configure(state="normal")
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
        self.attachment = {"name": file_path.name, "path": resolved, "text": text}
        self.attach_var.set(f"{usbchat.attach_label(resolved)} ({len(text)} chars, read-only)")

    def clear_attach(self) -> None:
        self.attachment = None
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

    def load_older(self) -> None:
        if self.loading_older or self.busy:
            return
        sessions = [p for p in usbchat.list_sessions(self.log_root) if p != self.session_path]
        already = {p.resolve() for p in self.older_files}
        nxt = next((p for p in sessions if p.resolve() not in already), None)
        if nxt is None:
            self._show_no_earlier_history()
            return
        self.loading_older = True
        turns = usbchat.load_turns(nxt)
        self.older_files.append(nxt)
        self.older_turns = turns + self.older_turns
        if turns:
            self._clear_history_empty()
            for turn in reversed(turns):
                if turn.get("response"):
                    self._prepend_message("assistant", str(turn["response"]))
                    self.messages.insert(0, ("assistant", str(turn["response"])))
                user_line = usbchat.display_user_prompt(turn)
                if user_line:
                    self._prepend_message("user", user_line)
                    self.messages.insert(0, ("user", user_line))
            self.transcript.configure(state="normal")
            self.transcript.insert("1.0", f"— earlier session {nxt.name} —\n", "system")
            self.transcript.configure(state="disabled")
        self.loading_older = False
        self._status(f"Loaded older log {nxt.name} as earlier turns")
        loaded = {p.resolve() for p in self.older_files}
        if not any(p.resolve() not in loaded for p in sessions):
            self._show_no_earlier_history()

    def send(self) -> None:
        if self.busy:
            return
        text = self._input_text()
        if not text:
            return
        choice = self._selected()
        if choice is None:
            messagebox.showerror("Send", "Pick a model that fits RAM.")
            return
        use_web = bool(self.web_visible and self.web_search_var.get())
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
        attachments = [self.attachment] if self.attachment else []
        quote = self.quote
        notes = usbchat.read_notes(self.notes_file)
        messages = usbchat.build_chat_messages(
            notes=notes,
            older_turns=self.older_turns,
            session_turns=self.session_turns,
            quote=quote,
            attachments=attachments,
            user_text=text,
        )
        shown = text
        if quote:
            shown = f"> {quote[: usbchat.QUOTE_CAP]}\n\n{text}"
        if self.attachment:
            shown = f"{usbchat.attach_label(self.attachment['path'])}\n{shown}"
        self._append("user", shown)
        self.input.delete("1.0", "end")
        self._input_hint = False
        self._restore_input_hint()
        self.clear_quote()
        self._set_busy(True)
        self.stop_event.clear()
        self._status(f"Loading {choice.label}…" if self.loaded_path != choice.path else "Thinking…")
        threading.Thread(
            target=self._generate,
            args=(choice, messages, text, attachments, quote, use_web),
            daemon=True,
        ).start()

    def _complete(self, messages: list[dict[str, str]]) -> str:
        parts: list[str] = []
        for piece in self.engine.stream(messages, self.stop_event):
            parts.append(piece)
            if self.stop_event.is_set():
                break
        if self.engine is not None:
            prompt_tokens, completion_tokens = self.engine.last_usage
            self._turn_prompt_tokens += prompt_tokens
            self._turn_completion_tokens += completion_tokens
        return "".join(parts).strip()

    def _ensure_engine(self, choice) -> None:
        if self.engine is not None and self.loaded_path == choice.path:
            return
        self.engine = None
        self.loaded_path = None
        self.engine = usbchat.make_engine(choice.path, n_ctx=self.n_ctx, here=HERE)
        self.loaded_path = choice.path
        self._ui_status(f"Loaded {choice.label}. Thinking…")

    def _generate(self, choice, messages, user_text, attachments, quote, use_web) -> None:
        err = ""
        reply_parts: list[str] = []
        self._turn_prompt_tokens = 0
        self._turn_completion_tokens = 0
        web_meta = {"used": False, "query": "", "urls": [], "log": ""}
        try:
            self._ensure_engine(choice)
            if use_web:
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
                elif web.get("ok"):
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
                else:
                    self._ui_status("Search failed; answering without the web.")
            if not err:
                if usbchat.messages_tokens(messages) > usbchat.token_budget(self.n_ctx) and messages:
                    last = dict(messages[-1])
                    cap = usbchat._blob_char_budget(self.n_ctx, user_text, str((messages[0] or {}).get("content") or ""))
                    last["content"] = str(last.get("content") or "")[:cap]
                    messages = [dict(m) for m in messages[:-1]] + [last]
                self.root.after(0, self._begin_assistant)
                for piece in self.engine.stream(messages, self.stop_event):
                    reply_parts.append(piece)
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
        prompt_tokens = self._turn_prompt_tokens
        completion_tokens = self._turn_completion_tokens
        reply = "".join(reply_parts).strip()
        if err and not reply:
            reply = "Web Search stopped." if err == "stopped" else f"(error: {err})"

        def finish() -> None:
            self._set_busy(False)
            if err and not reply_parts:
                self._append("system", reply)
            elif reply:
                if self._stream_holder is not None:
                    self._stream_holder["text"] = reply
                self.messages.append(("assistant", reply))
                self.transcript.configure(state="normal")
                self.transcript.insert("end", "\n", "assistant")
                self.transcript.configure(state="disabled")
                self._stream_holder = None
            shown = user_text
            if quote:
                shown = f"> {quote[: usbchat.QUOTE_CAP]}\n\n{user_text}"
            if attachments:
                names = "\n".join(usbchat.attach_label(a.get("path") or a["name"]) for a in attachments)
                shown = f"{names}\n{shown}"
            turn = {
                "time": usbchat.utc_now(),
                "model": choice.label,
                "prompt": user_text,
                "shown": shown,
                "response": reply,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "attached": [a.get("path") or a["name"] for a in attachments],
                "quote": quote,
                "web_search": bool(web_meta["used"]),
                "web_query": web_meta["query"],
                "web_urls": web_meta["urls"],
                "web_log": web_meta["log"],
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

    def _prepend_message(self, role: str, text: str) -> None:
        self.transcript.configure(state="normal")
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

        def append_last() -> None:
            last = next((t for t in reversed(self.session_turns) if t.get("response")), None)
            if last is None:
                messagebox.showinfo("notes.md", "No assistant reply in this session yet.")
                return
            snippet = str(last["response"]).strip()
            if not messagebox.askyesno("notes.md", "Append the last model reply to notes.md?"):
                return
            usbchat.append_notes(self.notes_file, snippet)
            win.destroy()
            self._status("Appended last reply to notes.md")

        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(row, text="Save notes", command=save).pack(side="right", padx=(0, 6))
        ttk.Button(row, text="Append last reply", command=append_last).pack(side="left")


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
