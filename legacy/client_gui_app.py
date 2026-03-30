import asyncio
import queue
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import setup_logging
from client.webrtc_client import WebRTCClient


class ClientUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Client - Helpdesk")
        self.root.geometry("420x220")

        self._ui_queue: queue.Queue[str] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._is_connecting = False

        self.target_host_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Enter a Host ID from the host PC, then click Connect.")

        self._build_ui()
        self._poll_ui_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        tk.Label(self.root, text="Host ID", font=("Segoe UI", 12)).pack(**pad)
        tk.Entry(self.root, textvariable=self.target_host_var, font=("Consolas", 16), justify="center").pack(**pad)

        tk.Button(
            self.root,
            text="Connect",
            height=2,
            command=self._connect,
        ).pack(pady=10, fill="x", padx=20)

        tk.Label(self.root, textvariable=self.status_var, wraplength=380, justify="center", fg="#222").pack(pady=6)

        tk.Label(
            self.root,
            text="Tip: OpenCV will open a separate video window.",
            font=("Segoe UI", 9),
            fg="#555",
        ).pack(pady=4)

    def _emit_from_worker(self, message: str) -> None:
        self._ui_queue.put(message)

    def _worker_main(self, target_host_id: str) -> None:
        async def run() -> None:
            setup_logging()
            client = WebRTCClient(target_host_id, on_event=self._emit_from_worker)
            await client.run()

        try:
            asyncio.run(run())
        except Exception as e:
            self._emit_from_worker(f"ERROR: {e}")
        finally:
            self._emit_from_worker("__DONE__")

    def _connect(self) -> None:
        if self._is_connecting:
            return

        host_id = self.target_host_var.get().strip()
        if not host_id:
            messagebox.showwarning("Host ID missing", "Please enter the 6-digit Host ID.")
            return
        if not host_id.isdigit():
            messagebox.showwarning("Invalid Host ID", "Host ID should be digits only.")
            return

        self._is_connecting = True
        self.status_var.set("Connecting...")

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
                    self._is_connecting = False
                    self.status_var.set("Disconnected.")
                elif msg.startswith("ERROR:"):
                    self.status_var.set(msg)
                else:
                    self.status_var.set(msg)
        except queue.Empty:
            pass

        self.root.after(200, self._poll_ui_queue)

    def _on_close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ClientUI().run()

