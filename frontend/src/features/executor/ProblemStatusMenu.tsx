import { useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMoveProblem, useProblemTransitions } from '@/lib/queries'
import type { ExecutorProblem, ProblemTransition } from '@/lib/types'
import { errorMessage } from '@/lib/utils'

/** «Сменить статус»: переходы задачи Jira по проблеме грузятся при открытии, выбранный выполняется в Jira */
export function ProblemStatusMenu({ problem }: { problem: ExecutorProblem }) {
  const [open, setOpen] = useState(false)
  const transitions = useProblemTransitions(problem.id, open)
  const move = useMoveProblem()

  if (!problem.issue_key) return null

  const run = async (t: ProblemTransition) => {
    try {
      await move.mutateAsync({ id: problem.id, transitionId: t.id })
      toast.success(`Задача ${problem.issue_key}: ${t.to_status}`)
      setOpen(false)
    } catch (e) {
      toast.error(errorMessage(e, 'Не удалось сменить статус'))
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
              <Button key={t.id} variant={t.closes ? 'primary' : 'outline'} size="sm" disabled={move.isPending} onClick={() => run(t)}>
                {t.to_status || t.name}
              </Button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
