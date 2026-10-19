import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Cpu, HardDrive, MemoryStick, Monitor, Terminal } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { DataState, FormError, QueryError } from '@/components/ui/data-state'
import { DepartmentOptions, Field, Input, Select } from '@/components/ui/input'
import { useSession } from '@/auth/AuthProvider'
import { useCreateVm, useDepartments, useVmOptions } from '@/lib/queries'
import { LAST_DEPARTMENT_KEY, safeStorage } from '@/lib/storage'
import { cn, todayLocal } from '@/lib/utils'

type Range = { min: number; max: number; step: number }

function Amount({ icon: Icon, label, unit, value, range, onChange }: {
  icon: typeof Cpu
  label: string
  unit: string
  value: number
  range: Range
  onChange: (v: number) => void
}) {
  return (
    <div className="rounded-xl border p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="flex items-center gap-2 text-[13px] font-medium">
          <Icon className="h-4 w-4 text-muted-foreground" />
          {label}
        </span>
        <span className="text-lg font-semibold tabular">
          {value} <span className="text-[13px] font-normal text-muted-foreground">{unit}</span>
        </span>
      </div>
      <input
        type="range"
        aria-label={label}
        className="w-full accent-[hsl(var(--primary))]"
        min={range.min}
        max={range.max}
        step={range.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{range.min}</span>
        <span>{range.max}</span>
      </div>
    </div>
  )
}

export function VmBuilderDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const session = useSession()
  const navigate = useNavigate()
  const options = useVmOptions(open)
  const departments = useDepartments()
  const create = useCreateVm()
  const o = options.data

  const [name, setName] = useState('')
  const [cpu, setCpu] = useState(2)
  const [ram, setRam] = useState(4)
  const [disk, setDisk] = useState(50)
  const [templateKey, setTemplateKey] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [person, setPerson] = useState('')
  const [nick, setNick] = useState('')
  const [until, setUntil] = useState('')

  useEffect(() => {
    if (!open || !o) return
    setName('')
    setCpu(o.min_cpu)
    setRam(o.min_ram_gb)
    setDisk(o.min_disk_gb)
    setTemplateKey(o.templates.find((t) => t.available)?.key ?? '')
    setDepartmentId(String(session.user.department_id ?? safeStorage.get(LAST_DEPARTMENT_KEY) ?? ''))
    setPerson(session.user.display_name)
    setNick(session.user.username.split('@')[0])
    setUntil('')
    create.reset()
  }, [open, o?.min_cpu])

  const nameOk = /^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$/.test(name)
  const tmpl = o?.templates.find((t) => t.key === templateKey)
  const minDisk = Math.max(o?.min_disk_gb ?? 0, tmpl?.min_disk_gb ?? 0)
  const valid = o?.enabled && tmpl?.available && nameOk && departmentId && person.trim().length >= 2 && nick.trim()

  const submit = async () => {
    try {
      const vm = await create.mutateAsync({
        name, cpu, ram_gb: ram, disk_gb: Math.max(disk, minDisk), department_id: Number(departmentId), template_key: templateKey,
        requester_name: person, requester_nick: nick, expected_return_at: until || null,
      })
      toast.success(`Заказ №${vm.order_number}: виртуалка ${vm.name} создаётся — примерно 10 минут`)
      onClose()
      navigate('/my')
    } catch {
      /* ошибка показывается в окне */
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Конструктор виртуалки"
      description={tmpl ? `Виртуальная машина будет создана на ${tmpl.label}. Примерное время создания — около 10 минут.` : 'Выберите операционную систему и ресурсы'}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={submit} loading={create.isPending} disabled={!valid}>
            Создать
          </Button>
        </>
      }
    >
      <DataState
        query={options}
        errorTitle="Не удалось загрузить параметры конструктора"
        loading={
          <p className="py-8 text-center text-muted-foreground">Загрузка…</p>
        }
      >
        {(o) =>
          !o.enabled ? (
            <div className="rounded-lg border border-warning/25 bg-warning/5 px-4 py-3 text-[13px] text-warning">{o.reason}</div>
          ) : (
            <div className="space-y-5">
              <Field
                label="Имя виртуалки"
                required
                hint={`В vCenter будет «${o.name_prefix}${name || 'имя'}». Латиница, цифры и дефис, 3–20 символов`}
                error={name && !nameOk ? 'Только a–z, 0–9 и дефис; не начинать и не заканчивать дефисом' : undefined}
              >
                <Input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="design-01" />
              </Field>

              <div>
                <p className="mb-2 text-[13px] font-medium">Операционная система</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {o.templates.map((t) => {
                    const Icon = t.os === 'linux' ? Terminal : Monitor
                    return (
                      <button
                        key={t.key}
                        type="button"
                        disabled={!t.available}
                        onClick={() => setTemplateKey(t.key)}
                        className={cn(
                          'flex items-center gap-3 rounded-xl border p-3 text-left text-[13px] transition-colors',
                          t.key === templateKey ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted/50',
                          !t.available && 'cursor-not-allowed opacity-50 hover:bg-transparent',
                        )}
                      >
                        <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium">{t.label}</span>
                          <span className="block text-xs text-muted-foreground">{t.available ? `диск от ${t.min_disk_gb} ГБ` : 'скоро'}</span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Amount icon={Cpu} label="Ядра" unit="шт" value={cpu} range={{ min: o.min_cpu, max: o.max_cpu, step: 1 }} onChange={setCpu} />
                <Amount icon={MemoryStick} label="Память" unit="ГБ" value={ram} range={{ min: o.min_ram_gb, max: o.max_ram_gb, step: 2 }} onChange={setRam} />
                <Amount icon={HardDrive} label="Диск" unit="ГБ" value={Math.max(disk, minDisk)} range={{ min: minDisk, max: o.max_disk_gb, step: 10 }} onChange={setDisk} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Отдел" required>
                  <Select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
                    <option value="" disabled>
                      Выберите отдел
                    </option>
                    <DepartmentOptions departments={departments.data} />
                  </Select>
                </Field>
                <Field label="Вернуть до" hint="Необязательно">
                  <Input type="date" min={todayLocal()} value={until} onChange={(e) => setUntil(e.target.value)} />
                </Field>
                <Field label="Имя и фамилия" required>
                  <Input value={person} onChange={(e) => setPerson(e.target.value)} />
                </Field>
                <Field label="Ник" required>
                  <Input value={nick} onChange={(e) => setNick(e.target.value)} />
                </Field>
              </div>

              <QueryError query={departments} title="Не удалось загрузить отделы" />

              <p className="text-xs text-muted-foreground">
                Занято виртуалок: {o.used_by_me} из {o.max_per_user}. Диск больше {o.min_disk_gb} ГБ нужно будет расширить в Windows
                («Управление дисками» → «Расширить том»).
              </p>

              {create.error && <FormError>{create.error.message}</FormError>}
            </div>
          )
        }
      </DataState>
    </Dialog>
  )
}
