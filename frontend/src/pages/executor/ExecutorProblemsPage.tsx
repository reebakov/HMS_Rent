import { Link } from 'react-router-dom'
import { ExternalLink, LifeBuoy } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { isOpenProblem } from '@/lib/dictionaries'
import { useExecutorProblems } from '@/lib/queries'
import { formatDateTime, plural } from '@/lib/utils'

/** Проблемы по заказам: о чём заказчики сообщили через «Сообщить о проблеме»; работа идёт в задаче Jira */
export function ExecutorProblemsPage() {
  const problems = useExecutorProblems()
  const open = problems.data?.filter(isOpenProblem).length ?? 0

  return (
    <>
      <PageHeader
        title="Проблемы по заказам"
        description={
          problems.data
            ? open
              ? `Открыто: ${open} ${plural(open, ['проблема', 'проблемы', 'проблем'])}`
              : 'Открытых проблем нет'
            : 'Заказчики сообщают о проблемах с ПК и ВМ, задачи приходят из Jira'
        }
      />
      <Card>
        <DataState
          query={problems}
          errorTitle="Не удалось загрузить проблемы"
          loading={<RowsSkeleton rows={5} className="h-12" />}
          empty={<EmptyState icon={LifeBuoy} title="Проблем нет" description="Сообщения заказчиков появятся здесь автоматически" />}
        >
          {(data) => (
            <DataTable
              className="min-w-[1000px]"
              head={
                <>
                  <Th>Задача</Th>
                  <Th>ПК или ВМ</Th>
                  <Th>Команда и заказчик</Th>
                  <Th>Проблема</Th>
                  <Th>Создана</Th>
                  <Th>Статус</Th>
                </>
              }
            >
              {data.map((p) => (
                <tr key={p.id} className="align-top hover:bg-muted/40">
                  <td className="px-4 py-3">
                    {p.issue_key && p.issue_url ? (
                      <a href={p.issue_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                        {p.issue_key}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : (
                      <span className="text-xs text-danger" title={p.error ?? undefined}>
                        Заявка в Jira не создана
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {p.booking_id ? (
                      <Link to={`/executor/orders/${p.booking_id}`} className="font-semibold text-primary hover:underline">
                        {p.target_name}
                      </Link>
                    ) : (
                      <span className="font-semibold">{p.target_name}</span>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {p.is_vm ? 'ВМ' : 'ПК'} · заказ №{p.order_number}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium">{p.department.name}</p>
                    <p className="text-xs text-muted-foreground">{p.reporter.display_name}</p>
                  </td>
                  <td className="max-w-md whitespace-pre-line px-4 py-3">{p.message}</td>
                  <td className="px-4 py-3 tabular">{formatDateTime(p.created_at)}</td>
                  <td className="px-4 py-3">
                    {p.error ? <Badge tone="danger">Не создана</Badge> : <Badge tone={isOpenProblem(p) ? 'warning' : 'success'}>{p.status ?? '…'}</Badge>}
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
