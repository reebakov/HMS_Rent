import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, Wrench } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { JiraRequestLink } from '@/features/executor/JiraRequestLink'
import { PreparationBadge } from '@/features/executor/PreparationBadge'
import { DiagnosticsCard } from '@/features/executor/DiagnosticsCard'
import { BuildsCard } from '@/features/executor/BuildsCard'
import { VmChecksCard } from '@/features/executor/VmChecksCard'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { useConfirmCleaned, useExecutorOrders, useExecutorReturns } from '@/lib/queries'
import type { ExecutorOrder } from '@/lib/types'
import { computerSpecs, errorMessage, formatDate, formatDateTime, plural } from '@/lib/utils'

/** Очередь исполнителя: выданные ПК, которые нужно подготовить; подготовленные убраны в «Архив заказов» */
export function ExecutorOrdersPage() {
  const orders = useExecutorOrders()
  const [archiveOpen, setArchiveOpen] = useState(false)
  const waiting = orders.data?.filter((o) => !o.prepared_at) ?? []
  const archive = orders.data?.filter((o) => o.prepared_at) ?? []

  return (
    <>
      <PageHeader
        title="Заказы на подготовку"
        description={
          orders.data
            ? waiting.length
              ? `Ждут подготовки: ${waiting.length} ${plural(waiting.length, ['заказ', 'заказа', 'заказов'])}`
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
          {() =>
            waiting.length ? (
              <OrdersTable rows={waiting} />
            ) : (
              <EmptyState icon={Wrench} title="Нет заказов на подготовку" description="Подготовленные ПК — в архиве заказов ниже" />
            )
          }
        </DataState>
      </Card>
      {archive.length > 0 && (
        <div className="mt-4">
          <Button variant="outline" aria-expanded={archiveOpen} onClick={() => setArchiveOpen((v) => !v)}>
            <Archive className="h-4 w-4" />
            Архив заказов ({archive.length})
          </Button>
          {archiveOpen && (
            <Card className="mt-3">
              <OrdersTable rows={archive} />
            </Card>
          )}
        </div>
      )}
      <BuildsCard />
      <VmChecksCard />
      <ReturnsCard />
      <DiagnosticsCard />
    </>
  )
}

function OrdersTable({ rows }: { rows: ExecutorOrder[] }) {
  return (
    <DataTable
      className="min-w-[1000px]"
      head={
        <>
          <Th>№ заказа</Th>
          <Th>ПК</Th>
          <Th>ОС</Th>
          <Th>Команда и заказчик</Th>
          <Th>Взят</Th>
          <Th>Вернуть до</Th>
          <Th>Подготовка</Th>
          <Th>Заявка в Jira</Th>
        </>
      }
    >
      {rows.map((o) => (
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
            <PreparationBadge order={o} />
          </td>
          <td className="px-4 py-3">
            <JiraRequestLink order={o} />
          </td>
        </tr>
      ))}
    </DataTable>
  )
}

/** Вернувшиеся ПК: заказчик вернул, исполнитель очищает диск и подтверждает, тогда ПК снова свободен */
function ReturnsCard() {
  const returns = useExecutorReturns()
  const confirm = useConfirmCleaned()

  const done = async (o: ExecutorOrder) => {
    try {
      await confirm.mutateAsync(o.id)
      toast.success(`${o.computer.name} очищен и снова свободен`)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <Card className="mt-6">
      <div className="border-b px-5 py-4">
        <p className="font-semibold">Ждут очистки</p>
        <p className="text-[13px] text-muted-foreground">Вернули заказчики: отформатируйте диски и подтвердите, тогда ПК снова появится в каталоге</p>
      </div>
      <DataState
        query={returns}
        errorTitle="Не удалось загрузить возвраты"
        loading={<RowsSkeleton rows={2} className="h-12" />}
        empty={<p className="px-5 py-6 text-[13px] text-muted-foreground">Все вернувшиеся ПК очищены</p>}
      >
        {(data) => (
          <DataTable
            className="min-w-[900px]"
            head={
              <>
                <Th>№ заказа</Th>
                <Th>ПК</Th>
                <Th>Команда и заказчик</Th>
                <Th>Вернули</Th>
                <Th>Заявка в Jira</Th>
                <Th>{''}</Th>
              </>
            }
          >
            {data.map((o) => (
              <tr key={o.id} className="hover:bg-muted/40">
                <td className="px-4 py-3 tabular text-muted-foreground">№{o.order_number}</td>
                <td className="px-4 py-3 font-semibold">{o.computer.name}</td>
                <td className="px-4 py-3">
                  <p className="font-medium">{o.department.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {o.requester_name} ({o.requester_nick})
                  </p>
                  {o.return_comment && <p className="text-xs text-muted-foreground">«{o.return_comment}»</p>}
                </td>
                <td className="px-4 py-3 tabular">{formatDateTime(o.returned_at)}</td>
                <td className="px-4 py-3">
                  <JiraRequestLink order={o} />
                </td>
                <td className="px-4 py-3 text-right">
                  <Button size="sm" variant="outline" loading={confirm.isPending && confirm.variables === o.id} onClick={() => done(o)}>
                    Диск очищен
                  </Button>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </DataState>
    </Card>
  )
}
