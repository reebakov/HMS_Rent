import { useState } from 'react'
import { toast } from 'sonner'
import { AlarmClock, Cloud, Mail, Monitor } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { Button, buttonClass } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { useOverdue, useReleaseVm, useReturnBooking } from '@/lib/queries'
import type { OverdueItem } from '@/lib/types'
import { errorMessage, formatDate, plural } from '@/lib/utils'

/** ПК и виртуалки, срок возврата которых прошёл: кто держит, сколько дней просрочки, связаться или забрать */
export function OverduePage() {
  const overdue = useOverdue()
  const returnPc = useReturnBooking()
  const releaseVm = useReleaseVm()
  const [taking, setTaking] = useState<OverdueItem | null>(null)

  const takeBack = async () => {
    if (!taking) return
    const item = taking
    try {
      if (item.kind === 'pc') await returnPc.mutateAsync({ id: item.id, comment: 'Возврат администратором: просрочка' })
      else await releaseVm.mutateAsync(item.id)
      toast.success(item.kind === 'pc' ? `${item.name} возвращён` : `${item.name} будет удалена`)
      setTaking(null)
    } catch (e) {
      toast.error(errorMessage(e))
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
            <DataTable
              className="min-w-[900px]"
              head={
                <>
                  <Th>Что</Th>
                  <Th>Команда / арендатор</Th>
                  <Th>Взят</Th>
                  <Th>Вернуть до</Th>
                  <Th>Просрочка</Th>
                  <Th />
                </>
              }
            >
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
                        <Button size="sm" variant="outline" onClick={() => setTaking(item)}>
                          {item.kind === 'pc' ? 'Вернуть' : 'Удалить'}
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </DataTable>
          )}
        </DataState>
      </Card>

      <ConfirmDialog
        open={!!taking}
        onClose={() => setTaking(null)}
        title={taking ? `${taking.kind === 'pc' ? 'Вернуть компьютер' : 'Удалить виртуалку'} ${taking.name} без участия арендатора?` : ''}
        confirmLabel={taking?.kind === 'pc' ? 'Вернуть' : 'Удалить'}
        pending={returnPc.isPending || releaseVm.isPending}
        onConfirm={takeBack}
      />
    </>
  )
}
