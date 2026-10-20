import { useState } from 'react'
import { toast } from 'sonner'
import { AlarmClock, CalendarCheck, CalendarPlus, Check, Cloud, Mail, Monitor } from 'lucide-react'
import { Card, CardHeader, EmptyState, PageHeader } from '@/components/ui/card'
import { Button, buttonClass } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { TermRequests } from '@/features/admin/TermRequests'
import { ExtendDialog, type ExtendTarget } from '@/features/booking/BookingDialog'
import { useAckExtension, useExtensions, useOverdue, useReleaseVm, useReturnBooking } from '@/lib/queries'
import type { ExtensionOut, OverdueItem } from '@/lib/types'
import { cn, errorMessage, formatDate, formatDateTime, plural } from '@/lib/utils'

/** Сроки аренды: просрочки (связаться, продлить или забрать) и продления, которые админ отмечает «Принято» */
export function OverduePage() {
  const overdue = useOverdue()
  const returnPc = useReturnBooking()
  const releaseVm = useReleaseVm()
  const [taking, setTaking] = useState<OverdueItem | null>(null)
  const [extending, setExtending] = useState<ExtendTarget | null>(null)

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
        title="Сроки аренды"
        description="Просрочки, заявки на срок дольше 3 месяцев и продления аренды. Раз в день сводка просрочек уходит в Mattermost"
      />
      <Card>
        <CardHeader title="Просрочки" description="Компьютеры и виртуалки, которые должны были вернуть, но не вернули" />
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
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setExtending({ kind: item.kind, id: item.id, name: item.name, due: item.due })}
                        >
                          <CalendarPlus className="h-3.5 w-3.5" />
                          Продлить
                        </Button>
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

      <TermRequests />

      <Extensions />

      <ExtendDialog target={extending} onClose={() => setExtending(null)} />
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

/** Продления: новые подсвечены, пока админ не нажмёт «Принято»; принятые видны ещё две недели */
function Extensions() {
  const extensions = useExtensions()
  const ack = useAckExtension()

  const accept = async (ext: ExtensionOut) => {
    try {
      await ack.mutateAsync(ext.id)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <Card className="mt-6">
      <CardHeader title="Продления" description="Новые продления ждут отметки «Принято». Принятые видны ещё 14 дней" />
      <DataState
        query={extensions}
        errorTitle="Не удалось загрузить продления"
        loading={<RowsSkeleton rows={3} />}
        empty={<EmptyState icon={CalendarCheck} title="Продлений нет" description="Никто не продлевал аренду за последние две недели" />}
      >
        {(data) => (
          <DataTable
            className="min-w-[900px]"
            head={
              <>
                <Th>Что</Th>
                <Th>Команда / арендатор</Th>
                <Th>Срок</Th>
                <Th>Причина</Th>
                <Th>Кто продлил</Th>
                <Th />
              </>
            }
          >
            {data.map((ext) => {
              const order = ext.booking ?? ext.vm // у продления ПК заполнен booking, у ВМ — vm
              if (!order) return null
              const isNew = !ext.acknowledged_at
              return (
                <tr key={ext.id} className={cn('hover:bg-muted/40', isNew && 'bg-primary/5')}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{ext.name}</span>
                      {isNew && <Badge tone="primary">Новое</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {ext.kind === 'vm' && 'ВМ · '}заказ №{order.order_number}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium">{order.department.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {order.requester_name} ({order.requester_nick})
                    </p>
                  </td>
                  <td className="px-4 py-3 tabular">
                    {ext.old_return_at ? `${formatDate(ext.old_return_at)} → ` : 'до '}
                    <span className="font-medium">{formatDate(ext.new_return_at)}</span>
                  </td>
                  <td className="max-w-[240px] px-4 py-3">{ext.comment ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className="px-4 py-3">
                    <p>{ext.user.display_name}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(ext.created_at)}</p>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {isNew ? (
                      <Button
                        size="sm"
                        variant="outline"
                        loading={ack.isPending && ack.variables === ext.id}
                        onClick={() => accept(ext)}
                      >
                        <Check className="h-3.5 w-3.5" />
                        Принято
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        Принято{ext.acknowledged_by ? ` · ${ext.acknowledged_by.display_name}` : ''}
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </DataTable>
        )}
      </DataState>
    </Card>
  )
}
