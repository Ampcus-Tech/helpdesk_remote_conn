import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import random
import string
import sys
import os
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import setup_logging
from host.webrtc_host import WebRTCHost

class HostGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Remote Desktop - Host")
        self.root.geometry("400x300")
        self.root.resizable(False, False)
        
        self.host_id = None
        self.host = None
        self.is_running = False
        
        self.setup_ui()
        self.center_window()
        
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="Remote Desktop Host", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 20))
        
        self.status_label = ttk.Label(status_frame, text="Not Started", foreground="red")
        self.status_label.grid(row=0, column=0)
        
        # Host ID frame
        id_frame = ttk.LabelFrame(main_frame, text="Your Host ID", padding="10")
        id_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 20))
        
        self.id_label = ttk.Label(id_frame, text="--------", font=("Courier", 20, "bold"), foreground="blue")
        self.id_label.grid(row=0, column=0)
        
        # Instructions
        instructions = ttk.Label(main_frame, text="Share this ID with the client\nto allow them to connect", 
                                justify=tk.CENTER, foreground="gray")
        instructions.grid(row=3, column=0, columnspan=2, pady=(0, 20))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2)
        
        self.start_button = ttk.Button(button_frame, text="Start Sharing", command=self.start_hosting)
        self.start_button.grid(row=0, column=0, padx=(0, 10))
        
        self.stop_button = ttk.Button(button_frame, text="Stop Sharing", command=self.stop_hosting, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1)
        
        # Copy button
        self.copy_button = ttk.Button(main_frame, text="Copy ID", command=self.copy_id, state=tk.DISABLED)
        self.copy_button.grid(row=5, column=0, columnspan=2, pady=(10, 0))
        
    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
    def generate_host_id(self, length=6):
        return ''.join(random.choices(string.digits, k=length))
        
    def copy_id(self):
        if self.host_id:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.host_id)
            messagebox.showinfo("Copied", f"Host ID {self.host_id} copied to clipboard!")
            
    def start_hosting(self):
        if not self.is_running:
            self.host_id = self.generate_host_id()
            self.id_label.config(text=self.host_id)
            self.status_label.config(text="Waiting for connection...", foreground="orange")
            
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.copy_button.config(state=tk.NORMAL)
            
            self.is_running = True
            
            # Start hosting in a separate thread
            threading.Thread(target=self._run_host, daemon=True).start()
            
    def stop_hosting(self):
        if self.is_running and self.host:
            self.is_running = False
            if hasattr(self.host, 'stop'):
                self.host.stop()
            
            self.status_label.config(text="Stopped", foreground="red")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.copy_button.config(state=tk.DISABLED)
            
    def _run_host(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            self.host = WebRTCHost(self.host_id)
            self.host.on_client_connected = self.on_client_connected
            self.host.on_client_disconnected = self.on_client_disconnected
            
            loop.run_until_complete(self.host.run())
        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"Host error: {str(e)}"))
        finally:
            if self.is_running:
                self.root.after(0, self.stop_hosting)
                
    def on_client_connected(self):
        self.root.after(0, lambda: self.status_label.config(text="Client Connected", foreground="green"))
        
    def on_client_disconnected(self):
        if self.is_running:
            self.root.after(0, lambda: self.status_label.config(text="Waiting for connection...", foreground="orange"))
            
    def _show_error(self, message):
        messagebox.showerror("Error", message)
        self.stop_hosting()
        
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
        
    def on_closing(self):
        if self.is_running:
            self.stop_hosting()
        self.root.destroy()

if __name__ == "__main__":
    setup_logging()
    app = HostGUI()
    app.run()
