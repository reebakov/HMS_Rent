import { Card, CardHeader, Skeleton } from '@/components/ui/card'
import { DataState } from '@/components/ui/data-state'
import { useClusterCapacity } from '@/lib/queries'

function UsageRow({ label, free, total, unit }: { label: string; free: number; total: number; unit: string }) {
  const usedPercent = total > 0 ? Math.round(((total - free) / total) * 100) : 0
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
        <span className="font-medium">{label}</span>
        <span className="tabular text-muted-foreground">
          свободно {free} из {total} {unit}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="meter"
        aria-label={`${label}: занято`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={usedPercent}
      >
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${usedPercent}%` }} />
      </div>
    </div>
  )
}

/** Свободные мощности кластера, в котором создаются ВМ (из vCenter) */
export function ClusterCapacityCard() {
  const cluster = useClusterCapacity()
  return (
    <Card>
      <CardHeader title="Мощности кластера" description="Сколько места осталось под виртуальные машины" />
      <div className="p-5">
        <DataState query={cluster} errorTitle="Не удалось загрузить мощности кластера" loading={<Skeleton className="h-40" />}>
          {(c) =>
            c.ok ? (
              <div className="space-y-4">
                <UsageRow label="Процессор" free={c.cpu_free_ghz} total={c.cpu_total_ghz} unit="ГГц" />
                <UsageRow label="Память" free={c.ram_free_gb} total={c.ram_total_gb} unit="ГБ" />
                <UsageRow label="Хранилище" free={c.storage_free_gb} total={c.storage_total_gb} unit="ГБ" />
              </div>
            ) : (
              <p className="py-6 text-center text-[13px] text-muted-foreground">{c.error}</p>
            )
          }
        </DataState>
      </div>
    </Card>
  )
}
