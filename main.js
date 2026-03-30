const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { PythonShell } = require('python-shell');

let mainWindow;
let pyshell;

function createWindow() {
  const mode = process.argv.find(arg => arg.startsWith('--mode='))?.split('=')[1] || 'host';
  
  mainWindow = new BrowserWindow({
    width: 600,
    height: 500,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  const indexPath = mode === 'client' ? 'client/ui/index.html' : 'host/ui/index.html';
  mainWindow.loadFile(indexPath);

  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit();
});

// IPC Handlers
ipcMain.handle('start-python', (event, { scriptPath, args }) => {
  return new Promise((resolve, reject) => {
    const pythonPath = process.platform === 'win32' 
      ? path.join(__dirname, 'venv', 'Scripts', 'python.exe')
      : path.join(__dirname, 'venv', 'bin', 'python');

    let options = {
      mode: 'text',
      pythonPath: pythonPath,
      pythonOptions: ['-u'], // get print results in real-time
      scriptPath: path.dirname(scriptPath),
      args: args
    };

    pyshell = new PythonShell(path.basename(scriptPath), options);

    pyshell.on('message', function (message) {
      // Send messages back to renderer
      mainWindow.webContents.send('python-output', message);
    });

    pyshell.on('stderr', function (stderr) {
      mainWindow.webContents.send('python-error', stderr);
    });

    pyshell.end(function (err, code, signal) {
      if (err) reject(err);
      console.log('The exit code was: ' + code);
      console.log('The exit signal was: ' + signal);
      mainWindow.webContents.send('python-done', code);
    });
    
    resolve('started');
  });
});

ipcMain.on('send-to-python', (event, message) => {
  if (pyshell) {
    pyshell.send(message);
  }
});
