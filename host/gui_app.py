import asyncio
import queue
import random
import string
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import SIGNALING_URL, setup_logging
from host.webrtc_host import WebRTCHost


def generate_host_id(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


class HostUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Host - Helpdesk")
        self.root.geometry("420x260")

        self._ui_queue: queue.Queue[str] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._is_running = False

        host_id = generate_host_id()
        self.host_id_var = tk.StringVar(value=host_id)
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

        btn_row = tk.Frame(self.root)
        btn_row.pack(pady=6)

        tk.Button(btn_row, text="Copy", width=10, command=self._copy_host_id).grid(row=0, column=0, padx=6)
        tk.Button(btn_row, text="New ID", width=10, command=self._new_host_id).grid(row=0, column=1, padx=6)

        tk.Label(
            self.root,
            text=f"Signaling: {SIGNALING_URL}",
            font=("Segoe UI", 9),
            wraplength=380,
            justify="center",
            fg="#555",
        ).pack(pady=10)

        tk.Button(self.root, text="Start Host", height=2, command=self._start_host).pack(pady=6, fill="x", padx=20)

        tk.Label(self.root, textvariable=self.status_var, wraplength=380, justify="center", fg="#222").pack(pady=6)

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

    def _emit_from_worker(self, message: str) -> None:
        self._ui_queue.put(message)

    def _worker_main(self, host_id: str) -> None:
        async def run() -> None:
            setup_logging()
            try:
                host = WebRTCHost(host_id, on_event=self._emit_from_worker)
                await host.run()
            except PermissionError as e:
                self._emit_from_worker(f"PERMISSION_ERROR: {e}")
            except Exception as e:
                self._emit_from_worker(f"ERROR: {e}")

        try:
            asyncio.run(run())
        except Exception as e:
            self._emit_from_worker(f"ERROR: {e}")
        finally:
            self._emit_from_worker("__DONE__")

    def _start_host(self) -> None:
        if self._is_running:
            return

        host_id = self.host_id_var.get().strip()
        if not host_id:
            messagebox.showwarning("Host ID missing", "Generate a Host ID first.")
            return

        self._is_running = True
        self.status_var.set("Starting host...")

        # Disable UI interactions by simply preventing actions.
        self._worker_thread = threading.Thread(
            target=self._worker_main,
            args=(host_id,),
            daemon=True,
        )
        self._worker_thread.start()

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                if msg == "__DONE__":
                    self._is_running = False
                    self.status_var.set("Host stopped.")
                elif msg.startswith("PERMISSION_ERROR:"):
                    error_msg = msg.replace("PERMISSION_ERROR: ", "")
                    self.status_var.set("Permission denied!")
                    messagebox.showerror("macOS Permission Required", error_msg)
                elif msg.startswith("ERROR:"):
                    self.status_var.set(msg)
                else:
                    # Coalesce repeated messages by just replacing the status text.
                    self.status_var.set(msg)
        except queue.Empty:
            pass

        self.root.after(200, self._poll_ui_queue)

    def _on_close(self) -> None:
        # Worker thread is daemon; closing the window ends the process.
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    HostUI().run()

