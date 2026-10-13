import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Cpu, HardDrive, MemoryStick } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/input'
import { useSession } from '@/auth/AuthProvider'
import { useCreateVm, useDepartments, useVmOptions } from '@/lib/queries'

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
    setDepartmentId(String(session.user.department_id ?? localStorage.getItem('hmsrent:last-department') ?? ''))
    setPerson(session.user.display_name)
    setNick(session.user.username.split('@')[0])
    setUntil('')
    create.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, o?.min_cpu])

  const nameOk = /^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$/.test(name)
  const valid = o?.enabled && nameOk && departmentId && person.trim().length >= 2 && nick.trim()

  const submit = async () => {
    try {
      const vm = await create.mutateAsync({
        name, cpu, ram_gb: ram, disk_gb: disk, department_id: Number(departmentId),
        requester_name: person, requester_nick: nick, expected_return_at: until || null,
      })
      toast.success(`Виртуалка ${vm.name} создаётся — это займёт несколько минут`)
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
      description={o ? `Windows 10 на основе шаблона ${o.template}. Готова через несколько минут после создания.` : ' '}
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
      {!o ? (
        <p className="py-8 text-center text-muted-foreground">Загрузка…</p>
      ) : !o.enabled ? (
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

          <div className="grid gap-3 sm:grid-cols-3">
            <Amount icon={Cpu} label="Ядра" unit="шт" value={cpu} range={{ min: o.min_cpu, max: o.max_cpu, step: 1 }} onChange={setCpu} />
            <Amount icon={MemoryStick} label="Память" unit="ГБ" value={ram} range={{ min: o.min_ram_gb, max: o.max_ram_gb, step: 2 }} onChange={setRam} />
            <Amount icon={HardDrive} label="Диск" unit="ГБ" value={disk} range={{ min: o.min_disk_gb, max: o.max_disk_gb, step: 10 }} onChange={setDisk} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Отдел" required>
              <Select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
                <option value="" disabled>
                  Выберите отдел
                </option>
                {departments.data?.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Вернуть до" hint="Необязательно">
              <Input type="date" min={new Date().toISOString().slice(0, 10)} value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
            <Field label="Имя и фамилия" required>
              <Input value={person} onChange={(e) => setPerson(e.target.value)} />
            </Field>
            <Field label="Ник" required>
              <Input value={nick} onChange={(e) => setNick(e.target.value)} />
            </Field>
          </div>

          <p className="text-xs text-muted-foreground">
            Занято виртуалок: {o.used_by_me} из {o.max_per_user}. Диск больше {o.min_disk_gb} ГБ нужно будет расширить в Windows
            («Управление дисками» → «Расширить том»).
          </p>

          {create.error && (
            <div className="rounded-lg border border-danger/20 bg-danger/5 px-3 py-2.5 text-[13px] text-danger">
              {create.error.message}
            </div>
          )}
        </div>
      )}
    </Dialog>
  )
}
