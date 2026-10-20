import { useSession } from '@/auth/AuthProvider'
import type { UserShort } from '@/lib/types'

/** Подпись арендатора у заказа участника команды; у своих заказов подписи нет */
export function RequesterNote({ order }: { order: { user: UserShort; requester_name: string; requester_nick: string } }) {
  const session = useSession()
  if (order.user.id === session.user.id) return null
  return (
    <p className="mt-0.5 text-xs text-muted-foreground">
      Арендатор: {order.requester_name} ({order.requester_nick})
    </p>
  )
}
