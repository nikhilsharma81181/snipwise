import { is } from '@electron-toolkit/utils'
import type { AuthErrorInfo } from './types'

const API_URL = import.meta.env.MAIN_VITE_API_URL ?? 'http://localhost:8000/api'

// friendlier text than the server's for the codes the user actually sees
const MESSAGES: Record<string, string> = {
  email_exists: 'An account with this email already exists',
  invalid_credentials: 'Invalid email or password',
  validation_error: 'Please check the fields below',
  network_error: "Can't reach the server",
  session_expired: 'Your session has ended. Please log in again.'
}

export class ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, string>

  constructor(status: number, code: string, message?: string, fields?: Record<string, string>) {
    super(MESSAGES[code] ?? message ?? 'Something went wrong')
    this.status = status
    this.code = code
    this.fields = fields
  }

  // server errors are {code, message}, validation errors add issues: [{field, message}]
  static fromResponse(status: number, body: unknown): ApiError {
    const data = (body ?? {}) as { code?: unknown; message?: unknown; issues?: unknown }
    const code = typeof data.code === 'string' ? data.code : 'http_error'
    const message = typeof data.message === 'string' ? data.message : undefined

    let fields: Record<string, string> | undefined
    if (Array.isArray(data.issues)) {
      fields = {}
      for (const issue of data.issues as { field?: string; message?: string }[]) {
        // first message per field is enough for the form
        if (issue.field && issue.message && !(issue.field in fields)) {
          fields[issue.field] = issue.message
        }
      }
    }
    return new ApiError(status, code, message, fields)
  }

  toInfo(): AuthErrorInfo {
    return { code: this.code, message: this.message, fields: this.fields }
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST'
  body?: unknown
  accessToken?: string
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.accessToken) headers['Authorization'] = `Bearer ${opts.accessToken}`

  const method = opts.method ?? 'GET'
  const started = Date.now()
  let res: Response
  try {
    res = await fetch(API_URL + path, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: AbortSignal.timeout(10_000)
    })
  } catch {
    // server down, offline, DNS, timeout... all look the same to the user
    if (is.dev) console.log(`[api] ${method} ${path} -> network error (${Date.now() - started}ms)`)
    throw new ApiError(0, 'network_error')
  }

  // dev only: these calls come from main, so they never show in the DevTools Network tab.
  // Only method, path, status and time. Never bodies or headers (tokens, passwords).
  if (is.dev) console.log(`[api] ${method} ${path} -> ${res.status} (${Date.now() - started}ms)`)

  if (res.status === 204) return undefined as T

  const data = await res.json().catch(() => null)
  if (!res.ok) throw ApiError.fromResponse(res.status, data)
  return data as T
}
