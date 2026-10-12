import { ArrowRight, SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EmptyState, Skeleton } from '@/components/ui/card'
import { Location, SpecGrid } from './SpecGrid'
import type { Computer } from '@/lib/types'

/** Список свободных ПК: каждая строка — карточка с характеристиками и кнопкой брони */
export function ComputerList({
  computers,
  loading,
  onOpen,
  onBook,
  onReset,
}: {
  computers?: Computer[]
  loading: boolean
  onOpen: (id: number) => void
  onBook: (computer: Computer) => void
  onReset: () => void
}) {
  if (loading && !computers) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-[92px] rounded-xl" />
        ))}
      </div>
    )
  }

  if (!computers?.length) {
    return (
      <div className="rounded-xl border border-dashed bg-card">
        <EmptyState
          icon={SearchX}
          title="Свободных компьютеров не найдено"
          description="Попробуйте другую категорию или ослабьте фильтры. Если нужно срочно — напишите в ИТ-отдел."
          action={
            <Button variant="outline" onClick={onReset}>
              Сбросить фильтры
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {computers.map((c) => (
        <div
          key={c.id}
          className="group flex flex-col gap-4 rounded-xl border bg-card p-4 shadow-card transition-colors hover:border-primary/40 md:flex-row md:items-center md:gap-6 md:px-5"
        >
          <button onClick={() => onOpen(c.id)} className="min-w-[150px] text-left">
            <p className="flex items-center gap-1.5 text-base font-semibold tracking-tight group-hover:text-primary">
              {c.name}
            </p>
            <p className="mt-0.5 font-mono text-xs text-muted-foreground">{c.hostname ?? c.insight_key}</p>
            <div className="mt-1.5">
              <Location value={c.location} />
            </div>
          </button>

          <SpecGrid computer={c} className="flex-1" />

          <div className="flex items-center gap-2 md:justify-end">
            <Button variant="ghost" size="sm" onClick={() => onOpen(c.id)}>
              Подробнее
            </Button>
            <Button size="sm" onClick={() => onBook(c)}>
              Забронировать
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}
