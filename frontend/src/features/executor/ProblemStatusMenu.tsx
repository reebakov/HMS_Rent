import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { FormError } from '@/components/ui/data-state'
import { Dialog } from '@/components/ui/dialog'
import { Field, Textarea } from '@/components/ui/input'
import { useMoveProblem, useProblemTransitions } from '@/lib/queries'
import type { ExecutorProblem, ProblemTransition } from '@/lib/types'
import { errorMessage } from '@/lib/utils'

/** «Сменить статус»: переходы задачи Jira по проблеме грузятся при открытии, выбранный выполняется в Jira;
 *  закрытие подтверждается в окне, где можно оставить заказчику свой комментарий */
export function ProblemStatusMenu({ problem }: { problem: ExecutorProblem }) {
  const [open, setOpen] = useState(false)
  const [closing, setClosing] = useState<ProblemTransition | null>(null)
  const [comment, setComment] = useState('')
  const transitions = useProblemTransitions(problem.id, open)
  const move = useMoveProblem()

  if (!problem.issue_key) return null

  const submit = async (t: ProblemTransition, text?: string) => {
    await move.mutateAsync({ id: problem.id, transitionId: t.id, comment: text })
    toast.success(`Задача ${problem.issue_key}: ${t.to_status}`)
    setOpen(false)
  }

  const run = async (t: ProblemTransition) => {
    try {
      await submit(t)
    } catch (e) {
      toast.error(errorMessage(e, 'Не удалось сменить статус'))
    }
  }

  const closeDialog = () => {
    setClosing(null)
    setComment('')
    move.reset()
  }

  const confirmClose = async (e: FormEvent) => {
    e.preventDefault()
    if (!closing) return
    try {
      await submit(closing, comment.trim())
      closeDialog()
    } catch {
      // текст ошибки показан в окне
    }
  }

  return (
    <div className="mt-2">
      <Button variant="outline" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Сменить статус
        <ChevronDown className="h-3.5 w-3.5" />
      </Button>
      {open && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {transitions.isError ? (
            <>
              <span className="text-xs text-danger">{errorMessage(transitions.error, 'Не удалось получить переходы')}</span>
              <Button variant="ghost" size="sm" onClick={() => transitions.refetch()}>
                Повторить
              </Button>
            </>
          ) : !transitions.data ? (
            <span className="text-xs text-muted-foreground">Загрузка…</span>
          ) : !transitions.data.length ? (
            <span className="text-xs text-muted-foreground">Из этого статуса переходов нет</span>
          ) : (
            transitions.data.map((t) => (
              <Button
                key={t.id}
                variant={t.closes ? 'primary' : 'outline'}
                size="sm"
                disabled={move.isPending}
                onClick={() => (t.closes ? setClosing(t) : run(t))}
              >
                {t.to_status || t.name}
              </Button>
            ))
          )}
        </div>
      )}
      <Dialog
        open={!!closing}
        onOpenChange={(o) => !o && closeDialog()}
        title={`Закрыть задачу ${problem.issue_key}?`}
        description="Задача перейдёт в закрытый статус, заказчик увидит «Выполнен» и получит уведомление. Вернуть её в работу можно только в Jira."
        onSubmit={confirmClose}
        footer={
          <>
            <Button type="button" variant="outline" onClick={closeDialog}>
              Отмена
            </Button>
            <Button type="submit" loading={move.isPending}>
              Закрыть задачу
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Комментарий для заказчика" hint="Необязательно: заказчик увидит его в «Моей аренде» вместе с заявкой">
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
          </Field>
          {move.isError && <FormError>{errorMessage(move.error)}</FormError>}
        </div>
      </Dialog>
    </div>
  )
}
