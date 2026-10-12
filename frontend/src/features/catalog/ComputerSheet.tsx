import { Sheet } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { StatusBadge, TierBadge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/card'
import { SpecGrid } from './SpecGrid'
import { useComputer } from '@/lib/queries'
import type { Computer } from '@/lib/types'
import { formatRelative } from '@/lib/utils'

/** Карточка ПК справа: все характеристики + все атрибуты из Insight */
export function ComputerSheet({
  computerId,
  onClose,
  onBook,
}: {
  computerId: number | null
  onClose: () => void
  onBook: (computer: Computer) => void
}) {
  const { data, isLoading } = useComputer(computerId)

  return (
    <Sheet
      open={computerId !== null}
      onOpenChange={(open) => !open && onClose()}
      title={data?.name ?? 'Компьютер'}
      description={
        data && (
          <span className="flex flex-wrap items-center gap-2">
            <TierBadge tier={data.tier} />
            <StatusBadge status={data.status} />
            {data.insight_key && <span className="font-mono text-xs">{data.insight_key}</span>}
          </span>
        )
      }
      footer={
        data?.status === 'available' && (
          <Button onClick={() => onBook(data)} className="w-full sm:w-auto">
            Забронировать
          </Button>
        )
      }
    >
      {isLoading || !data ? (
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="space-y-6">
          <SpecGrid computer={data} className="xl:grid-cols-2 sm:grid-cols-2" />

          <dl className="grid grid-cols-2 gap-4 rounded-xl border p-4 text-[13px]">
            {[
              ['Hostname', data.hostname],
              ['ОС', data.os],
              ['Расположение', data.location],
              ['IP-адрес', data.ip_address],
              ['Статус в Insight', data.insight_status],
              ['Обновлено', formatRelative(data.synced_at)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="mt-0.5 font-medium">{value || '—'}</dd>
              </div>
            ))}
          </dl>

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Все атрибуты Insight</p>
            <div className="divide-y rounded-xl border">
              {Object.entries(data.attributes).map(([key, value]) => (
                <div key={key} className="flex gap-4 px-4 py-2.5 text-[13px]">
                  <span className="w-40 shrink-0 text-muted-foreground">{key}</span>
                  <span className="min-w-0 break-words font-medium">{String(value)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Sheet>
  )
}
