use serde::Serialize;
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{AppHandle, Emitter, Manager, WindowEvent};

#[derive(Clone, Serialize)]
struct KeyboardEvent {
    key: String,
    pressed: bool,
}

struct AppState {
    focused: Arc<Mutex<bool>>,
}

fn main() {
    let focused = Arc::new(Mutex::new(true)); // Default to true or track via events
    let focused_clone = Arc::clone(&focused);

    tauri::Builder::default()
        .manage(AppState {
            focused: Arc::clone(&focused),
        })
        .setup(move |app| {
            let handle = app.handle().clone();
            
            // Start the cross-platform keyboard hook thread
            thread::spawn(move || {
                use rdev::{listen, Event, EventType};
                
                let callback = move |event: Event| {
                    let is_focused = *focused_clone.lock().unwrap();
                    if !is_focused {
                        return;
                    }

                    match event.event_type {
                        EventType::KeyPress(key) => {
                            let key_str = format!("{:?}", key);
                            let _ = handle.emit("remote-keyboard-event", KeyboardEvent {
                                key: key_str,
                                pressed: true,
                            });
                        }
                        EventType::KeyRelease(key) => {
                            let key_str = format!("{:?}", key);
                            let _ = handle.emit("remote-keyboard-event", KeyboardEvent {
                                key: key_str,
                                pressed: false,
                            });
                        }
                        _ => {}
                    }
                };

                if let Err(error) = listen(callback) {
                    println!("Error starting keyboard hook: {:?}", error);
                }
            });
            
            Ok(())
        })
        .on_window_event(move |window, event| {
            if let WindowEvent::Focused(f) = event {
                let state = window.state::<AppState>();
                let mut focused = state.focused.lock().unwrap();
                *focused = *f;
                println!("Window focus changed: {}", f);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
