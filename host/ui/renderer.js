const hostIdEl = document.getElementById('host-id');
const statusTextEl = document.getElementById('status-text');
const statusIndicator = document.querySelector('.status-indicator');
const startBtn = document.getElementById('start-btn');
const stopBtn = document.getElementById('stop-btn');
const copyBtn = document.getElementById('copy-btn');
const newIdBtn = document.getElementById('new-id-btn');

function generateHostId() {
    return Math.floor(100000 + Math.random() * 900000).toString();
}

let currentHostId = generateHostId();
hostIdEl.textContent = currentHostId;

copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(currentHostId);
    statusTextEl.textContent = 'Host ID copied to clipboard!';
});

newIdBtn.addEventListener('click', () => {
    currentHostId = generateHostId();
    hostIdEl.textContent = currentHostId;
    statusTextEl.textContent = 'New Host ID generated.';
});

startBtn.addEventListener('click', async () => {
    statusTextEl.textContent = 'Starting Python host...';
    startBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    newIdBtn.disabled = true;

    try {
        await window.electronAPI.startPython({
            scriptPath: 'host/bridge_host.py',
            args: [currentHostId]
        });
    } catch (err) {
        statusTextEl.textContent = `Error: ${err.message}`;
        resetUI();
    }
});

function resetUI() {
    startBtn.classList.remove('hidden');
    stopBtn.classList.add('hidden');
    newIdBtn.disabled = false;
    statusIndicator.classList.remove('active');
}

window.electronAPI.onPythonOutput((message) => {
    console.log('Python:', message);
    if (message.startsWith('EVENT:')) {
        const event = message.substring(6);
        if (event === '__DONE__') {
            statusTextEl.textContent = 'Host stopped.';
            resetUI();
        } else {
            statusTextEl.textContent = event;
            if (event.toLowerCase().includes('connected')) {
                statusIndicator.classList.add('active');
            }
        }
    }
});

window.electronAPI.onPythonError((error) => {
    console.error('Python Error:', error);
    statusTextEl.textContent = `Error: ${error}`;
});

window.electronAPI.onPythonDone((code) => {
    console.log('Python process exited with code:', code);
    resetUI();
});
