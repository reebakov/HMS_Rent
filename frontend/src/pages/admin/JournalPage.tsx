import { useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, QueryError, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { DateRange, DepartmentOptions, SearchInput, Select } from '@/components/ui/input'
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
          <SearchInput className="sm:w-64" label="Поиск по журналу" placeholder="ПК, имя или ник…" value={search} onChange={setSearch} />
          <Select className="w-40" aria-label="Фильтр по статусу" value={filters.status ?? ''} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">Все</option>
            <option value="active">Активные</option>
            <option value="returned">Возвращённые</option>
            <option value="cancelled">Отклонённые и отменённые</option>
          </Select>
          <Select
            className="w-48"
            aria-label="Фильтр по отделу"
            value={filters.department_id ?? ''}
            onChange={(e) => set({ department_id: e.target.value ? Number(e.target.value) : undefined })}
          >
            <option value="">Все отделы</option>
            <DepartmentOptions departments={departments.data} />
          </Select>
          <DateRange from={filters.date_from} to={filters.date_to} onChange={set} />
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
            <DataTable
              className="min-w-[960px]"
              head={
                <>
                  <Th>№ заказа</Th>
                  <Th>Компьютер</Th>
                  <Th>Отдел</Th>
                  <Th>Ответственный</Th>
                  <Th>Взят</Th>
                  <Th>Вернуть до</Th>
                  <Th>Возвращён</Th>
                  <Th>Длительность</Th>
                  <Th>Статус</Th>
                </>
              }
            >
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
                    {b.status === 'active' ? <Badge tone="primary" dot>Активна</Badge> : b.status === 'cancelled' ? <Badge tone="danger">{b.returned_by ? 'Отменена' : 'Отклонена'}</Badge> : <Badge>Закрыта</Badge>}
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
