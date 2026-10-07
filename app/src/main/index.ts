import { app, shell, BrowserWindow, nativeTheme } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { buildMenu } from './menu'
import { registerAuthIpc } from './auth/ipc'

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: false,
    titleBarStyle: 'hidden',
    // traffic lights are ~14px tall, y=17 centres them in the 48px (h-12) toolbar row
    trafficLightPosition: { x: 18, y: 17 },
    // native macOS blur behind the whole window. The page paints the main area solid,
    // so the blur only shows through where the page is transparent (the sidebar).
    // Transparent bg also means resizing shows the blur instead of a white flash.
    vibrancy: 'sidebar',
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      // renderer is treated as untrusted: no node, isolated world, sandboxed
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  win.on('ready-to-show', () => win.show())

  // any window.open / target=_blank goes to the system browser, never a new electron window
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  // app is dark only for now, so the blur material stays dark even in light mode
  nativeTheme.themeSource = 'dark'

  electronApp.setAppUserModelId('com.snipwise.app')

  // F12 toggles devtools in dev, Cmd+R is ignored in prod
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  buildMenu()
  registerAuthIpc()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
