#!/usr/bin/env python3
"""
Pre-build script to bundle Python applications using PyInstaller
This script runs before the Rust build to create standalone executables
"""

import os
import sys
import subprocess
import platform
import shutil
import tempfile
from pathlib import Path

def get_platform_name():
    """Get the current platform name for PyInstaller spec selection"""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    else:
        raise ValueError(f"Unsupported platform: {system}")

def get_python_scripts():
    """Get the list of Python scripts to bundle"""
    project_root = Path(__file__).parent.parent
    return {
        'host': project_root / 'host' / 'main.py',
        'input_helper': project_root / 'client' / 'input_helper.py'
    }

def create_spec_file(script_name, script_path, platform_name):
    """Create PyInstaller spec file for the given script and platform"""
    project_root = Path(__file__).parent.parent
    script_path_text = str(script_path).replace('\\', '\\\\')
    
    # Get paths for data files
    common_dir = project_root / 'common'
    host_dir = project_root / 'host'
    client_dir = project_root / 'client'
    
    data_files = []
    if script_name == 'host':
        data_files = [
            (str(common_dir), 'common'),
            (str(host_dir), 'host'),
        ]
    elif script_name == 'input_helper':
        data_files = [
            (str(common_dir), 'common'),
            (str(client_dir), 'client'),
        ]
    
    data_section = ",\n    datas=[\n"
    for src, dst in data_files:
        src_escaped = src.replace('\\', '\\\\')
        data_section += f'        ("{src_escaped}", "{dst}"),\n'
    data_section += "    ]"
    
    # Make repo root importable so namespace packages (common/host/client) resolve.
    repo_root_escaped = str(project_root).replace('\\', '\\\\')

    spec_content = f'''
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{script_path_text}'],
    pathex=['{repo_root_escaped}'],
    binaries=[]{data_section},
    hiddenimports=[],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{script_name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''

    spec_dir = Path(__file__).parent
    spec_file = spec_dir / f'{script_name}_{platform_name}.spec'
    with open(spec_file, 'w') as f:
        f.write(spec_content.strip())
    return spec_file

def run_pyinstaller(spec_file):
    """Run PyInstaller with the given spec file"""
    dist_dir = spec_file.parent / 'dist'
    try:
        dist_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp_work:
            subprocess.run([
                sys.executable, '-m', 'PyInstaller',
                '--clean',
                '--noconfirm',
                '--workpath', tmp_work,
                '--distpath', str(dist_dir),
                str(spec_file)
            ], check=True, cwd=spec_file.parent)
        return True
    except subprocess.CalledProcessError as e:
        print(f"PyInstaller failed for {spec_file}: {e}")
        return False

def copy_binaries_to_resources():
    """Copy the generated binaries to the Tauri resources directory"""
    platform_name = get_platform_name()
    repo_root = Path(__file__).parent.parent
    tauri_resources_dir = repo_root / 'desktop-client' / 'src-tauri' / 'resources'
    spec_dir = Path(__file__).parent

    # Create Tauri resources directory if it doesn't exist
    tauri_resources_dir.mkdir(parents=True, exist_ok=True)

    binaries = []
    for script_name in ['host', 'input_helper']:
        if platform_name == 'windows':
            binary_name = f'{script_name}.exe'
        else:
            binary_name = script_name

        dist_binary = spec_dir / 'dist' / binary_name
        if dist_binary.exists():
            target_path = tauri_resources_dir / binary_name
            
            # Kill any running instance of this binary to prevent lock errors (Windows only)
            if platform_name == 'windows':
                try:
                    subprocess.run(['taskkill', '/F', '/IM', binary_name, '/T'], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

            if target_path.exists():
                try:
                    os.chmod(target_path, 0o666)
                except Exception:
                    pass
                try:
                    target_path.unlink()
                except Exception:
                    pass
            shutil.copy2(dist_binary, target_path)
            binaries.append(target_path)
            print(f"Copied {binary_name} to {target_path}")
        else:
            print(f"Warning: {binary_name} not found in dist directory")

    return binaries

def main():
    """Main build function"""
    print("Starting Python bundling process...")

    # Check if PyInstaller is installed
    try:
        subprocess.run([sys.executable, '-c', 'import PyInstaller'], check=True)
    except subprocess.CalledProcessError:
        print("PyInstaller not found. Installing...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)

    platform_name = get_platform_name()
    print(f"Building for platform: {platform_name}")

    scripts = get_python_scripts()
    spec_files = []

    # Create spec files and run PyInstaller
    for script_name, script_path in scripts.items():
        if script_path.exists():
            print(f"Creating spec for {script_name}...")
            spec_file = create_spec_file(script_name, script_path, platform_name)
            spec_files.append(spec_file)

            print(f"Running PyInstaller for {script_name}...")
            if not run_pyinstaller(spec_file):
                print(f"Failed to build {script_name}")
                return 1
        else:
            print(f"Warning: {script_path} not found")

    # Copy binaries to resources
    print("Copying binaries to resources...")
    binaries = copy_binaries_to_resources()

    if binaries:
        print(f"Successfully bundled {len(binaries)} binaries")
        return 0
    else:
        print("No binaries were created")
        return 1

if __name__ == '__main__':
    sys.exit(main())