import { useEffect, useRef, useState, type ComponentType } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlarmClock, Bell, CalendarCheck, CircleAlert, ClipboardList, Cloud, Clock, Monitor } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DataState } from '@/components/ui/data-state'
import { useNotifications, useReadNotifications } from '@/lib/queries'
import type { NotificationKind, UserNotification } from '@/lib/types'
import { cn, formatDateTime } from '@/lib/utils'

const KINDS: Record<NotificationKind, { icon: ComponentType<{ className?: string }>; tone: string }> = {
  pc_ready: { icon: Monitor, tone: 'text-success' },
  vm_ready: { icon: Cloud, tone: 'text-success' },
  vm_failed: { icon: CircleAlert, tone: 'text-danger' },
  request_status: { icon: ClipboardList, tone: 'text-primary' },
  term_decision: { icon: CalendarCheck, tone: 'text-primary' },
  term_ending: { icon: Clock, tone: 'text-warning' },
  term_overdue: { icon: AlarmClock, tone: 'text-danger' },
}

/** Колокольчик в шапке: уведомления заказчику о его заказах; клик по уведомлению отмечает его прочитанным и ведёт в «Мою аренду» */
export function NotificationBell() {
  const query = useNotifications()
  const read = useReadNotifications()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const unread = query.data?.unread ?? 0

  // Esc возвращает фокус на кнопку, клик вне панели просто закрывает её
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      button.current?.focus()
    }
    const onPointerDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  const openNotification = (n: UserNotification) => {
    if (!n.read_at) read.mutate(n.id)
    setOpen(false)
    button.current?.focus()
    navigate('/my')
  }

  return (
    <div ref={root} className="relative">
      <Button
        ref={button}
        variant="ghost"
        size="icon"
        className="relative"
        title="Уведомления"
        aria-label={unread ? `Уведомления, непрочитанных: ${unread}` : 'Уведомления'}
        aria-expanded={open}
        aria-controls="notifications-panel"
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute right-0.5 top-0.5 min-w-4 rounded-full bg-danger px-1 text-[10px] font-semibold leading-4 text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </Button>
      {open && (
        <div
          id="notifications-panel"
          className="absolute right-0 top-full z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border bg-card shadow-lift"
        >
          <div className="flex items-center justify-between border-b px-4 py-2.5">
            <p className="text-sm font-semibold">Уведомления</p>
            {unread > 0 && (
              <Button variant="ghost" size="sm" className="-mr-2" onClick={() => read.mutate(undefined)}>
                Прочитать все
              </Button>
            )}
          </div>
          <div className="max-h-[26rem] overflow-y-auto">
            <DataState
              query={query}
              errorTitle="Не удалось загрузить уведомления"
              loading={<p className="px-4 py-6 text-center text-[13px] text-muted-foreground">Загрузка…</p>}
              empty={<p className="px-4 py-6 text-center text-[13px] text-muted-foreground">Пока ничего нет: здесь появятся новости по вашим заказам</p>}
              isEmpty={(list) => list.items.length === 0}
            >
              {(list) => (
                <ul className="divide-y">
                  {list.items.map((n) => {
                    const { icon: Icon, tone } = KINDS[n.kind]
                    return (
                      <li key={n.id}>
                        <button
                          onClick={() => openNotification(n)}
                          className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                        >
                          <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', tone)} />
                          <span className="min-w-0 flex-1">
                            <span className={cn('block text-[13px]', n.read_at ? 'text-muted-foreground' : 'font-semibold')}>
                              {n.title}
                              {!n.read_at && <span className="sr-only"> (новое)</span>}
                            </span>
                            {n.body && <span className="mt-0.5 block text-xs text-muted-foreground">{n.body}</span>}
                            <span className="mt-1 block text-[11px] text-muted-foreground">{formatDateTime(n.created_at)}</span>
                          </span>
                          {!n.read_at && <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </DataState>
          </div>
        </div>
      )}
    </div>
  )
}
