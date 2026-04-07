/**
 * Map browser keyboard events to the key names expected by `host/input_receiver.py`
 * (via pynput's `Key` attributes or single-character keys).
 */
export function mapKeyboardEvent(ev: KeyboardEvent): { key: string; pressed: boolean } | null {
  if (ev.repeat) return null;

  const code = ev.code;
  const key = ev.key;

  const codeMap: Record<string, string> = {
    Enter: "enter",
    Space: "space",
    Backspace: "backspace",
    Tab: "tab",
    Escape: "esc",
    ArrowUp: "up",
    ArrowDown: "down",
    ArrowLeft: "left",
    ArrowRight: "right",
    Delete: "delete",
    Insert: "insert",
    Home: "home",
    End: "end",
    PageUp: "page_up",
    PageDown: "page_down",
    CapsLock: "caps_lock",
    NumLock: "num_lock",
    ScrollLock: "scroll_lock",
    Pause: "pause",
    PrintScreen: "print_screen",
    ContextMenu: "menu",
    ControlLeft: "ctrl_l",
    ControlRight: "ctrl_r",
    AltLeft: "alt_l",
    AltRight: "alt_r",
    ShiftLeft: "shift_l",
    ShiftRight: "shift_r",
    MetaLeft: "cmd_l",
    MetaRight: "cmd_r",
  };

  if (codeMap[code]) {
    return { key: codeMap[code], pressed: ev.type === "keydown" };
  }

  if (code.startsWith("F") && /^F\d{1,2}$/.test(code)) {
    const n = code.slice(1);
    const fn = Number(n);
    if (fn >= 1 && fn <= 24) {
      return { key: `f${fn}`, pressed: ev.type === "keydown" };
    }
  }

  if (key.length === 1) {
    let ch = key;
    if (ev.ctrlKey && key.length === 1 && /[A-Z]/i.test(key)) {
      ch = key.toLowerCase();
    } else {
      ch = key.toLowerCase();
    }
    return { key: ch, pressed: ev.type === "keydown" };
  }

  return null;
}

/**
 * Map rdev key names (from Rust backend) to the key names expected by our protocol.
 */
export function mapRdevKey(rdevKey: string, pressed: boolean): { key: string; pressed: boolean } | null {
  // rdev formats keys like "KeyA", "CapsLock", "MetaLeft", etc.
  const mapping: Record<string, string> = {
    Enter: "enter",
    Space: "space",
    Backspace: "backspace",
    Tab: "tab",
    Escape: "esc",
    UpArrow: "up",
    DownArrow: "down",
    LeftArrow: "left",
    RightArrow: "right",
    Delete: "delete",
    Insert: "insert",
    Home: "home",
    End: "end",
    PageUp: "page_up",
    PageDown: "page_down",
    CapsLock: "caps_lock",
    NumLock: "num_lock",
    ScrollLock: "scroll_lock",
    Pause: "pause",
    PrintScreen: "print_screen",
    ContextMenu: "menu",
    ControlLeft: "ctrl_l",
    ControlRight: "ctrl_r",
    Alt: "alt_l",
    AltGr: "alt_r",
    ShiftLeft: "shift_l",
    ShiftRight: "shift_r",
    MetaLeft: "cmd_l",
    MetaRight: "cmd_r",
  };

  if (mapping[rdevKey]) {
    return { key: mapping[rdevKey], pressed };
  }

  // Handle Function keys F1..F24
  if (rdevKey.startsWith("F") && rdevKey.length <= 3) {
    const n = rdevKey.slice(1);
    if (!isNaN(Number(n))) {
      return { key: `f${n}`, pressed };
    }
  }

  // Handle single characters (KeyA -> a, Num1 -> 1, etc.)
  if (rdevKey.startsWith("Key")) {
    return { key: rdevKey.slice(3).toLowerCase(), pressed };
  }
  if (rdevKey.startsWith("Num")) {
    const n = rdevKey.slice(3);
    if (n.length === 1) return { key: n, pressed };
  }

  // Lowercase fallback for anything else (e.g. "a", "b", "1")
  if (rdevKey.length === 1) {
    return { key: rdevKey.toLowerCase(), pressed };
  }

  return null;
}
