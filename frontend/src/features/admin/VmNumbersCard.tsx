import { Card, CardHeader, Skeleton } from '@/components/ui/card'
import { DataState } from '@/components/ui/data-state'
import { useVmNumbers } from '@/lib/queries'
import { cn, plural } from '@/lib/utils'

/** Сколько номеров ВМ (объектов Insight «На складе») осталось: когда их нет, конструктор отклоняет заказы ВМ */
export function VmNumbersCard() {
  const numbers = useVmNumbers()
  return (
    <Card>
      <CardHeader title="Номера ВМ" description="Свободные объекты Insight для имён виртуалок" />
      <div className="p-5">
        <DataState query={numbers} errorTitle="Не удалось загрузить номера ВМ" loading={<Skeleton className="h-24" />}>
          {(n) =>
            n.ok ? (
              <div className="space-y-2 text-[13px]">
                <p className={cn('text-3xl font-semibold tabular', n.low && 'text-warning', n.free === 0 && 'text-danger')}>
                  {n.free}
                </p>
                <p className="text-muted-foreground">
                  {n.free} {plural(n.free, ['свободный номер', 'свободных номера', 'свободных номеров'])}
                </p>
                {n.low && (
                  <p className={n.free === 0 ? 'text-danger' : 'text-warning'}>
                    {n.free === 0
                      ? 'Номеров нет: заказы ВМ отклоняются. Заведите в Insight объекты Virtual со статусом «На складе».'
                      : 'Номера заканчиваются: когда их не останется, заказы ВМ будут отклоняться.'}
                  </p>
                )}
              </div>
            ) : (
              <p className="py-6 text-center text-[13px] text-muted-foreground">{n.error}</p>
            )
          }
        </DataState>
      </div>
    </Card>
  )
}
