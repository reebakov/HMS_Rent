import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { JiraRequestLink } from '@/features/executor/JiraRequestLink'
import { useExecutorDiagnostics, useRepairComputer } from '@/lib/queries'
import type { ExecutorDiagnostic } from '@/lib/types'
import { computerSpecs, errorMessage, formatDateTime } from '@/lib/utils'

/** ПК на диагностике: выведены из пула как неисправные; после ремонта исполнитель возвращает их в прежний пул */
export function DiagnosticsCard() {
  const diagnostics = useExecutorDiagnostics()
  const repair = useRepairComputer()
  const [returning, setReturning] = useState<ExecutorDiagnostic | null>(null)

  const doReturn = async () => {
    if (!returning) return
    try {
      await repair.mutateAsync(returning.id)
      toast.success(`${returning.computer.name} вернулся в ${returning.pool_name ? `пул «${returning.pool_name}»` : 'работу'}`)
      setReturning(null)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <Card className="mt-6">
      <div className="border-b px-5 py-4">
        <p className="font-semibold">ПК на диагностике</p>
        <p className="text-[13px] text-muted-foreground">
          Неисправные ПК выведены из пула. После ремонта верните ПК в прежний пул кнопкой или закройте задачу в Jira
        </p>
      </div>
      <DataState
        query={diagnostics}
        errorTitle="Не удалось загрузить ПК на диагностике"
        loading={<RowsSkeleton rows={2} className="h-12" />}
        empty={<p className="px-5 py-6 text-[13px] text-muted-foreground">Нет ПК на диагностике</p>}
      >
        {(data) => (
          <DataTable
            className="min-w-[900px]"
            head={
              <>
                <Th>ПК</Th>
                <Th>Прежний пул</Th>
                <Th>Что случилось</Th>
                <Th>Выведен</Th>
                <Th>Задача в Jira</Th>
                <Th>{''}</Th>
              </>
            }
          >
            {data.map((d) => (
              <tr key={d.id} className="align-top hover:bg-muted/40">
                <td className="px-4 py-3">
                  <p className="font-semibold">{d.computer.name}</p>
                  <p className="text-xs text-muted-foreground">{computerSpecs(d.computer)}</p>
                </td>
                <td className="px-4 py-3">{d.pool_name ?? <span className="text-xs text-muted-foreground">не известен</span>}</td>
                <td className="max-w-xs px-4 py-3">{d.comment || '—'}</td>
                <td className="px-4 py-3 tabular">{formatDateTime(d.created_at)}</td>
                <td className="px-4 py-3">
                  <JiraRequestLink order={{ request_key: d.issue_key, request_url: d.issue_url, request_status: d.status, request_error: d.error }} />
                </td>
                <td className="px-4 py-3 text-right">
                  <Button size="sm" onClick={() => setReturning(d)}>
                    Вернуть в пул
                  </Button>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </DataState>

      <ConfirmDialog
        open={!!returning}
        onClose={() => setReturning(null)}
        title={returning ? `Вернуть ${returning.computer.name} в пул?` : ''}
        description={
          returning?.pool_name
            ? `ПК вернётся в пул «${returning.pool_name}» и станет свободным, в Insight запишется «Ожидает». Задачу в Jira портал закроет сам.`
            : 'Прежний пул ПК не известен: он станет свободным, но в пул его придётся вернуть вручную. Задачу в Jira портал закроет сам.'
        }
        confirmLabel="Вернуть"
        pending={repair.isPending}
        onConfirm={doReturn}
      />
    </Card>
  )
}
