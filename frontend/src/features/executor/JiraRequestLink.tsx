import { ExternalLink } from 'lucide-react'
import type { ExecutorOrder } from '@/lib/types'

/** Ссылка на заявку Service Desk «подготовить ПК» по заказу: исполнитель ведёт работу и в Jira, и в портале */
export function JiraRequestLink({ order }: { order: Pick<ExecutorOrder, 'request_key' | 'request_url' | 'request_status' | 'request_error'> }) {
  if (order.request_key && order.request_url) {
    return (
      <span className="inline-flex flex-wrap items-center gap-x-1.5">
        <a href={order.request_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
          {order.request_key}
          <ExternalLink className="h-3 w-3" />
        </a>
        {order.request_status && <span className="text-xs text-muted-foreground">· {order.request_status}</span>}
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
