import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { MyBookingsPage } from './MyBookingsPage'
import { api, ApiError } from '@/lib/api'
import { useSdConfig } from '@/lib/queries'
import { makeSession, renderWithProviders } from '@/test/helpers'
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
  returned_at: null,
  returned_by: null,
  return_comment: null,
  ...over,
})

const makeVm = (over: Partial<Vm> = {}): Vm => ({
  id: 3,
  order_number: 200,
  name: 'rent-design-01',
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
  ip_address: '10.0.0.15',
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
let sdEnabled: boolean

beforeEach(() => {
  bookings = [makeBooking()]
  vms = []
  requests = []
  comments = []
  sdEnabled = true
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

/** Маркер «конфиг Service Desk уже загружен» — по нему проверяем отсутствие кнопки */
const CfgProbe = () => <span data-testid="cfg">{useSdConfig().isFetched ? 'loaded' : 'loading'}</span>
const cfgLoaded = () => waitFor(() => expect(screen.getByTestId('cfg')).toHaveTextContent('loaded'))
const renderPage = () => renderWithProviders(<><MyBookingsPage /><CfgProbe /></>, { route: '/my' })
/** Карточка активной брони или строка ВМ по имени */
const cardOf = (name: string) => within(screen.getByText(name).closest('.rounded-xl, .flex-wrap') as HTMLElement)

/** То же, но дожидается появления карточки после загрузки */
const card = async (name: string) => {
  await screen.findByText(name)
  return cardOf(name)
}

describe('MyBookingsPage: заявки Service Desk', () => {
  it('запрашивает конфиг и список заявок', async () => {
    renderPage()
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
    renderPage()
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
    renderPage()
    await screen.findByText('rent-design-01')
    expect(await cardOf('rent-design-01').findByRole('button', { name: /HMS-VM/ })).toBeInTheDocument()
    expect(cardOf('rent-design-01').queryByRole('button', { name: /HMS-PC/ })).not.toBeInTheDocument()
    expect(await (await card('PC-010')).findByRole('button', { name: /HMS-PC/ })).toBeInTheDocument()
    expect(cardOf('PC-010').queryByRole('button', { name: /HMS-VM/ })).not.toBeInTheDocument()
  })

  it('Service Desk выключен — кнопки «Сообщить о проблеме» нет ни у ПК, ни у ВМ', async () => {
    sdEnabled = false
    vms = [makeVm()]
    renderPage()
    await screen.findByText('rent-design-01')
    await cfgLoaded()
    expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
  })

  it('ВМ в статусе «Удаляется» — без кнопки «Сообщить о проблеме»', async () => {
    bookings = []
    vms = [makeVm({ status: 'deleting' })]
    renderPage()
    await screen.findByText('rent-design-01')
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
    renderPage()
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
      renderPage()
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
      renderPage()
      await user.click(await screen.findByRole('button', { name: 'Сообщить о проблеме' }))
      const dialog = screen.getByRole('dialog', { name: 'Проблема с rent-design-01' })
      await user.type(within(dialog).getByLabelText(/Что случилось/), 'Нет интернета')
      await user.click(within(dialog).getByRole('button', { name: 'Отправить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/requests', { booking_id: undefined, vm_id: 3, message: 'Нет интернета' }))
    })

    it('ошибка API — окно остаётся открытым, toast с причиной', async () => {
      const user = userEvent.setup()
      vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'Jira недоступна'))
      renderPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: 'Сообщить о проблеме' }))
      await user.type(screen.getByLabelText(/Что случилось/), 'Не включается')
      await user.click(screen.getByRole('button', { name: 'Отправить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Jira недоступна'))
      expect(screen.getByRole('dialog', { name: 'Проблема с PC-010' })).toBeInTheDocument()
    })

    it('«Отмена» закрывает окно без запроса', async () => {
      const user = userEvent.setup()
      renderPage()
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
      renderPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: 'Заявка HMS-101 · В работе' }))
      expect(await screen.findByRole('dialog', { name: 'Заявка HMS-101' })).toBeInTheDocument()
      expect(await screen.findByText('Заберите ПК в ИТ-отдел')).toBeInTheDocument()
      expect(api.get).toHaveBeenCalledWith('/requests/5')
      expect(screen.getByRole('link', { name: /Открыть в Service Desk/ })).toHaveAttribute('href', 'https://jira.example.com/browse/HMS-101')
    })

    it('ответ из панели уходит в POST /requests/{id}/comments', async () => {
      const user = userEvent.setup()
      requests = [makeRequest({ id: 5 })]
      renderPage()
      await user.click(await (await card('PC-010')).findByRole('button', { name: /Заявка HMS-101/ }))
      const box = await screen.findByPlaceholderText('Ответить администраторам…')
      await user.type(box, 'Спасибо')
      await user.click(within(box.parentElement!).getByRole('button'))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/requests/5/comments', { message: 'Спасибо' }))
    })

    it('Escape закрывает панель', async () => {
      const user = userEvent.setup()
      requests = [makeRequest({ id: 5 })]
      renderPage()
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
      renderPage()
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
      renderPage()
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
      renderPage()
      const table = await screen.findByRole('table')
      expect(within(table).queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
      await user.click(await within(table).findByRole('button', { name: /Возврат HMS-900/ }))
      expect(await screen.findByRole('dialog', { name: 'Заявка HMS-900' })).toBeInTheDocument()
      // заявка закрыта — поля ответа нет
      expect(screen.queryByPlaceholderText('Ответить администраторам…')).not.toBeInTheDocument()
    })
  })
})
