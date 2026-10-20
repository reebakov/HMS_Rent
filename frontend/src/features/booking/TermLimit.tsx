import { toast, type ExternalToast } from 'sonner'
import { MAX_TERM_MONTHS, addMonths, formatDate } from '@/lib/utils'

/** Крайний срок без согласования админа: от `base` (YYYY-MM-DD) плюс лимит месяцев */
export const termLimit = (base: string) => addMonths(base, MAX_TERM_MONTHS)

/** Подсказка под полем срока: выбрано дольше лимита — срок ставится по лимиту, а админу уходит заявка */
export function TermLimitNote({ until, base, verb }: { until: string; base: string; verb: string }) {
  const limit = termLimit(base)
  if (!until || until <= limit) return null
  return (
    <p className="rounded-lg bg-muted/50 px-3 py-2 text-[13px]">
      Без согласования — не больше {MAX_TERM_MONTHS} месяцев: аренда {verb} до {formatDate(limit)}, а администратору уйдёт заявка на{' '}
      {formatDate(until)}.
    </p>
  )
}

type Termed = { expected_return_at: string | null; requested_return_at: string | null }

/** Пояснение после оформления или продления, если срок из заявки ждёт админа; иначе null */
const termSentence = (order: Termed) =>
  order.requested_return_at
    ? `Срок ограничен ${formatDate(order.expected_return_at)} — заявка на ${formatDate(order.requested_return_at)} отправлена администратору`
    : null

/** Тост об успехе; если заказ ушёл в заявку админу, к нему добавляется пояснение */
export function toastTerm(message: string, order: Termed, options?: ExternalToast) {
  const description = termSentence(order)
  const merged = description ? { ...options, description } : options
  if (merged) toast.success(message, merged)
  else toast.success(message)
}

/** У заказа в «Моей аренде»: срок, который ждёт согласования */
export function PendingTermNote({ order }: { order: { requested_return_at: string | null } }) {
  if (!order.requested_return_at) return null
  return <p className="mt-0.5 text-xs text-muted-foreground">Заявка на срок до {formatDate(order.requested_return_at)} ждёт администратора</p>
}
