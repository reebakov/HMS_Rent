import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { UserPlus, Users } from 'lucide-react'
import { Card, EmptyState } from '@/components/ui/card'
import { DataState, QueryError, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog } from '@/components/ui/dialog'
import { DepartmentOptions, Field, Input, SearchInput, Select } from '@/components/ui/input'
import { useAdminUsers, useDepartments, useSaveUser } from '@/lib/queries'
import type { AdminUserRow } from '@/lib/types'
import { errorMessage, formatRelative } from '@/lib/utils'


/** Поиск по ФИО, нику (логину) и почте без учёта регистра */
const matches = (u: AdminUserRow, q: string) =>
  [u.display_name, u.username, u.email ?? ''].some((v) => v.toLowerCase().includes(q))

/** Сотрудники и их отделы: от отдела зависит, какие пулы человек видит в каталоге */
export function EmployeesTab() {
  const users = useAdminUsers()
  const departments = useDepartments()
  const save = useSaveUser()
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)
  const [email, setEmail] = useState('')
  const [deptForNew, setDeptForNew] = useState('')

  const setDepartment = async (id: number, value: string) => {
    try {
      await save.mutateAsync({ id, department_id: value ? Number(value) : null })
      toast.success('Отдел сохранён')
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const toggleActive = async (id: number, active: boolean) => {
    try {
      await save.mutateAsync({ id, is_active: !active })
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const emailOk = email.includes('@')

  const addUser = async (e: FormEvent) => {
    e.preventDefault()
    if (!emailOk) return
    try {
      await save.mutateAsync({ email, department_id: deptForNew ? Number(deptForNew) : null })
      toast.success('Сотрудник добавлен — при первом входе через Bouncer отдел уже будет назначен')
      setAdding(false)
      setEmail('')
      setDeptForNew('')
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <SearchInput className="sm:w-72" label="Поиск сотрудника" placeholder="Имя, ник или почта…" value={search} onChange={setSearch} />
        <Button onClick={() => setAdding(true)}>
          <UserPlus className="h-4 w-4" />
          Добавить заранее
        </Button>
      </div>

      <Card>
        <QueryError query={departments} title="Не удалось загрузить отделы" />
        <DataState query={users} errorTitle="Не удалось загрузить сотрудников" loading={<RowsSkeleton />}>
          {(all) => {
            const q = search.trim().toLowerCase()
            const data = q ? all.filter((u) => matches(u, q)) : all
            return data.length === 0 ? (
              <EmptyState icon={Users} title="Никого не найдено" description="Измените запрос — ищем по имени, нику и почте" />
            ) : (
              <DataTable
                className="min-w-[820px]"
                head={
                  <>
                    <Th>Сотрудник</Th>
                    <Th>Вход</Th>
                    <Th>Отдел</Th>
                    <Th>Последний вход</Th>
                    <Th />
                  </>
                }
              >
                {data.map((u) => (
                  <tr key={u.id} className={u.is_active ? '' : 'opacity-60'}>
                    <td className="px-4 py-3">
                      <p className="font-medium">
                        {u.display_name} {u.role === 'admin' && <Badge tone="primary">админ</Badge>}
                      </p>
                      <p className="text-xs text-muted-foreground">{u.email ?? u.username}</p>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {{ bouncer: 'Bouncer', microsoft: 'Bouncer', local: 'Локальная учётка', dev: 'Dev' }[u.auth_source]}
                    </td>
                    <td className="px-4 py-3">
                      <Select className="h-8 w-52" aria-label={`Отдел: ${u.display_name}`} value={u.department?.id ?? ''} onChange={(e) => setDepartment(u.id, e.target.value)}>
                        <option value="">— без отдела —</option>
                        <DepartmentOptions departments={departments.data} />
                      </Select>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{u.last_login_at ? formatRelative(u.last_login_at) : 'ещё не входил'}</td>
                    <td className="px-4 py-3 text-right">
                      <Button size="sm" variant="ghost" onClick={() => toggleActive(u.id, u.is_active)}>
                        {u.is_active ? 'Заблокировать' : 'Разблокировать'}
                      </Button>
                    </td>
                  </tr>
                ))}
              </DataTable>
            )
          }}
        </DataState>
      </Card>

      <Dialog
        open={adding}
        onOpenChange={(o) => !o && setAdding(false)}
        title="Добавить сотрудника заранее"
        onSubmit={addUser}
        description="Почта и отдел. Когда человек впервые войдёт через Bouncer, он сразу увидит пулы своего отдела."
        footer={
          <>
            <Button variant="outline" onClick={() => setAdding(false)}>
              Отмена
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!emailOk}>
              Добавить
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Рабочая почта" required>
            <Input autoFocus value={email} onChange={(e) => setEmail(e.target.value.trim())} placeholder="name@company.com" />
          </Field>
          <Field label="Отдел">
            <Select value={deptForNew} onChange={(e) => setDeptForNew(e.target.value)}>
              <option value="">— без отдела —</option>
              <DepartmentOptions departments={departments.data} />
            </Select>
          </Field>
        </div>
      </Dialog>
    </>
  )
}
