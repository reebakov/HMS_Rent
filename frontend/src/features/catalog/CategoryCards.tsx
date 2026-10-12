import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { Tier, TierSummary } from '@/lib/types'
import { cn, plural } from '@/lib/utils'
import { Skeleton } from '@/components/ui/card'

/** Четыре карточки категорий мощности — они же переключатель списка */
export function CategoryCards({
  summary,
  value,
  onChange,
}: {
  summary?: TierSummary[]
  value: Tier
  onChange: (tier: Tier) => void
}) {
  if (!summary) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {TIER_ORDER.map((t) => (
          <Skeleton key={t} className="h-[132px] rounded-xl" />
        ))}
      </div>
    )
  }
  const byTier = Object.fromEntries(summary.map((s) => [s.tier, s]))
  // категории, в которых нет ни одного ПК (например, виртуалки — пока не подключены), не показываем
  const tiers = TIER_ORDER.filter((t) => (byTier[t]?.total ?? 0) > 0)
  const visible = tiers.length ? tiers : TIER_ORDER

  return (
    <div className={cn('grid gap-4 sm:grid-cols-2', visible.length >= 4 ? 'xl:grid-cols-4' : 'xl:grid-cols-3')}>
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
    </div>
  )
}
