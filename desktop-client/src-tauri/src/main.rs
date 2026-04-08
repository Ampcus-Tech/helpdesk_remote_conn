#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod keyboard_hook;

use keyboard_hook::KeyboardHook;
use std::sync::Arc;
use tauri::{Manager, State};

type KeyboardHookState = Arc<KeyboardHook>;

#[tauri::command]
async fn start_keyboard_hook(
    _app_handle: tauri::AppHandle,
    state: State<'_, KeyboardHookState>,
) -> Result<(), String> {
    state.start_hooking().map_err(|e| e.to_string())
}

#[tauri::command]
async fn stop_keyboard_hook(state: State<'_, KeyboardHookState>) -> Result<(), String> {
    state.stop_hooking();
    Ok(())
}

#[tauri::command]
async fn is_window_focused(state: State<'_, KeyboardHookState>) -> Result<bool, String> {
    Ok(state.is_window_focused())
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let keyboard_hook = Arc::new(KeyboardHook::new(app.handle().clone()));
            app.manage(keyboard_hook);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_keyboard_hook,
            stop_keyboard_hook,
            is_window_focused
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
