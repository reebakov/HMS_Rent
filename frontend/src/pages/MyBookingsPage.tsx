import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { CalendarClock, Inbox, Undo2 } from 'lucide-react'
import { Badge, TierBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, EmptyState, PageHeader, Skeleton } from '@/components/ui/card'
import { DataState, QueryError } from '@/components/ui/data-state'
import { ReturnDialog } from '@/features/booking/BookingDialog'
import { MyVms } from '@/features/vms/MyVms'
import { ReportProblemButton, ReportProblemDialog, RequestBadges, RequestSheet, type ProblemTarget } from '@/features/support/ServiceDesk'
import { useMyBookings, useMyRequests, useReturnBooking } from '@/lib/queries'
import type { Booking } from '@/lib/types'
import { formatDate, formatDateTime, formatDuration, isOverdue } from '@/lib/utils'

export function MyBookingsPage() {
  const navigate = useNavigate()
  const bookings = useMyBookings()
  const data = bookings.data
  const returnMutation = useReturnBooking()
  const [returning, setReturning] = useState<Booking | null>(null)
  const requests = useMyRequests()
  const [problem, setProblem] = useState<ProblemTarget>(null)
  const [openedRequest, setOpenedRequest] = useState<number | null>(null)
  const requestsFor = (bookingId: number) => requests.data?.filter((r) => r.booking_id === bookingId) ?? []

  const active = data?.filter((b) => b.status === 'active') ?? []
  const history = data?.filter((b) => b.status !== 'active') ?? []

  const confirmReturn = async (comment: string) => {
    if (!returning) return
    try {
      await returnMutation.mutateAsync({ id: returning.id, comment: comment || undefined })
      toast.success(`${returning.computer.name} возвращён`)
      setReturning(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось вернуть')
    }
  }

  return (
    <>
      <PageHeader
        title="Моя аренда"
        description="Компьютеры и виртуалки, которые вы взяли"
        action={<Button onClick={() => navigate('/')}>Забронировать ещё</Button>}
      />

      <QueryError query={requests} title="Не удалось загрузить заявки" cardClass="mb-8" />

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
        isEmpty={() => active.length === 0}
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
                      <p className="mt-0.5 text-[13px] text-muted-foreground">
                        {[b.computer.cpu, b.computer.ram_gb && `${b.computer.ram_gb} ГБ`, b.computer.gpu].filter(Boolean).join(' · ')}
                      </p>
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

                  <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t pt-4">
                    <RequestBadges requests={requestsFor(b.id)} onOpen={setOpenedRequest} />
                    <div className="ml-auto flex gap-1">
                    <ReportProblemButton onClick={() => setProblem({ bookingId: b.id, name: b.computer.name })} />
                    <Button variant="outline" size="sm" onClick={() => setReturning(b)}>
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
          <CardHeader title="История" description="Возвращённые компьютеры" />
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-5 py-3 font-medium">Заказ</th>
                  <th className="px-5 py-3 font-medium">Компьютер</th>
                  <th className="px-5 py-3 font-medium">Отдел</th>
                  <th className="px-5 py-3 font-medium">Взят</th>
                  <th className="px-5 py-3 font-medium">Возвращён</th>
                  <th className="px-5 py-3 font-medium">Срок</th>
                  <th className="px-5 py-3 font-medium">Заявки</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {history.map((b) => (
                  <tr key={b.id} className="hover:bg-muted/40">
                    <td className="px-5 py-3 tabular text-muted-foreground">№{b.order_number}</td>
                    <td className="px-5 py-3 font-medium">{b.computer.name}</td>
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
        title={returning ? `Вернуть ${returning.computer.name}?` : ''}
        pending={returnMutation.isPending}
        onConfirm={confirmReturn}
        onClose={() => setReturning(null)}
      />
      <ReportProblemDialog target={problem} onClose={() => setProblem(null)} />
      <RequestSheet id={openedRequest} onClose={() => setOpenedRequest(null)} />
    </>
  )
}

