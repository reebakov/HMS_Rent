import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cpu, HardDrive, MemoryStick, Monitor, Terminal } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { DataState, FormError, QueryError } from '@/components/ui/data-state'
import { Field, Input } from '@/components/ui/input'
import { OrderDepartmentField, initialOrderDepartment } from '@/features/booking/OrderDepartment'
import { useSession } from '@/auth/AuthProvider'
import { TermLimitNote, termLimit, toastTerm } from '@/features/booking/TermLimit'
import { useCreateVm, useDepartments, useVmOptions } from '@/lib/queries'
import { cn, formatDate, todayLocal } from '@/lib/utils'

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
    setCpu(o.min_cpu)
    setRam(o.min_ram_gb)
    setDisk(o.min_disk_gb)
    setTemplateKey(o.templates.find((t) => t.available)?.key ?? '')
    setDepartmentId(initialOrderDepartment(session))
    setPerson(session.user.display_name)
    setNick(session.user.username.split('@')[0])
    setUntil('')
    create.reset()
  }, [open, o?.min_cpu])

  const tmpl = o?.templates.find((t) => t.key === templateKey)
  const minDisk = Math.max(o?.min_disk_gb ?? 0, tmpl?.min_disk_gb ?? 0)
  // ISO-даты сравниваются строками; прошлую дату можно впечатать вручную в обход min
  const valid =
    o?.enabled && tmpl?.available && departmentId && person.trim().length >= 2 && nick.trim() && until >= todayLocal()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    try {
      const vm = await create.mutateAsync({
        cpu, ram_gb: ram, disk_gb: Math.max(disk, minDisk), department_id: Number(departmentId), template_key: templateKey,
        requester_name: person, requester_nick: nick, expected_return_at: until,
      })
      toastTerm(`Заказ №${vm.order_number}: виртуалка ${vm.name} создаётся — примерно 10 минут`, vm)
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
      onSubmit={submit}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={create.isPending} disabled={!valid}>
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
              <p className="rounded-lg bg-muted px-3 py-2 text-[13px] text-muted-foreground">
                Имя виртуалки (A1…) назначается автоматически: номер берётся из свободных в Insight.
              </p>

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

              {o.sizes.length > 0 && (
                <div>
                  <p className="mb-2 text-[13px] font-medium">Размер</p>
                  <div className="flex flex-wrap gap-2">
                    {o.sizes.map((s) => {
                      const active = cpu === s.cpu && ram === s.ram_gb && Math.max(disk, minDisk) === Math.max(s.disk_gb, minDisk)
                      return (
                        <button
                          key={s.label}
                          type="button"
                          onClick={() => {
                            setCpu(s.cpu)
                            setRam(s.ram_gb)
                            setDisk(s.disk_gb)
                          }}
                          className={cn(
                            'rounded-xl border px-3 py-2 text-left text-[13px] transition-colors',
                            active ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted/50',
                          )}
                        >
                          <span className="block font-medium">{s.label}</span>
                          <span className="block text-xs text-muted-foreground">
                            {s.cpu} ядра · {s.ram_gb} ГБ · {Math.max(s.disk_gb, minDisk)} ГБ
                          </span>
                        </button>
                      )
                    })}
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">Или настройте ресурсы ползунками ниже</p>
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-3">
                <Amount icon={Cpu} label="Ядра" unit="шт" value={cpu} range={{ min: o.min_cpu, max: o.max_cpu, step: 1 }} onChange={setCpu} />
                <Amount icon={MemoryStick} label="Память" unit="ГБ" value={ram} range={{ min: o.min_ram_gb, max: o.max_ram_gb, step: 2 }} onChange={setRam} />
                <Amount icon={HardDrive} label="Диск" unit="ГБ" value={Math.max(disk, minDisk)} range={{ min: minDisk, max: o.max_disk_gb, step: 10 }} onChange={setDisk} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <OrderDepartmentField session={session} value={departmentId} onChange={setDepartmentId} departments={departments} />
                <Field label="Вернуть до" required hint={`Без согласования — до ${formatDate(termLimit(todayLocal()))}`}>
                  <Input type="date" min={todayLocal()} value={until} onChange={(e) => setUntil(e.target.value)} />
                </Field>
                <Field label="Имя и фамилия" required>
                  <Input value={person} onChange={(e) => setPerson(e.target.value)} />
                </Field>
                <Field label="Ник" required>
                  <Input value={nick} onChange={(e) => setNick(e.target.value)} />
                </Field>
              </div>

              <TermLimitNote until={until} base={todayLocal()} verb="оформится" />

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
