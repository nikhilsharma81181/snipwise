import { contextBridge, ipcRenderer } from 'electron'
import type { AuthResult, User } from '../main/auth/types'

// Everything the renderer can call lives here. Nothing else gets exposed.
const api = {
  platform: process.platform,

  // menu shortcut (Cmd+B) -> renderer. Returns an unsubscribe fn for useEffect cleanup.
  onToggleSidebar(cb: () => void): () => void {
    const listener = (): void => cb()
    ipcRenderer.on('sidebar:toggle', listener)
    return () => ipcRenderer.removeListener('sidebar:toggle', listener)
  },

  // Account. Main does the HTTP and keeps the tokens, we only get user data or an error.
  auth: {
    signup: (email: string, password: string): Promise<AuthResult<User>> =>
      ipcRenderer.invoke('auth:signup', { email, password }),
    login: (email: string, password: string): Promise<AuthResult<User>> =>
      ipcRenderer.invoke('auth:login', { email, password }),
    logout: (): Promise<AuthResult<void>> => ipcRenderer.invoke('auth:logout'),
    me: (): Promise<AuthResult<User>> => ipcRenderer.invoke('auth:me')
  }
}

export type SnipwiseApi = typeof api
export type { AuthErrorInfo, AuthResult, User } from '../main/auth/types'

contextBridge.exposeInMainWorld('snipwise', api)
