import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { FormError } from '@/components/ui/data-state'
import { Dialog } from '@/components/ui/dialog'
import { Field, Select, Textarea } from '@/components/ui/input'
import { useReplaceComputer, useReplacements } from '@/lib/queries'
import type { ExecutorOrder } from '@/lib/types'
import { computerSpecs, errorMessage } from '@/lib/utils'

/** Замена неисправного сервера в ещё не подготовленном заказе: заказ тот же, неисправный ПК уходит на диагностику */
export function ReplaceComputerCard({ order: o }: { order: ExecutorOrder }) {
  const [open, setOpen] = useState(false)
  return (
    <Card className="p-5">
      <p className="font-semibold">Заменить сервер</p>
      <p className="mt-1 text-[13px] text-muted-foreground">
        Если {o.computer.name} неисправен, а в пуле есть такой же свободный сервер и заказчик согласен, перенесите заказ на него: номер, срок и ОС
        останутся, неисправный ПК уйдёт на диагностику.
      </p>
      <Button className="mt-3" variant="outline" onClick={() => setOpen(true)}>
        Заменить сервер…
      </Button>
      <ReplaceDialog order={o} open={open} onClose={() => setOpen(false)} />
    </Card>
  )
}

function ReplaceDialog({ order: o, open, onClose }: { order: ExecutorOrder; open: boolean; onClose: () => void }) {
  const candidates = useReplacements(o.id, open)
  const replace = useReplaceComputer()
  const [computerId, setComputerId] = useState('')
  const [comment, setComment] = useState('')

  const close = () => {
    setComputerId('')
    setComment('')
    replace.reset()
    onClose()
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const chosen = candidates.data?.find((c) => String(c.id) === computerId)
    if (!chosen) return
    try {
      await replace.mutateAsync({ id: o.id, computer_id: chosen.id, comment: comment.trim() })
      toast.success(`Заказ перенесён на ${chosen.name}, заказчик получил уведомление`)
      close()
    } catch {
      // текст ошибки показан в окне
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => !v && close()}
      title={`Заменить ${o.computer.name}?`}
      description="Заказ перейдёт на выбранный свободный ПК той же категории, неисправный будет выведен из пула и уйдёт на диагностику."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={close}>
            Отмена
          </Button>
          <Button type="submit" loading={replace.isPending} disabled={!computerId || !comment.trim()}>
            Заменить
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {candidates.isError ? (
          <div className="flex items-center gap-2 text-[13px] text-danger">
            {errorMessage(candidates.error, 'Не удалось загрузить список')}
            <Button type="button" variant="ghost" size="sm" onClick={() => candidates.refetch()}>
              Повторить
            </Button>
          </div>
        ) : !candidates.data ? (
          <p className="text-[13px] text-muted-foreground">Загрузка…</p>
        ) : !candidates.data.length ? (
          <p className="text-[13px] text-muted-foreground">Свободных серверов той же категории в пулах команды нет</p>
        ) : (
          <Field label="Новый сервер" required>
            <Select value={computerId} onChange={(e) => setComputerId(e.target.value)}>
              <option value="">Выберите сервер</option>
              {candidates.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {computerSpecs(c)}
                  {c.pool_name ? ` · ${c.pool_name}` : ''}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Что с неисправным сервером" required>
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
        </Field>
        {replace.isError && <FormError>{errorMessage(replace.error)}</FormError>}
      </div>
    </Dialog>
  )
}
