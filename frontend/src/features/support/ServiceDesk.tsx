import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ExternalLink, LifeBuoy, Loader2, Send } from 'lucide-react'
import { Dialog, Sheet } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { DataState } from '@/components/ui/data-state'
import { Badge, type Tone } from '@/components/ui/badge'
import { Field, Textarea } from '@/components/ui/input'
import { useAddComment, useCreateRequest, useRequestDetail, useSdConfig } from '@/lib/queries'
import type { ServiceRequest } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'

const tone = (r: ServiceRequest): Tone =>
  r.error ? 'danger' : r.status_category === 'done' ? 'success' : r.status_category === 'indeterminate' ? 'primary' : 'warning'

/** Бейджи заявок по одному ПК/ВМ: номер задачи и статус из Jira */
export function RequestBadges({ requests, onOpen }: { requests: ServiceRequest[]; onOpen: (id: number) => void }) {
  if (!requests.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {requests.map((r) => (
        <button key={r.id} onClick={() => onOpen(r.id)} title={r.summary} className="transition-opacity hover:opacity-80">
          <Badge tone={tone(r)}>
            {r.kind === 'return' ? 'Возврат' : 'Заявка'} {r.issue_key ?? '—'} · {r.error ? 'не создана' : r.status ?? '…'}
          </Badge>
        </button>
      ))}
    </div>
  )
}

/** Кнопка «Сообщить о проблеме» — скрыта, если Service Desk не подключён; если проверить не удалось — недоступна с подсказкой */
export function ReportProblemButton({ onClick }: { onClick: () => void }) {
  const cfg = useSdConfig()
  if (!cfg.isError && !cfg.data?.enabled) return null
  return (
    // подсказка на обёртке: у отключённой кнопки браузер тултип не показывает
    <span title={cfg.isError ? 'Не удалось проверить, подключён ли Service Desk' : undefined}>
      <Button variant="ghost" size="sm" disabled={cfg.isError} onClick={onClick}>
        <LifeBuoy className="h-3.5 w-3.5" />
        Сообщить о проблеме
      </Button>
    </span>
  )
}

export type ProblemTarget = { bookingId?: number; vmId?: number; name: string } | null

export function ReportProblemDialog({ target, onClose }: { target: ProblemTarget; onClose: () => void }) {
  const create = useCreateRequest()
  const [message, setMessage] = useState('')
  useEffect(() => setMessage(''), [target])

  const submit = async () => {
    if (!target) return
    try {
      const req = await create.mutateAsync({ booking_id: target.bookingId, vm_id: target.vmId, message })
      toast.success(`Заявка ${req.issue_key} создана — ответ придёт сюда, в «Мою аренду»`)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось отправить')
    }
  }

  return (
    <Dialog
      open={!!target}
      onOpenChange={(o) => !o && onClose()}
      title={target ? `Проблема с ${target.name}` : ''}
      description="Опишите, что случилось. Заявка уйдёт администраторам в Service Desk, а их ответы появятся здесь."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={submit} loading={create.isPending} disabled={message.trim().length < 5}>
            <Send className="h-3.5 w-3.5" />
            Отправить
          </Button>
        </>
      }
    >
      <Field label="Что случилось" hint="Например: «Не включается», «Нет интернета», «Не подключается по VNC»">
        <Textarea autoFocus className="min-h-[140px]" value={message} onChange={(e) => setMessage(e.target.value)} />
      </Field>
    </Dialog>
  )
}

/** Заявка: статус и переписка с администраторами (публичные комментарии из Jira) */
export function RequestSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const detail = useRequestDetail(id)
  const { data } = detail
  const add = useAddComment()
  const [reply, setReply] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  const r = data?.request

  useEffect(() => bottom.current?.scrollIntoView({ behavior: 'smooth' }), [data?.comments.length])
  useEffect(() => setReply(''), [id])

  const send = async () => {
    if (!id) return
    try {
      await add.mutateAsync({ id, message: reply })
      setReply('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось отправить')
    }
  }

  return (
    <Sheet
      open={id !== null}
      onOpenChange={(o) => !o && onClose()}
      title={r?.issue_key ? `Заявка ${r.issue_key}` : 'Заявка'}
      description={
        r && (
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={tone(r)}>{r.error ? 'не создана' : r.status ?? '…'}</Badge>
            {r.url && (
              <a href={r.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                Открыть в Service Desk <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </span>
        )
      }
      footer={
        r?.issue_key && r.status_category !== 'done' ? (
          <div className="flex w-full gap-2">
            <Textarea
              className="min-h-[44px] flex-1"
              placeholder="Ответить администраторам…"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
            />
            <Button onClick={send} loading={add.isPending} disabled={!reply.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
        ) : undefined
      }
    >
      <DataState
        query={detail}
        errorTitle="Не удалось загрузить заявку"
        loading={
          <div className="flex justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        }
      >
        {(d) => (
          <div className="space-y-4">
            <p className="text-[13px] font-medium">{d.request.summary}</p>
            {d.request.error && <p className="rounded-lg bg-danger/5 px-3 py-2 text-[13px] text-danger">{d.request.error}</p>}
            {!d.comments.length ? (
              <p className="py-6 text-center text-[13px] text-muted-foreground">Администраторы ещё не ответили</p>
            ) : (
              <div className="space-y-3">
                {d.comments.map((c, i) => (
                  <div
                    key={i}
                    className={c.from_portal ? 'ml-8 rounded-xl bg-primary/10 px-4 py-3' : 'mr-8 rounded-xl border bg-muted/40 px-4 py-3'}
                  >
                    <p className="text-xs text-muted-foreground">
                      {c.from_portal ? 'Вы (с сайта)' : c.author} · {formatDateTime(c.created)}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-[13px]">{c.from_portal ? c.body.replace(/^\[HMS Rent\] [^:]+: /, '') : c.body}</p>
                  </div>
                ))}
                <div ref={bottom} />
              </div>
            )}
          </div>
        )}
      </DataState>
    </Sheet>
  )
}
