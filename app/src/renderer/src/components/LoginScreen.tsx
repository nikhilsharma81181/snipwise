import { useState } from 'react'
import { z } from 'zod'
import { Loader2, Lock, Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { AuthResult, User } from '../../../preload'

// Email + password, talking to the real server through main (window.snipwise.auth).
// Google and the email login link come later with Firebase, shown as "Coming soon".
// The old "check your email" view is in git history (commit 0b679e3).

const emailSchema = z.email('Enter a valid email')

// same rules as the server (backend/src/auth/schemas.py)
const loginSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Enter your password').max(128)
})
const signupSchema = z.object({
  email: emailSchema,
  password: z.string().min(8, 'Password must be at least 8 characters').max(128)
})

type Field = 'email' | 'password'
type FieldErrors = Partial<Record<Field, string>>

function GoogleIcon(): React.JSX.Element {
  return (
    <svg className="size-4" viewBox="0 0 24 24">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
      />
    </svg>
  )
}

function ComingSoon(): React.JSX.Element {
  return (
    <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      Coming soon
    </span>
  )
}

type Props = {
  onLoggedIn: (user: User) => void
  // shown above the form, e.g. server unreachable at app start
  notice?: string | null
  onRetry?: () => void
}

export default function LoginScreen({ onLoggedIn, notice, onRetry }: Props): React.JSX.Element {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSignup, setIsSignup] = useState(false)
  const [pending, setPending] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    if (pending) return

    const schema = isSignup ? signupSchema : loginSchema
    const parsed = schema.safeParse({ email: email.trim(), password })
    if (!parsed.success) {
      const errs: FieldErrors = {}
      for (const issue of parsed.error.issues) {
        const field = issue.path[0] as Field
        errs[field] ??= issue.message
      }
      setFieldErrors(errs)
      setError(null)
      return
    }

    setPending(true)
    setFieldErrors({})
    setError(null)

    const { email: cleanEmail, password: pw } = parsed.data
    let res: AuthResult<User>
    try {
      res = isSignup
        ? await window.snipwise.auth.signup(cleanEmail, pw)
        : await window.snipwise.auth.login(cleanEmail, pw)
    } catch {
      // only if IPC itself breaks, main already turns server errors into results
      res = { ok: false, error: { code: 'internal_error', message: 'Something went wrong' } }
    }

    if (res.ok) {
      onLoggedIn(res.data)
      return
    }

    setPending(false)
    // server's 422 comes with per-field messages, show them under the inputs
    if (res.error.fields) {
      setFieldErrors({ email: res.error.fields.email, password: res.error.fields.password })
    }
    if (!res.error.fields?.email && !res.error.fields?.password) setError(res.error.message)
  }

  function toggleSignup(): void {
    setIsSignup((v) => !v)
    setFieldErrors({})
    setError(null)
  }

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      {/* empty strip so the window can still be dragged */}
      <div className="drag h-12 shrink-0" />

      <div className="flex flex-1 items-center justify-center px-6 pb-12">
        <div className="w-full max-w-sm">
          <div className="text-center">
            <h1 className="text-2xl font-semibold tracking-tight">
              {isSignup ? 'Create your account' : 'Welcome to Snipwise'}
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {isSignup ? 'Sign up to start editing.' : 'Sign in to keep editing.'}
            </p>
          </div>

          {notice && (
            <div className="mt-6 flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5 text-sm">
              <span className="text-muted-foreground">{notice}</span>
              {onRetry && (
                <button onClick={onRetry} className="shrink-0 text-foreground hover:underline">
                  Try again
                </button>
              )}
            </div>
          )}

          <div className="mt-8 flex flex-col gap-4">
            <Button variant="outline" className="h-11 w-full gap-3" disabled>
              <GoogleIcon />
              Continue with Google
              <ComingSoon />
            </Button>

            <div className="flex items-center gap-4">
              <div className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or</span>
              <div className="h-px flex-1 bg-border" />
            </div>

            <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-3">
              <div>
                <div className="relative">
                  <Mail className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    type="email"
                    autoComplete="email"
                    placeholder="name@company.com"
                    value={email}
                    disabled={pending}
                    aria-invalid={!!fieldErrors.email}
                    onChange={(e) => {
                      setEmail(e.target.value)
                      setFieldErrors((f) => ({ ...f, email: undefined }))
                      setError(null)
                    }}
                    className="h-11 pl-10"
                  />
                </div>
                {fieldErrors.email && (
                  <p className="mt-1.5 text-xs text-destructive">{fieldErrors.email}</p>
                )}
              </div>

              <div>
                <div className="relative">
                  <Lock className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    type="password"
                    autoComplete={isSignup ? 'new-password' : 'current-password'}
                    placeholder={isSignup ? 'Password (at least 8 characters)' : 'Password'}
                    value={password}
                    disabled={pending}
                    aria-invalid={!!fieldErrors.password}
                    onChange={(e) => {
                      setPassword(e.target.value)
                      setFieldErrors((f) => ({ ...f, password: undefined }))
                      setError(null)
                    }}
                    className="h-11 pl-10"
                  />
                </div>
                {fieldErrors.password && (
                  <p className="mt-1.5 text-xs text-destructive">{fieldErrors.password}</p>
                )}
              </div>

              {error && <p className="text-sm text-destructive">{error}</p>}

              <Button
                type="submit"
                className="h-11 w-full"
                disabled={pending || !email.trim() || !password}
              >
                {pending && <Loader2 className="animate-spin" />}
                {isSignup ? 'Create account' : 'Log in'}
              </Button>
            </form>

            <button
              type="button"
              disabled
              className="flex items-center justify-center gap-2 text-sm text-muted-foreground opacity-60"
            >
              Email me a login link instead
              <ComingSoon />
            </button>
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            {isSignup ? 'Already have an account? ' : "Don't have an account? "}
            <button
              type="button"
              onClick={toggleSignup}
              disabled={pending}
              className="text-foreground underline-offset-4 hover:underline"
            >
              {isSignup ? 'Log in' : 'Sign up'}
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
