import asyncio
import logging
import multiprocessing
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import messagebox
from typing import Optional, Union

import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import setup_logging
from client.webrtc_client import WebRTCClient


def _darwin_client_process_entry(host_id: str, event_queue: "multiprocessing.Queue") -> None:
    """
    macOS: OpenCV HighGUI (namedWindow/imshow) must run on the process main thread.
    A background Tk worker thread violates that and triggers cv2.error. This entry
    runs asyncio.run on the child process's main thread instead.
    """

    async def run() -> None:
        setup_logging()
        logging.getLogger().setLevel(logging.INFO)
        print(
            f"\n[client/gui child pid={os.getpid()}] host_id={host_id!r}\n",
            file=sys.stderr,
            flush=True,
        )

        def emit(msg: str) -> None:
            event_queue.put(msg)

        client = WebRTCClient(host_id, on_event=emit)
        await client.run()

    try:
        asyncio.run(run())
    except Exception as e:
        traceback.print_exc()
        event_queue.put(f"ERROR: {type(e).__name__}: {e}")
    finally:
        event_queue.put("__DONE__")


class ClientUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Client - Helpdesk")
        self.root.geometry("420x220")

        self._ui_queue: Union[queue.Queue[str], multiprocessing.Queue] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_proc: Optional[multiprocessing.Process] = None
        self._is_connecting = False
        self._last_worker_message: str = ""
        self._use_child_process = sys.platform == "darwin"

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

        tip = (
            "Tip: A separate video window opens (OpenCV on macOS runs in a helper process)."
            if self._use_child_process
            else "Tip: OpenCV will open a separate video window."
        )
        tk.Label(self.root, text=tip, font=("Segoe UI", 9), fg="#555").pack(pady=4)

    def _emit_from_worker(self, message: str) -> None:
        self._ui_queue.put(message)

    def _worker_main_thread(self, target_host_id: str) -> None:
        async def run() -> None:
            setup_logging()
            logging.getLogger().setLevel(logging.INFO)
            print(
                f"\n[client/gui] Starting session for host_id={target_host_id!r}\n",
                file=sys.stderr,
                flush=True,
            )
            client = WebRTCClient(target_host_id, on_event=self._emit_from_worker)
            await client.run()

        try:
            asyncio.run(run())
        except Exception as e:
            traceback.print_exc()
            self._emit_from_worker(f"ERROR: {type(e).__name__}: {e}")
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
        self._last_worker_message = ""
        self.status_var.set("Connecting...")

        if self._use_child_process:
            self._ui_queue = multiprocessing.Queue()
            self._worker_proc = multiprocessing.Process(
                target=_darwin_client_process_entry,
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
                    self._is_connecting = False
                    self._worker_proc = None
                    if self._last_worker_message:
                        self.status_var.set(self._last_worker_message)
                        print(
                            f"[client/gui] Session finished. Last status:\n{self._last_worker_message}\n",
                            file=sys.stderr,
                            flush=True,
                        )
                    else:
                        self.status_var.set("Disconnected.")
                elif msg.startswith("ERROR:"):
                    self._last_worker_message = msg
                    self.status_var.set(msg)
                else:
                    self._last_worker_message = msg
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
    ClientUI().run()
