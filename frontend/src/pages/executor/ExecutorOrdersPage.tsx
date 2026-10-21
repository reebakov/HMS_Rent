import { Link } from 'react-router-dom'
import { Wrench } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { useExecutorOrders } from '@/lib/queries'
import { computerSpecs, formatDate, formatDateTime, plural } from '@/lib/utils'

/** Очередь исполнителя: выданные ПК, которые нужно подготовить, и уже подготовленные */
export function ExecutorOrdersPage() {
  const orders = useExecutorOrders()
  const waiting = orders.data?.filter((o) => !o.prepared_at).length ?? 0

  return (
    <>
      <PageHeader
        title="Заказы на подготовку"
        description={
          orders.data
            ? waiting
              ? `Ждут подготовки: ${waiting} ${plural(waiting, ['заказ', 'заказа', 'заказов'])}`
              : 'Все выданные ПК подготовлены'
            : 'Выданные ПК: установите ОС, настройте и внесите данные для подключения'
        }
      />
      <Card>
        <DataState
          query={orders}
          errorTitle="Не удалось загрузить заказы"
          loading={<RowsSkeleton rows={5} className="h-12" />}
          empty={<EmptyState icon={Wrench} title="Выданных ПК нет" description="Новые брони появятся здесь автоматически" />}
        >
          {(data) => (
            <DataTable
              className="min-w-[900px]"
              head={
                <>
                  <Th>№ заказа</Th>
                  <Th>ПК</Th>
                  <Th>ОС</Th>
                  <Th>Команда и заказчик</Th>
                  <Th>Взят</Th>
                  <Th>Вернуть до</Th>
                  <Th>Подготовка</Th>
                </>
              }
            >
              {data.map((o) => (
                <tr key={o.id} className="hover:bg-muted/40">
                  <td className="px-4 py-3 tabular text-muted-foreground">№{o.order_number}</td>
                  <td className="px-4 py-3">
                    <Link to={`/executor/orders/${o.id}`} className="font-semibold text-primary hover:underline">
                      {o.computer.name}
                    </Link>
                    <p className="text-xs text-muted-foreground">{computerSpecs(o.computer)}</p>
                  </td>
                  <td className="px-4 py-3">{o.os_label ?? '—'}</td>
                  <td className="px-4 py-3">
                    <p className="font-medium">{o.department.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {o.requester_name} ({o.requester_nick})
                    </p>
                  </td>
                  <td className="px-4 py-3 tabular">{formatDateTime(o.booked_at)}</td>
                  <td className="px-4 py-3 tabular">{formatDate(o.expected_return_at)}</td>
                  <td className="px-4 py-3">
                    {o.prepared_at ? <Badge tone="success">Подготовлен</Badge> : <Badge tone="warning" dot>Ждёт подготовки</Badge>}
                  </td>
                </tr>
              ))}
            </DataTable>
          )}
        </DataState>
      </Card>
    </>
  )
}
