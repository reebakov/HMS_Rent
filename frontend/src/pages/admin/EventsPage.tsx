import { useEffect, useState } from 'react'
import { Activity, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Search } from 'lucide-react'
import { Card, EmptyState, PageHeader, Skeleton } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useEvents, type EventFilters } from '@/lib/queries'
import { EVENT_LABELS } from '@/lib/dictionaries'
import { cn, formatDateTime } from '@/lib/utils'

const PAGE = 100

export function EventsPage() {
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<EventFilters>({})
  const [page, setPage] = useState(0)

  const { data, isLoading, isFetching } = useEvents({ ...filters, limit: PAGE, offset: page * PAGE })
  const rows = data?.items ?? []
  const total = data?.total ?? 0

  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters(f => ({ ...f, q: search.trim() || undefined }))
      setPage(0)
    }, 250)
    return () => clearTimeout(timer)
  }, [search])

  const set = (patch: Partial<EventFilters>) => {
    setFilters(f => ({ ...f, ...patch }))
    setPage(0)
  }

  const from = total ? page * PAGE + 1 : 0
  const to = Math.min(total, (page + 1) * PAGE)

  return (
    <>
      <PageHeader title="Логи системы" description="История всех системных событий, статусов и ручных правок" />

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" placeholder="ПК, текст события..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select className="w-56" value={filters.event_type ?? ''} onChange={(e) => set({ event_type: e.target.value || undefined })}>
            <option value="">Все типы событий</option>
            {Object.entries(EVENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            с <Input type="date" className="w-40" value={filters.date_from ?? ''} onChange={(e) => set({ date_from: e.target.value || undefined })} />
            по <Input type="date" className="w-40" value={filters.date_to ?? ''} onChange={(e) => set({ date_to: e.target.value || undefined })} />
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-11" />)}
          </div>
        ) : !rows.length ? (
          <EmptyState icon={Activity} title="Событий не найдено" description="Измените фильтры" />
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-[13px]">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Дата и время</th>
                  <th className="px-4 py-2.5 font-medium">Компьютер</th>
                  <th className="px-4 py-2.5 font-medium">Тип события</th>
                  <th className="px-4 py-2.5 font-medium">Сообщение / Статусы</th>
                  <th className="px-4 py-2.5 font-medium">Кто сделал</th>
                </tr>
              </thead>
              <tbody className="divide-y">
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
              </tbody>
            </table>
          </div>
        )}

        {/* Пагинация */}
        <div className="flex items-center justify-between border-t px-4 py-3 text-[13px] text-muted-foreground">
          <span className={cn(isFetching && 'animate-pulse')}>{total ? `${from}–${to} из ${total.toLocaleString()}` : '0 записей'}</span>
          {total > 0 && (() => {
            const totalPages = Math.ceil(total / PAGE)
            return (
              <div className="flex items-center gap-1">
                <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(0)}><ChevronsLeft className="h-4 w-4" /></Button>
                <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(p => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
                <span className="px-2 hidden sm:block">Стр. {page + 1} из {totalPages}</span>
                <Button size="sm" variant="outline" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
                <Button size="sm" variant="outline" disabled={page >= totalPages - 1} onClick={() => setPage(totalPages - 1)}><ChevronsRight className="h-4 w-4" /></Button>
              </div>
            )
          })()}
        </div>
      </Card>
    </>
  )
}