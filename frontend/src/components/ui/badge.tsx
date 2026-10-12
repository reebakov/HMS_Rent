import type { ReactNode } from 'react'
import { STATUSES, TIERS } from '@/lib/dictionaries'
import type { ComputerStatus, Tier } from '@/lib/types'
import { cn } from '@/lib/utils'

const tones = {
  success: 'bg-success/10 text-success ring-success/20',
  primary: 'bg-primary/10 text-primary ring-primary/20',
  warning: 'bg-warning/10 text-warning ring-warning/25',
  danger: 'bg-danger/10 text-danger ring-danger/20',
  muted: 'bg-muted text-muted-foreground ring-border',
}

export type Tone = keyof typeof tones

export function Badge({ tone = 'muted', dot, className, children }: { tone?: Tone; dot?: boolean; className?: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        tones[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

export function StatusBadge({ status }: { status: ComputerStatus }) {
  const s = STATUSES[status] ?? STATUSES.unknown
  return (
    <Badge tone={s.tone} dot>
      {s.label}
    </Badge>
  )
}

export function TierBadge({ tier }: { tier: Tier }) {
  const t = TIERS[tier]
  const Icon = t.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium', t.accent)}>
      <Icon className="h-3.5 w-3.5" />
      {t.short}
    </span>
  )
}
