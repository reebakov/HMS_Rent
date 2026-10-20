import { Card, CardHeader, Skeleton } from '@/components/ui/card'
import { DataState } from '@/components/ui/data-state'
import { useIdleServers } from '@/lib/queries'
import { plural } from '@/lib/utils'

const days = (n: number) => `${n} ${plural(n, ['день', 'дня', 'дней'])}`

/** Свободные ПК опубликованных пулов и сколько они не выдавались: данные для планирования мощностей */
export function IdleServersCard() {
  const idle = useIdleServers()
  return (
    <Card>
      <CardHeader title="Простой серверов" description="Свободные ПК в пулах выдачи: сколько не выдавались" />
      <div className="p-5">
        <DataState query={idle} errorTitle="Не удалось загрузить простой серверов" loading={<Skeleton className="h-40" />}>
          {(data) =>
            data.count === 0 ? (
              <p className="py-6 text-center text-[13px] text-muted-foreground">Свободных серверов в пулах нет</p>
            ) : (
              <>
                <p className="mb-3 text-[13px] text-muted-foreground">
                  Свободно: {data.count} · в среднем без выдачи {days(data.average_days)}
                </p>
                <ul className="space-y-2 text-[13px]">
                  {data.items.map((s) => (
                    <li key={s.id} className="flex items-baseline justify-between gap-3">
                      <span className="truncate font-medium">{s.name}</span>
                      <span className="tabular text-muted-foreground">{days(s.idle_days)}</span>
                    </li>
                  ))}
                </ul>
              </>
            )
          }
        </DataState>
      </div>
    </Card>
  )
}
