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
    AltGraph: "alt_gr",
    ShiftLeft: "shift_l",
    ShiftRight: "shift_r",
    MetaLeft: "cmd_l",
    MetaRight: "cmd_r",
    OSLeft: "cmd_l",
    OSRight: "cmd_r",
  };

  if (codeMap[code]) {
    return { key: codeMap[code], pressed: ev.type === "keydown" };
  }

  // Fallback for key names if code mapping missed it
  const keyMap: Record<string, string> = {
    " ": "space",
    Control: "ctrl",
    Alt: "alt",
    Shift: "shift",
    Meta: "cmd",
  };

  if (keyMap[key]) {
    return { key: keyMap[key], pressed: ev.type === "keydown" };
  }

  if (code.startsWith("F") && /^F\d{1,2}$/.test(code)) {
    const n = code.slice(1);
    const fn = Number(n);
    if (fn >= 1 && fn <= 24) {
      return { key: `f${fn}`, pressed: ev.type === "keydown" };
    }
  }

  // Single character keys
  if (key.length === 1) {
    let ch = key;
    // When Ctrl is held, browsers might emit control characters (e.g. ^A is \u0001).
    // We normalize back to lowercase a-z.
    const charCode = ch.charCodeAt(0);
    if (ev.ctrlKey && charCode >= 1 && charCode <= 26) {
      ch = String.fromCharCode(charCode + 96);
    } else {
      ch = ch.toLowerCase();
    }
    return { key: ch, pressed: ev.type === "keydown" };
  }

  return null;
}
