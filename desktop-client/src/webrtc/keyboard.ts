/**
 * Map browser keyboard events to the key names expected by `host/input_receiver.py`
 * (via pynput's `Key` attributes or single-character keys).
 */
export function mapKeyboardEvent(
  ev: KeyboardEvent,
  options: { swapModifiers?: boolean } = {}
): { key: string; pressed: boolean } | null {
  if (ev.repeat) return null;

  const code = ev.code;
  const key = ev.key;
  const swap = options.swapModifiers;

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
    // Base modifiers
    ControlLeft: swap ? "cmd_l" : "ctrl_l",
    ControlRight: swap ? "cmd_r" : "ctrl_r",
    AltLeft: "alt_l",
    AltRight: "alt_r",
    ShiftLeft: "shift_l",
    ShiftRight: "shift_r",
    MetaLeft: swap ? "ctrl_l" : "cmd_l",
    MetaRight: swap ? "ctrl_r" : "cmd_r",
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
    // Adjust logic if ctrlKey is involved but we swapped them
    const isCtrl = swap ? ev.metaKey : ev.ctrlKey;
    if (isCtrl && key.length === 1 && /[A-Z]/i.test(key)) {
      ch = key.toLowerCase();
    } else {
      ch = key.toLowerCase();
    }
    return { key: ch, pressed: ev.type === "keydown" };
  }

  return null;
}
