import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search } from 'lucide-react'
import { PageHeader } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import { CategoryCards } from '@/features/catalog/CategoryCards'
import { ComputerList } from '@/features/catalog/ComputerList'
import { ComputerSheet } from '@/features/catalog/ComputerSheet'
import { BookingDialog } from '@/features/booking/BookingDialog'
import { VmBuilderDialog } from '@/features/vms/VmBuilderDialog'
import { ViewToggle, useViewMode } from '@/components/ui/view-toggle'
import { useSession } from '@/auth/AuthProvider'
import { useDebouncedSearch } from '@/lib/hooks'
import { useCatalogSummary, useComputers, type ComputerFilters } from '@/lib/queries'
import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { Computer, Tier } from '@/lib/types'
import { cn, plural } from '@/lib/utils'

const RAM_OPTIONS = [0, 8, 16, 32, 64]
const SORTS: NonNullable<ComputerFilters['sort']>[] = ['name', 'ram_desc', 'ram_asc']

/** Значение из адресной строки, если оно допустимо, иначе значение по умолчанию */
const oneOf = <T extends string>(value: string | null, allowed: readonly T[], fallback: T): T =>
  allowed.find((a) => a === value) ?? fallback

export function CatalogPage() {
  // категория и фильтры живут в адресной строке — ссылкой можно поделиться
  const [params, setParams] = useSearchParams()
  const tier = oneOf<Tier>(params.get('tier'), TIER_ORDER, 'medium')
  const filters: ComputerFilters = {
    tier,
    q: params.get('q') ?? undefined,
    min_ram: Number(params.get('min_ram')) || undefined,
    gpu_only: params.get('gpu') === '1' || undefined,
    sort: oneOf(params.get('sort'), SORTS, 'name'),
  }

  const session = useSession()
  const summary = useCatalogSummary(session.catalog_refresh_sec)
  const computers = useComputers(filters, session.catalog_refresh_sec)
  const [view, setView] = useViewMode('catalog')
  const [vmOpen, setVmOpen] = useState(false)
  const [openedId, setOpenedId] = useState<number | null>(null)
  const [booking, setBooking] = useState<Computer | null>(null)
  const [search, setSearch] = useState(filters.q ?? '')

  const update = (patch: Record<string, string | undefined>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)))
        return next
      },
      { replace: true },
    )

  // поиск с задержкой, чтобы не дёргать API на каждую букву
  useDebouncedSearch(search, filters.q, (q) => update({ q }))

  const count = computers.data?.length ?? 0

  return (
    <>
      <PageHeader
        title="Свободные компьютеры"
        description="Выберите категорию мощности, затем подходящий компьютер или виртуальную машину"
      />

      <CategoryCards query={summary} value={tier} onChange={(t) => update({ tier: t })} onBuildVm={() => setVmOpen(true)} />

      <div className="mb-4 mt-8 flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h2 className="text-lg font-semibold tracking-tight">{TIERS[tier].label}</h2>
          <p className="text-[13px] text-muted-foreground">
            {computers.data
              ? `${count} ${plural(count, ['компьютер', 'компьютера', 'компьютеров'])} доступно`
              : !computers.isError && 'Загружаем…'}
          </p>
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            aria-label="Поиск по каталогу"
            placeholder="Имя, процессор, видеокарта…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select
          className="w-36"
          aria-label="Минимум ОЗУ"
          value={String(filters.min_ram ?? 0)}
          onChange={(e) => update({ min_ram: e.target.value === '0' ? undefined : e.target.value })}
        >
          {RAM_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {r ? `ОЗУ от ${r} ГБ` : 'Любая ОЗУ'}
            </option>
          ))}
        </Select>
        <Select className="w-44" aria-label="Сортировка" value={filters.sort} onChange={(e) => update({ sort: e.target.value })}>
          <option value="name">По имени</option>
          <option value="ram_desc">Сначала мощнее</option>
          <option value="ram_asc">Сначала проще</option>
        </Select>
        {tier !== 'vm' && (
          <button
            onClick={() => update({ gpu: filters.gpu_only ? undefined : '1' })}
            aria-pressed={!!filters.gpu_only}
            className={cn(
              'h-9 rounded-lg border px-3 text-[13px] font-medium transition-colors',
              filters.gpu_only ? 'border-primary bg-primary/10 text-primary' : 'bg-card hover:bg-muted/60',
            )}
          >
            С видеокартой
          </button>
        )}
        <ViewToggle value={view} onChange={setView} />
      </div>

      <ComputerList
        query={computers}
        compact={view === 'compact'}
        onOpen={setOpenedId}
        onBook={setBooking}
        onReset={() => {
          setSearch('')
          setParams(new URLSearchParams({ tier }), { replace: true })
        }}
      />

      <ComputerSheet
        computerId={openedId}
        onClose={() => setOpenedId(null)}
        onBook={(c) => {
          setOpenedId(null)
          setBooking(c)
        }}
      />
      <BookingDialog computer={booking} onClose={() => setBooking(null)} />
      <VmBuilderDialog open={vmOpen} onClose={() => setVmOpen(false)} />
    </>
  )
}
