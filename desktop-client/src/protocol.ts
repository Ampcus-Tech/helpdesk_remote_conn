/** Mirrors `common/messages.py` MessageType values. */
export const MessageType = {
  REGISTER_HOST: "register_host",
  FIND_HOST: "find_host",
  HOST_REGISTERED: "host_registered",
  HOST_NOT_FOUND: "host_not_found",
  SDP: "sdp",
  ICE: "ice",
  MOUSE_MOVE: "mouse_move",
  MOUSE_CLICK: "mouse_click",
  MOUSE_DOUBLE_CLICK: "mouse_double_click",
  MOUSE_SCROLL: "mouse_scroll",
  KEYBOARD: "keyboard",
  CURSOR_UPDATE: "cursor_update",
  CHAT_TEXT: "chat_text",
  FILE_OFFER: "file_offer",
  FILE_ACCEPT: "file_accept",
  FILE_START: "file_start",
  FILE_CHUNK: "file_chunk",
  FILE_END: "file_end",
} as const;

export type ControlMsg =
  | {
      type: typeof MessageType.MOUSE_MOVE;
      x: number;
      y: number;
      screen_width: number;
      screen_height: number;
    }
  | {
      type: typeof MessageType.MOUSE_CLICK;
      button: "left" | "right";
      pressed: boolean;
    }
  | {
      type: typeof MessageType.MOUSE_DOUBLE_CLICK;
      button: "left" | "right";
    }
  | {
      type: typeof MessageType.MOUSE_SCROLL;
      x: number;
      y: number;
      screen_width: number;
      screen_height: number;
      scroll_dx: number;
      scroll_dy: number;
    }
  | {
      type: typeof MessageType.KEYBOARD;
      key: string;
      pressed: boolean;
    };

export function ctrlPayload(m: ControlMsg): string {
  return JSON.stringify(m);
}
