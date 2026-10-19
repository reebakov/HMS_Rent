import { useState } from 'react'
import { toast } from 'sonner'
import { Cloud, Copy, Trash2 } from 'lucide-react'
import { VmStatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { DataState } from '@/components/ui/data-state'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useMyVms, useReleaseVm } from '@/lib/queries'
import type { ServiceRequest, Vm } from '@/lib/types'
import { ReportProblemButton, RequestBadges } from '@/features/support/ServiceDesk'
import { canReleaseVm } from '@/lib/dictionaries'
import { errorMessage, formatDate, formatDateTime } from '@/lib/utils'

/** Виртуалки в «Моей аренде». Заявки Service Desk по ВМ — через пропсы от страницы */
export function MyVms({
  requestsFor = () => [],
  onReport,
  onOpenRequest = () => undefined,
}: {
  requestsFor?: (vmId: number) => ServiceRequest[]
  onReport?: (vm: Vm) => void
  onOpenRequest?: (id: number) => void
} = {}) {
  const vms = useMyVms()
  const release = useReleaseVm()
  const [confirm, setConfirm] = useState<Vm | null>(null)
  const alive = vms.data?.filter((v) => v.status !== 'deleted') ?? []

  const doRelease = async () => {
    if (!confirm) return
    try {
      await release.mutateAsync(confirm.id)
      toast.success(`${confirm.name} будет удалена`)
      setConfirm(null)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <DataState
      query={vms}
      errorTitle="Не удалось загрузить виртуальные машины"
      errorCardClass="mb-8"
      loading={null}
      isEmpty={() => alive.length === 0}
      empty={null}
    >
      {() => (
        <Card className="mb-8">
          <CardHeader title="Виртуальные машины" description="Созданы в конструкторе. Подключение — по VNC" />
          <div className="divide-y">
            {alive.map((vm) => (
              <div key={vm.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500/10 text-teal-700 dark:text-teal-300">
                  <Cloud className="h-5 w-5" />
                </div>
                <div className="min-w-[180px] flex-1">
                  <p className="font-semibold">
                    {vm.name} <span className="ml-1 text-xs font-medium text-muted-foreground">Заказ №{vm.order_number}</span>
                  </p>
                  <p className="text-[13px] text-muted-foreground">
                    {vm.os_label ? `${vm.os_label} · ` : ''}{vm.cpu} ядра · {vm.ram_gb} ГБ · {vm.disk_gb} ГБ · {vm.department.name}
                  </p>
                </div>
                <div className="text-[13px]">
                  {vm.ip_address ? (
                    <button
                      className="flex items-center gap-1.5 font-mono font-medium hover:text-primary"
                      title="Скопировать"
                      onClick={() => navigator.clipboard.writeText(vm.ip_address!).then(() => toast.success('IP скопирован'))}
                    >
                      {vm.ip_address} <Copy className="h-3.5 w-3.5" />
                    </button>
                  ) : vm.status === 'ready' ? (
                    <span className="text-muted-foreground">Windows загружается…</span>
                  ) : null}
                  <p className="text-xs text-muted-foreground">
                    с {formatDateTime(vm.created_at)}
                    {vm.expected_return_at && ` · до ${formatDate(vm.expected_return_at)}`}
                  </p>
                </div>
                <VmStatusBadge status={vm.status} />
                <RequestBadges requests={requestsFor(vm.id)} onOpen={onOpenRequest} />
                {onReport && vm.status !== 'deleting' && <ReportProblemButton onClick={() => onReport(vm)} />}
                {canReleaseVm(vm.status) && (
                  <Button variant="outline" size="sm" onClick={() => setConfirm(vm)}>
                    <Trash2 className="h-3.5 w-3.5" />
                    {vm.status === 'queued' ? 'Отменить' : 'Отказаться'}
                  </Button>
                )}
                {vm.status === 'failed' && vm.error && (
                  <p className="w-full rounded-lg bg-danger/5 px-3 py-2 text-xs text-danger">{vm.error}</p>
                )}
              </div>
            ))}
          </div>

          <ConfirmDialog
            open={!!confirm}
            onClose={() => setConfirm(null)}
            title={confirm ? `Отказаться от ${confirm.name}?` : ''}
            description="Виртуалка будет выключена и удалена вместе с диском. Сохраните нужные файлы заранее."
            confirmLabel="Удалить"
            pending={release.isPending}
            onConfirm={doRelease}
          >
            <p className="text-[13px] text-muted-foreground">Отменить удаление после подтверждения будет нельзя.</p>
          </ConfirmDialog>
        </Card>
      )}
    </DataState>
  )
}
