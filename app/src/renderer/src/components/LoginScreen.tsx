import { useState } from 'react'
import { z } from 'zod'
import { ArrowLeft, ArrowRight, CheckCircle2, Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// Same flow as project ornn: Google or an emailed login link, no passwords.
// No account yet? It gets created on first login, so there's no separate sign-up.

const emailSchema = z.email('Enter a valid email')

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

type Props = { onLoggedIn: (email: string) => void }

export default function LoginScreen({ onLoggedIn }: Props): React.JSX.Element {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [linkSentTo, setLinkSentTo] = useState<string | null>(null)

  function handleGoogle(): void {
    // TODO: real google sign-in (system browser + redirect back to the app)
    onLoggedIn('nikhil@gmail.com')
  }

  function handleSendLink(e: React.FormEvent): void {
    e.preventDefault()
    const result = emailSchema.safeParse(email.trim())
    if (!result.success) {
      setError(result.error.issues[0].message)
      return
    }
    setError(null)
    // TODO: ask the server to email the link. For now we just pretend it went out.
    setLinkSentTo(result.data)
  }

  function resetEmail(): void {
    setLinkSentTo(null)
    setEmail('')
  }

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      {/* empty strip so the window can still be dragged */}
      <div className="drag h-12 shrink-0" />

      <div className="flex flex-1 items-center justify-center px-6 pb-12">
        {linkSentTo ? (
          <div className="w-full max-w-sm text-center">
            <CheckCircle2 className="mx-auto size-10 text-muted-foreground" />
            <h1 className="mt-5 text-2xl font-semibold tracking-tight">Check your email</h1>
            <p className="mt-2 text-sm text-muted-foreground">We sent a login link to</p>
            <p className="mt-0.5 text-sm font-medium">{linkSentTo}</p>
            <p className="mt-6 text-xs text-muted-foreground">
              Click the link in the email to sign in. Check spam if you don&apos;t see it.
            </p>
            <button
              onClick={resetEmail}
              className="mt-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="size-3.5" />
              Use a different email
            </button>
          </div>
        ) : (
          <div className="w-full max-w-sm">
            <div className="text-center">
              <h1 className="text-2xl font-semibold tracking-tight">Welcome to Snipwise</h1>
              <p className="mt-1.5 text-sm text-muted-foreground">Sign in to keep editing.</p>
            </div>

            <div className="mt-8 flex flex-col gap-4">
              <Button variant="outline" className="h-11 w-full gap-3" onClick={handleGoogle}>
                <GoogleIcon />
                Continue with Google
              </Button>

              <div className="flex items-center gap-4">
                <div className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground">or</span>
                <div className="h-px flex-1 bg-border" />
              </div>

              <form onSubmit={handleSendLink} noValidate className="flex flex-col gap-3">
                <div className="relative">
                  <Mail className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    type="email"
                    autoComplete="email"
                    placeholder="name@company.com"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value)
                      setError(null)
                    }}
                    className="h-11 pl-10"
                  />
                </div>

                {error && <p className="text-sm text-destructive">{error}</p>}

                <Button type="submit" className="h-11 w-full" disabled={!email.trim()}>
                  Send me a login link
                  <ArrowRight />
                </Button>
              </form>
            </div>

            <p className="mt-6 text-center text-xs text-muted-foreground">
              No account? One will be created automatically.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
