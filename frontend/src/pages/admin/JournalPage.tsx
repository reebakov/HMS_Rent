import { useState } from 'react'
import { ArrowLeftRight, Search } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, QueryError, RowsSkeleton } from '@/components/ui/data-state'
import { Input, Select } from '@/components/ui/input'
import { Badge, TierBadge } from '@/components/ui/badge'
import { useDebouncedSearch } from '@/lib/hooks'
import { useDepartments, useJournal, type JournalFilters } from '@/lib/queries'
import { cn, formatDate, formatDateTime, formatDuration, isOverdue } from '@/lib/utils'

/** Журнал выдачи: все бронирования — кто, что, когда взял и вернул */
export function JournalPage() {
  const departments = useDepartments()
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<JournalFilters>({})
  const journal = useJournal(filters)
  const { data, isFetching } = journal

  const set = (patch: Partial<JournalFilters>) => setFilters((f) => ({ ...f, ...patch }))

  useDebouncedSearch(search, filters.q, (q) => set({ q }))

  return (
    <>
      <PageHeader title="Журнал выдачи" description="Все бронирования и возвраты с датами" />

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" aria-label="Поиск по журналу" placeholder="ПК, имя или ник…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select className="w-40" aria-label="Фильтр по статусу" value={filters.status ?? ''} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">Все</option>
            <option value="active">Активные</option>
            <option value="returned">Возвращённые</option>
          </Select>
          <Select
            className="w-48"
            aria-label="Фильтр по отделу"
            value={filters.department_id ?? ''}
            onChange={(e) => set({ department_id: e.target.value ? Number(e.target.value) : undefined })}
          >
            <option value="">Все отделы</option>
            {departments.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            с
            <Input type="date" className="w-40" aria-label="Дата с" value={filters.date_from ?? ''} onChange={(e) => set({ date_from: e.target.value || undefined })} />
            по
            <Input type="date" className="w-40" aria-label="Дата по" value={filters.date_to ?? ''} onChange={(e) => set({ date_to: e.target.value || undefined })} />
          </div>
          <span className={cn('ml-auto text-[13px] text-muted-foreground', isFetching && 'animate-pulse')}>
            {data ? `${data.length} записей` : ''}
          </span>
        </div>

        <QueryError query={departments} title="Не удалось загрузить отделы" />
        <DataState
          query={journal}
          errorTitle="Не удалось загрузить журнал"
          loading={<RowsSkeleton rows={8} className="h-11" />}
          empty={<EmptyState icon={ArrowLeftRight} title="Записей нет" description="Бронирования появятся здесь сразу после создания" />}
        >
          {(data) => (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[960px] text-left text-[13px]">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">№ заказа</th>
                    <th className="px-4 py-2.5 font-medium">Компьютер</th>
                    <th className="px-4 py-2.5 font-medium">Отдел</th>
                    <th className="px-4 py-2.5 font-medium">Ответственный</th>
                    <th className="px-4 py-2.5 font-medium">Взят</th>
                    <th className="px-4 py-2.5 font-medium">Вернуть до</th>
                    <th className="px-4 py-2.5 font-medium">Возвращён</th>
                    <th className="px-4 py-2.5 font-medium">Длительность</th>
                    <th className="px-4 py-2.5 font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.map((b) => (
                    <tr key={b.id} className="hover:bg-muted/40">
                      <td className="px-4 py-3 tabular text-muted-foreground">№{b.order_number}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{b.computer.name}</span>
                          <TierBadge tier={b.computer.tier} />
                        </div>
                      </td>
                      <td className="px-4 py-3 font-medium">{b.department.name}</td>
                      <td className="px-4 py-3">
                        {b.requester_name}
                        <span className="block text-xs text-muted-foreground">
                          {b.requester_nick} · аккаунт {b.user.username}
                        </span>
                      </td>
                      <td className="px-4 py-3 tabular">{formatDateTime(b.booked_at)}</td>
                      <td className={cn('px-4 py-3 tabular', b.status === 'active' && isOverdue(b.expected_return_at) && 'text-danger')}>
                        {b.expected_return_at ? formatDate(b.expected_return_at) : '—'}
                      </td>
                      <td className="px-4 py-3 tabular">
                        {b.returned_at ? formatDateTime(b.returned_at) : '—'}
                        {b.returned_by && b.returned_by.id !== b.user.id && (
                          <span className="block text-xs text-muted-foreground">вернул {b.returned_by.display_name}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDuration(b.booked_at, b.returned_at)}</td>
                      <td className="px-4 py-3">
                        {b.status === 'active' ? <Badge tone="primary" dot>Активна</Badge> : <Badge>Закрыта</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </Card>
    </>
  )
}
