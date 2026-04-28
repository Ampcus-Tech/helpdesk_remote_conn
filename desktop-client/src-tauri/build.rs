fn main() {
    // Run the Python prebuild script to bundle Python applications.
    //
    // IMPORTANT: during `tauri dev` we should NOT constantly rebuild PyInstaller binaries,
    // otherwise `resources/host(.exe)` changes trigger an endless rebuild loop.
    println!("cargo:rerun-if-changed=../build_scripts/prebuild.py");
    println!("cargo:rerun-if-changed=../../requirements.txt");
    println!("cargo:rerun-if-changed=../../host/main.py");
    println!("cargo:rerun-if-changed=../../client/input_helper.py");
    println!("cargo:rerun-if-changed=../../common/");

    let profile = std::env::var("PROFILE").unwrap_or_else(|_| "debug".to_string());
    let force_prebuild = std::env::var("HELPDESK_FORCE_PREBUILD")
        .map(|v| matches!(v.trim().to_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(false);

    // Only bundle Python executables for release builds by default.
    if profile != "release" && !force_prebuild {
        tauri_build::build();
        return;
    }

    // Run the prebuild script
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set");
    let prebuild_path = std::path::Path::new(&manifest_dir)
        .join("../../build_scripts/prebuild.py");

    let python = std::env::var("HELPDESK_PYTHON").unwrap_or_else(|_| "python".to_string());
    let output = std::process::Command::new(python)
        .arg(prebuild_path)
        .output()
        .expect("Failed to run prebuild script");

    if !output.status.success() {
        panic!(
            "Prebuild script failed:\n{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    // Tell Tauri to include the resources directory
    println!("cargo:rerun-if-changed=resources/");

    tauri_build::build()
}
