import asyncio
import multiprocessing
import os
import queue
import random
import string
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional, Union

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import SIGNALING_URL, setup_logging


def generate_host_id(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _webrtc_worker_main(
    host_id: str,
    emit: Callable[[tuple], None],
    set_host: Optional[Callable[[object], None]] = None,
) -> None:
    from host.webrtc_host import WebRTCHost

    async def run() -> None:
        setup_logging()
        try:
            host = WebRTCHost(
                host_id,
                on_event=lambda msg: emit(("status", msg)),
                on_chat=lambda sender, text: emit(("chat", sender, text)),
                on_file_offer=lambda file_id, file_name, file_size: emit(
                    ("file_offer", file_id, file_name, file_size)
                ),
                on_file_progress=lambda file_name, transferred, total, direction: emit(
                    ("file_progress", file_name, transferred, total, direction)
                ),
                on_file_done=lambda file_name, path, direction: emit(("file_done", file_name, path, direction)),
            )
            if set_host:
                set_host(host)
            await host.run()
        except PermissionError as e:
            emit(("error", f"PERMISSION_ERROR: {e}"))
        except Exception as e:
            emit(("error", str(e)))
        finally:
            if set_host:
                set_host(None)

    try:
        asyncio.run(run())
    except Exception as e:
        emit(("error", str(e)))
    finally:
        emit(("done",))


def _darwin_host_process_entry(host_id: str, event_queue: multiprocessing.Queue) -> None:
    _webrtc_worker_main(host_id, event_queue.put)


class HostChatWindow:
    def __init__(self, parent: tk.Tk, send_chat_cb, send_file_cb) -> None:
        self._send_chat_cb = send_chat_cb
        self._send_file_cb = send_file_cb

        self.top = tk.Toplevel(parent)
        self.top.title("UltraViewer-style Chat - Host")
        self.top.geometry("380x420")

        tk.Label(self.top, text="Who's viewing your computer", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=8, pady=(6, 2)
        )
        tk.Label(self.top, text="● Client connected", fg="#0b5").pack(anchor="w", padx=8)

        tk.Label(self.top, text="Chat Log").pack(anchor="w", padx=8, pady=(4, 0))
        self.chat_view = tk.Text(self.top, height=14, state="disabled", wrap="word")
        self.chat_view.pack(fill="both", expand=True, padx=8, pady=4)

        self.file_status = tk.Label(self.top, text="", fg="#555")
        self.file_status.pack(anchor="w", padx=8)

        bottom = tk.Frame(self.top)
        bottom.pack(fill="x", padx=8, pady=6)

        self.chat_input = tk.Entry(bottom)
        self.chat_input.pack(side="left", fill="x", expand=True)
        self.chat_input.bind("<Return>", lambda _e: self._send_chat())

        tk.Button(bottom, text="Send", width=7, command=self._send_chat).pack(side="left", padx=(4, 0))
        tk.Button(bottom, text="Send file", width=9, command=self._send_file).pack(side="left", padx=(4, 0))

    def append_chat(self, sender: str, text: str) -> None:
        self.chat_view.config(state="normal")
        self.chat_view.insert("end", f"{sender}: {text}\n")
        self.chat_view.config(state="disabled")
        self.chat_view.see("end")

    def update_file_progress(self, file_name: str, transferred: int, total: int, direction: str) -> None:
        base = os.path.basename(file_name)
        pct = int((transferred / total) * 100) if total else 0
        self.file_status.config(text=f"{direction.upper()} {base}: {pct}% ({transferred}/{total} bytes)")

    def file_done(self, file_name: str, _path: str, direction: str) -> None:
        base = os.path.basename(file_name)
        self.append_chat("SYSTEM", f"{'SENT' if direction == 'send' else 'RECEIVED'}: {base}")
        self.file_status.config(text="")

    def _send_chat(self) -> None:
        text = self.chat_input.get().strip()
        if not text:
            return
        self._send_chat_cb(text)
        self.chat_input.delete(0, "end")

    def _send_file(self) -> None:
        path = filedialog.askopenfilename(title="Select file to send")
        if not path:
            return
        self.append_chat("SYSTEM", f"SEND: {os.path.basename(path)}")
        self._send_file_cb(path)


class HostUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Host - Helpdesk")
        self.root.geometry("420x300")

        self._ui_queue: Union[queue.Queue, multiprocessing.Queue] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_proc: Optional[multiprocessing.Process] = None
        self._is_running = False
        self._use_child_process = sys.platform == "darwin"
        self._host: Optional[object] = None
        self._chat_window: Optional[HostChatWindow] = None
        self._chat_backlog: list[tuple[str, str]] = []

        self.host_id_var = tk.StringVar(value=generate_host_id())
        self.status_var = tk.StringVar(value="Click 'Start Host' to begin.")

        self._build_ui()
        self._poll_ui_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        tk.Label(self.root, text="Host ID", font=("Segoe UI", 12)).pack(**pad)
        tk.Label(
            self.root,
            textvariable=self.host_id_var,
            font=("Consolas", 28, "bold"),
            fg="#0b5",
        ).pack(**pad)

        row = tk.Frame(self.root)
        row.pack(pady=4)
        tk.Button(row, text="Copy", width=10, command=self._copy_host_id).grid(row=0, column=0, padx=6)
        tk.Button(row, text="New ID", width=10, command=self._new_host_id).grid(row=0, column=1, padx=6)

        tk.Label(
            self.root,
            text=f"Signaling: {SIGNALING_URL}",
            font=("Segoe UI", 9),
            wraplength=380,
            justify="center",
            fg="#555",
        ).pack(pady=8)

        tk.Button(self.root, text="Start Host", height=2, command=self._start_host).pack(
            pady=4, fill="x", padx=20
        )
        tk.Button(self.root, text="Chat...", command=self._open_chat_window).pack(pady=(0, 4))

        tk.Label(
            self.root,
            textvariable=self.status_var,
            wraplength=380,
            justify="center",
            fg="#222",
        ).pack(pady=4)

    def _copy_host_id(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.host_id_var.get())
            self.status_var.set("Host ID copied.")
        except Exception as e:
            messagebox.showerror("Copy failed", str(e))

    def _new_host_id(self) -> None:
        if self._is_running:
            return
        self.host_id_var.set(generate_host_id())
        self.status_var.set("New Host ID generated. Click 'Start Host'.")

    def _open_chat_window(self) -> None:
        if self._chat_window and tk.Toplevel.winfo_exists(self._chat_window.top):
            self._chat_window.top.deiconify()
            self._chat_window.top.lift()
            return
        self._chat_window = HostChatWindow(
            self.root,
            send_chat_cb=self._send_chat_text,
            send_file_cb=self._send_file_path,
        )
        for sender, text in self._chat_backlog:
            self._chat_window.append_chat(sender, text)
        self._chat_backlog.clear()

    def _emit_from_worker(self, payload: tuple) -> None:
        self._ui_queue.put(payload)

    def _set_host_ref(self, host_obj: object) -> None:
        self._host = host_obj

    def _worker_main_thread(self, host_id: str) -> None:
        _webrtc_worker_main(host_id, self._emit_from_worker, self._set_host_ref)

    def _start_host(self) -> None:
        if self._is_running:
            return
        host_id = self.host_id_var.get().strip()
        if not host_id:
            messagebox.showwarning("Host ID missing", "Generate a Host ID first.")
            return
        self._is_running = True
        self.status_var.set("Starting host...")

        if self._use_child_process:
            self._ui_queue = multiprocessing.Queue()
            self._worker_proc = multiprocessing.Process(
                target=_darwin_host_process_entry,
                args=(host_id, self._ui_queue),
                daemon=True,
            )
            self._worker_proc.start()
        else:
            self._worker_thread = threading.Thread(
                target=self._worker_main_thread,
                args=(host_id,),
                daemon=True,
            )
            self._worker_thread.start()

    def _send_chat_text(self, text: str) -> None:
        if self._use_child_process:
            messagebox.showinfo("Unavailable", "Chat sending from host UI is unavailable in macOS process mode.")
            return
        if not self._host:
            messagebox.showinfo("Not connected", "Start host and wait for client.")
            return
        try:
            self._host.send_chat(text)
        except Exception as e:
            messagebox.showwarning("Chat send failed", str(e))

    def _send_file_path(self, path: str) -> None:
        if self._use_child_process:
            messagebox.showinfo("Unavailable", "File sending from host UI is unavailable in macOS process mode.")
            return
        if not self._host:
            messagebox.showinfo("Not connected", "Start host and wait for client.")
            return
        try:
            self._host.send_file(path)
        except Exception as e:
            messagebox.showwarning("File send failed", str(e))

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                payload = self._ui_queue.get_nowait()
                if isinstance(payload, str):
                    if payload == "__DONE__":
                        payload = ("done",)
                    elif payload.startswith("ERROR:"):
                        payload = ("error", payload.replace("ERROR: ", ""))
                    else:
                        payload = ("status", payload)

                kind, *rest = payload
                if kind == "status":
                    msg = rest[0]
                    if msg == "SESSION_CONNECTED":
                        self.status_var.set("Client connected.")
                    elif msg == "SESSION_CHANNELS_CLOSED":
                        self.status_var.set("Client disconnected.")
                    else:
                        self.status_var.set(msg)
                elif kind == "chat":
                    sender, text = rest
                    if self._chat_window:
                        self._chat_window.append_chat(sender, text)
                    else:
                        self._chat_backlog.append((sender, text))
                elif kind == "file_progress" and self._chat_window:
                    self._chat_window.update_file_progress(*rest)
                elif kind == "file_done":
                    if self._chat_window:
                        self._chat_window.file_done(*rest)
                    else:
                        base = os.path.basename(rest[0])
                        label = "SENT" if rest[2] == "send" else "RECEIVED"
                        self._chat_backlog.append(("SYSTEM", f"{label}: {base}"))
                elif kind == "file_offer":
                    file_id, file_name, _file_size = rest
                    save_path = filedialog.asksaveasfilename(
                        parent=self.root, title="Save incoming file", initialfile=file_name
                    )
                    if self._host:
                        self._host.respond_file_offer(file_id, save_path or None)
                elif kind == "error":
                    msg = str(rest[0])
                    if msg.startswith("PERMISSION_ERROR:"):
                        self.status_var.set("Permission denied!")
                        messagebox.showerror("macOS Permission Required", msg.replace("PERMISSION_ERROR: ", ""))
                    else:
                        self.status_var.set(f"ERROR: {msg}")
                elif kind == "done":
                    self._is_running = False
                    self._worker_proc = None
                    self.status_var.set("Host stopped.")
        except queue.Empty:
            pass

        self.root.after(200, self._poll_ui_queue)

    def _on_close(self) -> None:
        if self._worker_proc is not None and self._worker_proc.is_alive():
            self._worker_proc.terminate()
            self._worker_proc.join(timeout=3)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    HostUI().run()
