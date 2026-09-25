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

        usbchat.purge_old_logs(self.log_root)
        self._build()
        self.refresh_models()
        self._status(
            f"Session {self.session_path.name}  ·  models {self.models_root}  ·  notes {self.notes_file.name}"
        )

    def _build(self) -> None:
        self.root.title("USB chat")
        self.root.geometry("920x700")
        self.root.minsize(720, 520)

        top = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Model").pack(side="left")
        self.model_var = tk.StringVar()
        self.model_box = ttk.Combobox(top, textvariable=self.model_var, state="readonly", width=52)
        self.model_box.pack(side="left", padx=(6, 8), fill="x", expand=True)
        ttk.Button(top, text="Reload", command=self.refresh_models).pack(side="left")

        mid = ttk.Frame(self.root, padding=(10, 0, 10, 0))
        mid.pack(fill="both", expand=True)
        self.transcript = tk.Text(
            mid,
            wrap="word",
            height=24,
            state="disabled",
            font=("Segoe UI", 11) if sys.platform == "win32" else ("sans-serif", 11),
            padx=8,
            pady=8,
        )
        scroll = ttk.Scrollbar(mid, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=self._on_scroll(scroll))
        self.transcript.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.transcript.tag_configure("user", foreground="#0b57d0", spacing1=8, spacing3=4)
        self.transcript.tag_configure("assistant", foreground="#1a7f37", spacing1=8, spacing3=4)
        self.transcript.tag_configure("system", foreground="#5f6368", spacing1=6, spacing3=4)
        self.transcript.bind("<Button-3>", self._reply_menu)
        self.transcript.bind("<Control-c>", lambda e: None)

        quote_row = ttk.Frame(self.root, padding=(10, 4, 10, 0))
        quote_row.pack(fill="x")
        self.quote_var = tk.StringVar(value="")
        ttk.Label(quote_row, textvariable=self.quote_var, foreground="#5f6368").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(quote_row, text="Clear quote", command=self.clear_quote).pack(side="right")

        attach_row = ttk.Frame(self.root, padding=(10, 2, 10, 0))
        attach_row.pack(fill="x")
        self.attach_var = tk.StringVar(value="No document attached")
        ttk.Label(attach_row, textvariable=self.attach_var).pack(side="left", fill="x", expand=True)
        ttk.Button(attach_row, text="Attach…", command=self.attach).pack(side="right", padx=(6, 0))
        ttk.Button(attach_row, text="Clear file", command=self.clear_attach).pack(side="right")

        input_row = ttk.Frame(self.root, padding=(10, 6, 10, 4))
        input_row.pack(fill="x")
        self.input = tk.Text(input_row, height=4, wrap="word", font=("Segoe UI", 11) if sys.platform == "win32" else ("sans-serif", 11))
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", lambda e: self.send())

        buttons = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Send", command=self.send).pack(side="left")
        ttk.Button(buttons, text="Stop", command=self.stop).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Reply", command=self.reply_selection).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="New session", command=self.new_session).pack(side="left", padx=(16, 0))
        ttk.Button(buttons, text="Save PDF", command=self.save_pdf).pack(side="right")
        ttk.Button(buttons, text="Print", command=self.print_pdf).pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="Notes…", command=self.notes_dialog).pack(side="right", padx=(0, 6))

        self.status_var = tk.StringVar(value="")
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 0, 10, 8)).pack(fill="x")

        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def _on_scroll(self, scrollbar: ttk.Scrollbar):
        def set_view(*args):
            scrollbar.set(*args)
            if args and float(args[0]) <= 0.001:
                self.root.after(50, self.load_older)
            return None

        return set_view

    def _status(self, text: str) -> None:
        self.status_var.set(text)

    def _append(self, role: str, text: str, *, remember: bool = True) -> None:
        self.transcript.configure(state="normal")
        prefix = {"user": "You", "assistant": "Model", "system": "System"}.get(role, role)
        start = self.transcript.index("end-1c")
        self.transcript.insert("end", f"{prefix}\n{text}\n\n", role)
        end = self.transcript.index("end-1c")
        tag = f"msg_{len(self.messages)}"
        self.transcript.tag_add(tag, start, end)
        self.transcript.configure(state="disabled")
        if remember:
            self.messages.append((role, text))
        self.transcript.see("end")

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
        self.attachment = {"name": file_path.name, "text": text}
        self.attach_var.set(f"Attached {file_path.name} ({len(text)} chars, read-only)")

    def clear_attach(self) -> None:
        self.attachment = None
        self.attach_var.set("No document attached")

    def clear_quote(self) -> None:
        self.quote = ""
        self.quote_var.set("")

    def reply_selection(self) -> None:
        try:
            text = self.transcript.get("sel.first", "sel.last").strip()
        except tk.TclError:
            text = ""
        if not text:
            messagebox.showinfo("Reply", "Select text in the transcript first.")
            return
        self.quote = text
        shown = text if len(text) <= 80 else text[:77] + "…"
        self.quote_var.set(f"Replying to: {shown}")

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
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.clear_quote()
        self._status(f"New session {self.session_path.name}")

    def load_older(self) -> None:
        if self.loading_older or self.busy:
            return
        sessions = [p for p in usbchat.list_sessions(self.log_root) if p != self.session_path]
        already = {p.resolve() for p in self.older_files}
        nxt = next((p for p in sessions if p.resolve() not in already), None)
        if nxt is None:
            return
        self.loading_older = True
        turns = usbchat.load_turns(nxt)
        self.older_files.append(nxt)
        self.older_turns = turns + self.older_turns
        if turns:
            self.transcript.configure(state="normal")
            insert_at = "1.0"
            block = f"— earlier session {nxt.name} —\n"
            for turn in turns:
                if turn.get("prompt"):
                    block += f"You\n{turn['prompt']}\n\n"
                if turn.get("response"):
                    block += f"Model\n{turn['response']}\n\n"
            self.transcript.insert(insert_at, block, "system")
            self.transcript.configure(state="disabled")
            for turn in reversed(turns):
                if turn.get("response"):
                    self.messages.insert(0, ("assistant", str(turn["response"])))
                if turn.get("prompt"):
                    self.messages.insert(0, ("user", str(turn["prompt"])))
        self.loading_older = False
        self._status(f"Loaded older log {nxt.name} as earlier turns")

    def send(self) -> None:
        if self.busy:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        choice = self._selected()
        if choice is None:
            messagebox.showerror("Send", "Pick a model that fits RAM.")
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
            shown = f"[attached {self.attachment['name']}]\n{shown}"
        self._append("user", shown)
        self.input.delete("1.0", "end")
        self.clear_quote()
        self.busy = True
        self.stop_event.clear()
        self._status(f"Loading {choice.label}…" if self.loaded_path != choice.path else "Thinking…")
        threading.Thread(target=self._generate, args=(choice, messages, text, attachments, quote), daemon=True).start()

    def _generate(self, choice, messages, user_text, attachments, quote) -> None:
        err = ""
        reply_parts: list[str] = []
        try:
            if self.engine is None or self.loaded_path != choice.path:
                self.engine = None
                self.loaded_path = None
                self.engine = usbchat.make_engine(choice.path, n_ctx=self.n_ctx, here=HERE)
                self.loaded_path = choice.path
                self.root.after(0, lambda: self._status(f"Loaded {choice.label}. Thinking…"))
            self.root.after(0, self._begin_assistant)
            for piece in self.engine.stream(messages, self.stop_event):
                reply_parts.append(piece)
                self.root.after(0, lambda p=piece: self._stream_piece(p))
        except Exception as exc:
            err = str(exc)
        prompt_tokens, completion_tokens = (0, 0)
        if self.engine is not None:
            prompt_tokens, completion_tokens = self.engine.last_usage
        reply = "".join(reply_parts).strip()
        if err and not reply:
            reply = f"(error: {err})"

        def finish() -> None:
            self.busy = False
            if err and not reply_parts:
                self._append("system", reply)
            elif reply:
                self.messages.append(("assistant", reply))
                self.transcript.configure(state="normal")
                self.transcript.insert("end", "\n\n", "assistant")
                self.transcript.configure(state="disabled")
            turn = {
                "time": usbchat.utc_now(),
                "model": choice.label,
                "prompt": user_text,
                "response": reply,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "attached": [a["name"] for a in attachments],
                "quote": quote,
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

    def _begin_assistant(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", "Model\n", "assistant")
        self.transcript.configure(state="disabled")
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
