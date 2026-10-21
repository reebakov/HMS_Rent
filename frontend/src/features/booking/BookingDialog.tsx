import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { FormError, QueryError } from '@/components/ui/data-state'
import { Field, Input, Select, Textarea } from '@/components/ui/input'
import { OrderDepartmentField, initialOrderDepartment } from '@/features/booking/OrderDepartment'
import { TierBadge } from '@/components/ui/badge'
import { SpecGrid } from '@/features/catalog/SpecGrid'
import { TermLimitNote, termLimit, toastTerm } from '@/features/booking/TermLimit'
import { useSession } from '@/auth/AuthProvider'
import { useCreateBooking, useDepartments, useExtendBooking, useExtendVm, useOrderOptions } from '@/lib/queries'
import { LAST_DEPARTMENT_KEY, safeStorage } from '@/lib/storage'
import type { Computer } from '@/lib/types'
import { addDays, formatDate, todayLocal } from '@/lib/utils'

export function BookingDialog({ computer, onClose }: { computer: Computer | null; onClose: () => void }) {
  const session = useSession()
  const navigate = useNavigate()
  const departments = useDepartments()
  const create = useCreateBooking()
  const osList = useOrderOptions(!!computer).data?.os ?? []

  const [departmentId, setDepartmentId] = useState('')
  const [name, setName] = useState('')
  const [nick, setNick] = useState('')
  const [until, setUntil] = useState('')
  const [purpose, setPurpose] = useState('')
  const [os, setOs] = useState('')

  // при каждом открытии — подставляем данные из рабочего аккаунта
  useEffect(() => {
    if (!computer) return
    setDepartmentId(initialOrderDepartment(session))
    setName(session.user.display_name)
    setNick(session.user.username.split('@')[0])
    setUntil('')
    setPurpose('')
    setOs('')
    create.reset()
  }, [computer?.id])

  const knownDepartment = departments.data?.some((d) => String(d.id) === departmentId)
  // ISO-даты сравниваются строками; прошлую дату можно впечатать вручную в обход min
  const canBook =
    !!departmentId && name.trim().length >= 2 && !!nick.trim() && !!knownDepartment && until >= todayLocal() &&
    (!osList.length || !!os) // ОС ставит исполнитель по заявке «подготовить ПК»

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!computer || !canBook) return
    try {
      const booking = await create.mutateAsync({
        computer_id: computer.id,
        department_id: Number(departmentId),
        requester_name: name,
        requester_nick: nick,
        purpose: purpose || undefined,
        expected_return_at: until,
        os_label: os || undefined,
      })
      safeStorage.set(LAST_DEPARTMENT_KEY, departmentId)
      toastTerm(`${booking.computer.name} закреплён за отделом «${booking.department.name}» · заказ №${booking.order_number}`, booking, {
        action: { label: 'Моя аренда', onClick: () => navigate('/my') },
      })
      onClose()
    } catch {
      /* ошибка показывается в форме */
    }
  }


  return (
    <Dialog
      open={!!computer}
      onOpenChange={(open) => !open && onClose()}
      title={computer ? `Бронирование ${computer.name}` : ''}
      description="Компьютер будет закреплён за вашим отделом. Вернуть его можно в разделе «Моя аренда»."
      className="max-w-xl"
      onSubmit={submit}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={create.isPending} disabled={!canBook}>
            Забронировать
          </Button>
        </>
      }
    >
      {computer && (
        <div className="space-y-5">
          <div className="rounded-xl border bg-muted/40 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="font-semibold">{computer.name}</span>
              <TierBadge tier={computer.tier} />
              {computer.location && <span className="ml-auto text-xs text-muted-foreground">{computer.location}</span>}
            </div>
            <SpecGrid computer={computer} className="xl:grid-cols-2" />
          </div>

          <OrderDepartmentField session={session} value={departmentId} onChange={setDepartmentId} departments={departments} />
          <QueryError query={departments} title="Не удалось загрузить отделы" />

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Имя и фамилия" required>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Иван Иванов" />
            </Field>
            <Field label="Ник / логин" required>
              <Input value={nick} onChange={(e) => setNick(e.target.value)} placeholder="i.ivanov" />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Планирую вернуть" required hint={`Без согласования — до ${formatDate(termLimit(todayLocal()))}`}>
              <Input type="date" min={todayLocal()} value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
            <Field label="Для чего нужен" hint="Необязательно">
              <Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Новый сотрудник, тесты…" />
            </Field>
          </div>

          <TermLimitNote until={until} base={todayLocal()} verb="оформится" />

          {osList.length > 0 && (
            <Field label="Операционная система" required hint="Её установит исполнитель — заявка уйдёт сразу после брони">
              <Select value={os} onChange={(e) => setOs(e.target.value)}>
                <option value="" disabled>
                  Выберите ОС
                </option>
                {osList.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          {create.error && <FormError>{create.error.message}</FormError>}
        </div>
      )}
    </Dialog>
  )
}

export function ReturnDialog({
  open,
  title,
  pending,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  pending: boolean
  onConfirm: (comment: string) => void
  onClose: () => void
}) {
  const [comment, setComment] = useState('')
  useEffect(() => setComment(''), [open])
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={title}
      description="Компьютер снова станет доступен для бронирования другим отделам."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button variant="danger" loading={pending} onClick={() => onConfirm(comment)}>
            Вернуть
          </Button>
        </>
      }
    >
      <Field label="Комментарий" hint="Например: «Всё работает» или «Шумит кулер»">
        <Textarea value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
    </Dialog>
  )
}

/** Что продлеваем: бронь ПК или ВМ — из «Моей аренды» или из просрочек у админа */
export interface ExtendTarget {
  kind: 'pc' | 'vm'
  id: number
  name: string
  due: string | null
}

/** Продление аренды ПК или ВМ: новый срок позже текущего (и не в прошлом) и необязательная причина */
export function ExtendDialog({ target, onClose }: { target: ExtendTarget | null; onClose: () => void }) {
  const extendPc = useExtendBooking()
  const extendVm = useExtendVm()
  const extend = target?.kind === 'vm' ? extendVm : extendPc
  const [until, setUntil] = useState('')
  const [comment, setComment] = useState('')

  useEffect(() => {
    if (!target) return
    setUntil('')
    setComment('')
    extendPc.reset()
    extendVm.reset()
  }, [target?.kind, target?.id])

  const today = todayLocal()
  const inFuture = !!target?.due && target.due >= today
  const min = inFuture ? addDays(target.due!, 1) : today
  const limitBase = inFuture ? target.due! : today // как на backend: у просроченного заказа лимит считается от сегодня
  const canExtend = until >= min // ISO-даты сравниваются строками; пустая строка меньше любой даты

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!target || !canExtend) return
    try {
      const order = await extend.mutateAsync({ id: target.id, expected_return_at: until, comment: comment || undefined })
      // при заявке админу срок сразу стоит не тот, что выбран: берём его из ответа
      toastTerm(`Аренда ${target.name} продлена до ${formatDate(order.requested_return_at ? order.expected_return_at : until)}`, order)
      onClose()
    } catch {
      /* ошибка показывается в форме */
    }
  }

  return (
    <Dialog
      open={!!target}
      onOpenChange={(open) => !open && onClose()}
      title={target ? `Продлить аренду ${target.name}` : ''}
      description={
        target?.due ? `Текущий срок — ${formatDate(target.due)}. Администраторы увидят продление.` : 'Администраторы увидят продление.'
      }
      onSubmit={submit}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={extend.isPending} disabled={!canExtend}>
            Продлить
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Новый срок" required hint={`Без согласования — до ${formatDate(termLimit(limitBase))}`}>
          <Input type="date" min={min} value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        <TermLimitNote until={until} base={limitBase} verb="продлится" />
        <Field label="Причина" hint="Необязательно">
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Тесты ещё идут…" />
        </Field>
        {extend.error && <FormError>{extend.error.message}</FormError>}
      </div>
    </Dialog>
  )
}
