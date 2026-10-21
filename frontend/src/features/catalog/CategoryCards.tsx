import { Cloud, Plus, Wrench, type LucideIcon } from 'lucide-react'
import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { Tier, TierSummary } from '@/lib/types'
import { cn, plural } from '@/lib/utils'
import { Skeleton } from '@/components/ui/card'
import { DataState, type QueryLike } from '@/components/ui/data-state'

// Плитки компактные и идут в одну строку: категории и карточки-действия — до пяти штук
const CARD = cn(
  'group flex min-w-0 items-center gap-3 rounded-xl border bg-card px-3.5 py-3 text-left shadow-card transition-all',
  'hover:-translate-y-0.5 hover:shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
)
const ICON_BOX = 'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg'
const GRID = 'grid gap-3 sm:grid-cols-2 xl:grid-flow-col xl:auto-cols-fr'

/** Карточка-действие рядом с категориями: открывает конструктор или форму заказа */
function ActionCard({ icon: Icon, accent, title, hint, action, onClick }: {
  icon: LucideIcon
  accent: string
  title: string
  hint: string
  action: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(CARD, 'border-dashed hover:border-primary/60')}
    >
      <div className={cn(ICON_BOX, accent)}>
        <Icon className="h-[18px] w-[18px]" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{title}</p>
        <p className="truncate text-xs text-muted-foreground" title={hint}>{hint}</p>
        <p className="truncate text-[11px] font-medium text-primary">{action}</p>
      </div>
      <Plus className="h-4 w-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
    </button>
  )
}

/** Карточки категорий мощности — они же переключатель списка; рядом конструктор ВМ и сборка по запросу */
export function CategoryCards({
  query,
  value,
  onChange,
  onBuildVm,
  onOrderBuild,
}: {
  query: QueryLike<TierSummary[]>
  value: Tier
  onChange: (tier: Tier) => void
  onBuildVm?: () => void
  onOrderBuild?: () => void
}) {
  return (
    <DataState
      query={query}
      errorTitle="Не удалось загрузить категории"
      errorCardClass=""
      loading={
        <div className={GRID}>
          {TIER_ORDER.map((t) => (
            <Skeleton key={t} className="h-[68px] rounded-xl" />
          ))}
        </div>
      }
    >
      {(summary) => {
        const byTier = Object.fromEntries(summary.map((s) => [s.tier, s]))
        // категории, в которых нет ни одного ПК (например, виртуалки — пока не подключены), не показываем
        const tiers = TIER_ORDER.filter((t) => (byTier[t]?.total ?? 0) > 0)
        const visible = tiers.length ? tiers : TIER_ORDER

        return (
          <div className={GRID}>
            {visible.map((tier) => {
              const meta = TIERS[tier]
              const s = byTier[tier]
              const active = tier === value
              const Icon = meta.icon
              const ram =
                s?.min_ram_gb && s.max_ram_gb
                  ? s.min_ram_gb === s.max_ram_gb
                    ? `${s.min_ram_gb} ГБ ОЗУ`
                    : `${s.min_ram_gb}–${s.max_ram_gb} ГБ ОЗУ`
                  : null
              return (
                <button
                  key={tier}
                  onClick={() => onChange(tier)}
                  className={cn(CARD, active && 'border-primary ring-1 ring-primary')}
                >
                  <div className={cn(ICON_BOX, meta.accent)}>
                    <Icon className="h-[18px] w-[18px]" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{meta.label}</p>
                    <p className="truncate text-xs text-muted-foreground" title={meta.hint}>{meta.hint}</p>
                    {ram && <p className="truncate text-[11px] font-medium text-muted-foreground">{ram}</p>}
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-xl font-semibold tabular leading-none">{s?.available ?? 0}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {plural(s?.available ?? 0, ['свободен', 'свободно', 'свободно'])} из {s?.total ?? 0}
                    </p>
                  </div>
                </button>
              )
            })}
            {onBuildVm && (
              <ActionCard
                icon={Cloud}
                accent="bg-teal-500/10 text-teal-700 dark:text-teal-300"
                title="Виртуализация"
                hint="Соберите виртуалку: ядра, память, диск"
                action="Открыть конструктор →"
                onClick={onBuildVm}
              />
            )}
            {onOrderBuild && (
              <ActionCard
                icon={Wrench}
                accent="bg-amber-500/10 text-amber-700 dark:text-amber-300"
                title="Сборка по запросу"
                hint="Типовая сборка или своя конфигурация"
                action="Заказать сборку →"
                onClick={onOrderBuild}
              />
            )}
          </div>
        )
      }}
    </DataState>
  )
}
