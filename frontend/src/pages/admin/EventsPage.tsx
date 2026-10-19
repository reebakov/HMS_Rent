import { useState } from 'react'
import { Activity, Search } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Input, Select } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { useDebouncedSearch } from '@/lib/hooks'
import { useEvents, type EventFilters } from '@/lib/queries'
import { EVENT_LABELS } from '@/lib/dictionaries'
import { formatDateTime } from '@/lib/utils'

const PAGE = 100

export function EventsPage() {
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<EventFilters>({})
  const [page, setPage] = useState(0)

  const events = useEvents({ ...filters, limit: PAGE, offset: page * PAGE })
  const { data, isFetching } = events
  const rows = data?.items ?? []
  const total = data?.total ?? 0

  const set = (patch: Partial<EventFilters>) => {
    setFilters(f => ({ ...f, ...patch }))
    setPage(0)
  }

  useDebouncedSearch(search, filters.q, (q) => set({ q }))

  return (
    <>
      <PageHeader title="Логи системы" description="История всех системных событий, статусов и ручных правок" />

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" aria-label="Поиск по логам" placeholder="ПК, текст события..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select className="w-56" aria-label="Тип события" value={filters.event_type ?? ''} onChange={(e) => set({ event_type: e.target.value || undefined })}>
            <option value="">Все типы событий</option>
            {Object.entries(EVENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            с <Input type="date" className="w-40" aria-label="Дата с" value={filters.date_from ?? ''} onChange={(e) => set({ date_from: e.target.value || undefined })} />
            по <Input type="date" className="w-40" aria-label="Дата по" value={filters.date_to ?? ''} onChange={(e) => set({ date_to: e.target.value || undefined })} />
          </div>
        </div>

        <DataState
          query={events}
          errorTitle="Не удалось загрузить события"
          loading={<RowsSkeleton rows={8} className="h-11" />}
          empty={<EmptyState icon={Activity} title="Событий не найдено" description="Измените фильтры" />}
          isEmpty={(d) => !d.items.length}
        >
          {() => (
            <DataTable
              className="min-w-[960px]"
              head={
                <>
                  <Th>Дата и время</Th>
                  <Th>Компьютер</Th>
                  <Th>Тип события</Th>
                  <Th>Сообщение / Статусы</Th>
                  <Th>Кто сделал</Th>
                </>
              }
            >
              {rows.map((e) => (
                <tr key={e.id} className="hover:bg-muted/40">
                  <td className="px-4 py-3 tabular whitespace-nowrap text-muted-foreground">{formatDateTime(e.created_at)}</td>
                  <td className="px-4 py-3 font-semibold">{e.computer.name}</td>
                  <td className="px-4 py-3 font-medium">{EVENT_LABELS[e.event_type] ?? e.event_type}</td>
                  <td className="px-4 py-3">
                    <p>{e.message}</p>
                    {(e.from_status || e.to_status) && (
                      <p className="mt-0.5 text-xs text-muted-foreground font-mono">
                        [{e.from_status || '—'} ➔ {e.to_status || '—'}]
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{e.actor?.display_name || 'Система'}</td>
                </tr>
              ))}
            </DataTable>
          )}
        </DataState>

        {data && <Pagination page={page} pageSize={PAGE} total={total} fetching={isFetching} onChange={setPage} />}
      </Card>
    </>
  )
}