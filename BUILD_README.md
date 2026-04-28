# Remote Desktop Client - Build Instructions

This project creates a standalone remote desktop application that works on Windows, Mac, and Linux.

## Prerequisites

1. **Python 3.8+** with pip
2. **Node.js 16+** and npm
3. **Rust** (latest stable)
4. **Tauri CLI**: `cargo install tauri-cli`
5. **PyInstaller**: `pip install pyinstaller`

### Platform-Specific Requirements

#### Windows
- Visual Studio Build Tools (for Rust)
- Windows SDK

#### macOS
- Xcode Command Line Tools
- Apple Developer Account (for code signing)

#### Linux
- GTK development libraries
- WebKitGTK

## Build Process

The build process automatically:
1. Bundles Python applications using PyInstaller
2. Builds the frontend
3. Creates the final executable with all dependencies included

### Quick Build (Current Platform)

```bash
# Navigate to project root
cd helpdesk_remote_conn

# Run the build script
python build_scripts/build.py all
```

### Manual Build Steps

If you prefer manual control:

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. **Build frontend:**
   ```bash
   cd desktop-client
   npm install
   npm run build
   cd ..
   ```

3. **Build the application:**
   ```bash
   cd desktop-client/src-tauri
   cargo tauri build
   ```

## Output

The built application will be in:
- **Windows**: `desktop-client/src-tauri/target/release/bundle/nsis/`
- **macOS**: `desktop-client/src-tauri/target/release/bundle/dmg/`
- **Linux**: `desktop-client/src-tauri/target/release/bundle/deb/`

## Development

For development with hot reload:

```bash
cd desktop-client
npm run dev
# In another terminal:
cd desktop-client/src-tauri
cargo tauri dev
```

## Troubleshooting

### Python Not Found
- Ensure Python is in your PATH
- Or set `HELPDESK_PYTHON` environment variable to the full path

### Build Fails
- Clear build cache: `cargo clean` and `npm run clean`
- Reinstall dependencies
- Check that all prerequisites are installed

### Bundle Too Large
- The bundle includes Python runtime (~50-100MB)
- This is necessary for standalone operation without Python installation

## Distribution

- **Windows**: NSIS installer
- **macOS**: DMG with code signing
- **Linux**: DEB package

For distribution, consider:
- Code signing certificates
- Auto-updater configuration
- Platform-specific testing