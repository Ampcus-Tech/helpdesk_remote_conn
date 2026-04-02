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
from pathlib import Path
from PIL import Image, ImageTk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import SIGNALING_URL, setup_logging


def generate_host_id(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _webrtc_worker_main(
    host_id: str,
    emit: Callable[[tuple], None],
    command_queue: Optional[Union[queue.Queue, multiprocessing.Queue]] = None,
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
                command_queue=command_queue,
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


def _darwin_host_process_entry(host_id: str, event_queue: multiprocessing.Queue, command_queue: multiprocessing.Queue) -> None:
    _webrtc_worker_main(host_id, event_queue.put, command_queue)


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
        self.top.title("Helpdesk Remote Access - Host")
        self.top.geometry("380x500")
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        
        # Header
        header = tk.Frame(self.top, bg="#00adef", height=35)
        header.pack(fill="x")
        tk.Label(header, text="Helpdesk Remote Access (Host)", fg="white", bg="#00adef", font=("Segoe UI", 10, "bold")).pack(side="left", padx=10)
        
        tk.Button(header, text="X", fg="white", bg="#00adef", relief="flat", command=self.hide).pack(side="right", padx=5)
        tk.Button(header, text="_", fg="white", bg="#00adef", relief="flat", command=self.hide).pack(side="right", padx=5)

        # Connected client List
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

    def add_client(self, client_id):
        self.client_list.insert("end", f"● {client_id}")
        self.append_chat("SYSTEM", f"Client {client_id} connected")

    def remove_client(self, client_id):
        # Simple clear/re-add logic or just clear
        self.client_list.delete(0, "end")
        self.append_chat("SYSTEM", "Client disconnected")

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
        # Instead of popup, add to chat log with interactive save button
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
        # Avoid overwriting
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


class HostUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Remote Host - Helpdesk")
        self.root.geometry("420x300")

        self._ui_queue: Union[queue.Queue, multiprocessing.Queue] = queue.Queue()
        self._command_queue: Union[queue.Queue, multiprocessing.Queue] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_proc: Optional[multiprocessing.Process] = None
        self._is_running = False
        self._use_child_process = sys.platform == "darwin"
        self._host: Optional[object] = None
        self._chat_panel: Optional[UltraChatPanel] = None
        self._side_button: Optional[SideToggleButton] = None
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
        # Remote Access panel is hidden initially, side button will control it
        self.root.bind("<F1>", lambda _e: self._toggle_chat())

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

    def _emit_from_worker(self, payload: tuple) -> None:
        self._ui_queue.put(payload)

    def _set_host_ref(self, host_obj: object) -> None:
        self._host = host_obj

    def _worker_main_thread(self, host_id: str) -> None:
        _webrtc_worker_main(host_id, self._emit_from_worker, self._command_queue, self._set_host_ref)

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
            self._command_queue = multiprocessing.Queue()
            self._worker_proc = multiprocessing.Process(
                target=_darwin_host_process_entry,
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
                        self._init_chat_panel() # Ensure side button appears
                        if self._chat_panel:
                            self._chat_panel.add_client("Remote Client")
                    elif msg == "SESSION_CHANNELS_CLOSED":
                        self.status_var.set("Client disconnected.")
                        if self._chat_panel:
                            self._chat_panel.remove_client("Remote Client")
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
                        # Backlog if chat not open
                        self._chat_backlog.append(("SYSTEM", f"New file offer: {file_name}"))
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
