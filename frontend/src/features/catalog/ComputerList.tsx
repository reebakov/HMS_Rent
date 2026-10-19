import { ArrowRight, SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EmptyState, Skeleton } from '@/components/ui/card'
import { DataState, type QueryLike } from '@/components/ui/data-state'
import { Location, SpecGrid } from './SpecGrid'
import type { Computer } from '@/lib/types'
import { computerSpecs } from '@/lib/utils'

interface RowsProps {
  computers: Computer[]
  onOpen: (id: number) => void
  onBook: (computer: Computer) => void
}

/** Компактный режим: плотный вертикальный список (одна строка = один ПК) */
function CompactRows({ computers, onOpen, onBook }: RowsProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {computers.map((c) => (
        <div
          key={c.id}
          className="flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-card px-4 py-2 shadow-sm transition-colors hover:border-primary/40"
        >
          <div className="flex min-w-0 flex-1 items-center gap-4 sm:gap-6">
            <button
              onClick={() => onOpen(c.id)}
              className="w-24 shrink-0 text-left font-semibold tracking-tight hover:text-primary"
              title="Подробнее"
            >
              {c.name}
            </button>

            <div className="hidden min-w-0 flex-1 items-center gap-3 text-xs text-muted-foreground sm:flex">
              <span className="truncate">{computerSpecs(c)}</span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-4">
            <div className="hidden sm:block">
              <Location value={c.location} />
            </div>
            <Button size="sm" className="h-7 px-3 text-xs" onClick={() => onBook(c)}>
              Забронировать
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}

/** Обычный режим: каждая строка — карточка с характеристиками и кнопкой брони */
function CardRows({ computers, onOpen, onBook }: RowsProps) {
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

/** Список свободных ПК: загрузка, ошибка, пустая выдача и сами карточки */
export function ComputerList({
  query,
  onOpen,
  onBook,
  onReset,
  compact = false,
}: {
  query: QueryLike<Computer[]>
  compact?: boolean
  onOpen: (id: number) => void
  onBook: (computer: Computer) => void
  onReset: () => void
}) {
  const Rows = compact ? CompactRows : CardRows
  return (
    <DataState
      query={query}
      errorTitle="Не удалось загрузить компьютеры"
      errorCardClass=""
      loading={
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[92px] rounded-xl" />
          ))}
        </div>
      }
      empty={
        <div className="rounded-xl border border-dashed bg-card">
          <EmptyState
            icon={SearchX}
            title="Свободных компьютеров не найдено"
            description="Попробуйте другую категорию или ослабьте фильтры. Если нужно срочно — напишите в HMS."
            action={
              <Button variant="outline" onClick={onReset}>
                Сбросить фильтры
              </Button>
            }
          />
        </div>
      }
    >
      {(computers) => <Rows computers={computers} onOpen={onOpen} onBook={onBook} />}
    </DataState>
  )
}
