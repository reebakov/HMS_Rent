import { Cloud, Plus, Wrench, type LucideIcon } from 'lucide-react'
import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { Tier, TierSummary } from '@/lib/types'
import { cn, plural } from '@/lib/utils'
import { Skeleton } from '@/components/ui/card'
import { DataState, type QueryLike } from '@/components/ui/data-state'

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
      className={cn(
        'group relative rounded-xl border border-dashed bg-card p-5 text-left shadow-card transition-all',
        'hover:-translate-y-0.5 hover:border-primary/60 hover:shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      )}
    >
      <div className="flex items-start justify-between">
        <div className={cn('flex h-10 w-10 items-center justify-center rounded-lg', accent)}>
          <Icon className="h-5 w-5" />
        </div>
        <Plus className="h-5 w-5 text-muted-foreground transition-colors group-hover:text-primary" />
      </div>
      <p className="mt-4 font-semibold">{title}</p>
      <p className="mt-0.5 text-[13px] text-muted-foreground">{hint}</p>
      <p className="mt-3 text-xs font-medium text-primary">{action}</p>
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
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {TIER_ORDER.map((t) => (
            <Skeleton key={t} className="h-[132px] rounded-xl" />
          ))}
        </div>
      }
    >
      {(summary) => {
        const byTier = Object.fromEntries(summary.map((s) => [s.tier, s]))
        // категории, в которых нет ни одного ПК (например, виртуалки — пока не подключены), не показываем
        const tiers = TIER_ORDER.filter((t) => (byTier[t]?.total ?? 0) > 0)
        const visible = tiers.length ? tiers : TIER_ORDER
        const cards = visible.length + (onBuildVm ? 1 : 0) + (onOrderBuild ? 1 : 0)

        return (
          <div className={cn('grid gap-4 sm:grid-cols-2', cards >= 4 ? 'xl:grid-cols-4' : 'xl:grid-cols-3')}>
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
                  className={cn(
                    'group relative rounded-xl border bg-card p-5 text-left shadow-card transition-all',
                    'hover:-translate-y-0.5 hover:shadow-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    active && 'border-primary ring-1 ring-primary',
                  )}
                >
                  <div className="flex items-start justify-between">
                    <div className={cn('flex h-10 w-10 items-center justify-center rounded-lg', meta.accent)}>
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="text-right">
                      <p className="text-2xl font-semibold tabular leading-none">{s?.available ?? 0}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {plural(s?.available ?? 0, ['свободен', 'свободно', 'свободно'])} из {s?.total ?? 0}
                      </p>
                    </div>
                  </div>
                  <p className="mt-4 font-semibold">{meta.label}</p>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">{meta.hint}</p>
                  {ram && <p className="mt-3 text-xs font-medium text-muted-foreground">{ram}</p>}
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
