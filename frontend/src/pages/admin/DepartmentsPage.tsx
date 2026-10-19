import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Building2, Plus } from 'lucide-react'
import { Card, EmptyState, PageHeader } from '@/components/ui/card'
import { DataState, RowsSkeleton } from '@/components/ui/data-state'
import { DataTable, Th } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { useDepartmentUsage, useSaveDepartment } from '@/lib/queries'
import { TIERS, TIER_ORDER } from '@/lib/dictionaries'
import type { DepartmentUsage } from '@/lib/types'
import { errorMessage, formatDate } from '@/lib/utils'

type Editing = { id?: number; name: string; code: string; head_name: string }

export function DepartmentsPage() {
  const usage = useDepartmentUsage()
  const save = useSaveDepartment()
  const [editing, setEditing] = useState<Editing | null>(null)

  const open = (d?: DepartmentUsage) =>
    setEditing(d ? { id: d.department_id, name: d.name, code: d.code ?? '', head_name: d.head_name ?? '' } : { name: '', code: '', head_name: '' })

  const nameOk = !!editing && editing.name.trim().length >= 2

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!editing || !nameOk) return
    try {
      await save.mutateAsync({ id: editing.id, name: editing.name, code: editing.code || null, head_name: editing.head_name || null })
      toast.success(editing.id ? 'Отдел обновлён' : 'Отдел добавлен')
      setEditing(null)
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const toggle = async (d: DepartmentUsage) => {
    try {
      await save.mutateAsync({ id: d.department_id, is_active: !d.is_active })
      toast.success(d.is_active ? `«${d.name}» скрыт из формы бронирования` : `«${d.name}» снова доступен`)
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  return (
    <>
      <PageHeader
        title="Отделы"
        description="Справочник для формы бронирования и сводка: сколько и каких компьютеров у каждого отдела"
        action={
          <Button onClick={() => open()}>
            <Plus className="h-4 w-4" />
            Добавить отдел
          </Button>
        }
      />

      <Card>
        <DataState
          query={usage}
          errorTitle="Не удалось загрузить отделы"
          loading={<RowsSkeleton rows={6} className="h-12" />}
          empty={<EmptyState icon={Building2} title="Отделов пока нет" action={<Button onClick={() => open()}>Добавить первый</Button>} />}
        >
          {(data) => (
            <DataTable
              className="min-w-[900px]"
              head={
                <>
                  <Th>Отдел</Th>
                  <Th>Руководитель</Th>
                  <Th right>Сейчас ПК</Th>
                  {TIER_ORDER.map((t) => (
                    <Th key={t} right>
                      {TIERS[t].label}
                    </Th>
                  ))}
                  <Th right>Всего броней</Th>
                  <Th>Последняя</Th>
                  <Th />
                </>
              }
            >
              {data.map((d) => (
                <tr key={d.department_id} className="hover:bg-muted/40">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{d.name}</span>
                      {d.code && <span className="font-mono text-xs text-muted-foreground">{d.code}</span>}
                      {!d.is_active && <Badge>скрыт</Badge>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{d.head_name ?? '—'}</td>
                  <td className="px-4 py-3 text-right text-base font-semibold tabular">{d.active}</td>
                  {TIER_ORDER.map((t) => (
                    <td key={t} className="px-4 py-3 text-right tabular text-muted-foreground">
                      {d.by_tier[t] ?? 0}
                    </td>
                  ))}
                  <td className="px-4 py-3 text-right tabular">{d.total_bookings}</td>
                  <td className="px-4 py-3 tabular text-muted-foreground">{formatDate(d.last_booked_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => open(d)}>
                        Изменить
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => toggle(d)}>
                        {d.is_active ? 'Скрыть' : 'Вернуть'}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </DataTable>
          )}
        </DataState>
      </Card>

      <Dialog
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        title={editing?.id ? 'Редактирование отдела' : 'Новый отдел'}
        onSubmit={submit}
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Отмена
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!nameOk}>
              Сохранить
            </Button>
          </>
        }
      >
        {editing && (
          <div className="space-y-4">
            <Field label="Название" required>
              <Input autoFocus value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Код" hint="Например, QA или DEV">
                <Input value={editing.code} onChange={(e) => setEditing({ ...editing, code: e.target.value })} />
              </Field>
              <Field label="Руководитель">
                <Input value={editing.head_name} onChange={(e) => setEditing({ ...editing, head_name: e.target.value })} />
              </Field>
            </div>
          </div>
        )}
      </Dialog>
    </>
  )
}
