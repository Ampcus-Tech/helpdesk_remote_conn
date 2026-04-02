import asyncio
import logging
import multiprocessing
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, Union, Callable
from pathlib import Path
from PIL import Image, ImageTk
import time

import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import setup_logging
from client.webrtc_client import WebRTCClient


def _darwin_client_process_entry(host_id: str, event_queue: "multiprocessing.Queue", command_queue: "multiprocessing.Queue") -> None:
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

        client = WebRTCClient(host_id, on_event=emit, command_queue=command_queue)
        await client.run()

    try:
        asyncio.run(run())
    except Exception as e:
        traceback.print_exc()
        event_queue.put(f"ERROR: {type(e).__name__}: {e}")
    finally:
        event_queue.put("__DONE__")


class SideToggleButton:
    def __init__(self, parent_ui, on_click):
        self.parent_ui = parent_ui
        self.on_click = on_click
        self.top = tk.Toplevel(parent_ui.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        
        # Load blue arrow icon
        try:
            asset_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "blue_arrow.png")
            img = Image.open(asset_path)
            img = img.resize((30, 40), Image.LANCZOS)
            self.icon = ImageTk.PhotoImage(img)
        except Exception:
            self.icon = None

        self.btn = tk.Button(self.top, image=self.icon, text="<" if not self.icon else "", 
                             command=self.on_click, bg="white", relief="flat")
        self.btn.pack(fill="both", expand=True)
        
        self.update_position()
        self.top.bind("<B1-Motion>", self._on_drag)

    def update_position(self):
        self.top.update_idletasks()
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        # Bottom right side
        self.top.geometry(f"35x60+{sw-40}+{sh-150}")
        self.top.deiconify()
        self.top.lift()

    def _on_drag(self, event):
        # Allow vertical dragging of the toggle button
        sw = self.top.winfo_screenwidth()
        y = self.top.winfo_pointery() - 30
        self.top.geometry(f"35x60+{sw-40}+{max(0, y)}")

class RemoteChatPanel:
    def __init__(self, parent_ui, send_chat_cb, send_file_cb, respond_file_cb) -> None:
        self.parent_ui = parent_ui
        self._send_chat_cb = send_chat_cb
        self._send_file_cb = send_file_cb
        self._respond_file_cb = respond_file_cb

        self.top = tk.Toplevel(parent_ui.root)
        self.top.title("Helpdesk Remote Access - Client")
        self.top.geometry("380x500")
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        
        # Header
        header = tk.Frame(self.top, bg="#00adef", height=35)
        header.pack(fill="x")
        tk.Label(header, text="Helpdesk Remote Access (Client)", fg="white", bg="#00adef", font=("Segoe UI", 10, "bold")).pack(side="left", padx=10)
        
        tk.Button(header, text="X", fg="white", bg="#00adef", relief="flat", command=self.hide).pack(side="right", padx=5)
        tk.Button(header, text="_", fg="white", bg="#00adef", relief="flat", command=self.hide).pack(side="right", padx=5)

        # Connected To List
        tk.Label(self.top, text="Your remote client", font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(5, 0))
        self.client_list = tk.Listbox(self.top, height=3, bg="#f0f8ff", relief="flat", borderwidth=1)
        self.client_list.pack(fill="x", padx=10, pady=5)
        
        # Chat Log
        tk.Label(self.top, text="Chat Log", font=("Segoe UI", 9)).pack(anchor="w", padx=10)
        self.chat_view = tk.Text(self.top, height=15, state="disabled", wrap="word", font=("Segoe UI", 9))
        self.chat_view.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.file_status = tk.Label(self.top, text="", fg="#555", font=("Segoe UI", 8))
        self.file_status.pack(anchor="w", padx=10)

        # Input Area
        bottom = tk.Frame(self.top)
        bottom.pack(fill="x", padx=10, pady=10)
        
        self.chat_input = tk.Entry(bottom, font=("Segoe UI", 10))
        self.chat_input.insert(0, "Press F1 to toggle chat on/off")
        self.chat_input.bind("<FocusIn>", self._on_focus_in)
        self.chat_input.pack(side="left", fill="x", expand=True)
        self.chat_input.bind("<Return>", lambda _e: self._send_chat())

        # Load paperclip icon
        try:
            asset_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "paperclip.png")
            img = Image.open(asset_path)
            img = img.resize((20, 20), Image.LANCZOS)
            self.paperclip_icon = ImageTk.PhotoImage(img)
        except Exception:
            self.paperclip_icon = None

        tk.Button(bottom, image=self.paperclip_icon, text="F" if not self.paperclip_icon else "", 
                  command=self._send_file, relief="flat").pack(side="left", padx=5)
        
        self.hide()
        self.update_position()

    def update_position(self):
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        # Position near bottom right
        self.top.geometry(f"380x500+{sw-390}+{sh-550}")

    def _on_focus_in(self, event):
        if self.chat_input.get() == "Press F1 to toggle chat on/off":
            self.chat_input.delete(0, "end")

    def show(self):
        self.top.deiconify()
        self.top.lift()
        self.top.attributes("-topmost", True)
        self.update_position()

    def hide(self):
        self.top.withdraw()

    def toggle(self):
        if self.top.winfo_viewable():
            self.hide()
        else:
            self.show()

    def append_chat(self, sender: str, text: str) -> None:
        self.chat_view.config(state="normal")
        self.chat_view.insert("end", f"{sender}: {text}\n")
        self.chat_view.config(state="disabled")
        self.chat_view.see("end")
        self.show()

    def set_host(self, host_id):
        self.client_list.delete(0, "end")
        self.client_list.insert("end", f"● {host_id}")
        self.append_chat("SYSTEM", f"Connected to {host_id}")

    def update_file_progress(self, file_name: str, transferred: int, total: int, direction: str) -> None:
        base = os.path.basename(file_name)
        pct = int((transferred / total) * 100) if total else 0
        self.file_status.config(text=f"{direction.upper()} {base}: {pct}%")

    def file_done(self, file_name: str, path: str, direction: str) -> None:
        base = os.path.basename(file_name)
        self.append_chat("SYSTEM", f"{'SENT' if direction == 'send' else 'RECEIVED'}: {base}")
        self.file_status.config(text="")
        if direction == "recv":
            self.append_chat("SYSTEM", f"Saved to: {path}")

    def on_file_offer(self, file_id, file_name, file_size):
        self.chat_view.config(state="normal")
        self.chat_view.insert("end", f"Incoming file: {file_name} ({file_size} bytes)\n")
        
        btn_frame = tk.Frame(self.chat_view)
        tk.Button(btn_frame, text="Save to Downloads", font=("Segoe UI", 8), 
                  command=lambda: self._accept_file(file_id, file_name)).pack(side="left")
        tk.Button(btn_frame, text="Reject", font=("Segoe UI", 8), 
                  command=lambda: self._reject_file(file_id)).pack(side="left", padx=5)
        
        self.chat_view.window_create("end", window=btn_frame)
        self.chat_view.insert("end", "\n")
        self.chat_view.config(state="disabled")
        self.chat_view.see("end")
        self.show()

    def _accept_file(self, file_id, file_name):
        downloads = str(Path.home() / "Downloads")
        os.makedirs(downloads, exist_ok=True)
        save_path = os.path.join(downloads, file_name)
        if os.path.exists(save_path):
            base, ext = os.path.splitext(file_name)
            save_path = os.path.join(downloads, f"{base}_{int(time.time())}{ext}")
            
        self._respond_file_cb(file_id, save_path)
        self.append_chat("SYSTEM", f"Accepted file {file_name}")

    def _reject_file(self, file_id):
        self._respond_file_cb(file_id, None)
        self.append_chat("SYSTEM", "Rejected file offer")

    def _send_chat(self) -> None:
        text = self.chat_input.get().strip()
        if not text or text == "Press F1 to toggle chat on/off":
            return
        self._send_chat_cb(text)
        self.chat_input.delete(0, "end")

    def _send_file(self) -> None:
        path = filedialog.askopenfilename(title="Select file to send")
        if not path:
            return
        self._send_file_cb(path)


class ClientUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Client - Helpdesk")
        self.root.geometry("420x240")

        self._ui_queue: Union[queue.Queue[Union[str, tuple]],multiprocessing.Queue] = queue.Queue()
        self._command_queue: Union[queue.Queue, multiprocessing.Queue] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_proc: Optional[multiprocessing.Process] = None
        self._is_connecting = False
        self._last_worker_message: str = ""
        self._use_child_process = sys.platform == "darwin"
        self._client: Optional[WebRTCClient] = None
        self._chat_panel: Optional[UltraChatPanel] = None
        self._side_button: Optional[SideToggleButton] = None
        self._chat_backlog: list[tuple[str, str]] = []

        self.target_host_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Enter a Host ID from the host PC, then click Connect.")

        self._build_ui()
        self._poll_ui_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        tk.Label(self.root, text="Host ID", font=("Segoe UI", 12)).pack(**pad)
        tk.Entry(self.root, textvariable=self.target_host_var, font=("Consolas", 16), justify="center").pack(**pad)

        tk.Button(self.root, text="Connect", height=2, command=self._connect).pack(
            pady=8, fill="x", padx=20
        )
        self.root.bind("<F1>", lambda _e: self._toggle_chat())

        tk.Label(
            self.root, textvariable=self.status_var, wraplength=380, justify="center", fg="#222"
        ).pack(pady=4)
        tip = (
            "Tip: A separate video window opens (OpenCV on macOS runs in a helper process)."
            if self._use_child_process
            else "Tip: OpenCV will open a separate video window."
        )
        tk.Label(self.root, text=tip, font=("Segoe UI", 9), fg="#555").pack(pady=(0, 4))

    def _init_chat_panel(self) -> None:
        if not self._chat_panel:
            self._chat_panel = RemoteChatPanel(
                self,
                send_chat_cb=self._send_chat_text,
                send_file_cb=self._send_file_path,
                respond_file_cb=self._respond_file_offer,
            )
            for sender, text in self._chat_backlog:
                self._chat_panel.append_chat(sender, text)
            self._chat_backlog.clear()
            
            if not self._side_button:
                self._side_button = SideToggleButton(self, on_click=self._chat_panel.toggle)

    def _toggle_chat(self) -> None:
        self._init_chat_panel()
        self._chat_panel.toggle()

    def _emit_event(self, message: str) -> None:
        self._ui_queue.put(("status", message))

    def _emit_chat(self, sender: str, text: str) -> None:
        self._ui_queue.put(("chat", sender, text))

    def _emit_file_progress(self, file_name: str, transferred: int, total: int, direction: str) -> None:
        self._ui_queue.put(("file_progress", file_name, transferred, total, direction))

    def _emit_file_done(self, file_name: str, path: str, direction: str) -> None:
        self._ui_queue.put(("file_done", file_name, path, direction))

    def _on_file_offer(self, file_id: str, file_name: str, file_size: int) -> None:
        self._ui_queue.put(("file_offer", file_id, file_name, file_size))

    def _worker_main_thread(self, target_host_id: str) -> None:
        async def run() -> None:
            setup_logging()
            logging.getLogger().setLevel(logging.INFO)
            print(
                f"\n[client/gui] Starting session for host_id={target_host_id!r}\n",
                file=sys.stderr,
                flush=True,
            )
            self._client = WebRTCClient(
                target_host_id,
                on_event=self._emit_event,
                on_chat=self._emit_chat,
                on_file_offer=self._on_file_offer,
                on_file_progress=self._emit_file_progress,
                on_file_done=self._emit_file_done,
                command_queue=self._command_queue,
            )
            await self._client.run()

        try:
           asyncio.run(run())
        except Exception as e:
            traceback.print_exc()
            self._ui_queue.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            self._ui_queue.put(("done",))

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
            self._command_queue = multiprocessing.Queue()
            self._worker_proc = multiprocessing.Process(
                target=_darwin_client_process_entry,
                args=(host_id, self._ui_queue, self._command_queue),
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
        self._command_queue.put({"type": "send_chat", "text": text})

    def _send_file_path(self, path: str) -> None:
        self._command_queue.put({"type": "send_file", "path": path})

    def _respond_file_offer(self, file_id: str, save_path: Optional[str]) -> None:
        self._command_queue.put({"type": "respond_file_offer", "file_id": file_id, "save_path": save_path})

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                kind, *rest = self._ui_queue.get_nowait()
                if kind == "status":
                    msg = rest[0]
                    if msg == "SESSION_CONNECTED":
                        self.status_var.set("Connected. You are now viewing the remote screen.")
                        self._init_chat_panel() # Ensure side button appears
                        if self._chat_panel:
                            self._chat_panel.set_host(self.target_host_var.get())
                    elif msg == "SESSION_CHANNELS_CLOSED":
                        self.status_var.set("Disconnected.")
                    else:
                        self.status_var.set(msg)
                elif kind == "chat":
                    sender, text = rest
                    if self._chat_panel:
                        self._chat_panel.append_chat(sender, text)
                    else:
                        self._chat_backlog.append((sender, text))
                elif kind == "file_progress" and self._chat_panel:
                    self._chat_panel.update_file_progress(*rest)
                elif kind == "file_done":
                    if self._chat_panel:
                        self._chat_panel.file_done(*rest)
                    else:
                        base = os.path.basename(rest[0])
                        label = "SENT" if rest[2] == "send" else "RECEIVED"
                        self._chat_backlog.append(("SYSTEM", f"{label}: {base}"))
                elif kind == "file_offer":
                    file_id, file_name, file_size = rest
                    if self._chat_panel:
                        self._chat_panel.on_file_offer(file_id, file_name, file_size)
                    else:
                        self._chat_backlog.append(("SYSTEM", f"New file offer: {file_name}"))
                elif kind == "error":
                    self.status_var.set(f"ERROR: {rest[0]}")
                elif kind == "done":
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
            # Graceful shutdown first
            self._command_queue.put({"type": "shutdown"})
            self._worker_proc.join(timeout=1.5)
            if self._worker_proc.is_alive():
                self._worker_proc.terminate()
                self._worker_proc.join(timeout=1.0)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    ClientUI().run()
