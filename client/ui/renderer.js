const connectScreen = document.getElementById('connect-screen');
const viewerScreen = document.getElementById('viewer-screen');
const targetHostIdInput = document.getElementById('target-host-id');
const connectBtn = document.getElementById('connect-btn');
const statusTextEl = document.getElementById('status-text');
const remoteVideo = document.getElementById('remote-video');
const disconnectBtn = document.getElementById('disconnect-btn');
const viewingIdEl = document.getElementById('viewing-id');

let isConnected = false;

connectBtn.addEventListener('click', async () => {
    const hostId = targetHostIdInput.value.trim();
    if (!hostId || hostId.length !== 6) {
        statusTextEl.textContent = 'Please enter a valid 6-digit Host ID.';
        return;
    }

    statusTextEl.textContent = 'Connecting to host...';
    connectBtn.disabled = true;

    try {
        await window.electronAPI.startPython({
            scriptPath: 'client/bridge_client.py',
            args: [hostId]
        });
        viewingIdEl.textContent = hostId;
    } catch (err) {
        statusTextEl.textContent = `Error: ${err.message}`;
        connectBtn.disabled = false;
    }
});

disconnectBtn.addEventListener('click', () => {
    // In a real app, we'd send a signal to stop the process
    window.location.reload(); 
});

window.electronAPI.onPythonOutput((message) => {
    if (message.startsWith('FRAME:')) {
        const base64Data = message.substring(6);
        remoteVideo.src = `data:image/jpeg;base64,${base64Data}`;
        
        if (!isConnected) {
            isConnected = true;
            connectScreen.classList.add('hidden');
            viewerScreen.classList.remove('hidden');
        }
    } else if (message.startsWith('EVENT:')) {
        const event = message.substring(6);
        if (event === '__DONE__') {
            window.location.reload();
        } else {
            console.log('Event:', event);
            statusTextEl.textContent = event;
        }
    }
});

// Input Handling
remoteVideo.addEventListener('mousemove', (e) => {
    if (!isConnected) return;
    const rect = remoteVideo.getBoundingClientRect();
    sendControl({
        type: 'mouse_move',
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        screen_width: rect.width,
        screen_height: rect.height
    });
});

remoteVideo.addEventListener('mousedown', (e) => {
    if (!isConnected) return;
    sendControl({
        type: 'mouse_click',
        button: e.button === 0 ? 'left' : (e.button === 2 ? 'right' : 'middle'),
        pressed: true
    });
});

remoteVideo.addEventListener('mouseup', (e) => {
    if (!isConnected) return;
    sendControl({
        type: 'mouse_click',
        button: e.button === 0 ? 'left' : (e.button === 2 ? 'right' : 'middle'),
        pressed: false
    });
});

remoteVideo.addEventListener('dblclick', (e) => {
    if (!isConnected) return;
    sendControl({
        type: 'mouse_double_click',
        button: e.button === 0 ? 'left' : (e.button === 2 ? 'right' : 'middle')
    });
});

remoteVideo.addEventListener('wheel', (e) => {
    if (!isConnected) return;
    e.preventDefault();
    const rect = remoteVideo.getBoundingClientRect();
    sendControl({
        type: 'mouse_scroll',
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        screen_width: rect.width,
        screen_height: rect.height,
        scroll_dx: e.deltaX > 0 ? 1 : (e.deltaX < 0 ? -1 : 0),
        scroll_dy: e.deltaY > 0 ? -1 : (e.deltaY < 0 ? 1 : 0) // JS wheel is opposite to Python scroll
    });
}, { passive: false });

// Keyboard
const keyMap = {
    'Enter': 'enter',
    'Backspace': 'backspace',
    'Tab': 'tab',
    'Escape': 'esc',
    ' ': 'space',
    'ArrowUp': 'up',
    'ArrowDown': 'down',
    'ArrowLeft': 'left',
    'ArrowRight': 'right',
    'Control': 'ctrl',
    'Alt': 'alt',
    'Shift': 'shift',
    'Meta': 'cmd',
    'CapsLock': 'caps_lock',
    'Delete': 'delete',
    'Insert': 'insert',
    'Home': 'home',
    'End': 'end',
    'PageUp': 'page_up',
    'PageDown': 'page_down'
};

window.addEventListener('keydown', (e) => {
    if (!isConnected) return;
    if (document.activeElement === targetHostIdInput) return;
    
    // Prevent common browser shortcuts
    if (e.key === 'Tab' || e.key === 'Alt' || (e.ctrlKey && e.key !== 'v')) {
        e.preventDefault();
    }

    const keyName = keyMap[e.key] || e.key.toLowerCase();
    sendControl({
        type: 'keyboard',
        key: keyName,
        pressed: true
    });
});

window.addEventListener('keyup', (e) => {
    if (!isConnected) return;
    if (document.activeElement === targetHostIdInput) return;

    const keyName = keyMap[e.key] || e.key.toLowerCase();
    sendControl({
        type: 'keyboard',
        key: keyName,
        pressed: false
    });
});

// Cursor Sync
window.electronAPI.onPythonOutput((message) => {
    if (message.startsWith('FRAME:')) {
        const base64Data = message.substring(6);
        remoteVideo.src = `data:image/jpeg;base64,${base64Data}`;
        
        if (!isConnected) {
            isConnected = true;
            connectScreen.classList.add('hidden');
            viewerScreen.classList.remove('hidden');
        }
    } else if (message.startsWith('EVENT:')) {
        const event = message.substring(6);
        if (event === '__DONE__') {
            window.location.reload();
        } else if (event.startsWith('CURSOR:')) {
            const cursorName = event.substring(7);
            updateCursorStyle(cursorName);
        } else {
            console.log('Event:', event);
            statusTextEl.textContent = event;
        }
    }
});

function updateCursorStyle(cursorName) {
    const cssMap = {
        'arrow': 'default',
        'ibeam': 'text',
        'hand': 'pointer',
        'wait': 'wait',
        'crosshair': 'crosshair',
        'size_all': 'move',
        'size_we': 'ew-resize',
        'size_ns': 'ns-resize',
        'size_nwse': 'nwse-resize',
        'size_nesw': 'nesw-resize',
        'no': 'not-allowed',
        'help': 'help'
    };
    remoteVideo.style.cursor = cssMap[cursorName] || 'default';
}

function sendControl(data) {
    window.electronAPI.sendToPython(`CONTROL:${JSON.stringify(data)}`);
}
