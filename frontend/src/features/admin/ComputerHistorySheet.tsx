import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CircleAlert } from 'lucide-react'
import { Sheet } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge, StatusBadge, TierBadge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/card'
import { DataState } from '@/components/ui/data-state'
import { Field, Select, Textarea } from '@/components/ui/input'
import { InsightAttributes, SpecGrid } from '@/features/catalog/SpecGrid'
import { ReturnDialog } from '@/features/booking/BookingDialog'
import { EventTimeline } from './widgets'
import { useComputerHistory, useReturnBooking, useUpdateComputer } from '@/lib/queries'
import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { Tier } from '@/lib/types'
import { cn, errorMessage, formatDate, formatDateTime, formatDuration } from '@/lib/utils'

const TABS = ['Обзор', 'История выдачи', 'События', 'Insight'] as const

/** Полная карточка ПК для админа: кто держит, история, события, ручные правки */
export function ComputerHistorySheet({ computerId, onClose }: { computerId: number | null; onClose: () => void }) {
  const history = useComputerHistory(computerId)
  const { data } = history
  const update = useUpdateComputer()
  const returnMutation = useReturnBooking()
  const [tab, setTab] = useState<(typeof TABS)[number]>('Обзор')
  const [tierOverride, setTierOverride] = useState('')
  const [note, setNote] = useState('')
  const [returnOpen, setReturnOpen] = useState(false)

  useEffect(() => {
    if (!data) return
    setTierOverride(data.computer.tier_override ?? '')
    setNote(data.computer.note ?? '')
  }, [data])
  useEffect(() => setTab('Обзор'), [computerId])

  const c = data?.computer
  const dirty = c && (tierOverride !== (c.tier_override ?? '') || note !== (c.note ?? ''))

  const save = async () => {
    if (!c) return
    try {
      await update.mutateAsync({ id: c.id, tier_override: (tierOverride || null) as Tier | null, note: note || null })
      toast.success('Сохранено')
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const forceReturn = async (comment: string) => {
    if (!c?.booking) return
    try {
      await returnMutation.mutateAsync({ id: c.booking.id, comment: comment || 'Возврат администратором' })
      toast.success(`${c.name} возвращён`)
      setReturnOpen(false)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <Sheet
      open={computerId !== null}
      onOpenChange={(open) => !open && onClose()}
      title={c?.name ?? 'Компьютер'}
      description={
        c && (
          <span className="flex flex-wrap items-center gap-2">
            <TierBadge tier={c.tier} />
            <StatusBadge status={c.status} />
            {c.pool ? <Badge>Пул: {c.pool.name}</Badge> : <Badge tone="warning">Не в пуле</Badge>}
            {c.is_archived && <Badge tone="danger">Нет в Insight</Badge>}
            {c.insight_key && <span className="font-mono text-xs">{c.insight_key}</span>}
          </span>
        )
      }
    >
      <DataState
        query={history}
        errorTitle="Не удалось загрузить карточку компьютера"
        loading={
          <div className="space-y-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-64" />
          </div>
        }
      >
        {(data) => {
          const c = data.computer
          return (
            <>
              <div className="mb-5 flex gap-1 rounded-lg bg-muted p-1">
                {TABS.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={cn(
                      'flex-1 rounded-md px-2 py-1.5 text-[13px] font-medium transition-colors',
                      tab === t ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground',
                    )}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {tab === 'Обзор' && (
                <div className="space-y-5">
                  {c.issues.length > 0 && (
                    <div className="space-y-1.5 rounded-xl border border-danger/20 bg-danger/5 p-4">
                      {c.issues.map((issue) => (
                        <p key={issue} className="flex gap-2 text-[13px] text-danger">
                          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                          {issue}
                        </p>
                      ))}
                    </div>
                  )}

                  <div className="rounded-xl border p-4">
                    <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Сейчас</p>
                    {c.booking && c.department ? (
                      <div className="flex items-start justify-between gap-4">
                        <div className="text-[13px]">
                          <p className="text-base font-semibold">{c.department.name}</p>
                          <p className="mt-1">
                            {c.booking.requester_name} <span className="text-muted-foreground">({c.booking.requester_nick})</span>
                          </p>
                          <p className="mt-1 text-muted-foreground">
                            с {formatDate(c.booking.booked_at)} · {formatDuration(c.booking.booked_at)}
                            {c.booking.expected_return_at && ` · вернуть до ${formatDate(c.booking.expected_return_at)}`}
                          </p>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => setReturnOpen(true)}>
                          Вернуть
                        </Button>
                      </div>
                    ) : (
                      <p className="text-[13px] text-muted-foreground">Не закреплён ни за одним отделом</p>
                    )}
                  </div>

                  <SpecGrid computer={c} className="xl:grid-cols-2" />

                  <div className="space-y-4 rounded-xl border p-4">
                    <Field label="Категория" hint="По умолчанию определяется автоматически по характеристикам">
                      <Select value={tierOverride} onChange={(e) => setTierOverride(e.target.value)}>
                        <option value="">Автоматически</option>
                        {TIER_ORDER.map((t) => (
                          <option key={t} value={t}>
                            {TIERS[t].short}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="Заметка админа" hint="Видна только администраторам">
                      <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Например: шумит кулер" />
                    </Field>
                    <div className="flex justify-end">
                      <Button size="sm" disabled={!dirty} loading={update.isPending} onClick={save}>
                        Сохранить
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {tab === 'История выдачи' &&
                (data.bookings.length ? (
                  <div className="divide-y rounded-xl border">
                    {data.bookings.map((b) => (
                      <div key={b.id} className="px-4 py-3 text-[13px]">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{b.department.name}</span>
                          {b.status === 'active' ? <Badge tone="primary" dot>Сейчас</Badge> : <Badge>Возвращён</Badge>}
                        </div>
                        <p className="mt-1 text-muted-foreground">
                          {b.requester_name} ({b.requester_nick}) · {formatDateTime(b.booked_at)} → {b.returned_at ? formatDateTime(b.returned_at) : 'по сей день'}
                        </p>
                        {b.return_comment && <p className="mt-1 italic text-muted-foreground">«{b.return_comment}»</p>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="py-6 text-center text-[13px] text-muted-foreground">Компьютер ещё ни разу не выдавался</p>
                ))}

              {tab === 'События' && <EventTimeline events={data.events} showComputer={false} />}

              {tab === 'Insight' && <InsightAttributes attributes={data.attributes} />}

              <ReturnDialog
                open={returnOpen}
                title={`Вернуть ${c.name} от отдела «${c.department?.name ?? ''}»?`}
                pending={returnMutation.isPending}
                onConfirm={forceReturn}
                onClose={() => setReturnOpen(false)}
              />
            </>
          )
        }}
      </DataState>
    </Sheet>
  )
}
