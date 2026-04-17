import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import { ActiveSession, startSession } from "../webrtc/session";
 
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
};
 
class SessionManager {
  private mode: SessionMode = "idle";
  private jsSession: ActiveSession | null = null;
  private unlisteners: UnlistenFn[] = [];
  private events: Partial<SessionEvents> = {};
 
  setEvents(events: SessionEvents) {
    this.events = events;
  }
 
  async startHost() {
    this.mode = "host";
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
      } else if (line.includes("SESSION_CONNECTED")) {
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
    } catch (e) {
      this.events.onStatusChange?.(`Failed to start host: ${e}`);
    }
  }
 
  async stopHost() {
    try {
      await invoke("stop_host");
    } catch (e) {
      console.error(e);
    }
    this.cleanup();
  }
 
  async startClient(hostId: string) {
    this.mode = "client";
    this.events.onStatusChange?.("Connecting to host...");
 
    try {
      this.jsSession = await startSession(hostId, {
        onStatus: (msg) => this.events.onStatusChange?.(msg),
        onVideoStream: (stream) => this.events.onVideoStream?.(stream),
        onControlOpen: () => {},
        onControlMessage: () => {},
        onCursorName: (name) => this.events.onCursorChange?.(name),
        onChatText: (who, text) => this.events.onChatReceived?.(who, text),
        onHostInfo: (os) => {
          console.log("Remote Host OS:", os);
          this.events.onHostInfo?.(os);
        },
        onDataChannelsReady: (ch) => {
          this.events.onStatusChange?.("Connected to host");
          this.events.onConnected?.();
          // Start the global input helper when channels are ready
          void this.startInputHelper();
        },
        onSessionEnd: (reason) => {
          this.events.onDisconnected?.(reason);
          this.cleanup();
        },
      });
    } catch (e) {
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
      try {
        const data = JSON.parse(event.payload);
        if (this.jsSession?.channels.ctrl.readyState === "open") {
          this.jsSession.channels.ctrl.send(JSON.stringify({
            type: "keyboard",
            key: data.key,
            pressed: data.pressed
          }));
        }
      } catch (e) {
      }
    });
    this.unlisteners.push(un);
 
    try {
      await invoke("start_input_helper");
    } catch (e) {
      console.error("Failed to start input helper:", e);
    }
  }
 
  private async stopInputHelper() {
    try {
      await invoke("stop_input_helper");
    } catch (e) {
      console.error("Failed to stop input helper:", e);
    }
  }
 
  private cleanup() {
    this.mode = "idle";
    this.unlisteners.forEach((u) => u());
    this.unlisteners = [];
  }
 
  // Helper for sending chat via active JS session
  sendChat(text: string) {
    if (this.jsSession?.channels.chat) {
        const payload = {
            type: "chat_text",
            text: text.trim(),
            ts: Math.floor(Date.now() / 1000),
          };
          this.jsSession.channels.chat.send(JSON.stringify(payload));
    }
  }
 
  getActiveSession() {
    return this.jsSession;
  }
}
 
export const sessionManager = new SessionManager();
export default sessionManager;