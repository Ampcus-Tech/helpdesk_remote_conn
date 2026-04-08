#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::GlobalShortcutExt;

fn register_shortcuts(app: &AppHandle) {
    let shortcuts = vec![
        "Super+R",
        "Ctrl+Shift+Escape",
        "Alt+Tab",
        "Super+Tab",
        "Snapshot",
    ];

    for shortcut_str in shortcuts {
        let _ = app.global_shortcut().register(shortcut_str);
    }
}

fn unregister_shortcuts(app: &AppHandle) {
    let shortcuts = vec![
        "Super+R",
        "Ctrl+Shift+Escape",
        "Alt+Tab",
        "Super+Tab",
        "Snapshot",
    ];

    for shortcut_str in shortcuts {
        let _ = app.global_shortcut().unregister(shortcut_str);
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();
            let app_handle = app.handle().clone();

            // Register shortcuts when window gains focus
            let app_handle_clone = app_handle.clone();
            window.on_window_event(move |event| {
                match event {
                    tauri::WindowEvent::Focused(true) => {
                        register_shortcuts(&app_handle_clone);
                    }
                    tauri::WindowEvent::Focused(false) => {
                        unregister_shortcuts(&app_handle_clone);
                    }
                    _ => {}
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
