import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ChevronLeft, ChevronRight, CircleAlert, Download, Search, X, MapPin } from 'lucide-react'
import { Card, EmptyState, PageHeader, Skeleton } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { StatusBadge, TierBadge } from '@/components/ui/badge'
import { ComputerHistorySheet } from '@/features/admin/ComputerHistorySheet'
import { useAssignPool, useDepartments, useInventory, usePools, type InventoryFilters } from '@/lib/queries'
import { STATUSES, TIERS, TIER_ORDER } from '@/lib/dictionaries'
import { api } from '@/lib/api'
import type { ComputerStatus } from '@/lib/types'
import { cn, formatDate, isOverdue } from '@/lib/utils'

const PAGE = 100

export function InventoryPage() {
  const [params] = useSearchParams()
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<InventoryFilters>({
    issues_only: params.get('issues') === '1' || undefined,
    pool_id: params.get('pool') ?? undefined,
  })
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [targetPool, setTargetPool] = useState('')
  const [openedId, setOpenedId] = useState<number | null>(null)

  const departments = useDepartments()
  const pools = usePools()
  const assign = useAssignPool()
  const { data, isLoading, isFetching } = useInventory({ ...filters, limit: PAGE, offset: page * PAGE })
  const rows = data?.items ?? []
  const total = data?.total ?? 0

  useEffect(() => {
    const timer = setTimeout(() => set({ q: search.trim() || undefined }), 250)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  function set(patch: Partial<InventoryFilters>) {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(0)
    setSelected(new Set())
  }

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const allOnPage = rows.length > 0 && rows.every((r) => selected.has(r.id))
  const toggleAll = () => setSelected(allOnPage ? new Set() : new Set(rows.map((r) => r.id)))

  const moveSelected = async () => {
    try {
      const res = await assign.mutateAsync({
        pool_id: targetPool === 'none' ? null : Number(targetPool),
        computer_ids: [...selected],
      })
      toast.success(targetPool === 'none' ? `Убрано из пулов: ${res.updated}` : `Перемещено в пул: ${res.updated}`)
      setSelected(new Set())
      setTargetPool('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const exportUrl = api.url('/admin/inventory/export', { department_id: filters.department_id, pool_id: filters.pool_id })
  const from = total ? page * PAGE + 1 : 0
  const to = Math.min(total, (page + 1) * PAGE)

  return (
    <>
      <PageHeader
        title="Инвентаризация"
        description="Все компьютеры из Insight: в каком пуле, за каким отделом, кто и когда взял"
        action={
          <Button variant="outline" onClick={() => window.location.assign(exportUrl)}>
            <Download className="h-4 w-4" />
            Выгрузить в Excel (CSV)
          </Button>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b p-4">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" placeholder="Имя, ключ Insight, IP, CPU…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select className="w-44" value={filters.pool_id ?? ''} onChange={(e) => set({ pool_id: e.target.value || undefined })}>
            <option value="">Все пулы</option>
            <option value="none">Без пула (не выдаются)</option>
            {pools.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
          <Select className="w-40" value={filters.status ?? ''} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">Все статусы</option>
            {(Object.keys(STATUSES) as ComputerStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUSES[s].label}
              </option>
            ))}
          </Select>
          <Select className="w-40" value={filters.tier ?? ''} onChange={(e) => set({ tier: e.target.value || undefined })}>
            <option value="">Все категории</option>
            {TIER_ORDER.map((t) => (
              <option key={t} value={t}>
                {TIERS[t].label}
              </option>
            ))}
          </Select>
          <Select
            className="w-44"
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
          <label className="flex cursor-pointer items-center gap-2 text-[13px]">
            <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={!!filters.issues_only} onChange={(e) => set({ issues_only: e.target.checked || undefined })} />
            Только с проблемами
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px]">
            <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={!!filters.include_archived} onChange={(e) => set({ include_archived: e.target.checked || undefined })} />
            Удалённые из Insight
          </label>
        </div>

        {/* Панель массовых действий */}
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-3 border-b bg-primary/5 px-4 py-2.5 text-[13px] animate-fade-in">
            <span className="font-medium">Выбрано: {selected.size}</span>
            <Select className="h-8 w-56" value={targetPool} onChange={(e) => setTargetPool(e.target.value)}>
              <option value="" disabled>
                Переместить в пул…
              </option>
              {pools.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
              <option value="none">— Убрать из пулов</option>
            </Select>
            <Button size="sm" disabled={!targetPool} loading={assign.isPending} onClick={moveSelected}>
              Применить
            </Button>
            <button className="ml-auto flex items-center gap-1 text-muted-foreground hover:text-foreground" onClick={() => setSelected(new Set())}>
              <X className="h-3.5 w-3.5" /> Снять выделение
            </button>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-11" />
            ))}
          </div>
        ) : !rows.length ? (
          <EmptyState icon={Search} title="Ничего не найдено" description="Измените фильтры или строку поиска" />
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[1100px] text-left text-[13px]">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="w-10 px-4 py-2.5">
                    <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={allOnPage} onChange={toggleAll} />
                  </th>
                  <th className="px-3 py-2.5 font-medium">Компьютер</th>
                  <th className="px-3 py-2.5 font-medium">Пул</th>
                  <th className="px-3 py-2.5 font-medium">Категория</th>
                  <th className="px-3 py-2.5 font-medium">Характеристики</th>
                  <th className="px-3 py-2.5 font-medium">Статус</th>
                  <th className="px-3 py-2.5 font-medium">В Insight</th>
                  <th className="px-3 py-2.5 font-medium">Отдел / ответственный</th>
                  <th className="px-3 py-2.5 font-medium">С даты</th>
                  <th className="w-8 px-3 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => setOpenedId(c.id)}
                    className={cn(
                      'cursor-pointer transition-colors hover:bg-muted/40',
                      selected.has(c.id) && 'bg-primary/5',
                      c.is_archived && 'opacity-60',
                    )}
                  >
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={selected.has(c.id)} onChange={() => toggle(c.id)} />
                    </td>
                    <td className="px-3 py-3">
                      <p className="font-semibold">{c.name}</p>
                      <p className="font-mono text-xs text-muted-foreground">{c.insight_key}</p>
                      {c.location && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                          <MapPin className="h-3 w-3" />
                          {c.location}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {c.pool ? (
                        <span className={cn('font-medium', !c.pool.is_published && 'text-muted-foreground')}>{c.pool.name}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <TierBadge tier={c.tier} />
                    </td>
                    <td className="max-w-[260px] px-3 py-3">
                      <p className="truncate">{c.cpu ?? '—'}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {[c.ram_gb && `${c.ram_gb} ГБ`, c.storage, c.gpu].filter(Boolean).join(' · ')}
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="px-3 py-3 text-muted-foreground">{c.insight_status ?? '—'}</td>
                    <td className="px-3 py-3">
                      {c.booking && c.department ? (
                        <>
                          <p className="font-medium">{c.department.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {c.booking.requester_name} ({c.booking.requester_nick})
                          </p>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 tabular">
                      {c.booking ? (
                        <>
                          <p>{formatDate(c.booking.booked_at)}</p>
                          {c.booking.expected_return_at && (
                            <p className={cn('text-xs', isOverdue(c.booking.expected_return_at) ? 'text-danger' : 'text-muted-foreground')}>
                              до {formatDate(c.booking.expected_return_at)}
                            </p>
                          )}
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {c.issues.length > 0 && (
                        <span title={c.issues.join('\n')}>
                          <CircleAlert className="h-4 w-4 text-danger" />
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between border-t px-4 py-3 text-[13px] text-muted-foreground">
          <span className={cn(isFetching && 'animate-pulse')}>
            {total ? `${from}–${to} из ${total.toLocaleString('ru-RU')}` : ''}
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button size="sm" variant="outline" disabled={to >= total} onClick={() => setPage((p) => p + 1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </Card>

      <ComputerHistorySheet computerId={openedId} onClose={() => setOpenedId(null)} />
    </>
  )
}
