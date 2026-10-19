import { useState } from 'react'
import { toast } from 'sonner'
import { SyncRunDialog, type DetailsTab } from '@/features/admin/SyncRunDialog'
import { RefreshCw } from 'lucide-react'
import { Card, CardHeader, PageHeader, Skeleton } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { DataState } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { useRunSync, useSyncInfo } from '@/lib/queries'
import type { SyncInfo } from '@/lib/types'
import { errorMessage, formatDateTime } from '@/lib/utils'

export function SyncPage() {
  const info = useSyncInfo()
  const sync = useRunSync()
  const [opened, setOpened] = useState<{ id: number; tab: DetailsTab } | null>(null)
  // число > 0 — кнопка: по клику видно, что именно поменялось
  const count = (id: number, tab: DetailsTab, value: number) =>
    value > 0 ? (
      <button className="font-medium text-primary underline-offset-2 hover:underline" onClick={() => setOpened({ id, tab })}>
        {value}
      </button>
    ) : (
      value
    )

  const runNow = async () => {
    try {
      const run = await sync.mutateAsync()
      if (run.status === 'success') toast.success(`Готово: ${run.total} объектов, новых ${run.created}, изменено ${run.updated}`)
      else toast.error(run.error ?? 'Синхронизация завершилась с ошибкой')
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  // пока данных нет, на месте значений скелетоны
  const infoCards = (data?: SyncInfo) => (
    <div className="grid gap-4 md:grid-cols-4">
      {[
        ['Источник', data ? (data.mode === 'mock' ? 'Демо-данные (mock)' : 'Jira Insight') : null],
        ['Jira', data?.jira_url],
        ['Интервал', data ? `каждые ${Math.round(data.interval_sec / 60)} мин` : null],
        ['Запись в Insight', data ? (data.writeback ? 'Включена' : 'Выключена') : null],
      ].map(([label, value]) => (
        <Card key={label} className="p-5">
          <p className="text-[13px] text-muted-foreground">{label}</p>
          {value ? <p className="mt-1.5 truncate font-semibold">{value}</p> : <Skeleton className="mt-2 h-5 w-24" />}
        </Card>
      ))}
    </div>
  )

  return (
    <>
      <PageHeader
        title="Синхронизация с Insight"
        description="Портал регулярно забирает из Insight список компьютеров, характеристики и статусы"
        action={
          <Button onClick={runNow} loading={sync.isPending}>
            {!sync.isPending && <RefreshCw className="h-4 w-4" />}
            Синхронизировать сейчас
          </Button>
        }
      />

      <DataState
        query={info}
        errorTitle="Не удалось загрузить данные синхронизации"
        errorCardClass=""
        loading={infoCards()}
      >
        {(data) => (
          <>
            {infoCards(data)}

            <Card className="mt-6">
              <CardHeader title="Последние запуски" />
              <DataTable
                className="min-w-[760px]"
                head={
                  <>
                    <Th>Начало</Th>
                    <Th>Результат</Th>
                    <Th right>Объектов</Th>
                    <Th right>Новых</Th>
                    <Th right>Изменено</Th>
                    <Th right>В архив</Th>
                    <Th>Ошибка</Th>
                  </>
                }
              >
                {data.runs.map((r) => (
                  <tr key={r.id}>
                    <td className="px-4 py-3 tabular">{formatDateTime(r.started_at)}</td>
                    <td className="px-4 py-3">
                      {r.status === 'success' ? <Badge tone="success" dot>Успешно</Badge> : <Badge tone="danger" dot>Ошибка</Badge>}
                    </td>
                    <td className="px-4 py-3 text-right tabular">{r.total}</td>
                    <td className="px-4 py-3 text-right tabular">{count(r.id, 'created', r.created)}</td>
                    <td className="px-4 py-3 text-right tabular">{count(r.id, 'updated', r.updated)}</td>
                    <td className="px-4 py-3 text-right tabular">{count(r.id, 'archived', r.archived)}</td>
                    <td className="max-w-[320px] truncate px-4 py-3 text-danger" title={r.error ?? undefined}>
                      {r.error ?? ''}
                    </td>
                  </tr>
                ))}
              </DataTable>
            </Card>
          </>
        )}
      </DataState>
      <SyncRunDialog runId={opened?.id ?? null} tab={opened?.tab ?? 'updated'} onClose={() => setOpened(null)} />
    </>
  )
}
