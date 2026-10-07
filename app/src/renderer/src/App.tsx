import { useEffect, useState } from 'react'
import type { AuthResult, User } from '../../preload'
import { PanelLeft, Search } from 'lucide-react'
import Sidebar from '@/components/Sidebar'
import LoginScreen from '@/components/LoginScreen'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

type ToolbarButtonProps = {
  label: string
  shortcut?: string
  onClick?: () => void
  children: React.ReactNode
}

function ToolbarButton({
  label,
  shortcut,
  onClick,
  children
}: ToolbarButtonProps): React.JSX.Element {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        {label}
        {shortcut && <span className="ml-2 opacity-60">{shortcut}</span>}
      </TooltipContent>
    </Tooltip>
  )
}

export default function App(): React.JSX.Element {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [user, setUser] = useState<User | null>(null)
  // true until we know if there's a saved session, so the login screen doesn't flash
  const [checking, setChecking] = useState(true)
  const [startError, setStartError] = useState<string | null>(null)

  function applySession(res: AuthResult<User>): void {
    if (res.ok) {
      setUser(res.data)
      setStartError(null)
    } else {
      setUser(null)
      // session_expired just means "log in". Offline is worth telling the user.
      setStartError(res.error.code === 'network_error' ? res.error.message : null)
    }
    setChecking(false)
  }

  // App start: main refreshes with the stored token and loads /users/me
  useEffect(() => {
    let cancelled = false
    window.snipwise.auth.me().then((res) => {
      if (!cancelled) applySession(res)
    })
    return () => {
      cancelled = true
    }
  }, [])

  // main revokes the token on the server and deletes it locally (locally even if the
  // server can't be reached), then we show the login screen
  async function handleLogout(): Promise<void> {
    try {
      await window.snipwise.auth.logout()
    } catch {
      // IPC itself broke. Nothing we can do here, still leave the app.
    }
    setUser(null)
    setStartError(null)
  }

  function retrySession(): void {
    setChecking(true)
    window.snipwise.auth.me().then(applySession)
  }

  // Cmd+B is a menu accelerator in main, it reaches us over IPC
  useEffect(() => window.snipwise.onToggleSidebar(() => setSidebarOpen((open) => !open)), [])

  if (checking) {
    return <div className="drag h-full bg-background" />
  }

  if (!user) {
    return (
      <LoginScreen
        notice={startError}
        onRetry={retrySession}
        onLoggedIn={(u) => {
          setUser(u)
          setStartError(null)
        }}
      />
    )
  }

  // TODO: server has no name or plan yet
  const sidebarUser = { name: user.email.split('@')[0], email: user.email, plan: 'Free' }

  return (
    <TooltipProvider delayDuration={400}>
      <div className="relative flex h-full text-foreground">
        <Sidebar open={sidebarOpen} user={sidebarUser} onLogout={handleLogout} />

        <div className="drag flex-1 bg-background" />

        {/* toolbar next to the traffic lights. Same 48px row height (h-12) as the
            traffic light position in main, so everything sits on one centre line.
            Has to come AFTER the drag areas in the DOM: electron applies drag/no-drag
            regions in DOM order, z-index doesn't count */}
        <div className="no-drag absolute top-0 left-[84px] z-10 flex h-12 items-center gap-1">
          <ToolbarButton
            label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
            shortcut="⌘B"
            onClick={() => setSidebarOpen((open) => !open)}
          >
            <PanelLeft className="size-4" />
          </ToolbarButton>
          {/* TODO: search isn't wired up yet */}
          <ToolbarButton label="Search">
            <Search className="size-4" />
          </ToolbarButton>
        </div>
      </div>
    </TooltipProvider>
  )
}
