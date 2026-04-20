import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import { ActiveSession, startSession, sendChatLine, sendFile, respondFileOffer } from "../webrtc/session";
 
export type SessionMode = "idle" | "host" | "client";
 
export interface SessionState {
  mode: SessionMode;
  status: string;
  hostId: string;
  connected: boolean;
  error: string | null;
}
 
export type SessionEvents = {
  onStatusChange: (status: string) => void;
  onHostIdGenerated: (id: string) => void;
  onConnected: () => void;
  onDisconnected: (reason?: string) => void;
  onChatReceived: (who: string, text: string) => void;
  onVideoStream: (stream: MediaStream) => void;
  onCursorChange: (name: string) => void;
  onHostWarning: (msg: string) => void;
  onHostInfo: (os: string) => void;
  onFileOffer: (fileId: string, fileName: string, fileSize: number) => void;
  onFileProgress: (fileName: string, transferred: number, total: number, direction: "send" | "recv") => void;
  onFileDone: (fileName: string, path: string, direction: "send" | "recv") => void;
};
 
class SessionManager {
  private mode: SessionMode = "idle";
  private jsSession: ActiveSession | null = null;
  private unlisteners: UnlistenFn[] = [];
  private events: Partial<SessionEvents> = {};
  private inputHelperPaused = false;
 
  setEvents(events: SessionEvents) {
    this.events = events;
  }
 
  async startHost() {
    this.events.onStatusChange?.("Starting python host...");
 
    // Setup listeners for python output
    const un1 = await listen<string>("host-stdout", (event) => {
      const line = event.payload;
      console.log("Python stdout:", line);
 
      if (line.includes("UI_SIGNAL:HOST_ID:")) {
        const id = line.split("UI_SIGNAL:HOST_ID:")[1].trim();
        this.events.onHostIdGenerated?.(id);
      } else if (line.includes("UI_SIGNAL:WARN:")) {
        const warn = line.split("UI_SIGNAL:WARN:")[1].trim();
        this.events.onHostWarning?.(warn);
      } else if (line.includes("UI_SIGNAL:ERROR:")) {
        const err = line.split("UI_SIGNAL:ERROR:")[1].trim();
        this.events.onStatusChange?.(`Host Error: ${err}`);
      } else if (line.includes("UI_SIGNAL:STATUS:")) {
        const status = line.split("UI_SIGNAL:STATUS:")[1].trim();
        this.events.onStatusChange?.(status);
        if (status === "SESSION_CONNECTED") {
          this.events.onConnected?.();
        }
      } else if (line.includes("UI_SIGNAL:CHAT_RECEIVED:")) {
        const data = JSON.parse(line.split("UI_SIGNAL:CHAT_RECEIVED:")[1].trim());
        this.events.onChatReceived?.(data.sender, data.text);
      } else if (line.includes("UI_SIGNAL:FILE_OFFER:")) {
        const data = JSON.parse(line.split("UI_SIGNAL:FILE_OFFER:")[1].trim());
        this.events.onFileOffer?.(data.file_id, data.name, data.size);
      } else if (line.includes("UI_SIGNAL:FILE_PROGRESS:")) {
        const data = JSON.parse(line.split("UI_SIGNAL:FILE_PROGRESS:")[1].trim());
        this.events.onFileProgress?.(data.name, data.progress, data.total, data.direction);
      } else if (line.includes("UI_SIGNAL:FILE_DONE:")) {
        const data = JSON.parse(line.split("UI_SIGNAL:FILE_DONE:")[1].trim());
        this.events.onFileDone?.(data.name, data.path, data.direction);
      } else if (line.includes("SESSION_CONNECTED")) {
        // Fallback for older host versions
        this.events.onStatusChange?.("Client connected");
        this.events.onConnected?.();
      } else if (line.includes("SESSION_CHANNELS_CLOSED")) {
        this.events.onStatusChange?.("Client disconnected");
        this.events.onDisconnected?.("Client closed connection");
      } else if (line.startsWith("Host registered")) {
        this.events.onStatusChange?.("Waiting for client...");
      } else {
        // Generic status update if it looks useful
        if (line.length < 100 && !line.includes("{")) {
          this.events.onStatusChange?.(line);
        }
      }
    });
 
    const un2 = await listen<string>("host-stderr", (event) => {
      const line = event.payload;
      console.error("Python stderr:", line);
      // If it looks like a python error, show it in the UI
      if (line.toLowerCase().includes("error") || line.toLowerCase().includes("exception") || line.includes("can't open file")) {
        this.events.onStatusChange?.(`Host Error: ${line}`);
      }
    });
 
    this.unlisteners.push(un1, un2);
 
    try {
      await invoke("start_host");
    } catch (e: unknown) {
      this.events.onStatusChange?.(`Failed to start host: ${e}`);
    }
  }
 
  async stopHost() {
    try {
      await invoke("stop_host");
    } catch (e: unknown) {
      console.error(e);
    }
    this.cleanup();
  }
 
  async startClient(hostId: string) {
    this.events.onStatusChange?.("Connecting to host...");
 
    try {
      this.jsSession = await startSession(hostId, {
        onStatus: (msg) => this.events.onStatusChange?.(msg),
        onVideoStream: (stream) => this.events.onVideoStream?.(stream),
        onControlOpen: () => { },
        onControlMessage: () => { },
        onCursorName: (name) => this.events.onCursorChange?.(name),
        onChatText: (who, text) => this.events.onChatReceived?.(who, text),
        onHostInfo: (os) => {
          console.log("Remote Host OS:", os);
          this.events.onHostInfo?.(os);
        },
        onFileOffer: (fileId, fileName, fileSize) => this.events.onFileOffer?.(fileId, fileName, fileSize),
        onFileProgress: (fileName, transferred, total, direction) => this.events.onFileProgress?.(fileName, transferred, total, direction),
        onFileDone: (fileName, path, direction) => this.events.onFileDone?.(fileName, path, direction),
        onDataChannelsReady: () => {
          this.events.onStatusChange?.("Connected to host");
          this.events.onConnected?.();
          // Start the global input helper when channels are ready
          void this.startInputHelper();
        },
        onSessionEnd: (reason) => {
          void this.stopInputHelper();
          this.events.onDisconnected?.(reason);
          this.cleanup();
        },
      });
    } catch (e: unknown) {
      this.events.onStatusChange?.(e instanceof Error ? e.message : String(e));
      this.cleanup();
    }
  }
 
  async stopClient() {
    this.stopInputHelper().catch(console.error);
    this.jsSession?.close();
    this.jsSession = null;
    this.cleanup();
  }
 
  private async startInputHelper() {
    console.log("Starting input helper...");
 
    // Listen for helper output
    const un = await listen<string>("input-helper-stdout", (event) => {
      if (this.inputHelperPaused) return;
      try {
        const data = JSON.parse(event.payload);
        if (this.jsSession?.channels.ctrl.readyState === "open") {
          this.jsSession.channels.ctrl.send(JSON.stringify({
            type: "keyboard",
            key: data.key,
            pressed: data.pressed
          }));
        }
      } catch (e: unknown) {
        // Silently ignore parse errors
      }
    });
    this.unlisteners.push(un);
 
    try {
      await invoke("start_input_helper");
      console.log("Input helper started successfully");
    } catch (e: unknown) {
      console.error("Failed to start input helper:", e);
      // Remove the listener if starting failed
      un();
      this.unlisteners = this.unlisteners.filter(l => l !== un);
    }
  }
 
  async setInputHelperActive(active: boolean) {
    this.inputHelperPaused = !active;
    try {
      await invoke("set_input_helper_active", { active });
    } catch (e: unknown) {
      console.error("Failed to set input helper state:", e);
    }
  }
 
  private async stopInputHelper() {
    try {
      await invoke("stop_input_helper");
      console.log("Input helper stopped successfully");
    } catch (e: unknown) {
      // It's ok if the helper wasn't running
      const errorStr = String(e);
      if (!errorStr.includes("not running")) {
        console.error("Error stopping input helper:", e);
      }
    }
  }
 
  private cleanup() {
    // Always attempt to stop the helper so no global keyboard hook survives
    // after disconnects, failed sessions, or mode switches.
    void this.stopInputHelper();
    this.mode = "idle";
    this.unlisteners.forEach((u) => u());
    this.unlisteners = [];
  }
 
  // Helper for sending chat via active JS session OR host process
  sendChat(text: string) {
    if (this.jsSession?.channels.chat) {
      sendChatLine(this.jsSession.channels.chat, text);
    } else {
      // Assume host mode: send to python stdin
      void invoke("send_host_command", {
        cmd: JSON.stringify({ type: "send_chat", text })
      });
    }
  }
 
  async sendFile(file: File | string, onProgress: (p: number) => void) {
    if (this.jsSession?.channels.file && file instanceof File) {
      return await sendFile(this.jsSession.channels.file, file, onProgress);
    } else if (typeof file === "string") {
      // Host mode: send path to python
      await invoke("send_host_command", {
        cmd: JSON.stringify({ type: "send_file", path: file })
      });
      return true;
    }
    return false;
  }
 
  respondToFileOffer(fileId: string, accepted: boolean, savePath?: string) {
    if (this.jsSession?.channels.file) {
      respondFileOffer(this.jsSession.channels.file, fileId, accepted);
    } else {
      // Host mode: send to python stdin
      void invoke("send_host_command", {
        cmd: JSON.stringify({ type: "respond_file_offer", file_id: fileId, save_path: accepted ? (savePath || "received_file") : null })
      });
    }
  }
 
  getActiveSession() {
    return this.jsSession;
  }
}
 
export const sessionManager = new SessionManager();
export default sessionManager;