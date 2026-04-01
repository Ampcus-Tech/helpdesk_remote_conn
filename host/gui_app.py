import asyncio
import multiprocessing
import queue
import random
import string
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Optional, Union

import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import SIGNALING_URL, setup_logging


def generate_host_id(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _webrtc_worker_main(host_id: str, emit: Callable[[str], None]) -> None:
    """Run WebRTC host; emit() receives status lines and finally __DONE__."""
    from host.webrtc_host import WebRTCHost

    async def run() -> None:
        setup_logging()
        try:
            host = WebRTCHost(host_id, on_event=emit)
            await host.run()
        except PermissionError as e:
            emit(f"PERMISSION_ERROR: {e}")
        except Exception as e:
            emit(f"ERROR: {e}")

    try:
        asyncio.run(run())
    except Exception as e:
        emit(f"ERROR: {e}")
    finally:
        emit("__DONE__")


def _darwin_host_process_entry(host_id: str, event_queue: multiprocessing.Queue) -> None:
    """
    macOS: must run in a fresh process so asyncio + pynput run on *this* process's
    main thread. Background threads hit TSM/ctypes main-queue traps on macOS 15+.
    """
    _webrtc_worker_main(host_id, event_queue.put)


class HostUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Host - Helpdesk")
        self.root.geometry("420x260")

        self._ui_queue: Union[queue.Queue[str], multiprocessing.Queue] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_proc: Optional[multiprocessing.Process] = None
        self._is_running = False
        self._use_child_process = sys.platform == "darwin"

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

    def _worker_main_thread(self, host_id: str) -> None:
        _webrtc_worker_main(host_id, self._emit_from_worker)

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

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                if msg == "__DONE__":
                    self._is_running = False
                    self._worker_proc = None
                    self.status_var.set("Host stopped.")
                elif msg.startswith("PERMISSION_ERROR:"):
                    error_msg = msg.replace("PERMISSION_ERROR: ", "")
                    self.status_var.set("Permission denied!")
                    messagebox.showerror("macOS Permission Required", error_msg)
                elif msg.startswith("ERROR:"):
                    self.status_var.set(msg)
                else:
                    self.status_var.set(msg)
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
