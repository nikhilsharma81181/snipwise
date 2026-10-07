import { ChevronDown, CircleArrowUp, CircleHelp, Gauge, LogOut, Settings } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'

type User = { name: string; email: string; plan: string }

function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
}

// bottom of the sidebar: avatar + name + plan, click opens the account menu (opens upward)
// TODO: only Log out does something so far
type Props = { user: User; onLogout: () => void }

export default function UserMenu({ user, onLogout }: Props): React.JSX.Element {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left outline-none hover:bg-sidebar-accent data-[state=open]:bg-sidebar-accent">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-medium">
            {initials(user.name)}
          </div>
          <div className="min-w-0 flex-1 truncate text-sm">
            {user.name}
            <span className="text-muted-foreground"> · {user.plan}</span>
          </div>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent side="top" align="start" sideOffset={6} className="w-[244px]">
        <DropdownMenuLabel className="truncate font-normal text-muted-foreground">
          {user.email}
        </DropdownMenuLabel>
        <DropdownMenuItem>
          <Settings />
          Settings
          <DropdownMenuShortcut>⌘,</DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Gauge />
          Usage
        </DropdownMenuItem>
        <DropdownMenuItem>
          <CircleHelp />
          Get help
        </DropdownMenuItem>

        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <CircleArrowUp />
          Upgrade plan
        </DropdownMenuItem>

        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onLogout}>
          <LogOut />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
