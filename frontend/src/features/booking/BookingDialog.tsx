import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Field, Input, Select, Textarea } from '@/components/ui/input'
import { TierBadge } from '@/components/ui/badge'
import { SpecGrid } from '@/features/catalog/SpecGrid'
import { useSession } from '@/auth/AuthProvider'
import { useCreateBooking, useDepartments } from '@/lib/queries'
import type { Computer } from '@/lib/types'

const LAST_DEPARTMENT_KEY = 'hmsrent:last-department'

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
    setDepartmentId(localStorage.getItem(LAST_DEPARTMENT_KEY) ?? '')
    setName(session.user.display_name)
    setNick(session.user.username)
    setUntil('')
    setPurpose('')
    create.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [computer?.id])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!computer) return
    try {
      const booking = await create.mutateAsync({
        computer_id: computer.id,
        department_id: Number(departmentId),
        requester_name: name,
        requester_nick: nick,
        purpose: purpose || undefined,
        expected_return_at: until || null,
      })
      localStorage.setItem(LAST_DEPARTMENT_KEY, departmentId)
      toast.success(`${booking.computer.name} закреплён за отделом «${booking.department.name}»`, {
        action: { label: 'Мои брони', onClick: () => navigate('/my') },
      })
      onClose()
    } catch {
      /* ошибка показывается в форме */
    }
  }

  const today = new Date().toISOString().slice(0, 10)
  const valid = departmentId && name.trim().length >= 2 && nick.trim()
  const knownDepartment = departments.data?.some((d) => String(d.id) === departmentId)

  return (
    <Dialog
      open={!!computer}
      onOpenChange={(open) => !open && onClose()}
      title={computer ? `Бронирование ${computer.name}` : ''}
      description="Компьютер будет закреплён за вашим отделом. Вернуть его можно в разделе «Мои бронирования»."
      className="max-w-xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" form="booking-form" loading={create.isPending} disabled={!valid || !knownDepartment}>
            Забронировать
          </Button>
        </>
      }
    >
      {computer && (
        <form id="booking-form" onSubmit={submit} className="space-y-5">
          <div className="rounded-xl border bg-muted/40 p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="font-semibold">{computer.name}</span>
              <TierBadge tier={computer.tier} />
              {computer.location && <span className="ml-auto text-xs text-muted-foreground">{computer.location}</span>}
            </div>
            <SpecGrid computer={computer} className="xl:grid-cols-2" />
          </div>

          <Field label="Отдел" required hint="Если вашего отдела нет в списке — напишите в ИТ-отдел">
            <Select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
              <option value="" disabled>
                {departments.isLoading ? 'Загрузка…' : 'Выберите отдел'}
              </option>
              {departments.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </Select>
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Имя и фамилия" required>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Иван Иванов" />
            </Field>
            <Field label="Ник / логин" required>
              <Input value={nick} onChange={(e) => setNick(e.target.value)} placeholder="i.ivanov" />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Планирую вернуть" hint="Необязательно">
              <Input type="date" min={today} value={until} onChange={(e) => setUntil(e.target.value)} />
            </Field>
            <Field label="Для чего нужен" hint="Необязательно">
              <Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Новый сотрудник, тесты…" />
            </Field>
          </div>

          {create.error && (
            <div className="rounded-lg border border-danger/20 bg-danger/5 px-3 py-2.5 text-[13px] text-danger">
              {create.error.message}
            </div>
          )}
        </form>
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
