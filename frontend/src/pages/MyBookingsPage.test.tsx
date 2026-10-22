import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { MyBookingsPage } from './MyBookingsPage'
import { api, ApiError } from '@/lib/api'
import { useSdConfig } from '@/lib/queries'
import { failGetOnce, makeSession, renderWithProviders, unprepared } from '@/test/helpers'
import { formatDate } from '@/lib/utils'
import type { Booking, ServiceComment, ServiceRequest, Vm } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => makeSession() }))

const makeBooking = (over: Partial<Booking> = {}): Booking => ({
  id: 1,
  order_number: 100,
  status: 'active',
  computer: { id: 10, name: 'PC-010', tier: 'medium', is_virtual: false, cpu: 'Intel Core i5', ram_gb: 16, storage: null, gpu: null },
  department: { id: 1, name: 'Разработка' },
  user: { id: 1, username: 'i.ivanov', display_name: 'Иван Иванов' },
  requester_name: 'Иван Иванов',
  requester_nick: 'iivanov',
  purpose: null,
  booked_at: '2024-01-10T09:00:00Z',
  expected_return_at: '2999-12-31',
  requested_return_at: null,
  os_label: null,
  returned_at: null,
  returned_by: null,
  return_comment: null,
  ...unprepared,
  ...over,
})

const makeVm = (over: Partial<Vm> = {}): Vm => ({
  id: 3,
  order_number: 200,
  name: 'A1001',
  cpu: 4,
  ram_gb: 8,
  disk_gb: 80,
  template_key: null,
  os_label: null,
  status: 'ready',
  error: null,
  department: { id: 1, name: 'Разработка' },
  user: { id: 1, username: 'i.ivanov', display_name: 'Иван Иванов' },
  requester_name: 'Иван Иванов',
  requester_nick: 'iivanov',
  purpose: null,
  expected_return_at: null,
  requested_return_at: null,
  ip_address: '10.0.0.15',
  connection_login: 'user',
  connection_method: 'RDP',
  power_state: 'on',
  created_at: '2024-01-10T09:00:00Z',
  ready_at: '2024-01-10T09:10:00Z',
  released_at: null,
  deleted_at: null,
  ...over,
})

const makeRequest = (over: Partial<ServiceRequest> = {}): ServiceRequest => ({
  id: 5,
  kind: 'problem',
  booking_id: 1,
  vm_id: null,
  department_id: null,
  issue_key: 'HMS-101',
  summary: 'Не включается',
  status: 'В работе',
  status_category: 'indeterminate',
  error: null,
  created_at: '2024-01-10T09:00:00Z',
  url: null,
  ...over,
})

let bookings: Booking[]
let vms: Vm[]
let requests: ServiceRequest[]
let comments: ServiceComment[]
let sdEnabled: boolean // включается в блоке «заявки Service Desk»

const Where = () => <span data-testid="path">{useLocation().pathname}</span>
const renderPage = () => renderWithProviders(<><MyBookingsPage /><Where /></>, { route: '/my' })

beforeEach(() => {
  bookings = []
  vms = []
  requests = []
  comments = []
  sdEnabled = false
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/bookings/my') return bookings
    if (path === '/vms/my') return vms
    if (path === '/requests/config') return { enabled: sdEnabled }
    if (path === '/requests/my') return requests
    const m = /^\/requests\/(\d+)$/.exec(path)
    if (m) return { request: requests.find((r) => r.id === Number(m[1])), comments }
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('MyBookingsPage', () => {
  it('пока грузится — скелетоны, без пустого состояния', () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => undefined))
    renderPage()
    expect(screen.getByRole('heading', { name: 'Моя аренда' })).toBeInTheDocument()
    expect(screen.queryByText('Активных бронирований нет')).not.toBeInTheDocument()
  })

  it('пустое состояние ведёт в каталог', async () => {
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByText('Активных бронирований нет')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Открыть каталог' }))
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/$/)
  })

  it('«Забронировать ещё» переходит в каталог', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Активных бронирований нет')
    await user.click(screen.getByRole('button', { name: 'Забронировать ещё' }))
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/$/)
  })

  it('при ошибке загрузки не выдаёт ошибку за пустой список; «Повторить» перезапрашивает', async () => {
    const user = userEvent.setup()
    let fail = true
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === '/bookings/my') {
        if (fail) throw new ApiError(500, 'Сервер недоступен')
        return [makeBooking()]
      }
      return []
    })
    renderPage()
    expect(await screen.findByText('Не удалось загрузить бронирования')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Активных бронирований нет')).not.toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.queryByText('Не удалось загрузить бронирования')).not.toBeInTheDocument()
  })

  it('ошибка загрузки заявок: сообщение и «Повторить», брони при этом показываются', async () => {
    const user = userEvent.setup()
    bookings = [makeBooking()]
    failGetOnce(vi.mocked(api.get), '/requests/my', 'Jira недоступна')
    renderPage()
    expect(await screen.findByText('Не удалось загрузить заявки')).toBeInTheDocument()
    expect(screen.getByText('Jira недоступна')).toBeInTheDocument()
    expect(screen.getByText('PC-010')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() => expect(screen.queryByText('Не удалось загрузить заявки')).not.toBeInTheDocument())
  })

  it('рисует карточку активной брони: заказ, характеристики, отдел, ответственный, цель', async () => {
    bookings = [makeBooking({ purpose: 'Сборка релиза' })]
    renderPage()
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.getByText('Заказ №100')).toBeInTheDocument()
    expect(screen.getByText('Intel Core i5 · 16 ГБ')).toBeInTheDocument()
    expect(screen.getByText('Разработка')).toBeInTheDocument()
    expect(screen.getByText('(iivanov)')).toBeInTheDocument()
    expect(screen.getByText('Сборка релиза')).toBeInTheDocument()
    expect(screen.getByText('Активна')).toBeInTheDocument()
    expect(screen.queryByText('Срок вышел')).not.toBeInTheDocument()
    expect(screen.queryByText('История')).not.toBeInTheDocument()
  })

  it('без срока возврата — «Без срока», без цели — блока нет', async () => {
    bookings = [makeBooking({ expected_return_at: null })]
    renderPage()
    expect(await screen.findByText('Без срока')).toBeInTheDocument()
    expect(screen.getByText('Активна')).toBeInTheDocument()
  })

  it('просроченная бронь помечена «Срок вышел» вместо «Активна»', async () => {
    bookings = [makeBooking({ expected_return_at: '2020-01-01' })]
    renderPage()
    expect(await screen.findByText('Срок вышел')).toBeInTheDocument()
    expect(screen.queryByText('Активна')).not.toBeInTheDocument()
  })

  it('возвращённые брони уходят в историю, активные — в карточки', async () => {
    bookings = [
      makeBooking({ id: 1, order_number: 100 }),
      makeBooking({
        id: 2, order_number: 90, status: 'returned', returned_at: '2024-01-12T09:00:00Z',
        computer: { id: 11, name: 'PC-011', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null },
      }),
      makeBooking({ id: 3, order_number: 80, status: 'cancelled', computer: { id: 12, name: 'PC-012', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null } }),
    ]
    renderPage()
    await screen.findByText('История')
    const table = screen.getByRole('table')
    expect(within(table).getByText('PC-011')).toBeInTheDocument()
    expect(within(table).getByText('PC-012')).toBeInTheDocument()
    expect(within(table).getByText('№90')).toBeInTheDocument()
    expect(within(table).queryByText('PC-010')).not.toBeInTheDocument()
    // длительность между «взят» и «возвращён»
    expect(within(table).getByText('2 дня')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Вернуть компьютер/ })).toHaveLength(1)
  })

  it('отклонённый заказ в истории: метка «Отклонён» и причина исполнителя', async () => {
    bookings = [makeBooking({
      id: 3, order_number: 80, status: 'cancelled', returned_at: '2024-01-12T09:00:00Z',
      return_comment: 'Заказчик не ответил: Нет ответа 5 рабочих дней',
    })]
    renderPage()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Отклонён')).toBeInTheDocument()
    expect(within(table).getByText('Заказчик не ответил: Нет ответа 5 рабочих дней')).toBeInTheDocument()
  })

  it('если активных нет, но есть история — и пустое состояние, и таблица', async () => {
    bookings = [makeBooking({ status: 'returned', returned_at: '2024-01-11T09:00:00Z' })]
    renderPage()
    expect(await screen.findByText('Активных бронирований нет')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  describe('заказы команды', () => {
    const teammate = { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' }
    const PC_011 = { id: 11, name: 'PC-011', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null } as const
    const teamBookings = () => [
      makeBooking({ id: 1 }),
      makeBooking({ id: 2, order_number: 101, computer: PC_011, user: teammate, requester_name: 'Пётр Петров', requester_nick: 'p.petrov' }),
    ]

    it('брони команды видны рядом со своими: у чужой — «Арендатор: Имя (ник)», у своей подписи нет', async () => {
      bookings = teamBookings()
      renderPage()
      await screen.findByText('PC-011')
      expect(screen.getByText('PC-010')).toBeInTheDocument()
      expect(cardOf('PC-011').getByText('Арендатор: Пётр Петров (p.petrov)')).toBeInTheDocument()
      expect(cardOf('PC-010').queryByText(/Арендатор:/)).not.toBeInTheDocument()
    })

    it('у чужой брони есть «Продлить», «Вернуть компьютер» и «Сообщить о проблеме»', async () => {
      bookings = teamBookings()
      sdEnabled = true
      renderPage()
      const other = await card('PC-011')
      expect(other.getByRole('button', { name: 'Продлить' })).toBeInTheDocument()
      expect(other.getByRole('button', { name: /Вернуть компьютер/ })).toBeInTheDocument()
      expect(await other.findByRole('button', { name: 'Сообщить о проблеме' })).toBeInTheDocument()
    })

    it('чужую бронь можно вернуть: запрос уходит по её id', async () => {
      bookings = teamBookings()
      vi.mocked(api.post).mockResolvedValue(bookings[1])
      const user = userEvent.setup()
      renderPage()
      await user.click((await card('PC-011')).getByRole('button', { name: /Вернуть компьютер/ }))
      await user.click(within(screen.getByRole('dialog', { name: 'Вернуть PC-011?' })).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/2/return', { comment: undefined }))
      expect(toast.success).toHaveBeenCalledWith('PC-011 возвращён')
    })

    it('чужую бронь можно продлить: запрос уходит по её id', async () => {
      bookings = teamBookings()
      vi.mocked(api.post).mockResolvedValue(bookings[1])
      const user = userEvent.setup()
      renderPage()
      await user.click((await card('PC-011')).getByRole('button', { name: 'Продлить' }))
      const dialog = within(screen.getByRole('dialog', { name: 'Продлить аренду PC-011' }))
      await user.type(dialog.getByLabelText(/Новый срок/), '3000-01-31')
      await user.click(dialog.getByRole('button', { name: 'Продлить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/2/extend', { expected_return_at: '3000-01-31' }))
    })

    it('отказ backend (403) показывается тостом, как и прочие ошибки', async () => {
      bookings = teamBookings()
      vi.mocked(api.post).mockRejectedValue(new ApiError(403, 'Вернуть ПК может тот, кто его бронировал, участник его команды или администратор'))
      const user = userEvent.setup()
      renderPage()
      await user.click((await card('PC-011')).getByRole('button', { name: /Вернуть компьютер/ }))
      await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Вернуть ПК может тот, кто его бронировал, участник его команды или администратор'),
      )
    })
  })

  describe('продление', () => {
    it('«Продлить» открывает окно с текущим сроком; новый срок уходит в API и список обновляется', async () => {
      bookings = [makeBooking()]
      vi.mocked(api.post).mockImplementation(async () => {
        bookings = [makeBooking({ expected_return_at: '3000-01-31' })]
        return bookings[0]
      })
      const user = userEvent.setup()
      renderPage()
      await user.click(await screen.findByRole('button', { name: 'Продлить' }))
      const dialog = within(screen.getByRole('dialog', { name: 'Продлить аренду PC-010' }))
      expect(dialog.getByLabelText(/Новый срок/)).toHaveAttribute('min', '3000-01-01')
      await user.type(dialog.getByLabelText(/Новый срок/), '3000-01-31')
      await user.click(dialog.getByRole('button', { name: 'Продлить' }))

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).toHaveBeenCalledWith('/bookings/1/extend', { expected_return_at: '3000-01-31' })
      expect(await screen.findByText(formatDate('3000-01-31'))).toBeInTheDocument()
    })

    it('в истории кнопки «Продлить» нет', async () => {
      bookings = [makeBooking({ status: 'returned', returned_at: '2024-01-11T09:00:00Z' })]
      renderPage()
      await screen.findByText('История')
      expect(screen.queryByRole('button', { name: 'Продлить' })).not.toBeInTheDocument()
    })
  })

  describe('возврат', () => {
    const openReturn = async (user: ReturnType<typeof userEvent.setup>) => {
      await user.click(await screen.findByRole('button', { name: /Вернуть компьютер/ }))
      return screen.getByRole('dialog', { name: 'Вернуть PC-010?' })
    }

    it('отправляет комментарий, показывает toast, закрывает окно и обновляет список', async () => {
      bookings = [makeBooking()]
      vi.mocked(api.post).mockImplementation(async () => {
        bookings = [makeBooking({ status: 'returned', returned_at: '2024-01-11T09:00:00Z' })]
        return bookings[0]
      })
      const user = userEvent.setup()
      renderPage()
      const dialog = await openReturn(user)
      await user.type(within(dialog).getByLabelText(/Комментарий/), 'Шумит кулер')
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).toHaveBeenCalledWith('/bookings/1/return', { comment: 'Шумит кулер' })
      expect(toast.success).toHaveBeenCalledWith('PC-010 возвращён')
      // список перезапрошен: карточки нет, бронь в истории
      expect(await screen.findByText('Активных бронирований нет')).toBeInTheDocument()
      expect(within(screen.getByRole('table')).getByText('PC-010')).toBeInTheDocument()
    })

    it('пустой комментарий уходит как undefined', async () => {
      bookings = [makeBooking()]
      vi.mocked(api.post).mockResolvedValue(bookings[0])
      const user = userEvent.setup()
      renderPage()
      const dialog = await openReturn(user)
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(api.post).toHaveBeenCalled())
      expect(vi.mocked(api.post).mock.calls[0]).toEqual(['/bookings/1/return', { comment: undefined }])
    })

    it('возвращает именно выбранную бронь', async () => {
      bookings = [
        makeBooking({ id: 1, order_number: 100 }),
        makeBooking({ id: 2, order_number: 101, computer: { id: 11, name: 'PC-011', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null } }),
      ]
      vi.mocked(api.post).mockResolvedValue(bookings[1])
      const user = userEvent.setup()
      renderPage()
      await screen.findByText('PC-011')
      await user.click(screen.getAllByRole('button', { name: /Вернуть компьютер/ })[1])
      const dialog = screen.getByRole('dialog', { name: 'Вернуть PC-011?' })
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/2/return', { comment: undefined }))
    })

    it('«Отмена» закрывает окно без запроса', async () => {
      bookings = [makeBooking()]
      const user = userEvent.setup()
      renderPage()
      const dialog = await openReturn(user)
      await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).not.toHaveBeenCalled()
    })

    it('комментарий не переносится в следующее открытие окна', async () => {
      bookings = [makeBooking()]
      const user = userEvent.setup()
      renderPage()
      let dialog = await openReturn(user)
      await user.type(within(dialog).getByLabelText(/Комментарий/), 'черновик')
      await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      dialog = await openReturn(user)
      expect(within(dialog).getByLabelText(/Комментарий/)).toHaveValue('')
    })

    it('ошибка API — toast с текстом, окно остаётся открытым', async () => {
      bookings = [makeBooking()]
      vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Бронь уже закрыта'))
      const user = userEvent.setup()
      renderPage()
      const dialog = await openReturn(user)
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Бронь уже закрыта'))
      expect(toast.success).not.toHaveBeenCalled()
      expect(screen.getByRole('dialog', { name: 'Вернуть PC-010?' })).toBeInTheDocument()
    })
  })
})

/** Маркер «конфиг Service Desk уже загружен» — по нему проверяем отсутствие кнопки */
const CfgProbe = () => <span data-testid="cfg">{useSdConfig().isFetched ? 'loaded' : 'loading'}</span>
const cfgLoaded = () => waitFor(() => expect(screen.getByTestId('cfg')).toHaveTextContent('loaded'))
const renderSdPage = () => renderWithProviders(<><MyBookingsPage /><CfgProbe /></>, { route: '/my' })
/** Карточка активной брони или строка ВМ по имени */
const cardOf = (name: string) => within(screen.getByText(name).closest('.rounded-xl, .flex-wrap') as HTMLElement)

/** То же, но дожидается появления карточки после загрузки */
const card = async (name: string) => {
  await screen.findByText(name)
  return cardOf(name)
}

describe('MyBookingsPage: заявки Service Desk', () => {
  beforeEach(() => {
    bookings = [makeBooking()]
    sdEnabled = true
  })

  it('запрашивает конфиг и список заявок', async () => {
    renderSdPage()
    await screen.findByText('PC-010')
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/requests/my'))
    expect(api.get).toHaveBeenCalledWith('/requests/config')
  })

  it('у активного ПК видны только его заявки; кнопка «Сообщить о проблеме» есть у каждого ПК', async () => {
    bookings = [
      makeBooking({ id: 1 }),
      makeBooking({ id: 2, order_number: 101, computer: { id: 11, name: 'PC-011', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null } }),
    ]
    requests = [makeRequest({ id: 5, booking_id: 1 }), makeRequest({ id: 6, booking_id: 2, issue_key: 'HMS-202', status: 'Открыта', status_category: 'new' })]
    renderSdPage()
    await screen.findByText('PC-011')

    const first = cardOf('PC-010')
    expect(await first.findByRole('button', { name: 'Заявка HMS-101 · В работе' })).toBeInTheDocument()
    expect(first.queryByRole('button', { name: /HMS-202/ })).not.toBeInTheDocument()
    expect(first.getByRole('button', { name: 'Сообщить о проблеме' })).toBeInTheDocument()

    const second = cardOf('PC-011')
    expect(await second.findByRole('button', { name: 'Заявка HMS-202 · Открыта' })).toBeInTheDocument()
    expect(second.queryByRole('button', { name: /HMS-101/ })).not.toBeInTheDocument()
  })

  it('заявки ВМ привязаны по vm_id и не путаются с заявками брони с тем же id', async () => {
    vms = [makeVm({ id: 1 })]
    requests = [
      makeRequest({ id: 7, booking_id: null, vm_id: 1, issue_key: 'HMS-VM', summary: 'Нет интернета' }),
      makeRequest({ id: 8, booking_id: 1, vm_id: null, issue_key: 'HMS-PC' }),
    ]
    renderSdPage()
    await screen.findByText('A1001')
    expect(await cardOf('A1001').findByRole('button', { name: /HMS-VM/ })).toBeInTheDocument()
    expect(cardOf('A1001').queryByRole('button', { name: /HMS-PC/ })).not.toBeInTheDocument()
    expect(await (await card('PC-010')).findByRole('button', { name: /HMS-PC/ })).toBeInTheDocument()
    expect(cardOf('PC-010').queryByRole('button', { name: /HMS-VM/ })).not.toBeInTheDocument()
  })

  it('Service Desk выключен — кнопки «Сообщить о проблеме» нет ни у ПК, ни у ВМ', async () => {
    sdEnabled = false
    vms = [makeVm()]
    renderSdPage()
    await screen.findByText('A1001')
    await cfgLoaded()
    expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
  })

  it('ВМ в статусе «Удаляется» — без кнопки «Сообщить о проблеме»', async () => {
    bookings = []
    vms = [makeVm({ status: 'deleting' })]
    renderSdPage()
    await screen.findByText('A1001')
    await cfgLoaded()
    expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
  })

  it('ошибка загрузки заявок не ломает страницу: карточки есть, бейджей нет', async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === '/bookings/my') return bookings
      if (path === '/vms/my') return vms
      if (path === '/requests/config') return { enabled: true }
      throw new ApiError(500, 'Сервер недоступен')
    })
    renderSdPage()
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Сообщить о проблеме' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Заявка / })).not.toBeInTheDocument()
  })

  describe('создание заявки', () => {
    it('по ПК: диалог с именем, POST с booking_id, toast, закрытие, новый бейдж после обновления списка', async () => {
      const user = userEvent.setup()
      vi.mocked(api.post).mockImplementation(async () => {
        requests = [makeRequest({ id: 9, issue_key: 'HMS-300', status: 'Открыта', status_category: 'new' })]
        return requests[0]
      })
      renderSdPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: 'Сообщить о проблеме' }))
      const dialog = screen.getByRole('dialog', { name: 'Проблема с PC-010' })
      await user.type(within(dialog).getByLabelText(/Что случилось/), 'Не включается')
      await user.click(within(dialog).getByRole('button', { name: 'Отправить' }))

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).toHaveBeenCalledWith('/requests', { booking_id: 1, vm_id: undefined, message: 'Не включается' })
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('HMS-300'))
      expect(await (await card('PC-010')).findByRole('button', { name: 'Заявка HMS-300 · Открыта' })).toBeInTheDocument()
    })

    it('по ВМ: POST с vm_id', async () => {
      const user = userEvent.setup()
      bookings = []
      vms = [makeVm({ id: 3 })]
      vi.mocked(api.post).mockResolvedValue(makeRequest({ vm_id: 3, booking_id: null }))
      renderSdPage()
      await user.click(await screen.findByRole('button', { name: 'Сообщить о проблеме' }))
      const dialog = screen.getByRole('dialog', { name: 'Проблема с A1001' })
      await user.type(within(dialog).getByLabelText(/Что случилось/), 'Нет интернета')
      await user.click(within(dialog).getByRole('button', { name: 'Отправить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/requests', { booking_id: undefined, vm_id: 3, message: 'Нет интернета' }))
    })

    it('ошибка API — окно остаётся открытым, toast с причиной', async () => {
      const user = userEvent.setup()
      vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'Jira недоступна'))
      renderSdPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: 'Сообщить о проблеме' }))
      await user.type(screen.getByLabelText(/Что случилось/), 'Не включается')
      await user.click(screen.getByRole('button', { name: 'Отправить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Jira недоступна'))
      expect(screen.getByRole('dialog', { name: 'Проблема с PC-010' })).toBeInTheDocument()
    })

    it('«Отмена» закрывает окно без запроса', async () => {
      const user = userEvent.setup()
      renderSdPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: 'Сообщить о проблеме' }))
      await user.click(screen.getByRole('button', { name: 'Отмена' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).not.toHaveBeenCalled()
    })
  })

  describe('переписка', () => {
    it('клик по бейджу открывает панель заявки с комментариями', async () => {
      const user = userEvent.setup()
      requests = [makeRequest({ id: 5, url: 'https://jira.example.com/browse/HMS-101' })]
      comments = [{ author: 'Админ Петров', body: 'Заберите ПК в ИТ-отдел', created: '2024-01-10T10:00:00Z', from_portal: false }]
      renderSdPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: 'Заявка HMS-101 · В работе' }))
      expect(await screen.findByRole('dialog', { name: 'Заявка HMS-101' })).toBeInTheDocument()
      expect(await screen.findByText('Заберите ПК в ИТ-отдел')).toBeInTheDocument()
      expect(api.get).toHaveBeenCalledWith('/requests/5')
      expect(screen.getByRole('link', { name: /Открыть в Service Desk/ })).toHaveAttribute('href', 'https://jira.example.com/browse/HMS-101')
    })

    it('ответ из панели уходит в POST /requests/{id}/comments', async () => {
      const user = userEvent.setup()
      requests = [makeRequest({ id: 5 })]
      renderSdPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: /Заявка HMS-101/ }))
      const box = await screen.findByPlaceholderText('Ответить администраторам…')
      await user.type(box, 'Спасибо')
      await user.click(within(box.parentElement!).getByRole('button'))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/requests/5/comments', { message: 'Спасибо' }))
    })

    it('Escape закрывает панель', async () => {
      const user = userEvent.setup()
      requests = [makeRequest({ id: 5 })]
      renderSdPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: /Заявка HMS-101/ }))
      await screen.findByRole('dialog', { name: 'Заявка HMS-101' })
      await user.keyboard('{Escape}')
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('бейдж ВМ тоже открывает переписку', async () => {
      const user = userEvent.setup()
      bookings = []
      vms = [makeVm({ id: 3 })]
      requests = [makeRequest({ id: 7, booking_id: null, vm_id: 3, issue_key: 'HMS-VM' })]
      renderSdPage()
      await user.click(await screen.findByRole('button', { name: /HMS-VM/ }))
      expect(await screen.findByRole('dialog', { name: 'Заявка HMS-VM' })).toBeInTheDocument()
      expect(api.get).toHaveBeenCalledWith('/requests/7')
    })
  })

  describe('история', () => {
    const returned = () =>
      makeBooking({ id: 2, order_number: 90, status: 'returned', returned_at: '2024-01-12T09:00:00Z', computer: { id: 11, name: 'PC-011', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null } })

    it('в таблице есть колонка «Заявки»; заявка «Возврат» стоит в строке своей брони', async () => {
      bookings = [returned(), makeBooking({ id: 3, order_number: 91, status: 'cancelled', computer: { id: 12, name: 'PC-012', tier: 'weak', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null } })]
      requests = [makeRequest({ id: 11, kind: 'return', booking_id: 2, issue_key: 'HMS-900', status: 'Выполнено', status_category: 'done' })]
      renderSdPage()
      const table = await screen.findByRole('table')
      expect(within(table).getByRole('columnheader', { name: 'Заявки' })).toBeInTheDocument()
      const row = (name: string) => within(within(table).getByText(name).closest('tr')!)
      expect(await row('PC-011').findByRole('button', { name: 'Возврат HMS-900 · Выполнено' })).toBeInTheDocument()
      expect(row('PC-012').queryByRole('button')).not.toBeInTheDocument()
    })

    it('кнопки «Сообщить о проблеме» в истории нет; клик по заявке «Возврат» открывает переписку', async () => {
      const user = userEvent.setup()
      bookings = [returned()]
      requests = [makeRequest({ id: 11, kind: 'return', booking_id: 2, issue_key: 'HMS-900', status: 'Выполнено', status_category: 'done' })]
      renderSdPage()
      const table = await screen.findByRole('table')
      expect(within(table).queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
      await user.click(await within(table).findByRole('button', { name: /Возврат HMS-900/ }))
      expect(await screen.findByRole('dialog', { name: 'Заявка HMS-900' })).toBeInTheDocument()
      // заявка закрыта — поля ответа нет
      expect(screen.queryByPlaceholderText('Ответить администраторам…')).not.toBeInTheDocument()
    })
  })
})

describe('MyBookingsPage: заявка на срок', () => {
  it('срок из заявки, которая ждёт админа, виден у брони', async () => {
    bookings = [makeBooking({ requested_return_at: '2999-12-31' })]
    renderPage()
    expect(await screen.findByText(`Заявка на срок до ${formatDate('2999-12-31')} ждёт администратора`)).toBeInTheDocument()
  })

  it('без заявки пояснения нет', async () => {
    bookings = [makeBooking()]
    renderPage()
    await screen.findByText('PC-010')
    expect(screen.queryByText(/ждёт администратора/)).not.toBeInTheDocument()
  })
})

describe('MyBookingsPage: сборки по запросу и ОС', () => {
  it('сборки команды — отдельным блоком со статусом; клик открывает заявку', async () => {
    requests = [makeRequest({ id: 21, kind: 'build', booking_id: null, department_id: 1, issue_key: 'HMS-700',
                              summary: 'HMS Rent: сборка ПК — тип A (заказ №12)', status: 'Ожидает поддержки' })]
    const user = userEvent.setup()
    renderPage()
    expect(await screen.findByText('Сборки по запросу')).toBeInTheDocument()
    expect(screen.getByText('сборка ПК — тип A (заказ №12)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Сборка HMS-700 · Ожидает поддержки' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('без сборок блока нет', async () => {
    bookings = [makeBooking()]
    renderPage()
    await screen.findByText('PC-010')
    expect(screen.queryByText('Сборки по запросу')).not.toBeInTheDocument()
  })

  it('ОС брони видна в карточке', async () => {
    bookings = [makeBooking({ os_label: 'Debian 12' })]
    renderPage()
    expect(await screen.findByText('ОС: Debian 12')).toBeInTheDocument()
  })
})

describe('MyBookingsPage: данные для подключения к ПК', () => {
  it('пока исполнитель не подготовил ПК — подсказка, что данные появятся', async () => {
    bookings = [makeBooking()]
    renderPage()
    expect(await screen.findByText('Исполнитель готовит ПК — данные для подключения появятся здесь.')).toBeInTheDocument()
  })

  it('подготовленный ПК: имя, IP, логин, способ и напоминание сменить пароль', async () => {
    bookings = [makeBooking({
      connection_host: 'A032.ff.local', connection_ip: '10.1.2.3', connection_method: 'RDP', connection_login: 'user',
      prepared_at: '2026-10-21T10:00:00Z',
    })]
    renderPage()
    expect(await screen.findByText('10.1.2.3')).toBeInTheDocument()
    expect(screen.getByText(/A032\.ff\.local/)).toBeInTheDocument()
    expect(screen.getByText(/Логин user · RDP\. Пароль сообщит исполнитель — смените его при первом входе\./)).toBeInTheDocument()
    expect(screen.queryByText(/Исполнитель готовит ПК/)).not.toBeInTheDocument()
  })
})
