// Shapes the server sends back (camelCase). Tokens never leave the main process.

export type User = {
  id: string
  email: string
  role: string
  minutesUsed: number
  minutesLimit: number
}

export type TokenPair = {
  accessToken: string
  refreshToken: string
}

export type LoginResponse = TokenPair & {
  user: { id: string; email: string; role: string }
}

// what the renderer gets when something fails
export type AuthErrorInfo = {
  code: string
  message: string
  fields?: Record<string, string>
}

// Thrown errors lose their fields when they cross IPC, so every auth call
// resolves to one of these instead of throwing.
export type AuthResult<T> = { ok: true; data: T } | { ok: false; error: AuthErrorInfo }
