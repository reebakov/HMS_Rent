import { ArrowLeftRight, CircleAlert, Pencil, Plus, RefreshCw, Undo2 } from 'lucide-react'
import { EVENT_LABELS } from '@/lib/dictionaries'
import type { AssetEvent } from '@/lib/types'
import { cn, formatDateTime } from '@/lib/utils'

const EVENT_STYLE: Record<string, { icon: typeof Plus; className: string }> = {
  booked: { icon: ArrowLeftRight, className: 'bg-primary/10 text-primary' },
  returned: { icon: Undo2, className: 'bg-success/10 text-success' },
  insight_status_changed: { icon: RefreshCw, className: 'bg-warning/10 text-warning' },
  insight_created: { icon: Plus, className: 'bg-muted text-muted-foreground' },
  insight_removed: { icon: CircleAlert, className: 'bg-danger/10 text-danger' },
  writeback_failed: { icon: CircleAlert, className: 'bg-danger/10 text-danger' },
  admin_update: { icon: Pencil, className: 'bg-muted text-muted-foreground' },
}

/** Лента событий: бронь, возврат, смены статусов в Insight */
export function EventTimeline({ events, showComputer = true }: { events: AssetEvent[]; showComputer?: boolean }) {
  if (!events.length) return <p className="py-6 text-center text-[13px] text-muted-foreground">Событий пока нет</p>
  return (
    <ol className="relative space-y-5 before:absolute before:bottom-2 before:left-[15px] before:top-2 before:w-px before:bg-border">
      {events.map((e) => {
        const style = EVENT_STYLE[e.event_type] ?? EVENT_STYLE.admin_update
        const Icon = style.icon
        return (
          <li key={e.id} className="relative flex gap-3">
            <div className={cn('z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-4 ring-card', style.className)}>
              <Icon className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 pt-0.5">
              <p className="text-[13px]">
                {showComputer && <span className="font-semibold">{e.computer.name} · </span>}
                <span className="font-medium">{EVENT_LABELS[e.event_type] ?? e.event_type}</span>
              </p>
              <p className="mt-0.5 text-[13px] text-muted-foreground">{e.message}</p>
              <p className="mt-1 text-xs text-muted-foreground/80">
                {formatDateTime(e.created_at)} · {e.actor ? e.actor.display_name : 'система'}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/** Горизонтальные полоски — распределение по категориям/отделам без библиотек графиков */
export function BarList({ items }: { items: { label: string; value: number; hint?: string; className?: string }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label}>
          <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="truncate font-medium">{item.label}</span>
            <span className="tabular text-muted-foreground">
              {item.hint ?? item.value}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={cn('h-full rounded-full bg-primary transition-all', item.className)}
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string
  value: number | string
  hint?: string
  tone?: 'default' | 'success' | 'primary' | 'warning' | 'danger'
}) {
  const color = {
    default: 'text-foreground',
    success: 'text-success',
    primary: 'text-primary',
    warning: 'text-warning',
    danger: 'text-danger',
  }[tone]
  return (
    <div className="rounded-xl border bg-card p-5 shadow-card">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className={cn('mt-2 text-3xl font-semibold tabular tracking-tight', color)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}
