import asyncio
import os
import queue
import random
import string
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import SIGNALING_URL, setup_logging
from host.webrtc_host import WebRTCHost


def generate_host_id(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


class HostUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Remote Host - Helpdesk")
        self.resize(420, 260)

        self._ui_queue = queue.Queue()
        self._worker_thread = None
        self._is_running = False
        self._host = None
        self._channels_ready = False
        self._chat_window: "HostChatWindow | None" = None

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_ui_queue)
        self._timer.start(150)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        layout.addWidget(QLabel("Host ID"))
        self.host_id_input = QLineEdit(generate_host_id())
        self.host_id_input.setReadOnly(True)
        layout.addWidget(self.host_id_input)

        buttons_row = QHBoxLayout()
        new_id_btn = QPushButton("New ID")
        new_id_btn.clicked.connect(self._new_host_id)
        buttons_row.addWidget(new_id_btn)
        self.start_btn = QPushButton("Start Host")
        self.start_btn.clicked.connect(self._start_host)
        buttons_row.addWidget(self.start_btn)
        layout.addLayout(buttons_row)

        self.status_label = QLabel("Click 'Start Host' to begin.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel(f"Signaling: {SIGNALING_URL}"))

    def _new_host_id(self) -> None:
        if self._is_running:
            return
        self.host_id_input.setText(generate_host_id())

    def _emit_event(self, message: str) -> None:
        self._ui_queue.put(("status", message))

    def _emit_chat(self, sender: str, text: str) -> None:
        self._ui_queue.put(("chat", sender, text))

    def _emit_file_progress(self, file_name: str, transferred: int, total: int, direction: str) -> None:
        self._ui_queue.put(("file_progress", file_name, transferred, total, direction))

    def _emit_file_done(self, file_name: str, path: str, direction: str) -> None:
        self._ui_queue.put(("file_done", file_name, path, direction))

    def _on_file_offer(self, file_id: str, file_name: str, file_size: int) -> None:
        self._ui_queue.put(("file_offer_prompt", file_id, file_name, file_size))

    def _worker_main(self, host_id: str) -> None:
        async def run() -> None:
            setup_logging()
            self._host = WebRTCHost(
                host_id,
                on_event=self._emit_event,
                on_chat=self._emit_chat,
                on_file_offer=self._on_file_offer,
                on_file_progress=self._emit_file_progress,
                on_file_done=self._emit_file_done,
            )
            await self._host.run()

        try:
            asyncio.run(run())
        except Exception as e:
            self._ui_queue.put(("error", str(e)))
        finally:
            self._ui_queue.put(("done",))

    def _start_host(self) -> None:
        if self._is_running:
            return
        host_id = self.host_id_input.text().strip()
        if not host_id:
            QMessageBox.warning(self, "Host ID missing", "Generate a Host ID first.")
            return
        self._is_running = True
        self.status_label.setText("Starting host...")
        self._worker_thread = threading.Thread(target=self._worker_main, args=(host_id,), daemon=True)
        self._worker_thread.start()

    def _send_chat(self) -> None:
        if not self._chat_window:
            return
        self._chat_window.send_current_chat()

    def _send_file(self) -> None:
        if not self._chat_window:
            return
        self._chat_window.send_file()

    def _poll_ui_queue(self) -> None:
        while True:
            try:
                item = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "status":
                msg = item[1]
                if msg == "SESSION_CONNECTED":
                    self._channels_ready = True
                    self.status_label.setText("Client connected.")
                    if not self._chat_window:
                        self._chat_window = HostChatWindow(self)
                        self._chat_window.show()
                elif msg == "SESSION_CHANNELS_CLOSED":
                    self._channels_ready = False
                    self.status_label.setText("Client disconnected.")
                    if self._chat_window:
                        self._chat_window.close()
                        self._chat_window = None
                else:
                    self.status_label.setText(msg)
            elif kind == "chat":
                if self._chat_window:
                    self._chat_window.append_chat(item[1], item[2])
            elif kind == "file_progress":
                if self._chat_window:
                    self._chat_window.update_file_progress(*item[1:])
            elif kind == "file_done":
                if self._chat_window:
                    self._chat_window.file_done(*item[1:])
            elif kind == "file_offer_prompt":
                file_id, file_name, file_size = item[1], item[2], item[3]
                save_path, _ = QFileDialog.getSaveFileName(self, "Save incoming file", file_name)
                if self._host:
                    self._host.respond_file_offer(file_id, save_path or None)
            elif kind == "error":
                self.status_label.setText(f"ERROR: {item[1]}")
            elif kind == "done":
                self._is_running = False
                self.status_label.setText("Host stopped.")


class HostChatWindow(QMainWindow):
    """UltraViewer-like chat window shown only after connection (host side)."""

    def __init__(self, parent_ui: HostUI) -> None:
        super().__init__(parent=parent_ui)
        self._parent_ui = parent_ui
        self.setWindowTitle("UltraViewer-style Chat - Host")
        self.resize(380, 420)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QLabel("Who's viewing your computer")
        layout.addWidget(header)

        self.peer_label = QLabel("● Client connected")
        layout.addWidget(self.peer_label)

        layout.addWidget(QLabel("Chat Log"))

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        layout.addWidget(self.chat_view, 1)

        self.file_status = QLabel(" ")
        layout.addWidget(self.file_status)

        bottom_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.returnPressed.connect(self.send_current_chat)
        bottom_row.addWidget(self.chat_input, 1)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_current_chat)
        bottom_row.addWidget(send_btn)
        file_btn = QPushButton("Send file")
        file_btn.clicked.connect(self.send_file)
        bottom_row.addWidget(file_btn)
        layout.addLayout(bottom_row)

    def append_chat(self, sender: str, text: str) -> None:
        self.chat_view.append(f"{sender}: {text}")

    def update_file_progress(self, file_name: str, transferred: int, total: int, direction: str) -> None:
        pct = int((transferred / total) * 100) if total else 0
        self.file_status.setText(f"{direction.upper()} {file_name}: {pct}% ({transferred}/{total} bytes)")

    def file_done(self, file_name: str, path: str, direction: str) -> None:
        nice_name = Path(file_name).name
        if direction == "send":
            self.chat_view.append(f"SENT: {nice_name}")
        else:
            self.chat_view.append(f"RECEIVED: {nice_name}")
        self.file_status.setText(" ")

    def send_current_chat(self) -> None:
        text = self.chat_input.text().strip()
        if not text or not self._parent_ui._host:
            return
        try:
            self._parent_ui._host.send_chat(text)
            self.chat_input.clear()
        except Exception as e:
            QMessageBox.warning(self, "Chat send failed", str(e))

    def send_file(self) -> None:
        if not self._parent_ui._host:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select file to send")
        if not path:
            return
        try:
            self.chat_view.append(f"SEND: {Path(path).name}")
            self._parent_ui._host.send_file(path)
        except Exception as e:
            QMessageBox.warning(self, "File send failed", str(e))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = HostUI()
    win.show()
    sys.exit(app.exec())

