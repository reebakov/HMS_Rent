import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { MyBookingsPage } from './MyBookingsPage'
import { api, ApiError } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { Booking } from '@/lib/types'

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

let bookings: Booking[]

const Where = () => <span data-testid="path">{useLocation().pathname}</span>
const renderPage = () => renderWithProviders(<><MyBookingsPage /><Where /></>, { route: '/my' })

beforeEach(() => {
  bookings = []
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/bookings/my') return bookings
    if (path === '/vms/my') return []
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

  // БАГ: страница не читает isError — при падении /bookings/my пользователь видит
  // «Активных бронирований нет», хотя на деле просто не получил данные
  it.fails('при ошибке загрузки не выдаёт ошибку за пустой список', async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === '/bookings/my') throw new ApiError(500, 'Сервер недоступен')
      return []
    })
    renderPage()
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/bookings/my'))
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByText('Активных бронирований нет')).not.toBeInTheDocument()
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

  it('если активных нет, но есть история — и пустое состояние, и таблица', async () => {
    bookings = [makeBooking({ status: 'returned', returned_at: '2024-01-11T09:00:00Z' })]
    renderPage()
    expect(await screen.findByText('Активных бронирований нет')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
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
