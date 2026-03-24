import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import sys
import os
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import setup_logging
from client.webrtc_client import WebRTCClient

class ClientGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Remote Desktop - Client")
        self.root.geometry("400x350")
        self.root.resizable(False, False)
        
        self.client = None
        self.is_connected = False
        
        self.setup_ui()
        self.center_window()
        
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="Remote Desktop Client", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Connection frame
        conn_frame = ttk.LabelFrame(main_frame, text="Connect to Host", padding="15")
        conn_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 20))
        
        # Host ID input
        ttk.Label(conn_frame, text="Enter Host ID:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        self.host_id_var = tk.StringVar()
        self.host_id_entry = ttk.Entry(conn_frame, textvariable=self.host_id_var, font=("Courier", 14), width=15)
        self.host_id_entry.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Bind Enter key
        self.host_id_entry.bind('<Return>', lambda e: self.connect_to_host())
        
        # Connect button
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self.connect_to_host)
        self.connect_button.grid(row=2, column=0, sticky=(tk.W, tk.E))
        
        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 20))
        
        self.status_label = ttk.Label(status_frame, text="Ready to connect", foreground="blue")
        self.status_label.grid(row=0, column=0)
        
        # Instructions
        instructions_text = """Instructions:
1. Ask the host for their 6-digit ID
2. Enter the ID above
3. Click Connect or press Enter
4. Wait for the connection to establish"""
        
        instructions = ttk.Label(main_frame, text=instructions_text, justify=tk.LEFT, foreground="gray")
        instructions.grid(row=3, column=0, columnspan=2, pady=(0, 20))
        
        # Disconnect button (initially disabled)
        self.disconnect_button = ttk.Button(main_frame, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_button.grid(row=4, column=0, columnspan=2)
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        conn_frame.columnconfigure(0, weight=1)
        
    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
    def connect_to_host(self):
        host_id = self.host_id_var.get().strip()
        
        if not host_id:
            messagebox.showwarning("Invalid Input", "Please enter a Host ID")
            return
            
        if not host_id.isdigit() or len(host_id) != 6:
            messagebox.showwarning("Invalid Input", "Host ID must be 6 digits")
            return
            
        if self.is_connected:
            return
            
        self.status_label.config(text="Connecting...", foreground="orange")
        self.connect_button.config(state=tk.DISABLED)
        self.host_id_entry.config(state=tk.DISABLED)
        
        # Start connection in a separate thread
        threading.Thread(target=self._run_client, args=(host_id,), daemon=True).start()
        
    def disconnect(self):
        if self.is_connected and self.client:
            self.is_connected = False
            if hasattr(self.client, 'stop'):
                self.client.stop()
            
            self.status_label.config(text="Disconnected", foreground="red")
            self.connect_button.config(state=tk.NORMAL)
            self.disconnect_button.config(state=tk.DISABLED)
            self.host_id_entry.config(state=tk.NORMAL)
            
    def _run_client(self, host_id):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            self.client = WebRTCClient(host_id)
            self.client.on_connected = self.on_connected
            self.client.on_disconnected = self.on_disconnected
            self.client.on_error = self.on_error
            
            loop.run_until_complete(self.client.run())
        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"Connection error: {str(e)}"))
        finally:
            if self.is_connected:
                self.root.after(0, self.disconnect)
                
    def on_connected(self):
        self.root.after(0, lambda: self.status_label.config(text="Connected to host", foreground="green"))
        self.root.after(0, lambda: self.disconnect_button.config(state=tk.NORMAL))
        
    def on_disconnected(self):
        if self.is_connected:
            self.root.after(0, self.disconnect)
            
    def on_error(self, error_message):
        self.root.after(0, lambda: self._show_error(error_message))
        
    def _show_error(self, message):
        messagebox.showerror("Connection Error", message)
        self.disconnect()
        
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
        
    def on_closing(self):
        if self.is_connected:
            self.disconnect()
        self.root.destroy()

if __name__ == "__main__":
    setup_logging()
    app = ClientGUI()
    app.run()
