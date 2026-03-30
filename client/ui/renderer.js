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
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    
    sendControl({
        type: 'mouse_move',
        x: x,
        y: y
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

// Keyboard
window.addEventListener('keydown', (e) => {
    if (!isConnected) return;
    // Prevent default browser shortcuts if needed
    // e.preventDefault();
    sendControl({
        type: 'keyboard',
        key: e.key,
        pressed: true
    });
});

window.addEventListener('keyup', (e) => {
    if (!isConnected) return;
    sendControl({
        type: 'keyboard',
        key: e.key,
        pressed: false
    });
});

function sendControl(data) {
    window.electronAPI.sendToPython(`CONTROL:${JSON.stringify(data)}`);
}
