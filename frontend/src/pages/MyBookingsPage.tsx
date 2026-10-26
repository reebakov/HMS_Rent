import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { CalendarClock, CalendarPlus, Inbox, Undo2, Wrench } from 'lucide-react'
import { Badge, TierBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, EmptyState, PageHeader, Skeleton } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DataState, QueryError } from '@/components/ui/data-state'
import { ExtendDialog, ReturnDialog, type ExtendTarget } from '@/features/booking/BookingDialog'
import { RequesterNote } from '@/features/booking/RequesterNote'
import { PendingTermNote } from '@/features/booking/TermLimit'
import { MyVms } from '@/features/vms/MyVms'
import { ReportProblemButton, ReportProblemDialog, RequestBadges, RequestSheet, type ProblemTarget } from '@/features/support/ServiceDesk'
import { useCancelBuild, useExternalRentals, useMyBookings, useMyRequests, useReturnBooking, useReturnExternal } from '@/lib/queries'
import type { Booking, ExternalRental, ServiceRequest } from '@/lib/types'
import { computerSpecs, errorMessage, formatDate, formatDateTime, formatDuration, isOverdue } from '@/lib/utils'

export function MyBookingsPage() {
  const navigate = useNavigate()
  const bookings = useMyBookings()
  const data = bookings.data
  const returnMutation = useReturnBooking()
  const [returning, setReturning] = useState<Booking | null>(null)
  const [extending, setExtending] = useState<ExtendTarget | null>(null)
  const requests = useMyRequests()
  const external = useExternalRentals()
  const returnExternal = useReturnExternal()
  const [returningOutside, setReturningOutside] = useState<ExternalRental | null>(null)
  const outside = external.data ?? []
  const cancelBuild = useCancelBuild()
  const [cancelling, setCancelling] = useState<ServiceRequest | null>(null)
  const [problem, setProblem] = useState<ProblemTarget>(null)
  const [openedRequest, setOpenedRequest] = useState<number | null>(null)
  const requestsFor = (bookingId: number) => requests.data?.filter((r) => r.booking_id === bookingId) ?? []
  const builds = requests.data?.filter((r) => r.kind === 'build') ?? []

  const active = data?.filter((b) => b.status === 'active') ?? []
  const history = data?.filter((b) => b.status !== 'active') ?? []

  const confirmReturn = async (comment: string) => {
    if (!returning) return
    try {
      const closed = await returnMutation.mutateAsync({ id: returning.id, comment: comment || undefined })
      toast.success(closed.status === 'cancelled' ? `Заказ на ${returning.computer.name} отменён` : `${returning.computer.name} возвращён`)
      setReturning(null)
    } catch (e) {
      toast.error(errorMessage(e, returning.prepared_at ? 'Не удалось вернуть' : 'Не удалось отменить заказ'))
    }
  }

  const confirmReturnOutside = async (comment: string) => {
    if (!returningOutside) return
    try {
      await returnExternal.mutateAsync({ id: returningOutside.computer.id, comment: comment || undefined })
      toast.success(`${returningOutside.computer.name} возвращён`)
      setReturningOutside(null)
    } catch (e) {
      toast.error(errorMessage(e, 'Не удалось вернуть'))
    }
  }

  const confirmCancelBuild = async () => {
    if (!cancelling) return
    try {
      await cancelBuild.mutateAsync(cancelling.id)
      toast.success('Заказ на сборку отменён')
      setCancelling(null)
    } catch (e) {
      toast.error(errorMessage(e, 'Не удалось отменить заказ'))
    }
  }

  return (
    <>
      <PageHeader
        title="Моя аренда"
        description="Компьютеры и виртуалки, которые взяли вы и ваша команда"
        action={<Button onClick={() => navigate('/')}>Забронировать ещё</Button>}
      />

      <QueryError query={requests} title="Не удалось загрузить заявки" cardClass="mb-8" />
      <QueryError query={external} title="Не удалось загрузить ПК, выданные вне портала" cardClass="mb-8" />

      {builds.length > 0 && (
        <Card className="mb-8">
          <CardHeader title="Сборки по запросу" description="Заявки исполнителям: собранный компьютер выдадут после сборки" />
          <div className="divide-y">
            {builds.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <Wrench className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{r.summary.replace(/^HMS Rent: /, '')}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(r.created_at)}</p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <RequestBadges requests={[r]} onOpen={setOpenedRequest} />
                  {r.can_cancel && (
                    <Button size="sm" variant="outline" onClick={() => setCancelling(r)}>
                      Отменить
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <MyVms
        requestsFor={(vmId) => requests.data?.filter((r) => r.vm_id === vmId) ?? []}
        onReport={(vm) => setProblem({ vmId: vm.id, name: vm.name })}
        onOpenRequest={setOpenedRequest}
      />

      <DataState
        query={bookings}
        errorTitle="Не удалось загрузить бронирования"
        errorCardClass=""
        loading={
          <div className="grid gap-4 md:grid-cols-2">
            <Skeleton className="h-44 rounded-xl" />
            <Skeleton className="h-44 rounded-xl" />
          </div>
        }
        isEmpty={() => active.length === 0 && outside.length === 0}
        empty={
          <Card>
            <EmptyState
              icon={Inbox}
              title="Активных бронирований нет"
              description="Выберите свободный компьютер в каталоге — он появится здесь."
              action={
                <Button variant="outline" onClick={() => navigate('/')}>
                  Открыть каталог
                </Button>
              }
            />
          </Card>
        }
      >
        {() => (
          <div className="grid gap-4 md:grid-cols-2">
            {active.map((b) => {
              const overdue = isOverdue(b.expected_return_at)
              return (
                <Card key={b.id} className="p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-lg font-semibold tracking-tight">{b.computer.name}</p>
                        <TierBadge tier={b.computer.tier} />
                      </div>
                      <p className="mt-0.5 text-xs font-medium text-muted-foreground">Заказ №{b.order_number}</p>
                      <RequesterNote order={b} />
                      <PendingTermNote order={b} />
                      <p className="mt-0.5 text-[13px] text-muted-foreground">
                        {computerSpecs(b.computer)}
                      </p>
                      {b.os_label && <p className="mt-0.5 text-[13px] text-muted-foreground">ОС: {b.os_label}</p>}
                    </div>
                    {overdue ? <Badge tone="danger">Срок вышел</Badge> : <Badge tone="primary" dot>Активна</Badge>}
                  </div>

                  <dl className="mt-5 grid grid-cols-2 gap-4 text-[13px]">
                    <div>
                      <dt className="text-xs text-muted-foreground">Отдел</dt>
                      <dd className="mt-0.5 font-medium">{b.department.name}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Ответственный</dt>
                      <dd className="mt-0.5 font-medium">
                        {b.requester_name} <span className="text-muted-foreground">({b.requester_nick})</span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Взят</dt>
                      <dd className="mt-0.5 font-medium">
                        {formatDate(b.booked_at)} <span className="text-muted-foreground">· {formatDuration(b.booked_at)}</span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Вернуть до</dt>
                      <dd className={overdue ? 'mt-0.5 font-medium text-danger' : 'mt-0.5 font-medium'}>
                        {b.expected_return_at ? formatDate(b.expected_return_at) : 'Без срока'}
                      </dd>
                    </div>
                  </dl>
                  {b.purpose && <p className="mt-4 rounded-lg bg-muted/50 px-3 py-2 text-[13px]">{b.purpose}</p>}
                  <ConnectionInfo booking={b} />

                  <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t pt-4">
                    <RequestBadges requests={requestsFor(b.id)} onOpen={setOpenedRequest} />
                    <div className="ml-auto flex gap-1">
                    <ReportProblemButton onClick={() => setProblem({ bookingId: b.id, name: b.computer.name })} />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setExtending({ kind: 'pc', id: b.id, name: b.computer.name, due: b.expected_return_at })}
                    >
                      <CalendarPlus className="h-3.5 w-3.5" />
                      Продлить
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setReturning(b)}>
                      <Undo2 className="h-3.5 w-3.5" />
                      {b.prepared_at ? 'Вернуть компьютер' : 'Отменить заказ'}
                    </Button>
                    </div>
                  </div>
                </Card>
              )
            })}
            {outside.map((r) => {
              const overdue = isOverdue(r.usage_until)
              return (
                <Card key={r.computer.id} className="p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-lg font-semibold tracking-tight">{r.computer.name}</p>
                        <TierBadge tier={r.computer.tier} />
                      </div>
                      <p className="mt-0.5 text-[13px] text-muted-foreground">{computerSpecs(r.computer)}</p>
                    </div>
                    {overdue ? <Badge tone="danger">Срок вышел</Badge> : <Badge tone="primary" dot>Активна</Badge>}
                  </div>
                  <dl className="mt-5 grid grid-cols-2 gap-4 text-[13px]">
                    <div>
                      <dt className="text-xs text-muted-foreground">Отдел</dt>
                      <dd className="mt-0.5 font-medium">{r.department.name}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Вернуть до</dt>
                      <dd className={overdue ? 'mt-0.5 font-medium text-danger' : 'mt-0.5 font-medium'}>
                        {r.usage_until ? formatDate(r.usage_until) : 'Без срока'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">IP-адрес</dt>
                      <dd className="mt-0.5 font-medium">
                        {r.ip_address ? <span className="font-mono">{r.ip_address}</span> : <span className="text-muted-foreground">не указан</span>}
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-4 text-[13px] text-muted-foreground">Выдан вне портала: продлить срок здесь нельзя, срок ведётся в Insight.</p>
                  <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t pt-4">
                    <RequestBadges requests={requests.data?.filter((q) => q.computer_id === r.computer.id) ?? []} onOpen={setOpenedRequest} />
                    <div className="ml-auto flex gap-1">
                      <ReportProblemButton onClick={() => setProblem({ computerId: r.computer.id, name: r.computer.name })} />
                      <Button variant="outline" size="sm" onClick={() => setReturningOutside(r)}>
                        <Undo2 className="h-3.5 w-3.5" />
                        Вернуть компьютер
                      </Button>
                    </div>
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </DataState>

      {history.length > 0 && (
        <Card className="mt-8">
          <CardHeader title="История" description="Возвращённые и отклонённые заказы" />
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-5 py-3 font-medium">Заказ</th>
                  <th className="px-5 py-3 font-medium">Компьютер</th>
                  <th className="px-5 py-3 font-medium">Отдел</th>
                  <th className="px-5 py-3 font-medium">Взят</th>
                  <th className="px-5 py-3 font-medium">Закрыт</th>
                  <th className="px-5 py-3 font-medium">Срок</th>
                  <th className="px-5 py-3 font-medium">Заявки</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {history.map((b) => (
                  <tr key={b.id} className="hover:bg-muted/40">
                    <td className="px-5 py-3 tabular text-muted-foreground">№{b.order_number}</td>
                    <td className="px-5 py-3 font-medium">
                      {b.computer.name}
                      {b.status === 'cancelled' && (
                        <span className="mt-0.5 flex items-center gap-1.5 text-xs font-normal">
                          <Badge tone="danger">{b.returned_by ? 'Отменён' : 'Отклонён'}</Badge>
                          <span className="text-muted-foreground">{b.return_comment}</span>
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3">{b.department.name}</td>
                    <td className="px-5 py-3 tabular">{formatDateTime(b.booked_at)}</td>
                    <td className="px-5 py-3 tabular">{formatDateTime(b.returned_at)}</td>
                    <td className="px-5 py-3">
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <CalendarClock className="h-3.5 w-3.5" />
                        {formatDuration(b.booked_at, b.returned_at)}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <RequestBadges requests={requestsFor(b.id)} onOpen={setOpenedRequest} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <ReturnDialog
        open={!!returning}
        title={returning ? `${returning.prepared_at ? 'Вернуть' : 'Отменить заказ на'} ${returning.computer.name}?` : ''}
        cancel={!!returning && !returning.prepared_at}
        pending={returnMutation.isPending}
        onConfirm={confirmReturn}
        onClose={() => setReturning(null)}
      />
      <ReturnDialog
        open={!!returningOutside}
        title={returningOutside ? `Вернуть ${returningOutside.computer.name}?` : ''}
        pending={returnExternal.isPending}
        onConfirm={confirmReturnOutside}
        onClose={() => setReturningOutside(null)}
      />
      <ConfirmDialog
        open={!!cancelling}
        onClose={() => setCancelling(null)}
        title="Отменить заказ на сборку?"
        description="Пока исполнитель не взял заказ в работу, его можно отменить: задача в Jira будет закрыта. Позже отмена недоступна."
        confirmLabel="Отменить заказ"
        pending={cancelBuild.isPending}
        onConfirm={confirmCancelBuild}
      />
      <ExtendDialog target={extending} onClose={() => setExtending(null)} />
      <ReportProblemDialog target={problem} onClose={() => setProblem(null)} />
      <RequestSheet id={openedRequest} onClose={() => setOpenedRequest(null)} />
    </>
  )
}

/** Данные для подключения к ПК: их вносит исполнитель, когда подготовил ПК; пароль в портале не хранится */
function ConnectionInfo({ booking: b }: { booking: Booking }) {
  if (!b.prepared_at) {
    return <p className="mt-4 text-[13px] text-muted-foreground">Исполнитель готовит ПК — данные для подключения появятся здесь.</p>
  }
  return (
    <div className="mt-4 rounded-lg border px-3 py-2.5 text-[13px]">
      <p className="font-medium">
        {b.connection_host} · <span className="font-mono">{b.connection_ip}</span>
      </p>
      <p className="text-muted-foreground">
        Логин {b.connection_login} · {b.connection_method}. Пароль сообщит исполнитель — смените его при первом входе.
      </p>
    </div>
  )
}
