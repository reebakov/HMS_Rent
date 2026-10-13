import { useState } from 'react'
import { toast } from 'sonner'
import { Cloud, Copy, Loader2, Trash2 } from 'lucide-react'
import { Badge, type Tone } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { useMyVms, useReleaseVm } from '@/lib/queries'
import type { Vm, VmStatus } from '@/lib/types'
import { formatDate, formatDateTime } from '@/lib/utils'

export const VM_STATUS: Record<VmStatus, { label: string; tone: Tone; busy?: boolean }> = {
  queued: { label: 'В очереди', tone: 'muted', busy: true },
  creating: { label: 'Создаётся', tone: 'primary', busy: true },
  ready: { label: 'Готова', tone: 'success' },
  failed: { label: 'Ошибка', tone: 'danger' },
  deleting: { label: 'Удаляется', tone: 'warning', busy: true },
  deleted: { label: 'Удалена', tone: 'muted' },
}

/** Виртуалки сотрудника в «Моей аренде» */
export function MyVms() {
  const { data } = useMyVms()
  const release = useReleaseVm()
  const [confirm, setConfirm] = useState<Vm | null>(null)
  const alive = data?.filter((v) => v.status !== 'deleted') ?? []

  if (!alive.length) return null

  const doRelease = async () => {
    if (!confirm) return
    try {
      await release.mutateAsync(confirm.id)
      toast.success(`${confirm.name} будет удалена`)
      setConfirm(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  return (
    <Card className="mb-8">
      <CardHeader title="Виртуальные машины" description="Созданы в конструкторе. Подключение — по RDP на IP-адрес" />
      <div className="divide-y">
        {alive.map((vm) => {
          const st = VM_STATUS[vm.status]
          return (
            <div key={vm.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500/10 text-teal-700 dark:text-teal-300">
                <Cloud className="h-5 w-5" />
              </div>
              <div className="min-w-[180px] flex-1">
                <p className="font-semibold">{vm.name}</p>
                <p className="text-[13px] text-muted-foreground">
                  {vm.cpu} ядра · {vm.ram_gb} ГБ · {vm.disk_gb} ГБ · {vm.department.name}
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
              <Badge tone={st.tone} dot={!st.busy}>
                {st.busy && <Loader2 className="h-3 w-3 animate-spin" />}
                {st.label}
              </Badge>
              {(vm.status === 'ready' || vm.status === 'failed' || vm.status === 'queued') && (
                <Button variant="outline" size="sm" onClick={() => setConfirm(vm)}>
                  <Trash2 className="h-3.5 w-3.5" />
                  {vm.status === 'queued' ? 'Отменить' : 'Отказаться'}
                </Button>
              )}
              {vm.status === 'failed' && vm.error && (
                <p className="w-full rounded-lg bg-danger/5 px-3 py-2 text-xs text-danger">{vm.error}</p>
              )}
            </div>
          )
        })}
      </div>

      <Dialog
        open={!!confirm}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm ? `Отказаться от ${confirm.name}?` : ''}
        description="Виртуалка будет выключена и удалена вместе с диском. Сохраните нужные файлы заранее."
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              Отмена
            </Button>
            <Button variant="danger" loading={release.isPending} onClick={doRelease}>
              Удалить
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-muted-foreground">Отменить удаление после подтверждения будет нельзя.</p>
      </Dialog>
    </Card>
  )
}
