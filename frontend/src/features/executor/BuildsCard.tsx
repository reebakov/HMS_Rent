import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { DataState, FormError, RowsSkeleton } from '@/components/ui/data-state'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input, Select, Textarea } from '@/components/ui/input'
import { DataTable, Th } from '@/components/ui/table'
import { JiraRequestLink } from '@/features/executor/JiraRequestLink'
import { BUILD_REJECT_REASONS } from '@/lib/dictionaries'
import { useExecutorBuilds, useExecutorPools, useIssueBuild, useRejectBuild } from '@/lib/queries'
import type { ConnectionMethod, ExecutorBuild } from '@/lib/types'
import { errorMessage, formatDate, formatDateTime } from '@/lib/utils'

// Имя собранного ПК по регламенту — A###.ff.local, где A### — номер комплекта (имя ПК в Insight)
const PC_DOMAIN = 'ff.local'

const defaultMethod = (os: string | null): ConnectionMethod => (os && !/windows/i.test(os) ? 'VNC' : 'RDP')

/** Сборки по запросу: исполнитель собирает ПК, заводит его в Insight, затем выдаёт заказчику здесь или отклоняет заказ */
export function BuildsCard() {
  const builds = useExecutorBuilds()
  const [issuing, setIssuing] = useState<ExecutorBuild | null>(null)
  const [rejecting, setRejecting] = useState<ExecutorBuild | null>(null)

  return (
    <Card className="mt-6">
      <div className="border-b px-5 py-4">
        <p className="font-semibold">Сборки по запросу</p>
        <p className="text-[13px] text-muted-foreground">
          Соберите ПК и заведите его в Insight, дождитесь синхронизации и выдайте заказчику: укажите имя ПК, пул и данные для подключения
        </p>
      </div>
      <DataState
        query={builds}
        errorTitle="Не удалось загрузить сборки"
        loading={<RowsSkeleton rows={2} className="h-12" />}
        empty={<p className="px-5 py-6 text-[13px] text-muted-foreground">Заказов на сборку нет</p>}
      >
        {(data) => (
          <DataTable
            className="min-w-[1000px]"
            head={
              <>
                <Th>№ заказа</Th>
                <Th>Конфигурация</Th>
                <Th>Команда и заказчик</Th>
                <Th>Нужен к</Th>
                <Th>Вернуть до</Th>
                <Th>Задача в Jira</Th>
                <Th>{''}</Th>
              </>
            }
          >
            {data.map((b) => (
              <tr key={b.id} className="align-top hover:bg-muted/40">
                <td className="px-4 py-3 tabular text-muted-foreground">№{b.order_number}</td>
                <td className="px-4 py-3">
                  <p className="inline-flex items-center gap-1.5 font-semibold">
                    <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
                    {b.configuration}
                  </p>
                  <p className="text-xs text-muted-foreground">{b.os_label ?? 'ОС не указана'}</p>
                </td>
                <td className="px-4 py-3">
                  <p className="font-medium">{b.department.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {b.user.display_name} ({b.requester_nick})
                  </p>
                  {b.purpose && <p className="text-xs text-muted-foreground">{b.purpose}</p>}
                  <p className="text-xs text-muted-foreground">Заказан {formatDateTime(b.created_at)}</p>
                </td>
                <td className="px-4 py-3 tabular">{formatDate(b.wanted_by)}</td>
                <td className="px-4 py-3 tabular">{formatDate(b.expected_return_at)}</td>
                <td className="px-4 py-3">
                  <JiraRequestLink order={b} />
                  {b.request_done && <p className="text-xs text-danger">Задача закрыта в Jira — выдайте ПК или отклоните заказ</p>}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap justify-end gap-1.5">
                    <Button size="sm" onClick={() => setIssuing(b)}>
                      Выдать ПК…
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRejecting(b)}>
                      Отклонить…
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </DataState>
      <IssueBuildDialog build={issuing} onClose={() => setIssuing(null)} />
      <RejectBuildDialog build={rejecting} onClose={() => setRejecting(null)} />
    </Card>
  )
}

function IssueBuildDialog({ build, onClose }: { build: ExecutorBuild | null; onClose: () => void }) {
  const pools = useExecutorPools(!!build)
  const issue = useIssueBuild()
  const [name, setName] = useState('')
  const [poolId, setPoolId] = useState('')
  const [host, setHost] = useState('')
  const [hostEdited, setHostEdited] = useState(false)
  const [ip, setIp] = useState('')
  const [method, setMethod] = useState<ConnectionMethod | null>(null)

  const close = () => {
    setName('')
    setPoolId('')
    setHost('')
    setHostEdited(false)
    setIp('')
    setMethod(null)
    issue.reset()
    onClose()
  }

  const changeName = (value: string) => {
    setName(value)
    if (!hostEdited) setHost(value.trim() ? `${value.trim()}.${PC_DOMAIN}` : '') // имя хоста следует за именем ПК, пока его не правили
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!build) return
    try {
      await issue.mutateAsync({
        id: build.id,
        computer_name: name.trim(),
        pool_id: Number(poolId),
        host: host.trim(),
        ip: ip.trim(),
        method: method ?? defaultMethod(build.os_label),
      })
      toast.success(`${name.trim()} выдан, заказчик получил данные для подключения`)
      close()
    } catch {
      // текст ошибки показан в окне
    }
  }

  return (
    <Dialog
      open={!!build}
      onOpenChange={(o) => !o && close()}
      title={build ? `Выдать ПК по заказу №${build.order_number}` : ''}
      description="ПК должен быть заведён в Insight и уже синхронизирован с порталом. Заказчик получит уведомление с данными для подключения."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={close}>
            Отмена
          </Button>
          <Button type="submit" loading={issue.isPending} disabled={!name.trim() || !poolId}>
            Выдать
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Имя ПК" required hint="Как в Insight, например A500">
          <Input value={name} onChange={(e) => changeName(e.target.value)} required maxLength={128} />
        </Field>
        <Field label="Пул" required hint="После возврата ПК останется в этом пуле">
          <Select value={poolId} onChange={(e) => setPoolId(e.target.value)} required>
            <option value="">Выберите пул</option>
            {pools.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        {pools.isError && <FormError>Не удалось загрузить пулы</FormError>}
        <Field label="Доменное имя" required hint="Имя хоста с доменом, как его увидит заказчик">
          <Input
            value={host}
            onChange={(e) => {
              setHost(e.target.value)
              setHostEdited(true)
            }}
            required
            maxLength={255}
          />
        </Field>
        <Field label="IP-адрес" required>
          <Input value={ip} onChange={(e) => setIp(e.target.value)} required placeholder="10.1.2.3" inputMode="decimal" />
        </Field>
        <Field label="Способ подключения" required>
          <Select value={method ?? (build ? defaultMethod(build.os_label) : 'RDP')} onChange={(e) => setMethod(e.target.value as ConnectionMethod)}>
            <option value="RDP">RDP</option>
            <option value="VNC">VNC</option>
          </Select>
        </Field>
        {issue.isError && <FormError>{errorMessage(issue.error)}</FormError>}
      </div>
    </Dialog>
  )
}

function RejectBuildDialog({ build, onClose }: { build: ExecutorBuild | null; onClose: () => void }) {
  const reject = useRejectBuild()
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')

  const close = () => {
    setReason('')
    setComment('')
    reject.reset()
    onClose()
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!build) return
    try {
      await reject.mutateAsync({ id: build.id, reason, comment: comment.trim() })
      toast.success(`Заказ №${build.order_number} отклонён, заказчик получил уведомление`)
      close()
    } catch {
      // текст ошибки показан в окне
    }
  }

  return (
    <Dialog
      open={!!build}
      onOpenChange={(o) => !o && close()}
      title={build ? `Отклонить заказ №${build.order_number}?` : ''}
      description="Заказчик получит уведомление с основанием и комментарием, задача в Jira закроется с резолюцией Rejected."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={close}>
            Отмена
          </Button>
          <Button type="submit" variant="danger" loading={reject.isPending} disabled={!reason || !comment.trim()}>
            Отклонить
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Основание" required>
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Выберите основание</option>
            {BUILD_REJECT_REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Комментарий для заказчика" required>
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
        </Field>
        {reject.isError && <FormError>{errorMessage(reject.error)}</FormError>}
      </div>
    </Dialog>
  )
}
