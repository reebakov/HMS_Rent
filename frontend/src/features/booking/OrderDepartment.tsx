import { CircleAlert } from 'lucide-react'
import { DepartmentOptions, Field, Select } from '@/components/ui/input'
import type { QueryLike } from '@/components/ui/data-state'
import { LAST_DEPARTMENT_KEY, safeStorage } from '@/lib/storage'
import type { Department, Session } from '@/lib/types'

/** Отдел заказа при открытии формы: свой; админу, если своего нет, — тот, что выбирал в прошлый раз */
export function initialOrderDepartment(session: Session): string {
  const own = session.user.department_id
  if (own != null) return String(own)
  return session.user.role === 'admin' ? (safeStorage.get(LAST_DEPARTMENT_KEY) ?? '') : ''
}

/**
 * Отдел заказа. Сотрудник оформляет заказ на свой отдел и не выбирает его (без отдела заказать нельзя, его назначает
 * админ); админ может оформить на любой отдел.
 */
export function OrderDepartmentField({
  session,
  value,
  onChange,
  departments,
}: {
  session: Session
  value: string
  onChange: (id: string) => void
  departments: QueryLike<Department[]> & { isLoading?: boolean }
}) {
  if (session.user.role === 'admin') {
    return (
      <Field label="Отдел" required hint="Админ может оформить заказ на любой отдел">
        <Select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="" disabled>
            {departments.isLoading ? 'Загрузка…' : 'Выберите отдел'}
          </option>
          <DepartmentOptions departments={departments.data} />
        </Select>
      </Field>
    )
  }
  if (session.user.department_id == null) {
    return (
      <p role="alert" className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning/5 px-3 py-2 text-[13px] text-warning">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
        Вам не назначен отдел, поэтому заказ оформить нельзя. Обратитесь к администратору.
      </p>
    )
  }
  const own = departments.data?.find((d) => d.id === session.user.department_id)
  return (
    <Field label="Отдел" hint="Заказ оформляется на ваш отдел: его участники видят заказ и могут его продлить или вернуть">
      <p className="flex h-9 items-center rounded-lg border bg-muted/40 px-3 text-sm">{own?.name ?? (departments.isLoading ? 'Загрузка…' : '—')}</p>
    </Field>
  )
}
