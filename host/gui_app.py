import asyncio
import os
import queue
import random
import string
import sys
import threading

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
    QTabWidget,
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
        self.setWindowTitle("Remote Host - Helpdesk (PyQt6)")
        self.resize(760, 520)

        self._ui_queue = queue.Queue()
        self._worker_thread = None
        self._is_running = False
        self._host = None
        self._channels_ready = False

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_ui_queue)
        self._timer.start(150)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        top.addWidget(QLabel("Host ID"))
        self.host_id_input = QLineEdit(generate_host_id())
        top.addWidget(self.host_id_input, 1)
        new_id_btn = QPushButton("New ID")
        new_id_btn.clicked.connect(self._new_host_id)
        top.addWidget(new_id_btn)
        self.start_btn = QPushButton("Start Host")
        self.start_btn.clicked.connect(self._start_host)
        top.addWidget(self.start_btn)
        layout.addLayout(top)

        self.status_label = QLabel("Click 'Start Host' to begin.")
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel(f"Signaling: {SIGNALING_URL}"))

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        chat_layout.addWidget(self.chat_view, 1)
        chat_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.returnPressed.connect(self._send_chat)
        chat_row.addWidget(self.chat_input, 1)
        self.send_chat_btn = QPushButton("Send")
        self.send_chat_btn.clicked.connect(self._send_chat)
        chat_row.addWidget(self.send_chat_btn)
        chat_layout.addLayout(chat_row)
        self.tabs.addTab(chat_tab, "Chat")
        self.chat_tab_idx = 0

        file_tab = QWidget()
        file_layout = QVBoxLayout(file_tab)
        self.send_file_btn = QPushButton("Send File...")
        self.send_file_btn.clicked.connect(self._send_file)
        file_layout.addWidget(self.send_file_btn)
        self.file_status = QLabel("No transfer yet.")
        file_layout.addWidget(self.file_status)
        self.file_log = QTextEdit()
        self.file_log.setReadOnly(True)
        file_layout.addWidget(self.file_log, 1)
        self.tabs.addTab(file_tab, "Files")
        self.files_tab_idx = 1

        # UltraViewer-like behavior: Chat/Files enabled only after connection.
        self.chat_input.setEnabled(False)
        self.send_chat_btn.setEnabled(False)
        self.send_file_btn.setEnabled(False)
        self.tabs.setTabEnabled(self.chat_tab_idx, False)
        self.tabs.setTabEnabled(self.files_tab_idx, False)

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

    def _on_file_offer(self, file_name: str, file_size: int) -> str | None:
        holder = {"path": None}
        event = threading.Event()
        self._ui_queue.put(("file_offer_prompt", file_name, file_size, holder, event))
        event.wait()
        return holder["path"]

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
        text = self.chat_input.text().strip()
        if not text:
            return
        if not self._channels_ready or not self._host:
            QMessageBox.information(self, "Not connected", "Wait for connection to complete first.")
            return
        try:
            self._host.send_chat(text)
            self.chat_input.clear()
        except Exception as e:
            QMessageBox.warning(self, "Chat send failed", str(e))

    def _send_file(self) -> None:
        if not self._channels_ready or not self._host:
            QMessageBox.information(self, "Not connected", "Wait for connection to complete first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select file to send")
        if not path:
            return
        try:
            self.file_log.append(f"Sending: {path}")
            self._host.send_file(path)
        except Exception as e:
            QMessageBox.warning(self, "File send failed", str(e))

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
                    self.tabs.setTabEnabled(self.chat_tab_idx, True)
                    self.tabs.setTabEnabled(self.files_tab_idx, True)
                    self.chat_input.setEnabled(True)
                    self.send_chat_btn.setEnabled(True)
                    self.send_file_btn.setEnabled(True)
                    self.status_label.setText("Connected. Chat and Files enabled.")
                elif msg == "SESSION_CHANNELS_CLOSED":
                    self._channels_ready = False
                    self.tabs.setTabEnabled(self.chat_tab_idx, False)
                    self.tabs.setTabEnabled(self.files_tab_idx, False)
                    self.chat_input.setEnabled(False)
                    self.send_chat_btn.setEnabled(False)
                    self.send_file_btn.setEnabled(False)
                    self.status_label.setText("Disconnected. Chat and Files disabled.")
                else:
                    self.status_label.setText(msg)
            elif kind == "chat":
                self.chat_view.append(f"{item[1]}: {item[2]}")
            elif kind == "file_progress":
                file_name, transferred, total, direction = item[1], item[2], item[3], item[4]
                pct = int((transferred / total) * 100) if total else 0
                self.file_status.setText(f"{direction.upper()} {file_name}: {pct}% ({transferred}/{total} bytes)")
            elif kind == "file_done":
                file_name, path, direction = item[1], item[2], item[3]
                self.file_log.append(f"{direction.upper()} complete: {file_name} -> {path}")
            elif kind == "file_offer_prompt":
                file_name, file_size, holder, event = item[1], item[2], item[3], item[4]
                save_path, _ = QFileDialog.getSaveFileName(self, "Save incoming file", file_name)
                holder["path"] = save_path or None
                event.set()
            elif kind == "error":
                self.status_label.setText(f"ERROR: {item[1]}")
            elif kind == "done":
                self._is_running = False
                self.status_label.setText("Host stopped.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = HostUI()
    win.show()
    sys.exit(app.exec())

