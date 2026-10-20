import { useEffect, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { CalendarClock, Check, Cloud, Monitor, X } from 'lucide-react'
import { Card, CardHeader, EmptyState } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DataState, FormError, RowsSkeleton } from '@/components/ui/data-state'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { DataTable, Th } from '@/components/ui/table'
import { useApproveTermRequest, useRejectTermRequest, useTermRequests } from '@/lib/queries'
import type { TermRequestOut } from '@/lib/types'
import { addDays, errorMessage, formatDate, formatDateTime, todayLocal } from '@/lib/utils'

/** Заявки на срок дольше лимита: админ согласует (можно поставить свою дату) или отклоняет */
export function TermRequests() {
  const requests = useTermRequests()
  const reject = useRejectTermRequest()
  const [approving, setApproving] = useState<TermRequestOut | null>(null)
  const [rejecting, setRejecting] = useState<TermRequestOut | null>(null)

  const doReject = async () => {
    if (!rejecting) return
    try {
      await reject.mutateAsync(rejecting.id)
      toast.success(`Заявка по ${rejecting.name} отклонена — срок остался ${formatDate(rejecting.current_return_at)}`)
      setRejecting(null)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <Card className="mt-6">
      <CardHeader
        title="Заявки на срок"
        description="Арендатор просит больше 3 месяцев: сейчас у заказа максимальный срок, согласуйте нужный или оставьте как есть"
      />
      <DataState
        query={requests}
        errorTitle="Не удалось загрузить заявки на срок"
        loading={<RowsSkeleton rows={3} />}
        empty={<EmptyState icon={CalendarClock} title="Заявок нет" description="Никто не просит срок дольше 3 месяцев" />}
      >
        {(data) => (
          <DataTable
            className="min-w-[900px]"
            head={
              <>
                <Th>Что</Th>
                <Th>Команда / арендатор</Th>
                <Th>Срок</Th>
                <Th>Причина</Th>
                <Th>Кто просит</Th>
                <Th />
              </>
            }
          >
            {data.map((req) => {
              const Icon = req.kind === 'pc' ? Monitor : Cloud
              return (
                <tr key={req.id} className="bg-primary/5 hover:bg-muted/40">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      <span className="font-semibold">{req.name}</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {req.kind === 'pc' ? 'Компьютер' : 'Виртуалка'} · заказ №{req.order_number}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium">{req.department.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {req.requester_name} ({req.requester_nick})
                    </p>
                  </td>
                  <td className="px-4 py-3 tabular">
                    {formatDate(req.current_return_at)} → <span className="font-medium">{formatDate(req.requested_return_at)}</span>
                  </td>
                  <td className="max-w-[240px] px-4 py-3">{req.comment ?? <span className="text-muted-foreground">—</span>}</td>
                  <td className="px-4 py-3">
                    <p>{req.user.display_name}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(req.created_at)}</p>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="outline" onClick={() => setApproving(req)}>
                        <Check className="h-3.5 w-3.5" />
                        Согласовать
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRejecting(req)}>
                        <X className="h-3.5 w-3.5" />
                        Отклонить
                      </Button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </DataTable>
        )}
      </DataState>

      <ApproveDialog request={approving} onClose={() => setApproving(null)} />
      <ConfirmDialog
        open={!!rejecting}
        onClose={() => setRejecting(null)}
        title={rejecting ? `Отклонить заявку по ${rejecting.name}?` : ''}
        description="Срок аренды останется прежним, арендатор сможет подать новую заявку."
        confirmLabel="Отклонить"
        pending={reject.isPending}
        onConfirm={doReject}
      />
    </Card>
  )
}

/** Согласование: по умолчанию срок из заявки, админ может поставить свою дату */
function ApproveDialog({ request, onClose }: { request: TermRequestOut | null; onClose: () => void }) {
  const approve = useApproveTermRequest()
  const [until, setUntil] = useState('')

  useEffect(() => {
    if (!request) return
    setUntil(request.requested_return_at)
    approve.reset()
  }, [request?.id])

  const today = todayLocal()
  const due = request?.current_return_at
  const min = due && due >= today ? addDays(due, 1) : today
  const canApprove = until >= min // ISO-даты сравниваются строками; пустая строка меньше любой даты

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!request || !canApprove) return
    try {
      await approve.mutateAsync({ id: request.id, approved_return_at: until })
      toast.success(`Срок ${request.name} согласован до ${formatDate(until)}`)
      onClose()
    } catch {
      /* ошибка показывается в окне */
    }
  }

  return (
    <Dialog
      open={!!request}
      onOpenChange={(open) => !open && onClose()}
      title={request ? `Согласовать срок ${request.name}` : ''}
      description={
        request ? `Сейчас — до ${formatDate(request.current_return_at)}, просят — до ${formatDate(request.requested_return_at)}.` : ''
      }
      onSubmit={submit}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={approve.isPending} disabled={!canApprove}>
            Согласовать
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Срок возврата" required hint="Можно оставить запрошенный или поставить свою дату">
          <Input type="date" min={min} value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        {approve.error && <FormError>{approve.error.message}</FormError>}
      </div>
    </Dialog>
  )
}
