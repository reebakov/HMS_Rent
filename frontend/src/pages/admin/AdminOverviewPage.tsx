import { Link } from 'react-router-dom'
import { CheckCircle2, CircleAlert, RefreshCw } from 'lucide-react'
import { Card, CardHeader, PageHeader, Skeleton } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { BarList, EventTimeline, StatCard } from '@/features/admin/widgets'
import { useDepartmentUsage, useEvents, useStats } from '@/lib/queries'
import { TIERS } from '@/lib/dictionaries'
import { formatRelative } from '@/lib/utils'

export function AdminOverviewPage() {
  const stats = useStats()
  const departments = useDepartmentUsage()
  const events = useEvents(10)
  const s = stats.data

  return (
    <>
      <PageHeader title="Обзор парка" description="Сводка по всем компьютерам, бронированиям и синхронизации с Insight" />

      {!s ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[116px] rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <StatCard label="Всего в учёте" value={s.total} hint={`в пулах выдачи: ${s.in_pools}`} />
          <StatCard label="Свободно" value={s.by_status.available ?? 0} tone="success" hint="доступно для брони" />
          <StatCard
            label="За отделами"
            value={s.active_bookings}
            tone="primary"
            hint={`${s.departments_using} отделов пользуются`}
          />
          <Link to="/admin/inventory?status=unavailable" className="block transition-opacity hover:opacity-90">
            <StatCard
              label="Недоступно"
              value={(s.by_status.maintenance ?? 0) + (s.by_status.in_use ?? 0) + (s.by_status.retired ?? 0)}
              tone="warning"
              hint="ремонт, резерв, заняты мимо портала"
            />
          </Link>
          <Link to="/admin/inventory?issues=1" className="block transition-opacity hover:opacity-90">
            <StatCard
              label="Требуют внимания"
              value={s.issues}
              tone={s.issues ? 'danger' : 'default'}
              hint={s.overdue ? `из них просрочено: ${s.overdue}` : 'расхождения с Insight, просрочки'}
            />
          </Link>
        </div>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader title="По категориям" description="Занято / всего" />
          <div className="p-5">
            {s ? (
              <BarList
                items={s.by_tier.map((t) => ({
                  label: TIERS[t.tier].label,
                  value: t.booked,
                  hint: `${t.booked} из ${t.total} · свободно ${t.available}`,
                }))}
              />
            ) : (
              <Skeleton className="h-40" />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Отделы"
            description="Сколько компьютеров закреплено"
            action={
              <Link to="/admin/departments" className="text-[13px] font-medium text-primary hover:underline">
                Все
              </Link>
            }
          />
          <div className="p-5">
            {departments.data ? (
              <BarList
                items={departments.data
                  .filter((d) => d.active > 0)
                  .slice(0, 7)
                  .map((d) => ({ label: d.name, value: d.active }))}
              />
            ) : (
              <Skeleton className="h-40" />
            )}
            {departments.data && !departments.data.some((d) => d.active) && (
              <p className="py-6 text-center text-[13px] text-muted-foreground">Пока ни один ПК не закреплён</p>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Синхронизация с Insight"
            action={
              <Link to="/admin/sync" className="text-[13px] font-medium text-primary hover:underline">
                Подробнее
              </Link>
            }
          />
          <div className="space-y-4 p-5 text-[13px]">
            {s?.last_sync ? (
              <>
                <div className="flex items-center gap-3">
                  {s.last_sync.status === 'success' ? (
                    <CheckCircle2 className="h-9 w-9 text-success" />
                  ) : (
                    <CircleAlert className="h-9 w-9 text-danger" />
                  )}
                  <div>
                    <p className="font-medium">
                      {s.last_sync.status === 'success' ? 'Данные актуальны' : 'Последняя синхронизация с ошибкой'}
                    </p>
                    <p className="text-muted-foreground">{formatRelative(s.last_sync.finished_at ?? s.last_sync.started_at)}</p>
                  </div>
                  <Badge className="ml-auto">{s.last_sync.mode === 'mock' ? 'демо' : 'Insight'}</Badge>
                </div>
                {s.last_sync.error ? (
                  <p className="rounded-lg bg-danger/5 px-3 py-2 text-danger">{s.last_sync.error}</p>
                ) : (
                  <p className="text-muted-foreground">
                    Объектов: {s.last_sync.total} · новых {s.last_sync.created} · изменено {s.last_sync.updated}
                  </p>
                )}
              </>
            ) : (
              <p className="flex items-center gap-2 text-muted-foreground">
                <RefreshCw className="h-4 w-4" /> Синхронизаций ещё не было
              </p>
            )}
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader
          title="Последние события"
          action={
            <Link to="/admin/events" className="text-[13px] font-medium text-primary hover:underline">
              Все логи
            </Link>
          }
        />
        <div className="p-5">{events.data ? <EventTimeline events={events.data.items} /> : <Skeleton className="h-40" />}</div>
      </Card>
    </>
  )
}
