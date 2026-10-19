import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CheckCircle2, CircleAlert, Server } from 'lucide-react'
import { Card, CardHeader, PageHeader, Skeleton } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { DataState } from '@/components/ui/data-state'
import { Field, Input } from '@/components/ui/input'
import { useAppSettings, useSaveSettings, useVsphereCheck } from '@/lib/queries'
import type { AppSettings } from '@/lib/types'
import { errorMessage } from '@/lib/utils'
import { VmTemplatesEditor } from '@/features/admin/VmTemplatesEditor'

type NumKey = { [K in keyof AppSettings]: AppSettings[K] extends number ? K : never }[keyof AppSettings]

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl border p-4">
      <span>
        <span className="block text-[13px] font-medium">{label}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
      </span>
      <input type="checkbox" className="mt-1 h-5 w-5 accent-[hsl(var(--primary))]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  )
}

/** Настройки без правки кода: сохраняются в базе и сразу применяются в API и worker */
export function SettingsPage() {
  const settings = useAppSettings()
  return (
    <DataState
      query={settings}
      errorTitle="Не удалось загрузить настройки"
      errorCardClass=""
      loading={<Skeleton className="h-96 rounded-xl" />}
    >
      {(data) => <SettingsForm data={data} />}
    </DataState>
  )
}

function SettingsForm({ data }: { data: AppSettings }) {
  const save = useSaveSettings()
  const check = useVsphereCheck()
  const [form, setForm] = useState(data)

  useEffect(() => setForm(data), [data])

  const num = (key: NumKey, label: string, hint?: string) => (
    <Field label={label} hint={hint}>
      <Input type="number" value={form[key]} onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })} />
    </Field>
  )
  const dirty = JSON.stringify(form) !== JSON.stringify(data)

  const submit = async () => {
    const { vsphere_configured: _a, vcenter_host: _b, ...changes } = form
    try {
      await save.mutateAsync(changes)
      toast.success('Настройки сохранены и уже действуют')
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <>
      <PageHeader
        title="Настройки"
        description="Меняются без перезапуска: портал и фоновый процесс подхватывают их в течение нескольких секунд"
        action={
          <Button onClick={submit} disabled={!dirty} loading={save.isPending}>
            Сохранить
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Синхронизация с Insight" />
          <div className="space-y-4 p-5">
            {num('insight_sync_interval_min', 'Интервал синхронизации, минут', 'Как часто забирать изменения из Insight. Бронь и возврат отправляются в Insight сразу')}
            <Toggle
              checked={form.insight_writeback}
              onChange={(v) => setForm({ ...form, insight_writeback: v })}
              label="Запись статусов в Insight"
              hint="Бронь → «Используется», возврат → «Ожидает». Меняется только атрибут Status"
            />
            {num('catalog_refresh_sec', 'Автообновление каталога, секунд', 'Как часто страница каталога сама обновляет список ПК')}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Конструктор виртуалок"
            description={data.vsphere_configured ? `vCenter: ${data.vcenter_host}` : 'vCenter не настроен — впишите VCENTER_* в .env'}
            action={
              <Button size="sm" variant="outline" loading={check.isPending} onClick={() => check.mutate()} disabled={!data.vsphere_configured}>
                <Server className="h-3.5 w-3.5" />
                Проверить
              </Button>
            }
          />
          <div className="space-y-4 p-5">
            {check.data && (
              <div className={`rounded-lg px-3 py-2.5 text-[13px] ${check.data.ok ? 'bg-success/5 text-success' : 'bg-danger/5 text-danger'}`}>
                {check.data.ok ? (
                  <span className="flex gap-2">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                    {`Всё найдено: ${check.data.datacenter} → ${check.data.pool}, шаблон ${check.data.template} (${check.data.template_cpu} CPU, ${check.data.template_ram_gb} ГБ, диск ${check.data.template_disk_gb} ГБ)`}
                  </span>
                ) : (
                  <span className="flex gap-2">
                    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    {check.data.error}
                  </span>
                )}
              </div>
            )}
            <Toggle
              checked={form.vm_enabled}
              onChange={(v) => setForm({ ...form, vm_enabled: v })}
              label="Конструктор включён"
              hint="Выключите, чтобы временно запретить создавать новые виртуалки"
            />
            <div className="grid gap-4 sm:grid-cols-2">
              {num('vm_min_cpu', 'Ядер от')}
              {num('vm_max_cpu', 'Ядер до')}
              {num('vm_min_ram_gb', 'Памяти от, ГБ')}
              {num('vm_max_ram_gb', 'Памяти до, ГБ')}
              {num('vm_min_disk_gb', 'Диск от, ГБ', 'Не меньше диска шаблона')}
              {num('vm_max_disk_gb', 'Диск до, ГБ')}
              {num('vm_max_per_user', 'Виртуалок на человека')}
            </div>
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="Шаблоны ОС для виртуалок" description="Какие ОС можно выбрать в конструкторе и из каких шаблонов vCenter их клонировать" />
        <VmTemplatesEditor value={form.vm_templates ?? []} onChange={(v) => setForm({ ...form, vm_templates: v })} />
      </Card>
    </>
  )
}
