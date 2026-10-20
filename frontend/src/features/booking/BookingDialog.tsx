import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { FormError, QueryError } from '@/components/ui/data-state'
import { DepartmentOptions, Field, Input, Select, Textarea } from '@/components/ui/input'
import { TierBadge } from '@/components/ui/badge'
import { SpecGrid } from '@/features/catalog/SpecGrid'
import { useSession } from '@/auth/AuthProvider'
import { useCreateBooking, useDepartments, useExtendBooking, useExtendVm } from '@/lib/queries'
import { LAST_DEPARTMENT_KEY, safeStorage } from '@/lib/storage'
import type { Computer } from '@/lib/types'
import { addDays, formatDate, todayLocal } from '@/lib/utils'

export function BookingDialog({ computer, onClose }: { computer: Computer | null; onClose: () => void }) {
  const session = useSession()
  const navigate = useNavigate()
  const departments = useDepartments()
  const create = useCreateBooking()

  const [departmentId, setDepartmentId] = useState('')
  const [name, setName] = useState('')
  const [nick, setNick] = useState('')
  const [until, setUntil] = useState('')
  const [purpose, setPurpose] = useState('')

  // при каждом открытии — подставляем данные из рабочего аккаунта
  useEffect(() => {
    if (!computer) return
    setDepartmentId(safeStorage.get(LAST_DEPARTMENT_KEY) ?? '')
    setName(session.user.display_name)
    setNick(session.user.username.split('@')[0])
    setUntil('')
    setPurpose('')
    create.reset()
  }, [computer?.id])

  const knownDepartment = departments.data?.some((d) => String(d.id) === departmentId)
  // ISO-даты сравниваются строками; прошлую дату можно впечатать вручную в обход min
  const canBook =
    !!departmentId && name.trim().length >= 2 && !!nick.trim() && !!knownDepartment && until >= todayLocal()

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
      })
      safeStorage.set(LAST_DEPARTMENT_KEY, departmentId)
      toast.success(`${booking.computer.name} закреплён за отделом «${booking.department.name}» · заказ №${booking.order_number}`, {
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

          <Field label="Отдел" required hint="Если вашего отдела нет в списке — напишите в HMS">
            <Select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
              <option value="" disabled>
                {departments.isLoading ? 'Загрузка…' : 'Выберите отдел'}
              </option>
              <DepartmentOptions departments={departments.data} />
            </Select>
          </Field>
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
            <Field label="Планирую вернуть" required>
              <Input type="date" min={todayLocal()} value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
            <Field label="Для чего нужен" hint="Необязательно">
              <Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Новый сотрудник, тесты…" />
            </Field>
          </div>

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
  const min = target?.due && target.due >= today ? addDays(target.due, 1) : today
  const canExtend = until >= min // ISO-даты сравниваются строками; пустая строка меньше любой даты

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!target || !canExtend) return
    try {
      await extend.mutateAsync({ id: target.id, expected_return_at: until, comment: comment || undefined })
      toast.success(`Аренда ${target.name} продлена до ${formatDate(until)}`)
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
        <Field label="Новый срок" required>
          <Input type="date" min={min} value={until} onChange={(e) => setUntil(e.target.value)} />
        </Field>
        <Field label="Причина" hint="Необязательно">
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Тесты ещё идут…" />
        </Field>
        {extend.error && <FormError>{extend.error.message}</FormError>}
      </div>
    </Dialog>
  )
}
