import { useEffect, useRef, useState, type ComponentType, type MouseEvent } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AlarmClock, ArrowLeftRight, BarChart3, Boxes, ClipboardList, Cloud, Layers, LayoutGrid, LogOut, Menu, MonitorSmartphone, RefreshCw, Settings, Users, Wrench, X, Activity } from 'lucide-react'
import { useExecutorOrders, useExtensions, useOverdue, useTermRequests } from '@/lib/queries'
import { canExecute, ROLE_LABELS } from '@/lib/dictionaries'
import { useAuth, useSession } from '@/auth/AuthProvider'
import { NotificationBell } from './NotificationBell'
import { ShortcutsButton } from './Shortcuts'
import { ThemeToggle } from './ThemeToggle'
import { cn, initials } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  badge?: number // красный счётчик справа (например, сколько просрочек и новых продлений)
}

const userNav: NavItem[] = [
  { to: '/', label: 'Каталог', icon: LayoutGrid },
  { to: '/my', label: 'Моя аренда', icon: ClipboardList },
]

const executorNav: NavItem[] = [{ to: '/executor', label: 'Заказы на подготовку', icon: Wrench }]

const adminNav: NavItem[] = [
  { to: '/admin', label: 'Обзор', icon: BarChart3 },
  { to: '/admin/inventory', label: 'Инвентаризация', icon: Boxes },
  { to: '/admin/pools', label: 'Пулы выдачи', icon: Layers },
  { to: '/admin/journal', label: 'Журнал выдачи', icon: ArrowLeftRight },
  { to: '/admin/overdue', label: 'Сроки аренды', icon: AlarmClock },
  { to: '/admin/vms', label: 'Виртуалки', icon: Cloud },
  { to: '/admin/people', label: 'Сотрудники и отделы', icon: Users },
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
  const isAdmin = session.user.role === 'admin'
  const isExecutor = canExecute(session.user.role)
  // счётчик у «Заказов на подготовку»: выданные ПК, по которым исполнитель ещё не внёс данные для подключения
  const waitingCount = useExecutorOrders(isExecutor).data?.filter((o) => !o.prepared_at).length ?? 0
  // «Сроки аренды» требуют внимания: просрочки, заявки на срок и продления, которые ещё не отметили «Принято»
  const deadlinesCount =
    (useOverdue(isAdmin).data?.length ?? 0) +
    (useTermRequests(isAdmin).data?.length ?? 0) +
    (useExtensions(isAdmin).data?.filter((e) => !e.acknowledged_at).length ?? 0)
  const { logout } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const burger = useRef<HTMLButtonElement>(null)
  const mobileMenu = useRef<HTMLElement>(null)
  const main = useRef<HTMLElement>(null)

  // Закрытие меню возвращает фокус на бургер: открытый пункт меню исчезает, и фокус иначе пропал бы
  const closeMenu = () => {
    if (!mobileOpen) return
    setMobileOpen(false)
    burger.current?.focus()
  }

  // Меню лежит в DOM раньше шапки, поэтому при открытии фокус переносится в него; Esc закрывает
  useEffect(() => {
    if (!mobileOpen) return
    mobileMenu.current?.querySelector('a')?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setMobileOpen(false)
      burger.current?.focus()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [mobileOpen])

  const skipToContent = (e: MouseEvent) => {
    e.preventDefault() // якорь #content не должен менять адрес страницы
    main.current?.focus()
  }

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
        <NavGroup items={userNav} onNavigate={closeMenu} />
        {isExecutor && (
          <NavGroup title="Исполнитель" items={executorNav.map((i) => ({ ...i, badge: waitingCount }))} onNavigate={closeMenu} />
        )}
        {isAdmin && (
          <NavGroup
            title="Администрирование"
            items={adminNav.map((i) => (i.to === '/admin/overdue' ? { ...i, badge: deadlinesCount } : i))}
            onNavigate={closeMenu}
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
              {session.user.username} · {ROLE_LABELS[session.user.role]}
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
      <a
        href="#content"
        onClick={skipToContent}
        className="fixed left-4 top-4 z-50 -translate-y-20 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-lift focus:translate-y-0"
      >
        Перейти к содержимому
      </a>

      {/* Десктоп: фиксированный сайдбар */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">{sidebar}</aside>

      {/* Мобильный: выезжающее меню */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-950/40" onClick={closeMenu} />
          <aside ref={mobileMenu} className="relative h-full w-64 animate-fade-in">{sidebar}</aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur lg:px-8">
          <button
            ref={burger}
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
          <NotificationBell />
          <ShortcutsButton />
          <ThemeToggle />
        </header>

        <main ref={main} id="content" tabIndex={-1} key={location.pathname} className="mx-auto max-w-7xl animate-fade-in px-4 py-8 focus:outline-none lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
