import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Skeleton } from '@/components/ui/card'
import { DataState } from '@/components/ui/data-state'
import { useIdleServers } from '@/lib/queries'
import { plural } from '@/lib/utils'

const VISIBLE = 10 // сколько самых долго простаивающих видно, пока список не раскрыт

const days = (n: number) => `${n} ${plural(n, ['день', 'дня', 'дней'])}`

/** Свободные ПК опубликованных пулов и сколько они не выдавались: данные для планирования мощностей */
export function IdleServersCard() {
  const idle = useIdleServers()
  const [expanded, setExpanded] = useState(false)
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
                <ul className={expanded ? 'max-h-80 space-y-2 overflow-y-auto pr-1 text-[13px]' : 'space-y-2 text-[13px]'}>
                  {(expanded ? data.items : data.items.slice(0, VISIBLE)).map((s) => (
                    <li key={s.id} className="flex items-baseline justify-between gap-3">
                      <span className="truncate font-medium">{s.name}</span>
                      <span className="tabular text-muted-foreground">{days(s.idle_days)}</span>
                    </li>
                  ))}
                </ul>
                {data.items.length > VISIBLE && (
                  <Button variant="ghost" size="sm" className="mt-3" onClick={() => setExpanded((v) => !v)}>
                    {expanded ? 'Свернуть' : `Показать все ${data.items.length}`}
                  </Button>
                )}
              </>
            )
          }
        </DataState>
      </div>
    </Card>
  )
}
