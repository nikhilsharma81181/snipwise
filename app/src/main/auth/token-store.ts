import { app, safeStorage } from 'electron'
import { readFile, rm, writeFile } from 'fs/promises'
import { join } from 'path'

// Refresh token on disk, encrypted with safeStorage (Keychain on mac).
// The access token is never written anywhere, it only lives in session.ts.

function sessionFile(): string {
  return join(app.getPath('userData'), 'session.bin')
}

export async function saveRefreshToken(token: string): Promise<void> {
  if (!safeStorage.isEncryptionAvailable()) {
    // never fall back to plain text. User just has to log in again next launch.
    console.warn('safeStorage unavailable, session will not survive a restart')
    return
  }
  await writeFile(sessionFile(), safeStorage.encryptString(token), { mode: 0o600 })
}

export async function loadRefreshToken(): Promise<string | null> {
  try {
    const encrypted = await readFile(sessionFile())
    return safeStorage.decryptString(encrypted)
  } catch {
    // no file yet, or it can't be decrypted (e.g. keychain entry reset)
    return null
  }
}

export async function clearRefreshToken(): Promise<void> {
  await rm(sessionFile(), { force: true })
}
