import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const WINDOW = 5

/** Подвал таблицы: диапазон записей и переход по страницам (до 5 номеров вокруг текущей) */
export function Pagination({
  page,
  pageSize,
  total,
  fetching = false,
  onChange,
}: {
  page: number
  pageSize: number
  total: number
  fetching?: boolean
  onChange: (page: number) => void
}) {
  const totalPages = Math.ceil(total / pageSize)
  const last = totalPages - 1
  let start = Math.max(0, page - 2)
  let end = Math.min(last, page + 2)
  if (end - start < WINDOW - 1) {
    if (start === 0) end = Math.min(last, WINDOW - 1)
    else if (end === last) start = Math.max(0, totalPages - WINDOW)
  }
  const pages = Array.from({ length: end - start + 1 }, (_, i) => start + i)
  const from = total ? page * pageSize + 1 : 0
  const to = Math.min(total, (page + 1) * pageSize)

  const nav = (label: string, target: number, disabled: boolean, Icon: typeof ChevronLeft) => (
    <Button size="sm" variant="outline" disabled={disabled} onClick={() => onChange(target)} aria-label={label} title={label}>
      <Icon className="h-4 w-4" />
    </Button>
  )

  return (
    <div className="flex items-center justify-between border-t px-4 py-3 text-[13px] text-muted-foreground">
      <span className={cn(fetching && 'animate-pulse')}>
        {total ? `${from}–${to} из ${total.toLocaleString('ru-RU')}` : '0 записей'}
      </span>
      {total > 0 && (
        <nav aria-label="Страницы" className="flex items-center gap-1">
          {nav('На первую страницу', 0, page === 0, ChevronsLeft)}
          {nav('Предыдущая страница', page - 1, page === 0, ChevronLeft)}
          <div className="hidden items-center gap-1 px-2 sm:flex">
            {pages.map((p) => (
              <Button
                key={p}
                size="sm"
                variant={page === p ? 'primary' : 'ghost'}
                className={cn('w-8 px-0', page !== p && 'text-muted-foreground')}
                aria-current={page === p ? 'page' : undefined}
                onClick={() => onChange(p)}
              >
                {p + 1}
              </Button>
            ))}
          </div>
          {nav('Следующая страница', page + 1, page >= last, ChevronRight)}
          {nav('На последнюю страницу', last, page >= last, ChevronsRight)}
        </nav>
      )}
    </div>
  )
}
