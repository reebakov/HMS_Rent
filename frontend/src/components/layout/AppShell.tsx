import { useState, type ComponentType } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AlarmClock, ArrowLeftRight, BarChart3, Boxes, Building2, ClipboardList, Cloud, Layers, LayoutGrid, LogOut, Menu, MonitorSmartphone, RefreshCw, Settings, Users, X, Activity } from 'lucide-react'
import { useOverdue } from '@/lib/queries'
import { useAuth, useSession } from '@/auth/AuthProvider'
import { ThemeToggle } from './ThemeToggle'
import { cn, initials } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  badge?: number // красный счётчик справа (например, сколько просрочек)
}

const userNav: NavItem[] = [
  { to: '/', label: 'Каталог', icon: LayoutGrid },
  { to: '/my', label: 'Моя аренда', icon: ClipboardList },
]

const adminNav: NavItem[] = [
  { to: '/admin', label: 'Обзор', icon: BarChart3 },
  { to: '/admin/inventory', label: 'Инвентаризация', icon: Boxes },
  { to: '/admin/pools', label: 'Пулы выдачи', icon: Layers },
  { to: '/admin/journal', label: 'Журнал выдачи', icon: ArrowLeftRight },
  { to: '/admin/overdue', label: 'Просрочки', icon: AlarmClock },
  { to: '/admin/vms', label: 'Виртуалки', icon: Cloud },
  { to: '/admin/departments', label: 'Отделы', icon: Building2 },
  { to: '/admin/users', label: 'Сотрудники', icon: Users },
  { to: '/admin/events', label: 'Логи системы', icon: Activity },
  { to: '/admin/sync', label: 'Синхронизация', icon: RefreshCw },
  { to: '/admin/settings', label: 'Настройки', icon: Settings },
]

function NavGroup({ title, items, onNavigate }: { title?: string; items: NavItem[]; onNavigate: () => void }) {
  return (
    <div className="space-y-0.5">
      {title && <p className="px-3 pb-2 pt-5 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">{title}</p>}
      {items.map(({ to, label, icon: Icon, badge }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/' || to === '/admin'}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors',
              isActive
                ? 'bg-white/10 text-white'
                : 'text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground',
            )
          }
        >
          <Icon className="h-[18px] w-[18px]" />
          {label}
          {!!badge && (
            <span className="ml-auto rounded-full bg-danger px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white">{badge}</span>
          )}
        </NavLink>
      ))}
    </div>
  )
}

export function AppShell() {
  const session = useSession()
  const overdueCount = useOverdue(session.user.role === 'admin').data?.length ?? 0
  const { logout } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const isAdmin = session.user.role === 'admin'

  const sidebar = (
    <div className="flex h-full flex-col bg-sidebar px-3 py-5 text-sidebar-foreground">
      <div className="flex items-center gap-2.5 px-3 pb-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-white">
          <MonitorSmartphone className="h-[18px] w-[18px]" />
        </div>
        <div>
          <p className="text-[15px] font-semibold leading-tight text-white">{session.app_name}</p>
          <p className="text-[11px] text-sidebar-muted">{session.app_subtitle}</p>
        </div>
      </div>

      <nav className="flex-1">
        <NavGroup items={userNav} onNavigate={() => setMobileOpen(false)} />
        {isAdmin && (
          <NavGroup
            title="Администрирование"
            items={adminNav.map((i) => (i.to === '/admin/overdue' ? { ...i, badge: overdueCount } : i))}
            onNavigate={() => setMobileOpen(false)}
          />
        )}
      </nav>

      <div className="mt-4 border-t border-white/10 pt-4">
        <div className="flex items-center gap-3 px-2">
          {session.user.avatar_url ? (
            <img src={session.user.avatar_url} alt="" referrerPolicy="no-referrer" className="h-9 w-9 shrink-0 rounded-full" />
          ) : (
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-white">
              {initials(session.user.display_name || session.user.username)}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-white">{session.user.display_name}</p>
            <p className="truncate text-[11px] text-sidebar-muted">
              {session.user.username} · {isAdmin ? 'администратор' : 'сотрудник'}
            </p>
          </div>
          <button
            onClick={logout}
            title="Выйти"
            className="rounded-md p-1.5 text-sidebar-muted transition-colors hover:bg-white/10 hover:text-white"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen">
      {/* Десктоп: фиксированный сайдбар */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">{sidebar}</aside>

      {/* Мобильный: выезжающее меню */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-950/40" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-64 animate-fade-in">{sidebar}</aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur lg:px-8">
          <button
            className="rounded-md p-1.5 hover:bg-muted lg:hidden"
            aria-label={mobileOpen ? 'Закрыть меню' : 'Открыть меню'}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((v) => !v)}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex-1" />
          {session.insight_mode === 'mock' && (
            <span className="hidden rounded-md bg-warning/10 px-2.5 py-1 text-xs font-medium text-warning sm:inline">
              Демо-данные: Insight не подключён
            </span>
          )}
          {session.user.auth_source === 'dev' && (
            <span className="hidden rounded-md bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground sm:inline">
              Dev-вход
            </span>
          )}
          <ThemeToggle />
        </header>

        <main key={location.pathname} className="mx-auto max-w-7xl animate-fade-in px-4 py-8 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
