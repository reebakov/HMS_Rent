import { ExternalLink } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { useExecutorNorms } from '@/lib/queries'
import type { ExecutorOrder } from '@/lib/types'
import { cn, workHours } from '@/lib/utils'

/** Норматив задачи под ссылкой: потрачено из положенного, «Просрочено», «Не взята», пауза заморозки */
function NormLine({ issueKey }: { issueKey: string }) {
  const norm = useExecutorNorms().data?.find((n) => n.issue_key === issueKey)
  if (!norm) return null
  return (
    <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
      {norm.not_taken_late && <Badge tone="danger">Не взята</Badge>}
      {norm.limit_seconds !== null && (
        <span className={cn(norm.state === 'overdue' ? 'font-medium text-danger' : norm.state === 'warning' ? 'text-warning' : 'text-muted-foreground')}>
          {norm.state === 'overdue' ? 'Просрочено: ' : 'Норматив: '}
          {workHours(norm.spent_seconds)} из {workHours(norm.limit_seconds)} ч
        </span>
      )}
      {norm.frozen && <span className="text-muted-foreground">· пауза (Frozen)</span>}
    </span>
  )
}

/** Ссылка на заявку Service Desk «подготовить ПК» по заказу: исполнитель ведёт работу и в Jira, и в портале */
export function JiraRequestLink({ order }: { order: Pick<ExecutorOrder, 'request_key' | 'request_url' | 'request_status' | 'request_error'> }) {
  if (order.request_key && order.request_url) {
    return (
      <span className="inline-flex flex-col">
        <span className="inline-flex flex-wrap items-center gap-x-1.5">
          <a href={order.request_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
            {order.request_key}
            <ExternalLink className="h-3 w-3" />
          </a>
          {order.request_status && <span className="text-xs text-muted-foreground">· {order.request_status}</span>}
        </span>
        <NormLine issueKey={order.request_key} />
      </span>
    )
  }
  if (order.request_error) {
    return (
      <span className="text-xs text-danger" title={order.request_error}>
        Заявка в Jira не создана
      </span>
    )
  }
  return <span className="text-xs text-muted-foreground">Заявки нет</span>
}
