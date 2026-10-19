import { useState } from 'react'
import { toast } from 'sonner'
import { Cloud, Loader2 } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Badge } from '@/components/ui/badge'
import { VM_STATUS } from '@/features/vms/MyVms'
import { useAdminVms, useReleaseVm } from '@/lib/queries'
import type { Vm } from '@/lib/types'
import { errorMessage, formatDate, formatDateTime } from '@/lib/utils'

/** Все виртуалки из конструктора: кто, когда, какие ресурсы; админ может удалить любую */
export function VmsPage() {
  const [showDeleted, setShowDeleted] = useState(false)
  const vms = useAdminVms(showDeleted)
  const release = useReleaseVm()
  const [removing, setRemoving] = useState<Vm | null>(null)

  const remove = async () => {
    if (!removing) return
    try {
      await release.mutateAsync(removing.id)
      toast.success(`${removing.name} будет удалена`)
      setRemoving(null)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const totals = (vms.data ?? []).filter((v) => v.status === 'ready').reduce(
    (acc, v) => ({ cpu: acc.cpu + v.cpu, ram: acc.ram + v.ram_gb, disk: acc.disk + v.disk_gb }),
    { cpu: 0, ram: 0, disk: 0 },
  )

  return (
    <>
      <PageHeader
        title="Виртуалки"
        description={`Работают сейчас: ${totals.cpu} ядер, ${totals.ram} ГБ памяти, ${totals.disk} ГБ дисков`}
        action={
          <label className="flex cursor-pointer items-center gap-2 text-[13px]">
            <input type="checkbox" className="h-4 w-4 accent-[hsl(var(--primary))]" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
            Показать удалённые
          </label>
        }
      />
      <Card>
        <DataState
          query={vms}
          errorTitle="Не удалось загрузить виртуалки"
          loading={<RowsSkeleton rows={5} className="h-12" />}
          empty={<EmptyState icon={Cloud} title="Виртуалок пока нет" description="Они появятся, когда сотрудники соберут их в конструкторе" />}
        >
          {(data) => (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[980px] text-left text-[13px]">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">№ заказа</th>
                    <th className="px-4 py-2.5 font-medium">ВМ</th>
                    <th className="px-4 py-2.5 font-medium">Ресурсы</th>
                    <th className="px-4 py-2.5 font-medium">Владелец</th>
                    <th className="px-4 py-2.5 font-medium">IP</th>
                    <th className="px-4 py-2.5 font-medium">Создана</th>
                    <th className="px-4 py-2.5 font-medium">Вернуть до</th>
                    <th className="px-4 py-2.5 font-medium">Статус</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.map((vm) => {
                    const st = VM_STATUS[vm.status]
                    return (
                      <tr key={vm.id} className="hover:bg-muted/40">
                        <td className="px-4 py-3 tabular text-muted-foreground">№{vm.order_number}</td>
                        <td className="px-4 py-3 font-semibold">{vm.name}</td>
                        <td className="px-4 py-3 tabular">{vm.os_label ? `${vm.os_label} · ` : ''}{vm.cpu} CPU · {vm.ram_gb} ГБ · {vm.disk_gb} ГБ</td>
                        <td className="px-4 py-3">
                          <p className="font-medium">{vm.department.name}</p>
                          <p className="text-xs text-muted-foreground">{vm.requester_name} ({vm.requester_nick})</p>
                        </td>
                        <td className="px-4 py-3 font-mono">{vm.ip_address ?? '—'}</td>
                        <td className="px-4 py-3 tabular">{formatDateTime(vm.created_at)}</td>
                        <td className="px-4 py-3 tabular">{vm.expected_return_at ? formatDate(vm.expected_return_at) : '—'}</td>
                        <td className="px-4 py-3">
                          <Badge tone={st.tone} dot={!st.busy}>
                            {st.busy && <Loader2 className="h-3 w-3 animate-spin" />}
                            {st.label}
                          </Badge>
                          {vm.error && <p className="mt-1 max-w-[260px] truncate text-xs text-danger" title={vm.error}>{vm.error}</p>}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {['ready', 'failed', 'queued'].includes(vm.status) && (
                            <Button size="sm" variant="ghost" onClick={() => setRemoving(vm)}>
                              Удалить
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </Card>

      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title={removing ? `Удалить виртуалку ${removing.name}?` : ''}
        description="Она будет выключена и удалена вместе с диском."
        confirmLabel="Удалить"
        pending={release.isPending}
        onConfirm={remove}
      />
    </>
  )
}
