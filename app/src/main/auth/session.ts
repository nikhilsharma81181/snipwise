import { ApiError, request } from './api'
import { clearRefreshToken, loadRefreshToken, saveRefreshToken } from './token-store'
import type { LoginResponse, TokenPair, User } from './types'

let accessToken: string | null = null
let refreshToken: string | null = null
let refreshing: Promise<void> | null = null

async function setTokens(pair: TokenPair): Promise<void> {
  accessToken = pair.accessToken
  refreshToken = pair.refreshToken
  await saveRefreshToken(pair.refreshToken)
}

async function clearSession(): Promise<void> {
  accessToken = null
  refreshToken = null
  await clearRefreshToken()
}

async function doRefresh(): Promise<void> {
  const token = refreshToken ?? (await loadRefreshToken())
  if (!token) throw new ApiError(401, 'session_expired')

  try {
    const pair = await request<TokenPair>('/auth/refresh', {
      method: 'POST',
      body: { refreshToken: token }
    })
    // tokens rotate: the old refresh token is dead now, so store the new one right away
    await setTokens(pair)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      await clearSession()
      throw new ApiError(401, 'session_expired')
    }
    throw err
  }
}

// Single-flight. If three calls hit a 401 together they all wait on ONE refresh.
// Sending the same refresh token twice would get the second one rejected (rotation)
// and we'd log the user out for nothing.
function refreshTokens(): Promise<void> {
  if (!refreshing) {
    refreshing = doRefresh().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

// For protected routes: on 401 refresh once and retry once, otherwise the session is over.
async function authedRequest<T>(
  path: string,
  opts: { method?: 'GET' | 'POST'; body?: unknown } = {}
): Promise<T> {
  if (!accessToken) await refreshTokens()

  const tokenUsed = accessToken
  try {
    return await request<T>(path, { ...opts, accessToken: tokenUsed ?? undefined })
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 401) throw err
  }

  // someone else may have refreshed while our request was out, then just retry with theirs
  if (accessToken === tokenUsed) await refreshTokens()

  try {
    return await request<T>(path, { ...opts, accessToken: accessToken ?? undefined })
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      await clearSession()
      throw new ApiError(401, 'session_expired')
    }
    throw err
  }
}

export function me(): Promise<User> {
  return authedRequest<User>('/users/me')
}

export async function login(email: string, password: string): Promise<User> {
  const res = await request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: { email, password }
  })
  await setTokens(res)
  // login only returns id/email/role, /me has the usage numbers too
  return me()
}

// signup doesn't log in on the server, so log in straight after
export async function signup(email: string, password: string): Promise<User> {
  await request('/auth/signup', { method: 'POST', body: { email, password } })
  return login(email, password)
}

export async function logout(): Promise<void> {
  // if a refresh is mid-flight, wait so we revoke the token it ends up storing
  await refreshing?.catch(() => {})
  const token = refreshToken ?? (await loadRefreshToken())
  try {
    if (token) await request('/auth/logout', { method: 'POST', body: { refreshToken: token } })
  } catch {
    // server down or whatever, we still log out locally
  }
  await clearSession()
}
