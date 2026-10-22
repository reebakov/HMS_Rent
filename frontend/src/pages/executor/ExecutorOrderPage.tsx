import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowLeft } from 'lucide-react'
import { Card, PageHeader } from '@/components/ui/card'
import { DataState, FormError, RowsSkeleton } from '@/components/ui/data-state'
import { Field, Input, Select, Textarea } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button, buttonClass } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { JiraRequestLink } from '@/features/executor/JiraRequestLink'
import { FAULTY_REASON, REJECT_REASONS } from '@/lib/dictionaries'
import { useExecutorOrder, useRejectExecutorOrder, useSaveExecutorResult } from '@/lib/queries'
import type { ConnectionMethod, ExecutorOrder } from '@/lib/types'
import { computerSpecs, errorMessage, formatDate, formatDateTime } from '@/lib/utils'

// Имя подготовленного ПК по регламенту — A###.ff.local, где A### — номер комплекта (имя ПК в Insight)
const PC_DOMAIN = 'ff.local'

const defaultMethod = (os: string | null): ConnectionMethod => (os && !/windows/i.test(os) ? 'VNC' : 'RDP')

/** Страница заказа для исполнителя: ссылка на неё — в заявке Service Desk «подготовить ПК» */
export function ExecutorOrderPage() {
  const id = Number(useParams().id)
  const order = useExecutorOrder(id)

  return (
    <>
      <Link to="/executor" className={buttonClass({ variant: 'ghost', size: 'sm' }) + ' mb-3'}>
        <ArrowLeft className="h-3.5 w-3.5" />
        Все заказы
      </Link>
      <DataState query={order} errorTitle="Не удалось загрузить заказ" errorCardClass="" loading={<RowsSkeleton rows={4} />}>
        {(o) => (
          <>
            <PageHeader title={`${o.computer.name} · заказ №${o.order_number}`} description={computerSpecs(o.computer)} />
            <div className="grid gap-4 lg:grid-cols-2">
              <OrderDetails order={o} />
              {o.status === 'active' ? (
                <div className="space-y-4">
                  <ResultForm key={`${o.id}-${o.prepared_at}`} order={o} />
                  <RejectForm order={o} />
                </div>
              ) : (
                <Card className="p-5 text-[13px] text-muted-foreground">Заказ закрыт: ПК вернули {formatDateTime(o.returned_at)}.</Card>
              )}
            </div>
          </>
        )}
      </DataState>
    </>
  )
}

function OrderDetails({ order: o }: { order: ExecutorOrder }) {
  const rows: [string, string][] = [
    ['ОС', o.os_label ?? 'не выбрана'],
    ['Команда', o.department.name],
    ['Заказчик', `${o.requester_name} (${o.requester_nick})`],
    ['Взят', formatDateTime(o.booked_at)],
    ['Вернуть до', formatDate(o.expected_return_at)],
  ]
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between gap-2">
        <p className="font-semibold">Заказ</p>
        {o.prepared_at ? <Badge tone="success">Подготовлен</Badge> : <Badge tone="warning" dot>Ждёт подготовки</Badge>}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[13px]">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium">{value}</dd>
          </div>
        ))}
        <dt className="text-muted-foreground">Заявка в Jira</dt>
        <dd className="font-medium">
          <JiraRequestLink order={o} />
        </dd>
      </dl>
      {o.purpose && <p className="mt-4 rounded-lg bg-muted/50 px-3 py-2 text-[13px]">{o.purpose}</p>}
      {o.prepared_at && (
        <p className="mt-4 text-xs text-muted-foreground">
          Подготовил {o.prepared_by?.display_name ?? '—'}, {formatDateTime(o.prepared_at)}
        </p>
      )}
    </Card>
  )
}

/** Данные для подключения: логин user подставляет портал, пароль в портал не вносится */
function ResultForm({ order: o }: { order: ExecutorOrder }) {
  const save = useSaveExecutorResult()
  const [host, setHost] = useState(o.connection_host ?? `${o.computer.name}.${PC_DOMAIN}`)
  const [ip, setIp] = useState(o.connection_ip ?? '')
  const [method, setMethod] = useState<ConnectionMethod>(o.connection_method ?? defaultMethod(o.os_label))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await save.mutateAsync({ id: o.id, host: host.trim(), ip: ip.trim(), method })
      toast.success('Данные для подключения отправлены заказчику')
    } catch {
      // текст ошибки показан в форме
    }
  }

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="space-y-4">
        <p className="font-semibold">Данные для подключения</p>
        <Field label="Доменное имя" required hint="Имя хоста с доменом, как его увидит заказчик">
          <Input value={host} onChange={(e) => setHost(e.target.value)} required maxLength={255} />
        </Field>
        <Field label="IP-адрес" required>
          <Input value={ip} onChange={(e) => setIp(e.target.value)} required placeholder="10.1.2.3" inputMode="decimal" />
        </Field>
        <Field label="Способ подключения" required>
          <Select value={method} onChange={(e) => setMethod(e.target.value as ConnectionMethod)}>
            <option value="RDP">RDP</option>
            <option value="VNC">VNC</option>
          </Select>
        </Field>
        <p className="text-xs text-muted-foreground">
          Логин <span className="font-mono">user</span> заказчик увидит сам. Пароль в портал и в заявку не пишется.
        </p>
        {save.isError && <FormError>{errorMessage(save.error)}</FormError>}
        <Button type="submit" loading={save.isPending}>
          {o.prepared_at ? 'Сохранить изменения' : 'Отправить заказчику'}
        </Button>
      </form>
    </Card>
  )
}

/** Отклонение заказа: основание из списка регламента и обязательный комментарий, который увидит заказчик */
function RejectForm({ order: o }: { order: ExecutorOrder }) {
  const navigate = useNavigate()
  const reject = useRejectExecutorOrder()
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [confirming, setConfirming] = useState(false)
  const faulty = reason === FAULTY_REASON

  const submit = async () => {
    try {
      await reject.mutateAsync({ id: o.id, reason, comment: comment.trim() })
      toast.success('Заказ отклонён, заказчик получил уведомление')
      navigate('/executor')
    } catch {
      // текст ошибки показан в окне подтверждения
    }
  }

  return (
    <Card className="p-5">
      <div className="space-y-4">
        <p className="font-semibold">Отклонить заказ</p>
        <Field label="Основание" required>
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="" disabled>
              Выберите основание
            </option>
            {REJECT_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Комментарий для заказчика" required hint="Заказчик увидит этот текст в уведомлении и в «Моей аренде»">
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} rows={3} />
        </Field>
        {faulty && (
          <p className="text-xs text-muted-foreground">
            ПК будет выведен из пула, а исполнителям создастся заявка «Диагностика комплекта». Если в пуле есть такой же свободный
            сервер, предложите заказчику замену в комментарии к заявке.
          </p>
        )}
        <Button variant="outline" disabled={!reason || !comment.trim()} onClick={() => setConfirming(true)}>
          Отклонить заказ…
        </Button>
      </div>
      <ConfirmDialog
        open={confirming}
        onClose={() => setConfirming(false)}
        title={`Отклонить заказ №${o.order_number}?`}
        description={
          faulty
            ? 'ПК будет выведен из пула, заказчик получит уведомление с причиной. Отменить отклонение нельзя.'
            : 'ПК освободится, заказчик получит уведомление с причиной. Отменить отклонение нельзя.'
        }
        confirmLabel="Отклонить"
        pending={reject.isPending}
        onConfirm={submit}
      >
        {reject.isError && <FormError>{errorMessage(reject.error)}</FormError>}
      </ConfirmDialog>
    </Card>
  )
}
