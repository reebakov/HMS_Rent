import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/ui/card'
import { SearchInput, Select } from '@/components/ui/input'
import { CategoryCards } from '@/features/catalog/CategoryCards'
import { ComputerList } from '@/features/catalog/ComputerList'
import { ComputerSheet } from '@/features/catalog/ComputerSheet'
import { BookingDialog } from '@/features/booking/BookingDialog'
import { VmBuilderDialog } from '@/features/vms/VmBuilderDialog'
import { BuildOrderDialog } from '@/features/catalog/BuildOrderDialog'
import { ViewToggle, useViewMode } from '@/components/ui/view-toggle'
import { useSession } from '@/auth/AuthProvider'
import { useDebouncedSearch } from '@/lib/hooks'
import { useCatalogSummary, useComputers, useSdConfig, type ComputerFilters } from '@/lib/queries'
import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { Computer, Tier } from '@/lib/types'
import { plural } from '@/lib/utils'

const RAM_OPTIONS = [0, 8, 16, 32, 64]
const SORTS: NonNullable<ComputerFilters['sort']>[] = ['name', 'ram_desc', 'ram_asc']
const GPU_KINDS: NonNullable<ComputerFilters['gpu']>[] = ['discrete', 'integrated']

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
    // старые ссылки с gpu=1 («с видеокартой») открываются как «дискретная»
    gpu: params.get('gpu') === '1' ? 'discrete' : GPU_KINDS.find((k) => k === params.get('gpu')),
    sort: oneOf(params.get('sort'), SORTS, 'name'),
  }

  const session = useSession()
  const summary = useCatalogSummary(session.catalog_refresh_sec)
  const computers = useComputers(filters, session.catalog_refresh_sec)
  const [view, setView] = useViewMode('catalog')
  const [vmOpen, setVmOpen] = useState(false)
  const [buildOpen, setBuildOpen] = useState(false)
  const sdEnabled = useSdConfig().data?.enabled // сборка уходит заявкой в Service Desk
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
      {/* выбор категории — главный шаг, поэтому он в своей рамке; -mx-5 оставляет плашки вровень со списком ниже */}
      <section className="-mx-5 rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/[0.09] via-primary/[0.03] to-transparent px-5 pb-5 pt-5 shadow-card">
        <PageHeader
          title="Свободные компьютеры"
          description="Выберите категорию мощности, затем подходящий компьютер или виртуальную машину"
        />

        <CategoryCards
          query={summary}
          value={tier}
          onChange={(t) => update({ tier: t })}
          onBuildVm={() => setVmOpen(true)}
          onOrderBuild={sdEnabled ? () => setBuildOpen(true) : undefined}
        />
      </section>

      <div className="mb-4 mt-8 flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h2 className="text-lg font-semibold tracking-tight">{TIERS[tier].label}</h2>
          <p className="text-[13px] text-muted-foreground">
            {computers.data
              ? `${count} ${plural(count, ['компьютер', 'компьютера', 'компьютеров'])} доступно`
              : !computers.isError && 'Загружаем…'}
          </p>
        </div>

        <SearchInput className="sm:w-64" label="Поиск по каталогу" placeholder="Имя, процессор, видеокарта…" value={search} onChange={setSearch} />
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
          <Select className="w-44" aria-label="Видеокарта" value={filters.gpu ?? ''} onChange={(e) => update({ gpu: e.target.value || undefined })}>
            <option value="">Любая видеокарта</option>
            <option value="discrete">Дискретная</option>
            <option value="integrated">Встроенная</option>
          </Select>
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
      <BuildOrderDialog open={buildOpen} onClose={() => setBuildOpen(false)} />
    </>
  )
}
