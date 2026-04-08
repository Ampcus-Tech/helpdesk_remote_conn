use std::collections::HashSet;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::AppHandle;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyEvent {
    pub key: String,
    pub pressed: bool,
}

#[derive(Clone)]
pub struct KeyboardHook {
    pub is_hooking: Arc<Mutex<bool>>,
    pub pressed_keys: Arc<Mutex<HashSet<String>>>,
    app_handle: AppHandle,
}

impl KeyboardHook {
    pub fn new(app_handle: AppHandle) -> Self {
        Self {
            is_hooking: Arc::new(Mutex::new(false)),
            pressed_keys: Arc::new(Mutex::new(HashSet::new())),
            app_handle,
        }
    }

    pub fn start_hooking(&self) -> Result<(), Box<dyn std::error::Error>> {
        let mut is_hooking = self.is_hooking.lock().unwrap();
        if *is_hooking {
            return Ok(());
        }
        *is_hooking = true;
        drop(is_hooking);

        let is_hooking_clone = Arc::clone(&self.is_hooking);
        let pressed_keys_clone = Arc::clone(&self.pressed_keys);
        let app_handle = self.app_handle.clone();

        thread::spawn(move || {
            #[cfg(windows)]
            {
                self::windows::start_windows_keyboard_hook(
                    is_hooking_clone,
                    pressed_keys_clone,
                    app_handle,
                );
            }
            
            #[cfg(not(windows))]
            {
                // For non-Windows platforms, we'll need a different approach
                // For now, just keep the thread alive
                while *is_hooking_clone.lock().unwrap() {
                    thread::sleep(Duration::from_millis(100));
                }
            }
        });

        Ok(())
    }

    pub fn stop_hooking(&self) {
        let mut is_hooking = self.is_hooking.lock().unwrap();
        *is_hooking = false;
        
        // Release all pressed keys
        let mut pressed_keys = self.pressed_keys.lock().unwrap();
        for key in pressed_keys.drain() {
            let event = KeyEvent { key, pressed: false };
            let _ = self.app_handle.emit("keyboard-event", &event);
        }
    }

    pub fn is_window_focused(&self) -> bool {
        #[cfg(windows)]
        {
            self::windows::is_window_focused(&self.app_handle)
        }
        
        #[cfg(not(windows))]
        {
            true // Placeholder for non-Windows
        }
    }
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::ptr;
    use winapi::um::winuser::{
        SetWindowsHookExA, UnhookWindowsHookEx, CallNextHookEx, GetMessageA,
        HC_ACTION, WH_KEYBOARD_LL, KBDLLHOOKSTRUCT, WM_KEYDOWN, WM_KEYUP,
        WM_SYSKEYDOWN, WM_SYSKEYUP, GetForegroundWindow, GetWindowTextLengthW,
        GetWindowTextW, IsIconic, IsWindowVisible,
    };
    use winapi::um::processthreadsapi::GetCurrentThreadId;
    use winapi::um::handleapi::INVALID_HANDLE_VALUE;
    use winapi::shared::windef::{HHOOK, HHOOK__, HWND};
    use winapi::shared::minwindef::{DWORD, WPARAM, LPARAM, LRESULT};
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt;

    static mut HOOK: Option<HHOOK> = None;
    static mut HOOK_DATA: Option<(Arc<Mutex<bool>>, Arc<Mutex<HashSet<String>>>, AppHandle)> = None;

    unsafe extern "system" fn keyboard_proc(
        n_code: i32,
        w_param: WPARAM,
        l_param: LPARAM,
    ) -> LRESULT {
        if n_code == HC_ACTION {
            let hook_struct = *(l_param as *const KBDLLHOOKSTRUCT);
            let vk_code = hook_struct.vkCode;
            
            if let Some((is_hooking, pressed_keys, app_handle)) = &HOOK_DATA {
                if *is_hooking.lock().unwrap() && is_window_focused(app_handle) {
                    let key_name = map_vk_code_to_string(vk_code);
                    if let Some(key) = key_name {
                        let pressed = matches!(
                            w_param,
                            WM_KEYDOWN | WM_SYSKEYDOWN
                        );
                        
                        let mut keys = pressed_keys.lock().unwrap();
                        if pressed {
                            if !keys.contains(&key) {
                                keys.insert(key.clone());
                                let event = KeyEvent { key, pressed };
                                let _ = app_handle.emit("keyboard-event", &event);
                            }
                        } else {
                            if keys.remove(&key) {
                                let event = KeyEvent { key, pressed };
                                let _ = app_handle.emit("keyboard-event", &event);
                            }
                        }
                    }
                    
                    // Suppress the key to prevent local handling
                    return 1;
                }
            }
        }
        
        CallNextHookEx(ptr::null_mut(), n_code, w_param, l_param)
    }

    pub fn start_windows_keyboard_hook(
        is_hooking: Arc<Mutex<bool>>,
        pressed_keys: Arc<Mutex<HashSet<String>>>,
        app_handle: AppHandle,
    ) {
        unsafe {
            HOOK_DATA = Some((is_hooking, pressed_keys, app_handle));
            
            let hook = SetWindowsHookExA(
                WH_KEYBOARD_LL,
                Some(keyboard_proc),
                ptr::null_mut(),
                0,
            );
            
            if hook != (INVALID_HANDLE_VALUE as HOOK) {
                HOOK = Some(hook);
                
                let mut msg = std::mem::zeroed();
                while *HOOK_DATA.as_ref().unwrap().0.lock().unwrap() {
                    if GetMessageA(&mut msg, ptr::null_mut(), 0, 0) <= 0 {
                        break;
                    }
                }
                
                if let Some(h) = HOOK {
                    UnhookWindowsHookEx(h);
                }
                HOOK = None;
            }
            
            HOOK_DATA = None;
        }
    }

    pub fn is_window_focused(app_handle: &AppHandle) -> bool {
        unsafe {
            let hwnd = GetForegroundWindow();
            if hwnd.is_null() {
                return false;
            }
            
            // Check if window is minimized
            if IsIconic(hwnd) != 0 {
                return false;
            }
            
            // Check if window is visible
            if IsWindowVisible(hwnd) == 0 {
                return false;
            }
            
            // Get window title and check if it contains our app name
            let length = GetWindowTextLengthW(hwnd);
            if length == 0 {
                return false;
            }
            
            let mut buffer = vec![0u16; (length + 1) as usize];
            GetWindowTextW(hwnd, buffer.as_mut_ptr(), length + 1);
            
            let title = OsString::from_wide(&buffer)
                .to_string_lossy()
                .to_lowercase();
            
            // Check if title contains indicators of our remote desktop app
            title.contains("remote") || title.contains("desktop") || title.contains("helpdesk")
        }
    }

    fn map_vk_code_to_string(vk_code: DWORD) -> Option<String> {
        match vk_code {
            0x01 => Some("esc".to_string()),
            0x02 => Some("1".to_string()),
            0x03 => Some("2".to_string()),
            0x04 => Some("3".to_string()),
            0x05 => Some("4".to_string()),
            0x06 => Some("5".to_string()),
            0x07 => Some("6".to_string()),
            0x08 => Some("7".to_string()),
            0x09 => Some("8".to_string()),
            0x0A => Some("9".to_string()),
            0x0B => Some("0".to_string()),
            0x0C => Some("-".to_string()),
            0x0D => Some("=".to_string()),
            0x0E => Some("backspace".to_string()),
            0x0F => Some("tab".to_string()),
            0x10 => Some("q".to_string()),
            0x11 => Some("w".to_string()),
            0x12 => Some("e".to_string()),
            0x13 => Some("r".to_string()),
            0x14 => Some("t".to_string()),
            0x15 => Some("y".to_string()),
            0x16 => Some("u".to_string()),
            0x17 => Some("i".to_string()),
            0x18 => Some("o".to_string()),
            0x19 => Some("p".to_string()),
            0x1A => Some("[".to_string()),
            0x1B => Some("]".to_string()),
            0x1C => Some("enter".to_string()),
            0x1D => Some("ctrl_l".to_string()),
            0x1E => Some("a".to_string()),
            0x1F => Some("s".to_string()),
            0x20 => Some("d".to_string()),
            0x21 => Some("f".to_string()),
            0x22 => Some("g".to_string()),
            0x23 => Some("h".to_string()),
            0x24 => Some("j".to_string()),
            0x25 => Some("k".to_string()),
            0x26 => Some("l".to_string()),
            0x27 => Some(";".to_string()),
            0x28 => Some("'".to_string()),
            0x29 => Some("`".to_string()),
            0x2A => Some("shift_l".to_string()),
            0x2B => Some("\\".to_string()),
            0x2C => Some("z".to_string()),
            0x2D => Some("x".to_string()),
            0x2E => Some("c".to_string()),
            0x2F => Some("v".to_string()),
            0x30 => Some("b".to_string()),
            0x31 => Some("n".to_string()),
            0x32 => Some("m".to_string()),
            0x33 => Some(",".to_string()),
            0x34 => Some(".".to_string()),
            0x35 => Some("/".to_string()),
            0x36 => Some("shift_r".to_string()),
            0x37 => Some("*".to_string()),
            0x38 => Some("alt_l".to_string()),
            0x39 => Some("space".to_string()),
            0x3A => Some("caps_lock".to_string()),
            0x3B => Some("f1".to_string()),
            0x3C => Some("f2".to_string()),
            0x3D => Some("f3".to_string()),
            0x3E => Some("f4".to_string()),
            0x3F => Some("f5".to_string()),
            0x40 => Some("f6".to_string()),
            0x41 => Some("f7".to_string()),
            0x42 => Some("f8".to_string()),
            0x43 => Some("f9".to_string()),
            0x44 => Some("f10".to_string()),
            0x45 => Some("num_lock".to_string()),
            0x46 => Some("scroll_lock".to_string()),
            0x47 => Some("7".to_string()), // Numpad 7
            0x48 => Some("8".to_string()), // Numpad 8
            0x49 => Some("9".to_string()), // Numpad 9
            0x4A => Some("-".to_string()), // Numpad -
            0x4B => Some("4".to_string()), // Numpad 4
            0x4C => Some("5".to_string()), // Numpad 5
            0x4D => Some("6".to_string()), // Numpad 6
            0x4E => Some("+".to_string()), // Numpad +
            0x4F => Some("1".to_string()), // Numpad 1
            0x50 => Some("2".to_string()), // Numpad 2
            0x51 => Some("3".to_string()), // Numpad 3
            0x52 => Some("0".to_string()), // Numpad 0
            0x53 => Some(".".to_string()), // Numpad .
            0x54 => Some("print_screen".to_string()),
            0x57 => Some("f11".to_string()),
            0x58 => Some("f12".to_string()),
            0x5B => Some("cmd_l".to_string()), // Windows key
            0x5C => Some("cmd_r".to_string()), // Windows key
            0x5D => Some("menu".to_string()),
            0x5E => Some("".to_string()), // Unknown
            0x5F => Some("".to_string()), // Unknown
            0x60 => Some("".to_string()), // Unknown
            0x61 => Some("".to_string()), // Unknown
            0x62 => Some("".to_string()), // Unknown
            0x63 => Some("".to_string()), // Unknown
            0x64 => Some("f13".to_string()),
            0x65 => Some("f14".to_string()),
            0x66 => Some("f15".to_string()),
            0x67 => Some("f16".to_string()),
            0x68 => Some("f17".to_string()),
            0x69 => Some("f18".to_string()),
            0x6A => Some("f19".to_string()),
            0x6B => Some("f20".to_string()),
            0x6C => Some("f21".to_string()),
            0x6D => Some("f22".to_string()),
            0x6E => Some("f23".to_string()),
            0x6F => Some("f24".to_string()),
            0x70 => Some("".to_string()), // Unknown
            0x71 => Some("".to_string()), // Unknown
            0x72 => Some("".to_string()), // Unknown
            0x73 => Some("".to_string()), // Unknown
            0x74 => Some("".to_string()), // Unknown
            0x75 => Some("".to_string()), // Unknown
            0x76 => Some("".to_string()), // Unknown
            0x77 => Some("".to_string()), // Unknown
            0x78 => Some("".to_string()), // Unknown
            0x79 => Some("".to_string()), // Unknown
            0x7A => Some("".to_string()), // Unknown
            0x7B => Some("".to_string()), // Unknown
            0x7C => Some("".to_string()), // Unknown
            0x7D => Some("".to_string()), // Unknown
            0x7E => Some("".to_string()), // Unknown
            0x7F => Some("".to_string()), // Unknown
            0x90 => Some("num_lock".to_string()),
            0x91 => Some("scroll_lock".to_string()),
            0xA0 => Some("shift_l".to_string()),
            0xA1 => Some("shift_r".to_string()),
            0xA2 => Some("ctrl_l".to_string()),
            0xA3 => Some("ctrl_r".to_string()),
            0xA4 => Some("alt_l".to_string()),
            0xA5 => Some("alt_r".to_string()),
            0xB0 => Some("".to_string()), // Unknown
            0xB1 => Some("".to_string()), // Unknown
            0xB2 => Some("".to_string()), // Unknown
            0xB3 => Some("".to_string()), // Unknown
            0xB4 => Some("".to_string()), // Unknown
            0xB5 => Some("".to_string()), // Unknown
            0xB6 => Some("".to_string()), // Unknown
            0xB7 => Some("".to_string()), // Unknown
            0xBA => Some(";".to_string()),
            0xBB => Some("=".to_string()),
            0xBC => Some(",".to_string()),
            0xBD => Some("-".to_string()),
            0xBE => Some(".".to_string()),
            0xBF => Some("/".to_string()),
            0xC0 => Some("`".to_string()),
            0xDB => Some("[".to_string()),
            0xDC => Some("\\".to_string()),
            0xDD => Some("]".to_string()),
            0xDE => Some("'".to_string()),
            0xE2 => Some("\\".to_string()), // Non-US backslash
            _ => None,
        }
    }
}
