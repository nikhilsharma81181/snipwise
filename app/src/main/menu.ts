import { BrowserWindow, Menu } from 'electron'

// Native menu. Shortcuts live here (not in the page) so they work even
// when the web page doesn't have keyboard focus.
export function buildMenu(): void {
  const send = (channel: string) => () => {
    BrowserWindow.getFocusedWindow()?.webContents.send(channel)
  }

  const menu = Menu.buildFromTemplate([
    { role: 'appMenu' },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { label: 'Toggle Sidebar', accelerator: 'CmdOrCtrl+B', click: send('sidebar:toggle') },
        { type: 'separator' },
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    { role: 'windowMenu' }
  ])
  Menu.setApplicationMenu(menu)
}
