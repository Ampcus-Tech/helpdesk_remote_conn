#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
 
use std::fs;
use std::io::Write;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, State};
 
struct AppState {
    host_process: Arc<Mutex<Option<Child>>>,
    input_helper_process: Arc<Mutex<Option<Child>>>,
}
 
/// Python with project deps (aiortc, etc.). Prefer HELPDESK_PYTHON, then venvs at repo root.
fn find_python() -> String {
    if let Ok(explicit) = std::env::var("HELPDESK_PYTHON") {
        let t = explicit.trim();
        if !t.is_empty() && std::path::Path::new(t).exists() {
            return t.to_string();
        }
    }
 
    let venv_dirs = [
        "venv",
        ".venv",
        "venv310",
        "venv311",
        "env",
    ];
    let rel_prefixes = ["./", "../", "../../", "../../../"];
 
    let mut candidates: Vec<String> = Vec::new();
    for prefix in rel_prefixes {
        for dir in venv_dirs {
            if cfg!(target_os = "windows") {
                candidates.push(format!("{}{}/Scripts/python.exe", prefix, dir));
            } else {
                candidates.push(format!("{}{}/bin/python", prefix, dir));
            }
        }
    }
 
    if cfg!(target_os = "windows") {
        candidates.push("python".to_string());
    } else {
        candidates.push("python3".to_string());
        candidates.push("python".to_string());
    }
 
    for path in &candidates {
        if std::path::Path::new(path).exists() {
            return path.clone();
        }
    }
 
    for path in &["python3", "python"] {
        if which::which(path).is_ok() {
            return (*path).to_string();
        }
    }
 
    if cfg!(target_os = "windows") {
        "python".to_string()
    } else {
        "python3".to_string()
    }
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

fn is_bundled_app() -> bool {
    // Check if we're running from a bundled app by looking for the resources directory
    let exe_path = std::env::current_exe().unwrap_or_default();
    let fallback = std::path::PathBuf::new();
    let app_dir = exe_path.parent().unwrap_or(&fallback);
    app_dir.join("resources").exists()
}

fn get_bundled_binary_path(binary_name: &str) -> String {
    let exe_path = std::env::current_exe().unwrap_or_default();
    let fallback = std::path::PathBuf::new();
    let app_dir = exe_path.parent().unwrap_or(&fallback);

    if cfg!(target_os = "windows") {
        format!("{}/resources/{}.exe", app_dir.display(), binary_name)
    } else {
        format!("{}/resources/{}", app_dir.display(), binary_name)
    }
}

fn kill_process_by_name(name: &str) {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        let _ = std::process::Command::new("taskkill")
            .args(&["/F", "/IM", name, "/T"])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .status();
    }
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
 
    // Proactively kill any dangling host processes
    kill_process_by_name("host.exe");

    let (cmd, args) = if is_bundled_app() {
        // Use bundled binary
        let binary_path = get_bundled_binary_path("host");
        println!("Starting bundled host: {}", binary_path);
        (binary_path, vec![])
    } else {
        // Use Python script (development mode)
        let python_cmd = find_python();
        let script_path = find_script(vec![
            "../host/main.py",
            "../../host/main.py",
            "host/main.py",
        ]);
        println!("Starting python host: {} {}", python_cmd, script_path);
        (python_cmd, vec![script_path])
    };

    let mut command = Command::new(&cmd);
    command
        .args(&args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let mut child = command
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
    if let Some(child) = lock.take() {
        let pid = child.id();
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(&["/F", "/PID", &pid.to_string(), "/T"])
                .creation_flags(0x08000000)
                .status();
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = child.kill();
        }
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
 
    // Proactively kill any dangling helper processes
    kill_process_by_name("input_helper.exe");
    kill_process_by_name("input_handler.exe");

    let (cmd, args) = if is_bundled_app() {
        // Use bundled binary
        let binary_path = get_bundled_binary_path("input_helper");
        println!("Starting bundled input helper: {}", binary_path);
        (binary_path, vec![])
    } else {
        // Use Python script (development mode)
        let python_cmd = find_python();
        let script_path = find_script(vec![
            "../client/input_helper.py",
            "../../client/input_helper.py",
            "client/input_helper.py",
        ]);
        println!("Starting input helper: {} {}", python_cmd, script_path);
        (python_cmd, vec![script_path])
    };

    let mut command = Command::new(&cmd);
    command
        .args(&args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let mut child = command
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
 
    if let Some(child) = lock.take() {
        let pid = child.id();
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(&["/F", "/PID", &pid.to_string(), "/T"])
                .creation_flags(0x08000000)
                .status();
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = child.kill();
        }
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
 
#[tauri::command]
fn save_received_file(path: String, bytes: Vec<u8>) -> Result<(), String> {
    let normalized = if let Some(rest) = path.strip_prefix("file://") {
        // Linux portals may return URI paths; normalize to filesystem path.
        #[cfg(target_os = "windows")]
        {
            rest.strip_prefix('/').unwrap_or(rest).to_string()
        }
        #[cfg(not(target_os = "windows"))]
        {
            format!("/{}", rest.trim_start_matches('/'))
        }
    } else {
        path.clone()
    };
 
    fs::write(&normalized, bytes)
        .map_err(|e| format!("Failed to save file to {}: {}", normalized, e))
}
 
fn cleanup_processes(state: &AppState) {
    // 1. Kill tracked processes first (by PID)
    let mut host_lock = state.host_process.lock().unwrap();
    if let Some(child) = host_lock.take() {
        let pid = child.id();
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(&["/F", "/PID", &pid.to_string(), "/T"])
                .creation_flags(0x08000000)
                .status();
        }
        #[cfg(not(target_os = "windows"))]
        let _ = child.kill();
    }
 
    let mut helper_lock = state.input_helper_process.lock().unwrap();
    if let Some(child) = helper_lock.take() {
        let pid = child.id();
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            let _ = std::process::Command::new("taskkill")
                .args(&["/F", "/PID", &pid.to_string(), "/T"])
                .creation_flags(0x08000000)
                .status();
        }
        #[cfg(not(target_os = "windows"))]
        let _ = child.kill();
    }

    // 2. Perform a global name-based sweep as a fallback
    // This catches any processes that might have detached from our PID tracking
    kill_process_by_name("host.exe");
    kill_process_by_name("input_helper.exe");
    kill_process_by_name("input_handler.exe"); // Catch older or alternative names

    // Give OS a moment to finalize termination
    std::thread::sleep(std::time::Duration::from_millis(200));
}

#[tauri::command]
fn close_app(app: tauri::AppHandle) {
    app.exit(0);
}

fn main() {
    let app_state = AppState {
        host_process: Arc::new(Mutex::new(None)),
        input_helper_process: Arc::new(Mutex::new(None)),
    };

    tauri::Builder::default()
        .manage(app_state)
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            start_host,
            stop_host,
            send_host_command,
            start_input_helper,
            stop_input_helper,
            set_input_helper_active,
            save_received_file,
            close_app
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                use tauri::Manager;
                let state = app_handle.state::<AppState>();
                cleanup_processes(&state);
            }
        });
}