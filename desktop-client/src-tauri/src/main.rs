#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
 
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, State};
 
struct AppState {
    host_process: Arc<Mutex<Option<Child>>>,
    input_helper_process: Arc<Mutex<Option<Child>>>,
}
 
#[tauri::command]
fn start_host(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let mut lock = state.host_process.lock().map_err(|_| "Failed to lock state")?;
    if lock.is_some() {
        // Check if it's actually still running
        if let Some(child) = lock.as_mut() {
            match child.try_wait() {
                Ok(None) => return Err("Host already running".into()), // Still running
                _ => *lock = None, // Finished or error, so we can restart
            }
        }
    }
 
    // Detect python executable (check venv in multiple locations)
    let python_cmd = if std::path::Path::new("./venv/Scripts/python.exe").exists() {
        "./venv/Scripts/python.exe".to_string()
    } else if std::path::Path::new("../venv/Scripts/python.exe").exists() {
        "../venv/Scripts/python.exe".to_string()
    } else if std::path::Path::new("../../venv/Scripts/python.exe").exists() {
        "../../venv/Scripts/python.exe".to_string()
    } else {
        "python".to_string()
    };
 
    // Detect script path
    let script_path = if std::path::Path::new("../host/main.py").exists() {
        "../host/main.py"
    } else if std::path::Path::new("../../host/main.py").exists() {
        "../../host/main.py"
    } else {
        "host/main.py" // Fallback
    };
 
    println!("Starting python host: {} {}", python_cmd, script_path);
 
    let mut child = Command::new(&python_cmd)
        .arg(script_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn python host: {}", e))?;
 
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    *lock = Some(child);
 
    // Stdout tracking thread
    let app_stdout = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if let Ok(l) = line {
                app_stdout.emit("host-stdout", l).ok();
            }
        }
    });
 
    // Stderr tracking thread
    let app_stderr = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(l) = line {
                app_stderr.emit("host-stderr", l).ok();
            }
        }
    });
 
    Ok("Host starting...".into())
}
 
#[tauri::command]
fn stop_host(state: State<'_, AppState>) -> Result<String, String> {
    let mut lock = state.host_process.lock().map_err(|_| "Failed to lock state")?;
    if let Some(mut child) = lock.take() {
        let _ = child.kill();
        Ok("Host stopped".into())
    } else {
        Err("Host not running".into())
    }
}
 
#[tauri::command]
fn start_input_helper(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let mut lock = state.input_helper_process.lock().map_err(|_| "Failed to lock state")?;
    if lock.is_some() {
        return Err("Input helper already running".into());
    }
 
    // Detect python executable
    let python_cmd = if std::path::Path::new("./venv/Scripts/python.exe").exists() {
        "./venv/Scripts/python.exe".to_string()
    } else if std::path::Path::new("../venv/Scripts/python.exe").exists() {
        "../venv/Scripts/python.exe".to_string()
    } else {
        "python".to_string()
    };
 
    // Detect script path
    let script_path = if std::path::Path::new("../client/input_helper.py").exists() {
        "../client/input_helper.py"
    } else if std::path::Path::new("../../client/input_helper.py").exists() {
        "../../client/input_helper.py"
    } else {
        "client/input_helper.py"
    };
 
    println!("Starting input helper: {} {}", python_cmd, script_path);
 
    let mut child = Command::new(&python_cmd)
        .arg(script_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn input helper: {}", e))?;
 
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    *lock = Some(child);
 
    // Stdout tracking
    let app_stdout = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if let Ok(l) = line {
                app_stdout.emit("input-helper-stdout", l).ok();
            }
        }
    });
 
    // Stderr tracking
    let app_stderr = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(l) = line {
                app_stderr.emit("input-helper-stderr", l).ok();
            }
        }
    });
 
    Ok("Input helper starting...".into())
}
 
#[tauri::command]
fn stop_input_helper(state: State<'_, AppState>) -> Result<String, String> {
    let mut lock = state.input_helper_process.lock().map_err(|_| "Failed to lock state")?;
    if let Some(mut child) = lock.take() {
        let _ = child.kill();
        Ok("Input helper stopped".into())
    } else {
        Err("Input helper not running".into())
    }
}
 
fn main() {
    tauri::Builder::default()
        .manage(AppState {
            host_process: Arc::new(Mutex::new(None)),
            input_helper_process: Arc::new(Mutex::new(None)),
        })
        .invoke_handler(tauri::generate_handler![
            start_host,
            stop_host,
            start_input_helper,
            stop_input_helper
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
 