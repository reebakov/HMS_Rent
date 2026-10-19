import type { ReactNode } from 'react'
import { CircleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, Skeleton } from '@/components/ui/card'

/** Минимум от результата useQuery, который нужен для показа загрузки и ошибки */
export interface QueryLike<T> {
  data: T | undefined
  isError: boolean
  error: Error | null
  refetch: () => unknown
}

/** Полоса с текстом ошибки и кнопкой «Повторить»: ошибка загрузки не должна выглядеть как пустой список */
export function ErrorNotice({ title, error, onRetry }: { title: string; error?: Error | null; onRetry: () => unknown }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 px-5 py-4 text-[13px] text-danger">
      <CircleAlert className="h-4 w-4 shrink-0" />
      <div className="mr-auto">
        <p className="font-medium">{title}</p>
        {error?.message && <p className="mt-0.5 text-muted-foreground">{error.message}</p>}
      </div>
      <Button variant="outline" size="sm" onClick={() => onRetry()}>
        Повторить
      </Button>
    </div>
  )
}

/**
 * Ошибка запроса без данных. Пока запрос грузится или успешен — ничего не рисует (годится для справочников,
 * от которых зависит фильтр или список). cardClass — если задан (можно пустой), ошибка в своей карточке.
 */
export function QueryError({ query, title, cardClass }: { query: QueryLike<unknown>; title: string; cardClass?: string }) {
  if (!query.isError || query.data !== undefined) return null
  const notice = <ErrorNotice title={title} error={query.error} onRetry={query.refetch} />
  return cardClass === undefined ? notice : <Card className={cardClass}>{notice}</Card>
}

/** Заглушка загрузки: несколько строк-скелетонов */
export function RowsSkeleton({ rows = 6, className = 'h-12' }: { rows?: number; className?: string }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={className} />
      ))}
    </div>
  )
}

const isEmptyList = (data: unknown) => Array.isArray(data) && data.length === 0

/**
 * Состояния запроса в одном месте: загрузка → скелетон, ошибка без данных → «Повторить», пусто → empty, иначе данные.
 * Если данные уже есть, а фоновое обновление упало, показываются данные.
 * errorCardClass — класс карточки вокруг ошибки (можно пустой): нужен, когда снаружи карточки нет.
 */
export function DataState<T>({
  query,
  errorTitle,
  loading = <RowsSkeleton />,
  empty,
  isEmpty = isEmptyList,
  errorCardClass,
  children,
}: {
  query: QueryLike<T>
  errorTitle: string
  loading?: ReactNode
  empty?: ReactNode
  isEmpty?: (data: T) => boolean
  errorCardClass?: string
  children: (data: T) => ReactNode
}) {
  const { data } = query
  if (data === undefined) {
    return query.isError ? <QueryError query={query} title={errorTitle} cardClass={errorCardClass} /> : <>{loading}</>
  }
  if (empty !== undefined && isEmpty(data)) return <>{empty}</>
  return <>{children(data)}</>
}
