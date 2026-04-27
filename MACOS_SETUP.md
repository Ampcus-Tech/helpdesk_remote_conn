# macOS Setup Guide
 
## Required Permissions
 
This remote desktop application requires macOS security permissions to function properly.
 
### 1. Screen Recording Permission
**Required for:** Screen capture functionality
 
1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **Privacy & Security** → **Screen Recording**
3. Click the **+** button to add an application
4. Select your terminal application:
   - **Terminal.app** (if using built-in Terminal)
   - **iTerm.app** (if using iTerm)
   - Or your GUI application when packaged as .app
5. **Toggle the switch** to enable screen recording
6. **Restart the application** after granting permission
 
### 2. Accessibility Permission
**Required for:** Remote mouse and keyboard control
 
1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Click the **+** button to add an application
3. Select your terminal application
4. **Toggle the switch** to enable accessibility
5. **Restart the application** after granting permission
 
### 3. Input Monitoring Permission (Optional)
**Required for:** Enhanced keyboard monitoring
 
1. Open **System Settings** → **Privacy & Security** → **Input Monitoring**
2. Click the **+** button to add an application
3. Select your terminal application
4. **Toggle the switch** to enable input monitoring
 
## Troubleshooting
 
 
### For Packaged Applications (.app bundles)
When distributing as a packaged application:
1. The application itself (not the terminal) needs the permissions
2. Users will be prompted automatically on first launch
3. Guide users to grant permissions when prompted
 
## Testing Permissions
 
You can test if permissions are working by running:
 
```bash
# Test screen capture
python -c "import mss; sct = mss.mss(); print('Screen capture OK')"
 
# Test input control
python -c "from pynput.mouse import Controller; print('Input control OK')"
```
 
If either command fails or crashes, the corresponding permission is missing.