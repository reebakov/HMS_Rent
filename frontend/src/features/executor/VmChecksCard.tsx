import { useState } from 'react'
import { toast } from 'sonner'
import { Cloud } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DataState, FormError, RowsSkeleton } from '@/components/ui/data-state'
import { Dialog } from '@/components/ui/dialog'
import { Field, Select, Textarea } from '@/components/ui/input'
import { DataTable, Th } from '@/components/ui/table'
import { JiraRequestLink } from '@/features/executor/JiraRequestLink'
import { VM_REJECT_REASONS } from '@/lib/dictionaries'
import { useConfirmVm, useExecutorVms, useRecreateVm, useRejectVm } from '@/lib/queries'
import type { ExecutorVm } from '@/lib/types'
import { errorMessage, formatDateTime } from '@/lib/utils'

/** ВМ на проверке: созданы в vSphere, исполнитель проверяет и подтверждает, пересоздаёт или отклоняет; заказчик ждёт решения */
export function VmChecksCard() {
  const vms = useExecutorVms()
  const confirm = useConfirmVm()
  const recreate = useRecreateVm()
  const [recreating, setRecreating] = useState<ExecutorVm | null>(null)
  const [rejecting, setRejecting] = useState<ExecutorVm | null>(null)

  const approve = async (vm: ExecutorVm) => {
    try {
      await confirm.mutateAsync(vm.id)
      toast.success(`${vm.name} подтверждена, заказчик получил данные для подключения`)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const doRecreate = async () => {
    if (!recreating) return
    try {
      await recreate.mutateAsync(recreating.id)
      toast.success(`${recreating.name} будет пересоздана`)
      setRecreating(null)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <Card className="mt-6">
      <div className="border-b px-5 py-4">
        <p className="font-semibold">ВМ на проверке</p>
        <p className="text-[13px] text-muted-foreground">
          Проверьте: запущена, ОС и ресурсы по заказу, есть интернет, имя разрешается, RDP или VNC работает. Подтвердите — заказчик получит данные
        </p>
      </div>
      <DataState
        query={vms}
        errorTitle="Не удалось загрузить ВМ на проверке"
        loading={<RowsSkeleton rows={2} className="h-12" />}
        empty={<p className="px-5 py-6 text-[13px] text-muted-foreground">Все созданные ВМ проверены</p>}
      >
        {(data) => (
          <DataTable
            className="min-w-[1000px]"
            head={
              <>
                <Th>№ заказа</Th>
                <Th>ВМ</Th>
                <Th>IP</Th>
                <Th>Команда и заказчик</Th>
                <Th>Создана</Th>
                <Th>Задача в Jira</Th>
                <Th>{''}</Th>
              </>
            }
          >
            {data.map((vm) => (
              <tr key={vm.id} className="align-top hover:bg-muted/40">
                <td className="px-4 py-3 tabular text-muted-foreground">№{vm.order_number}</td>
                <td className="px-4 py-3">
                  <p className="inline-flex items-center gap-1.5 font-semibold">
                    <Cloud className="h-3.5 w-3.5 text-teal-600" />
                    {vm.name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {vm.os_label ?? 'ОС не указана'} · {vm.cpu} ядра · {vm.ram_gb} ГБ · {vm.disk_gb} ГБ
                  </p>
                </td>
                <td className="px-4 py-3">
                  {vm.ip_address ? <span className="font-mono">{vm.ip_address}</span> : <span className="text-xs text-muted-foreground">пока нет</span>}
                  {vm.connection_method && <p className="text-xs text-muted-foreground">{vm.connection_method}</p>}
                </td>
                <td className="px-4 py-3">
                  <p className="font-medium">{vm.department.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {vm.requester_name} ({vm.requester_nick})
                  </p>
                  {vm.purpose && <p className="text-xs text-muted-foreground">{vm.purpose}</p>}
                </td>
                <td className="px-4 py-3 tabular">{formatDateTime(vm.created_at)}</td>
                <td className="px-4 py-3">
                  <JiraRequestLink order={vm} />
                  {vm.request_done && <p className="text-xs text-danger">Задача закрыта в Jira — подтвердите или отклоните ВМ</p>}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap justify-end gap-1.5">
                    <Button size="sm" loading={confirm.isPending && confirm.variables === vm.id} onClick={() => approve(vm)}>
                      Подтвердить
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setRecreating(vm)}>
                      Пересоздать
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRejecting(vm)}>
                      Отклонить…
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </DataState>

      <ConfirmDialog
        open={!!recreating}
        onClose={() => setRecreating(null)}
        title={recreating ? `Пересоздать ${recreating.name}?` : ''}
        description="ВМ будет удалена в vCenter и создана заново из шаблона под тем же номером и именем. Заказчик увидит, что ВМ ещё проверяется."
        confirmLabel="Пересоздать"
        pending={recreate.isPending}
        onConfirm={doRecreate}
      />
      <RejectVmDialog vm={rejecting} onClose={() => setRejecting(null)} />
    </Card>
  )
}

function RejectVmDialog({ vm, onClose }: { vm: ExecutorVm | null; onClose: () => void }) {
  const reject = useRejectVm()
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')

  const close = () => {
    setReason('')
    setComment('')
    reject.reset()
    onClose()
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!vm) return
    try {
      await reject.mutateAsync({ id: vm.id, reason, comment: comment.trim() })
      toast.success(`${vm.name} отклонена, заказчик получил уведомление`)
      close()
    } catch {
      // текст ошибки показан в окне
    }
  }

  return (
    <Dialog
      open={!!vm}
      onOpenChange={(o) => !o && close()}
      title={vm ? `Отклонить ${vm.name}?` : ''}
      description="ВМ будет удалена, номер вернётся в Insight, заказчик получит уведомление с основанием и комментарием."
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
            {VM_REJECT_REASONS.map((r) => (
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
