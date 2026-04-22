#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
 
use std::io::Write;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, State};
 
struct AppState {
    host_process: Arc<Mutex<Option<Child>>>,
    input_helper_process: Arc<Mutex<Option<Child>>>,
}
 
// ✅ Cross-platform Python detection
fn find_python() -> String {
    let candidates = if cfg!(target_os = "windows") {
        vec![
            "./venv/Scripts/python.exe",
            "../venv/Scripts/python.exe",
            "../../venv/Scripts/python.exe",
            "python",
        ]
    } else {
        vec![
            "./venv/bin/python",
            "../venv/bin/python",
            "../../venv/bin/python",
            "python3",
            "python",
        ]
    };
 
    for path in &candidates {
        if std::path::Path::new(path).exists() || which::which(path).is_ok() {
            return path.to_string();
        }
    }
 
    "python3".to_string()
}
 
// ✅ FIXED: no move issue
fn find_script(possible_paths: Vec<&str>) -> String {
    for path in &possible_paths {
        if std::path::Path::new(path).exists() {
            return path.to_string();
        }
    }
    possible_paths.last().unwrap_or(&"").to_string()
}
 
#[tauri::command]
fn start_host(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let mut lock = state.host_process.lock().map_err(|_| "Failed to lock state")?;
 
    if let Some(child) = lock.as_mut() {
        if child.try_wait().ok().flatten().is_none() {
            return Err("Host already running".into());
        }
        *lock = None;
    }
 
    let python_cmd = find_python();
 
    let script_path = find_script(vec![
        "../host/main.py",
        "../../host/main.py",
        "host/main.py",
    ]);
 
    println!("Starting python host: {} {}", python_cmd, script_path);
 
    let mut child = Command::new(&python_cmd)
        .arg(&script_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn python host: {}", e))?;
 
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
 
    *lock = Some(child);
 
    let app_stdout = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        for line in BufReader::new(stdout).lines().flatten() {
            app_stdout.emit("host-stdout", line).ok();
        }
    });
 
    let app_stderr = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        for line in BufReader::new(stderr).lines().flatten() {
            app_stderr.emit("host-stderr", line).ok();
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
fn send_host_command(state: State<'_, AppState>, cmd: String) -> Result<(), String> {
    let mut lock = state.host_process.lock().map_err(|_| "Failed to lock state")?;
 
    if let Some(child) = lock.as_mut() {
        if let Some(stdin) = child.stdin.as_mut() {
            writeln!(stdin, "{}", cmd).map_err(|e| e.to_string())?;
            stdin.flush().map_err(|e| e.to_string())?;
            return Ok(());
        }
    }
 
    Err("Host not running or stdin not available".into())
}
 
#[tauri::command]
fn start_input_helper(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let mut lock = state.input_helper_process.lock().map_err(|_| "Failed to lock state")?;
 
    if lock.is_some() {
        return Err("Input helper already running".into());
    }
 
    let python_cmd = find_python();
 
    let script_path = find_script(vec![
        "../client/input_helper.py",
        "../../client/input_helper.py",
        "client/input_helper.py",
    ]);
 
    println!("Starting input helper: {} {}", python_cmd, script_path);
 
    let mut child = Command::new(&python_cmd)
        .arg(&script_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn input helper: {}", e))?;
 
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
 
    *lock = Some(child);
 
    let app_stdout = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        for line in BufReader::new(stdout).lines().flatten() {
            app_stdout.emit("input-helper-stdout", line).ok();
        }
    });
 
    let app_stderr = app.clone();
    std::thread::spawn(move || {
        use std::io::{BufRead, BufReader};
        for line in BufReader::new(stderr).lines().flatten() {
            app_stderr.emit("input-helper-stderr", line).ok();
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
 
#[tauri::command]
fn set_input_helper_active(
    state: State<'_, AppState>,
    active: bool,
) -> Result<(), String> {
    let mut lock = state.input_helper_process.lock().map_err(|_| "Failed to lock state")?;
 
    if let Some(child) = lock.as_mut() {
        if let Some(stdin) = child.stdin.as_mut() {
            let cmd = if active {
                r#"{"command":"resume"}"#
            } else {
                r#"{"command":"pause"}"#
            };
 
            writeln!(stdin, "{}", cmd).map_err(|e| e.to_string())?;
            stdin.flush().map_err(|e| e.to_string())?;
            return Ok(());
        }
    }
 
    Err("Input helper not running or lacks stdin".into())
}
 
fn main() {
    tauri::Builder::default()
        .manage(AppState {
            host_process: Arc::new(Mutex::new(None)),
            input_helper_process: Arc::new(Mutex::new(None)),
        })
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            start_host,
            stop_host,
            send_host_command,
            start_input_helper,
            stop_input_helper,
            set_input_helper_active
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}