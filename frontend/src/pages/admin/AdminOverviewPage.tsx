import { Link } from 'react-router-dom'
import { CheckCircle2, CircleAlert, RefreshCw } from 'lucide-react'
import { Card, CardHeader, PageHeader, Skeleton } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DataState } from '@/components/ui/data-state'
import { ClusterCapacityCard } from '@/features/admin/ClusterCapacityCard'
import { IdleServersCard } from '@/features/admin/IdleServersCard'
import { BarList, EventTimeline, StatCard } from '@/features/admin/widgets'
import { useDepartmentUsage, useEvents, useStats } from '@/lib/queries'
import { TIERS } from '@/lib/dictionaries'
import { formatRelative } from '@/lib/utils'

export function AdminOverviewPage() {
  const stats = useStats()
  const departments = useDepartmentUsage()
  const events = useEvents({ limit: 10, offset: 0 })

  return (
    <>
      <PageHeader title="Обзор парка" description="Сводка по всем компьютерам, бронированиям и синхронизации с Insight" />

      <DataState
        query={stats}
        errorTitle="Не удалось загрузить сводку"
        errorCardClass=""
        loading={
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-[116px] rounded-xl" />
            ))}
          </div>
        }
      >
        {(s) => (
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
      </DataState>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader title="По категориям" description="Занято / всего" />
          <div className="p-5">
            <DataState query={stats} errorTitle="Не удалось загрузить сводку" loading={<Skeleton className="h-40" />}>
              {(s) => (
                <BarList
                  items={s.by_tier.map((t) => ({
                    label: TIERS[t.tier].label,
                    value: t.booked,
                    hint: `${t.booked} из ${t.total} · свободно ${t.available}`,
                  }))}
                />
              )}
            </DataState>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Отделы"
            description="Сколько компьютеров закреплено"
            action={
              <Link to="/admin/people?tab=departments" className="text-[13px] font-medium text-primary hover:underline">
                Все
              </Link>
            }
          />
          <div className="p-5">
            <DataState query={departments} errorTitle="Не удалось загрузить отделы" loading={<Skeleton className="h-40" />}>
              {(data) =>
                data.some((d) => d.active) ? (
                  <BarList
                    items={data
                      .filter((d) => d.active > 0)
                      .slice(0, 7)
                      .map((d) => ({ label: d.name, value: d.active }))}
                  />
                ) : (
                  <p className="py-6 text-center text-[13px] text-muted-foreground">Пока ни один ПК не закреплён</p>
                )
              }
            </DataState>
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
            <DataState query={stats} errorTitle="Не удалось загрузить сводку" loading={<Skeleton className="h-20" />}>
              {({ last_sync }) =>
                last_sync ? (
                  <>
                    <div className="flex items-center gap-3">
                      {last_sync.status === 'success' ? (
                        <CheckCircle2 className="h-9 w-9 text-success" />
                      ) : (
                        <CircleAlert className="h-9 w-9 text-danger" />
                      )}
                      <div>
                        <p className="font-medium">
                          {last_sync.status === 'success' ? 'Данные актуальны' : 'Последняя синхронизация с ошибкой'}
                        </p>
                        <p className="text-muted-foreground">{formatRelative(last_sync.finished_at ?? last_sync.started_at)}</p>
                      </div>
                      <Badge className="ml-auto">{last_sync.mode === 'mock' ? 'демо' : 'Insight'}</Badge>
                    </div>
                    {last_sync.error ? (
                      <p className="rounded-lg bg-danger/5 px-3 py-2 text-danger">{last_sync.error}</p>
                    ) : (
                      <p className="text-muted-foreground">
                        Объектов: {last_sync.total} · новых {last_sync.created} · изменено {last_sync.updated}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="flex items-center gap-2 text-muted-foreground">
                    <RefreshCw className="h-4 w-4" /> Синхронизаций ещё не было
                  </p>
                )
              }
            </DataState>
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <IdleServersCard />
        <ClusterCapacityCard />
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
        <div className="p-5">
          <DataState query={events} errorTitle="Не удалось загрузить события" loading={<Skeleton className="h-40" />}>
            {(data) => <EventTimeline events={data.items} />}
          </DataState>
        </div>
      </Card>
    </>
  )
}
