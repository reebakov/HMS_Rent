import { HardDrive, MemoryStick, Monitor, Cpu, MapPin, type LucideIcon } from 'lucide-react'
import type { Computer } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Компактная строка характеристик: процессор, память, диск, видеокарта */
export function SpecGrid({ computer, className }: { computer: Computer; className?: string }) {
  const items: { icon: LucideIcon; label: string; value: string | null }[] = [
    { icon: Cpu, label: 'Процессор', value: computer.cpu && (computer.cpu_cores ? `${computer.cpu} · ${computer.cpu_cores} ядер` : computer.cpu) },
    { icon: MemoryStick, label: 'Память', value: computer.ram_gb ? `${computer.ram_gb} ГБ` : null },
    { icon: HardDrive, label: 'Диск', value: computer.storage },
    { icon: Monitor, label: 'Видеокарта', value: computer.gpu ?? (computer.is_virtual ? 'Виртуальный адаптер' : null) },
  ]
  return (
    // В строку колонки делят ширину в одинаковых долях у всех карточек, поэтому подписи стоят ровно друг под другом;
    // при ширине по содержимому (auto) у каждой карточки сетка получалась своей, и колонки «скакали»
    <div
      className={cn(
        'grid gap-x-4 gap-y-2 sm:grid-cols-2',
        'xl:grid-cols-[minmax(0,1.5fr)_minmax(0,0.7fr)_minmax(0,1.1fr)_minmax(0,1.4fr)]',
        className,
      )}
    >
      {items.map(({ icon: Icon, label, value }) => (
        <div key={label} className="flex min-w-0 items-center gap-2.5">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className="truncate text-[13px] font-medium" title={value ?? undefined}>
              {value ?? '—'}
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}

/** Атрибуты ПК из Insight «ключ — значение» списком */
export function InsightAttributes({ attributes }: { attributes: Record<string, string> }) {
  return (
    <div className="divide-y rounded-xl border">
      {Object.entries(attributes).map(([key, value]) => (
        <div key={key} className="flex gap-4 px-4 py-2.5 text-[13px]">
          <span className="w-40 shrink-0 text-muted-foreground">{key}</span>
          <span className="min-w-0 break-words font-medium">{String(value)}</span>
        </div>
      ))}
    </div>
  )
}

export function Location({ value }: { value: string | null }) {
  if (!value) return null
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <MapPin className="h-3.5 w-3.5" />
      {value}
    </span>
  )
}
