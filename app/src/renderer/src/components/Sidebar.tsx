import { useState } from 'react'
import { ChevronDown, ChevronRight, Folder, Plus } from 'lucide-react'
import { cn } from 'cn'
import UserMenu from '@/components/UserMenu'

// mock data until projects come from the main process
type Session = { id: string; title: string }
type Project = { id: string; name: string; sessions: Session[] }

const PROJECTS: Project[] = [
  {
    id: 'p1',
    name: 'podcast-ep-12',
    sessions: [
      { id: 's1', title: 'Remove silences' },
      { id: 's2', title: 'Tighten the intro' },
      { id: 's3', title: 'Put the pricing part back' }
    ]
  },
  {
    id: 'p2',
    name: 'product-demo',
    sessions: [{ id: 's4', title: 'First cut' }]
  }
]

type User = { name: string; email: string; plan: string }

type Props = { open: boolean; user: User; onLogout: () => void }

export default function Sidebar({ open, user, onLogout }: Props): React.JSX.Element {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ p1: true })
  const [activeSession, setActiveSession] = useState('s1')

  function toggleProject(id: string): void {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    // outer div animates the width, inner one keeps a fixed width so text doesn't reflow
    <div
      className={cn(
        'shrink-0 overflow-hidden border-r border-sidebar-border transition-[width] duration-200',
        open ? 'w-[260px]' : 'w-0 border-r-0'
      )}
    >
      <aside className="flex h-full w-[260px] flex-col bg-sidebar text-sidebar-foreground">
        {/* space for traffic lights + toggle button, also drags the window */}
        <div className="drag h-12 shrink-0" />

        <div className="px-2">
          <button className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-sidebar-accent">
            <span className="flex size-6 items-center justify-center rounded-full bg-sidebar-accent">
              <Plus className="size-3.5" />
            </span>
            New
          </button>
        </div>

        <div className="mt-6 px-4 pb-1 text-xs text-muted-foreground">Projects</div>

        <div className="flex-1 overflow-y-auto px-2">
          {PROJECTS.map((project) => {
            const isOpen = !!expanded[project.id]
            return (
              <div key={project.id}>
                <button
                  onClick={() => toggleProject(project.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-sidebar-accent"
                >
                  {isOpen ? (
                    <ChevronDown className="size-3.5 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                  )}
                  <Folder className="size-4 text-muted-foreground" />
                  <span className="truncate">{project.name}</span>
                </button>

                {isOpen && (
                  <div className="mb-1 ml-4 flex flex-col gap-0.5 border-l border-sidebar-border pl-2">
                    {project.sessions.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => setActiveSession(s.id)}
                        className={cn(
                          'truncate rounded-lg px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-sidebar-accent',
                          activeSession === s.id && 'bg-sidebar-accent text-sidebar-foreground'
                        )}
                      >
                        {s.title}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="border-t border-sidebar-border p-2">
          <UserMenu user={user} onLogout={onLogout} />
        </div>
      </aside>
    </div>
  )
}
