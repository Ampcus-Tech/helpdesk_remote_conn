#!/usr/bin/env python3
"""
Cross-platform build script for Remote Desktop Client
Builds the application for Windows, macOS, and Linux
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def run_command(cmd, cwd=None, shell=False):
    """Run a command and return success status"""
    try:
        print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
        result = subprocess.run(
            cmd,
            cwd=cwd,
            shell=shell,
            check=True,
            capture_output=True,
            text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False

def build_frontend():
    """Build the frontend"""
    print("Building frontend...")
    repo_root = Path(__file__).resolve().parent.parent
    frontend_dir = repo_root / "desktop-client"

    # Install dependencies
    if not run_command(["npm", "install"], cwd=frontend_dir):
        return False

    # Build the frontend
    if not run_command(["npm", "run", "build"], cwd=frontend_dir):
        return False

    return True

def build_tauri(target=None):
    """Build the Tauri application"""
    print(f"Building Tauri application for {target or 'current platform'}...")
    repo_root = Path(__file__).resolve().parent.parent
    tauri_dir = repo_root / "desktop-client" / "src-tauri"

    cmd = ["cargo", "tauri", "build"]
    if target:
        cmd.extend(["--target", target])

    if not run_command(cmd, cwd=tauri_dir):
        return False

    return True

def build_for_windows():
    """Build for Windows"""
    print("Building for Windows...")

    # Check if we're on Windows or have cross-compilation set up
    if platform.system() == "Windows":
        return build_tauri()
    else:
        print("Cross-compiling for Windows requires Windows or proper cross-compilation setup")
        return False

def build_for_macos():
    """Build for macOS"""
    print("Building for macOS...")

    if platform.system() == "Darwin":
        # Build universal binary for both Intel and Apple Silicon
        return build_tauri("universal-apple-darwin")
    else:
        print("Building for macOS requires macOS or proper cross-compilation setup")
        return False

def build_for_linux():
    """Build for Linux"""
    print("Building for Linux...")

    if platform.system() == "Linux":
        return build_tauri()
    else:
        print("Cross-compiling for Linux requires Linux or proper cross-compilation setup")
        return False

def main():
    """Main build function"""
    if len(sys.argv) < 2:
        print("Usage: python build.py <platform>")
        print("Platforms: windows, macos, linux, all")
        return 1

    platform_arg = sys.argv[1].lower()

    # Build frontend first
    if not build_frontend():
        print("Frontend build failed")
        return 1

    # Build for specified platform(s)
    if platform_arg == "all":
        success = True
        if platform.system() == "Windows":
            success &= build_for_windows()
        elif platform.system() == "Darwin":
            success &= build_for_macos()
        elif platform.system() == "Linux":
            success &= build_for_linux()
        else:
            print(f"Unsupported platform: {platform.system()}")
            return 1

        if success:
            print("Build completed successfully!")
            return 0
        else:
            print("Build failed")
            return 1

    elif platform_arg == "windows":
        return 0 if build_for_windows() else 1
    elif platform_arg == "macos":
        return 0 if build_for_macos() else 1
    elif platform_arg == "linux":
        return 0 if build_for_linux() else 1
    else:
        print(f"Unknown platform: {platform_arg}")
        return 1

if __name__ == "__main__":
    sys.exit(main())