import { contextBridge, ipcRenderer } from 'electron'

// Everything the renderer can call lives here. Nothing else gets exposed.
const api = {
  platform: process.platform,

  // menu shortcut (Cmd+B) -> renderer. Returns an unsubscribe fn for useEffect cleanup.
  onToggleSidebar(cb: () => void): () => void {
    const listener = (): void => cb()
    ipcRenderer.on('sidebar:toggle', listener)
    return () => ipcRenderer.removeListener('sidebar:toggle', listener)
  }
}

export type SnipwiseApi = typeof api

contextBridge.exposeInMainWorld('snipwise', api)
