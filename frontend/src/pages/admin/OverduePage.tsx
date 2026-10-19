import { toast } from 'sonner'
import { AlarmClock, Cloud, Mail, Monitor } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { Button, buttonClass } from '@/components/ui/button'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { Badge } from '@/components/ui/badge'
import { useOverdue, useReleaseVm, useReturnBooking } from '@/lib/queries'
import type { OverdueItem } from '@/lib/types'
import { formatDate, plural } from '@/lib/utils'

/** ПК и виртуалки, срок возврата которых прошёл: кто держит, сколько дней просрочки, связаться или забрать */
export function OverduePage() {
  const overdue = useOverdue()
  const returnPc = useReturnBooking()
  const releaseVm = useReleaseVm()

  const takeBack = async (item: OverdueItem) => {
    const what = item.kind === 'pc' ? 'Вернуть компьютер' : 'Удалить виртуалку'
    if (!window.confirm(`${what} ${item.name} без участия арендатора?`)) return
    try {
      if (item.kind === 'pc') await returnPc.mutateAsync({ id: item.id, comment: 'Возврат администратором: просрочка' })
      else await releaseVm.mutateAsync(item.id)
      toast.success(item.kind === 'pc' ? `${item.name} возвращён` : `${item.name} будет удалена`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const mailto = (item: OverdueItem) =>
    `mailto:${item.email}?subject=${encodeURIComponent(`HMS Rent: просрочен возврат ${item.name} (заказ №${item.order_number})`)}` +
    `&body=${encodeURIComponent(`Здравствуйте! Срок аренды ${item.name} истёк ${formatDate(item.due)}. Подскажите, когда вернёте или продлеваем?`)}`

  return (
    <>
      <PageHeader
        title="Просрочки"
        description="Компьютеры и виртуалки, которые должны были вернуть, но не вернули. Раз в день сводка уходит в Mattermost"
      />
      <Card>
        <DataState
          query={overdue}
          errorTitle="Не удалось загрузить просрочки"
          loading={<RowsSkeleton rows={4} />}
          empty={<EmptyState icon={AlarmClock} title="Просрочек нет" description="Все вернули технику вовремя" />}
        >
          {(data) => (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-[13px]">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Что</th>
                    <th className="px-4 py-2.5 font-medium">Команда / арендатор</th>
                    <th className="px-4 py-2.5 font-medium">Взят</th>
                    <th className="px-4 py-2.5 font-medium">Вернуть до</th>
                    <th className="px-4 py-2.5 font-medium">Просрочка</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.map((item) => {
                    const Icon = item.kind === 'pc' ? Monitor : Cloud
                    return (
                      <tr key={`${item.kind}-${item.id}`} className="hover:bg-muted/40">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Icon className="h-4 w-4 text-muted-foreground" />
                            <span className="font-semibold">{item.name}</span>
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {item.kind === 'pc' ? 'Компьютер' : 'Виртуалка'}
                            {item.order_number ? ` · заказ №${item.order_number}` : ''}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <p className="font-medium">{item.department}</p>
                          <p className="text-xs text-muted-foreground">
                            {item.requester_name} ({item.requester_nick}){item.email ? ` · ${item.email}` : ''}
                          </p>
                        </td>
                        <td className="px-4 py-3 tabular">{formatDate(item.taken_at)}</td>
                        <td className="px-4 py-3 tabular text-danger">{formatDate(item.due)}</td>
                        <td className="px-4 py-3">
                          <Badge tone={item.days > 7 ? 'danger' : 'warning'} dot>
                            {item.days} {plural(item.days, ['день', 'дня', 'дней'])}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-1">
                            {item.email && (
                              <a href={mailto(item)} className={buttonClass({ variant: 'ghost', size: 'sm' })}>
                                <Mail className="h-3.5 w-3.5" />
                                Написать
                              </a>
                            )}
                            <Button size="sm" variant="outline" onClick={() => takeBack(item)}>
                              {item.kind === 'pc' ? 'Вернуть' : 'Удалить'}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </Card>
    </>
  )
}
