import { ipcMain, type IpcMainInvokeEvent } from 'electron'
import { is } from '@electron-toolkit/utils'
import { z } from 'zod'
import { ApiError } from './api'
import * as session from './session'
import type { AuthResult } from './types'

// Renderer is untrusted: check the shape here. The real rules (email format,
// 8+ char password) are the server's job, it answers with validation_error.
const credentials = z.object({
  email: z.string().trim().min(1).max(320),
  password: z.string().min(1).max(128)
})

// only our own window may call these, never some other frame or page
function fromOurApp(e: IpcMainInvokeEvent): boolean {
  const url = e.senderFrame?.url ?? ''
  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (is.dev && devUrl) return url.startsWith(devUrl)
  return url.startsWith('file://')
}

async function run<T>(e: IpcMainInvokeEvent, fn: () => Promise<T>): Promise<AuthResult<T>> {
  if (!fromOurApp(e)) {
    return { ok: false, error: { code: 'forbidden', message: 'Not allowed' } }
  }
  try {
    return { ok: true, data: await fn() }
  } catch (err) {
    if (err instanceof ApiError) return { ok: false, error: err.toInfo() }
    console.error('auth ipc failed', err)
    return { ok: false, error: { code: 'internal_error', message: 'Something went wrong' } }
  }
}

function badInput<T>(): AuthResult<T> {
  return {
    ok: false,
    error: { code: 'validation_error', message: 'Please check the fields below' }
  }
}

export function registerAuthIpc(): void {
  ipcMain.handle('auth:signup', (e, payload: unknown) => {
    const parsed = credentials.safeParse(payload)
    if (!parsed.success) return badInput()
    return run(e, () => session.signup(parsed.data.email, parsed.data.password))
  })

  ipcMain.handle('auth:login', (e, payload: unknown) => {
    const parsed = credentials.safeParse(payload)
    if (!parsed.success) return badInput()
    return run(e, () => session.login(parsed.data.email, parsed.data.password))
  })

  ipcMain.handle('auth:logout', (e) => run(e, () => session.logout()))

  // also the app-start check: no access token yet -> refresh with the stored one -> /me
  ipcMain.handle('auth:me', (e) => run(e, () => session.me()))
}
