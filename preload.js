const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  startPython: (options) => ipcRenderer.invoke('start-python', options),
  onPythonOutput: (callback) => ipcRenderer.on('python-output', (_event, value) => callback(value)),
  onPythonError: (callback) => ipcRenderer.on('python-error', (_event, value) => callback(value)),
  onPythonDone: (callback) => ipcRenderer.on('python-done', (_event, value) => callback(value)),
  sendToPython: (message) => ipcRenderer.send('send-to-python', message),
});
