import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Eye, EyeOff, Layers, ListPlus, Pencil, Plus, Trash2 } from 'lucide-react'
import { Card, EmptyState, PageHeader, Skeleton } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { DataState, QueryError } from '@/components/ui/data-state'
import { Badge } from '@/components/ui/badge'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { useAssignPool, useDeletePool, useDepartments, usePools, useSavePool } from '@/lib/queries'
import type { Pool } from '@/lib/types'

type Editing = { id?: number; name: string; description: string; departmentIds: number[] }

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Ошибка')

/** Пулы выдачи: сотрудники видят в каталоге только ПК из опубликованных пулов */
export function PoolsPage() {
  const navigate = useNavigate()
  const pools = usePools()
  const save = useSavePool()
  const remove = useDeletePool()
  const assign = useAssignPool()
  const departments = useDepartments()
  const [editing, setEditing] = useState<Editing | null>(null)
  const [filling, setFilling] = useState<Pool | null>(null)
  const [names, setNames] = useState('')

  const submit = async () => {
    if (!editing) return
    try {
      await save.mutateAsync({
        id: editing.id, name: editing.name, description: editing.description || null, department_ids: editing.departmentIds,
      })
      toast.success(editing.id ? 'Пул обновлён' : 'Пул создан')
      setEditing(null)
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  const togglePublished = async (pool: Pool) => {
    try {
      await save.mutateAsync({ id: pool.id, is_published: !pool.is_published })
      toast.success(pool.is_published ? `«${pool.name}» скрыт из каталога` : `«${pool.name}» опубликован`)
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  const destroy = async (pool: Pool) => {
    if (!window.confirm(`Удалить пул «${pool.name}»? Компьютеры останутся в инвентаризации без пула.`)) return
    try {
      await remove.mutateAsync(pool.id)
      toast.success('Пул удалён')
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  const addByNames = async () => {
    if (!filling) return
    try {
      const res = await assign.mutateAsync({ pool_id: filling.id, names })
      if (res.not_found.length) {
        toast.warning(`Добавлено: ${res.updated}. Не найдены: ${res.not_found.slice(0, 15).join(', ')}${res.not_found.length > 15 ? '…' : ''}`)
      } else {
        toast.success(`Добавлено в «${filling.name}»: ${res.updated}`)
      }
      setFilling(null)
      setNames('')
    } catch (e) {
      toast.error(errorText(e))
    }
  }

  return (
    <>
      <PageHeader
        title="Пулы выдачи"
        description="Сотрудники видят в каталоге только компьютеры из опубликованных пулов. ПК без пула видят только администраторы."
        action={
          <Button onClick={() => setEditing({ name: '', description: '', departmentIds: [] })}>
            <Plus className="h-4 w-4" />
            Новый пул
          </Button>
        }
      />

      <DataState
        query={pools}
        errorTitle="Не удалось загрузить пулы"
        errorCardClass=""
        loading={
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-48 rounded-xl" />
            ))}
          </div>
        }
        empty={
          <Card>
            <EmptyState icon={Layers} title="Пулов пока нет" description="Создайте пул и добавьте в него компьютеры для выдачи" />
          </Card>
        }
      >
        {(data) => (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.map((pool) => (
              <Card key={pool.id} className="flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold">{pool.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-[13px] text-muted-foreground">{pool.description || 'Без описания'}</p>
                    <p className="mt-1.5 text-xs font-medium">
                      {pool.departments.length ? `Видят: ${pool.departments.map((d) => d.name).join(', ')}` : 'Видят все сотрудники'}
                    </p>
                  </div>
                  {pool.is_published ? <Badge tone="success" dot>В каталоге</Badge> : <Badge>Скрыт</Badge>}
                </div>

                <div className="mt-5 grid grid-cols-3 gap-3 text-center">
                  {[
                    ['Всего', pool.total, ''],
                    ['Свободно', pool.available, 'text-success'],
                    ['Выдано', pool.booked, 'text-primary'],
                  ].map(([label, value, color]) => (
                    <div key={label as string} className="rounded-lg bg-muted/50 py-2.5">
                      <p className={`text-xl font-semibold tabular ${color}`}>{value}</p>
                      <p className="text-[11px] text-muted-foreground">{label}</p>
                    </div>
                  ))}
                </div>

                <div className="mt-5 flex flex-wrap gap-1.5 border-t pt-4">
                  <Button size="sm" onClick={() => setFilling(pool)}>
                    <ListPlus className="h-3.5 w-3.5" />
                    Добавить ПК
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => navigate(`/admin/inventory?pool=${pool.id}`)}>
                    Состав
                  </Button>
                  <div className="ml-auto flex gap-1">
                    <Button size="icon" variant="ghost" title={pool.is_published ? 'Скрыть из каталога' : 'Опубликовать'} onClick={() => togglePublished(pool)}>
                      {pool.is_published ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                    <Button size="icon" variant="ghost" title="Изменить" onClick={() => setEditing({ id: pool.id, name: pool.name, description: pool.description ?? '', departmentIds: pool.departments.map((d) => d.id) })}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="ghost" title="Удалить" onClick={() => destroy(pool)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </DataState>

      <Dialog
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        title={editing?.id ? 'Редактирование пула' : 'Новый пул'}
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Отмена
            </Button>
            <Button onClick={submit} loading={save.isPending} disabled={!editing || editing.name.trim().length < 2}>
              Сохранить
            </Button>
          </>
        }
      >
        {editing && (
          <div className="space-y-4">
            <Field label="Название" required>
              <Input autoFocus value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="Например: Аренда для отделов" />
            </Field>
            <div>
                  <p className="mb-1.5 text-[13px] font-medium">Кто видит пул</p>
                  <p className="mb-2 text-xs text-muted-foreground">Ничего не отмечено — все сотрудники. Отдел человеку назначается в «Сотрудниках»</p>
                  <QueryError query={departments} title="Не удалось загрузить отделы" />
                  <div className="grid grid-cols-2 gap-2">
                    {departments.data?.map((d) => (
                      <label key={d.id} className="flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[13px]">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-[hsl(var(--primary))]"
                          checked={editing.departmentIds.includes(d.id)}
                          onChange={(e) =>
                            setEditing({
                              ...editing,
                              departmentIds: e.target.checked
                                ? [...editing.departmentIds, d.id]
                                : editing.departmentIds.filter((x) => x !== d.id),
                            })
                          }
                        />
                        {d.name}
                      </label>
                    ))}
                  </div>
                </div>
                <Field label="Описание" hint="Видно только администраторам">
              <Textarea value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
            </Field>
          </div>
        )}
      </Dialog>

      <Dialog
        open={!!filling}
        onOpenChange={(o) => !o && setFilling(null)}
        title={filling ? `Добавить ПК в «${filling.name}»` : ''}
        description="Вставьте имена или ключи Insight через пробел, запятую или с новой строки. ПК из другого пула будут перенесены сюда."
        footer={
          <>
            <Button variant="outline" onClick={() => setFilling(null)}>
              Отмена
            </Button>
            <Button onClick={addByNames} loading={assign.isPending} disabled={!names.trim()}>
              Добавить
            </Button>
          </>
        }
      >
        <Textarea
          className="min-h-[180px] font-mono text-xs"
          value={names}
          onChange={(e) => setNames(e.target.value)}
          placeholder={'A24\nA432, A434\nITASSETS-192737'}
        />
        <p className="mt-2 text-xs text-muted-foreground">
          Удобнее выбирать галочками? В «Инвентаризации» отметьте ПК и нажмите «В пул…».
        </p>
      </Dialog>
    </>
  )
}
