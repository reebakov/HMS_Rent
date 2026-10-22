import { Badge } from '@/components/ui/badge'
import type { ExecutorOrder } from '@/lib/types'

/** Состояние подготовки ПК; если задачу в Jira уже закрыли, а данных подключения нет, — подсказка внести их */
export function PreparationBadge({ order }: { order: Pick<ExecutorOrder, 'prepared_at' | 'request_done'> }) {
  if (order.prepared_at) return <Badge tone="success">Подготовлен</Badge>
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Badge tone="warning" dot>
        Ждёт подготовки
      </Badge>
      {order.request_done && <span className="text-xs text-danger">Задача закрыта в Jira — внесите данные подключения</span>}
    </span>
  )
}
