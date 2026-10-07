import { useEffect, useState } from 'react'
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
  // null = logged out. Fake for now, real user comes from the server once auth is wired.
  const [user, setUser] = useState<{ name: string; email: string; plan: string } | null>(null)

  // Cmd+B is a menu accelerator in main, it reaches us over IPC
  useEffect(() => window.snipwise.onToggleSidebar(() => setSidebarOpen((open) => !open)), [])

  if (!user) {
    return (
      <LoginScreen
        onLoggedIn={(email) => setUser({ name: email.split('@')[0], email, plan: 'Free' })}
      />
    )
  }

  return (
    <TooltipProvider delayDuration={400}>
      <div className="relative flex h-full text-foreground">
        <Sidebar open={sidebarOpen} user={user} onLogout={() => setUser(null)} />

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
