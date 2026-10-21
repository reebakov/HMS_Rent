import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { DataState, FormError, QueryError } from '@/components/ui/data-state'
import { Field, Input, Select, Textarea } from '@/components/ui/input'
import { OrderDepartmentField, initialOrderDepartment } from '@/features/booking/OrderDepartment'
import { Tabs } from '@/components/ui/tabs'
import { useSession } from '@/auth/AuthProvider'
import { termLimit } from '@/features/booking/TermLimit'
import { useCreateBuild, useDepartments, useOrderOptions } from '@/lib/queries'
import { addDays, formatDate, todayLocal } from '@/lib/utils'

const VARIANTS = ['Типовая сборка', 'Своя конфигурация'] as const
type Variant = (typeof VARIANTS)[number]

/** Сборка по запросу: заявка исполнителям в Service Desk; собранный ПК выдают отдельно */
export function BuildOrderDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const session = useSession()
  const navigate = useNavigate()
  const options = useOrderOptions(open)
  const departments = useDepartments()
  const create = useCreateBuild()

  const [variant, setVariant] = useState<Variant>('Типовая сборка')
  const [build, setBuild] = useState('')
  const [custom, setCustom] = useState('')
  const [os, setOs] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [person, setPerson] = useState('')
  const [nick, setNick] = useState('')
  const [until, setUntil] = useState('')
  const [wantedBy, setWantedBy] = useState('')
  const [purpose, setPurpose] = useState('')

  useEffect(() => {
    if (!open) return
    setVariant('Типовая сборка')
    setBuild('')
    setCustom('')
    setOs('')
    setDepartmentId(initialOrderDepartment(session))
    setPerson(session.user.display_name)
    setNick(session.user.username.split('@')[0])
    setUntil('')
    setWantedBy('')
    setPurpose('')
    create.reset()
  }, [open])

  const today = todayLocal()
  const tomorrow = addDays(today, 1)
  // нет типовых сборок в «Настройках» — остаётся только своя конфигурация
  const typical = variant === 'Типовая сборка' && !!options.data?.builds.length
  // ISO-даты сравниваются строками; прошлую дату можно впечатать вручную в обход min
  const valid =
    (typical ? !!build : custom.trim().length >= 5) &&
    !!os &&
    !!departmentId &&
    person.trim().length >= 2 &&
    !!nick.trim() &&
    until >= today &&
    (!wantedBy || wantedBy >= tomorrow)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    try {
      const req = await create.mutateAsync({
        build: typical ? build : undefined,
        custom: typical ? undefined : custom,
        os_label: os,
        department_id: Number(departmentId),
        requester_name: person,
        requester_nick: nick,
        expected_return_at: until,
        wanted_by: wantedBy || undefined,
        purpose: purpose || undefined,
      })
      toast.success(`Заявка ${req.issue_key} на сборку отправлена — статус в «Моей аренде»`, {
        action: { label: 'Моя аренда', onClick: () => navigate('/my') },
      })
      onClose()
    } catch {
      /* ошибка показывается в окне */
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Сборка по запросу"
      description="Исполнители проверят комплектующие, соберут и настроят компьютер. Заявка и ответы — в «Моей аренде»."
      className="max-w-2xl"
      onSubmit={submit}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={create.isPending} disabled={!valid}>
            Отправить заявку
          </Button>
        </>
      }
    >
      <DataState query={options} errorTitle="Не удалось загрузить варианты сборки" loading={<p className="py-8 text-center text-muted-foreground">Загрузка…</p>}>
        {(o) => (
          <div className="space-y-5">
            {o.builds.length > 0 && <Tabs tabs={VARIANTS} value={variant} onChange={setVariant} />}

            {typical ? (
              <Field label="Типовая сборка" required>
                <Select value={build} onChange={(e) => setBuild(e.target.value)}>
                  <option value="" disabled>
                    Выберите сборку
                  </option>
                  {o.builds.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : (
              <Field label="Конфигурация" required hint="Процессор, память, диск, видеокарта — что важно для задачи">
                <Textarea value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Например: Ryzen 7, 32 ГБ, SSD 1 ТБ, RTX 3060" />
              </Field>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Операционная система" required>
                <Select value={os} onChange={(e) => setOs(e.target.value)}>
                  <option value="" disabled>
                    {o.os.length ? 'Выберите ОС' : 'Список ОС не настроен — напишите в HMS'}
                  </option>
                  {o.os.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              </Field>
              <OrderDepartmentField session={session} value={departmentId} onChange={setDepartmentId} departments={departments} />
              <Field label="Имя и фамилия" required>
                <Input value={person} onChange={(e) => setPerson(e.target.value)} />
              </Field>
              <Field label="Ник" required>
                <Input value={nick} onChange={(e) => setNick(e.target.value)} />
              </Field>
              <Field label="Вернуть до" required hint={`Дольше чем до ${formatDate(termLimit(today))} — по согласованию администратора`}>
                <Input type="date" min={today} value={until} onChange={(e) => setUntil(e.target.value)} />
              </Field>
              <Field label="Нужен к" hint="Необязательно: не раньше завтрашнего дня">
                <Input type="date" min={tomorrow} value={wantedBy} onChange={(e) => setWantedBy(e.target.value)} />
              </Field>
            </div>
            <Field label="Для чего нужен" hint="Необязательно">
              <Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Новый проект, нагрузочные тесты…" />
            </Field>

            <QueryError query={departments} title="Не удалось загрузить отделы" />
            {create.error && <FormError>{create.error.message}</FormError>}
          </div>
        )}
      </DataState>
    </Dialog>
  )
}
