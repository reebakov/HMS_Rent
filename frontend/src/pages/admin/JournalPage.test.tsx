import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { JournalPage } from './JournalPage'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders, unprepared } from '@/test/helpers'
import type { Booking } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

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
  expected_return_at: null,
  requested_return_at: null,
  os_label: null,
  returned_at: null,
  returned_by: null,
  return_comment: null,
  ...unprepared,
  ...over,
})

const departments = [{ id: 1, name: 'Разработка', code: 'DEV', head_name: null, is_active: true }]
let bookings: Booking[]

/** Query-параметры запросов /admin/bookings */
const journalCalls = () =>
  vi.mocked(api.get).mock.calls.filter(([p]) => p === '/admin/bookings').map(([, q]) => q as Record<string, unknown>)

const lastQuery = () => journalCalls()[journalCalls().length - 1]

beforeEach(() => {
  bookings = [makeBooking(), makeBooking({ id: 2, order_number: 101, status: 'returned', returned_at: '2024-01-12T09:00:00Z', computer: { ...makeBooking().computer, name: 'PC-011' } })]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/bookings') return bookings
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('JournalPage', () => {
  it('рисует бронирования и счётчик записей', async () => {
    renderWithProviders(<JournalPage />)
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.getByText('PC-011')).toBeInTheDocument()
    expect(screen.getByText('№100')).toBeInTheDocument()
    expect(screen.getByText('2 записей')).toBeInTheDocument()
  })

  it('закрытые заказы без выдачи: отклонённый исполнителем — «Отклонена», отменённый заказчиком — «Отменена»', async () => {
    const who = { id: 1, username: 'i.ivanov', display_name: 'Иван Иванов' }
    bookings = [
      makeBooking({ id: 3, order_number: 102, status: 'cancelled', returned_at: '2024-01-12T09:00:00Z' }),
      makeBooking({ id: 4, order_number: 103, status: 'cancelled', returned_at: '2024-01-12T09:00:00Z', returned_by: who }),
    ]
    renderWithProviders(<JournalPage />)
    expect(await screen.findByText('Отклонена')).toBeInTheDocument()
    expect(screen.getByText('Отменена')).toBeInTheDocument()
  })

  it('пока грузится — скелетоны без пустого состояния', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    renderWithProviders(<JournalPage />)
    expect(screen.queryByText('Записей нет')).not.toBeInTheDocument()
  })

  it('пустой журнал — «Записей нет»', async () => {
    bookings = []
    renderWithProviders(<JournalPage />)
    expect(await screen.findByText('Записей нет')).toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Записей нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/bookings')
    renderWithProviders(<JournalPage />)
    expect(await screen.findByText('Не удалось загрузить журнал')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Записей нет')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ошибка загрузки отделов: сообщение и «Повторить», журнал при этом показан', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/departments')
    renderWithProviders(<JournalPage />)
    expect(await screen.findByText('Не удалось загрузить отделы')).toBeInTheDocument()
    expect(screen.getByText('PC-010')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() => expect(screen.queryByText('Не удалось загрузить отделы')).not.toBeInTheDocument())
  })

  it('поиск уходит в API с debounce, обрезает пробелы и возвращается к «без поиска» при очистке', async () => {
    const user = userEvent.setup()
    renderWithProviders(<JournalPage />)
    await screen.findByText('PC-010')
    const input = screen.getByPlaceholderText(/ПК, имя или ник/)
    await user.type(input, '  pc-7 ')
    await waitFor(() => expect(lastQuery()).toMatchObject({ q: 'pc-7' }))
    expect(new Set(journalCalls().map((q) => q.q).filter(Boolean))).toEqual(new Set(['pc-7']))

    await user.clear(input)
    await waitFor(() => expect(lastQuery().q).toBeUndefined())
  })

  it('без ввода в поиск лишних запросов после монтирования нет', async () => {
    renderWithProviders(<JournalPage />)
    await screen.findByText('PC-010')
    await new Promise((r) => setTimeout(r, 400)) // дольше дебаунса поиска в 250 мс
    expect(journalCalls()).toHaveLength(1)
  })

  it('поиск, фильтры и даты доступны по подписи', async () => {
    renderWithProviders(<JournalPage />)
    await screen.findByText('PC-010')
    expect(screen.getByRole('textbox', { name: 'Поиск по журналу' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Фильтр по статусу' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Фильтр по отделу' })).toBeInTheDocument()
    expect(screen.getByLabelText('Дата с')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Дата по')).toHaveAttribute('type', 'date')
  })

  it('фильтры статуса и отдела попадают в запрос', async () => {
    const user = userEvent.setup()
    renderWithProviders(<JournalPage />)
    await screen.findByText('PC-010')
    await screen.findByRole('option', { name: 'Разработка' })

    await user.selectOptions(screen.getByDisplayValue('Все'), 'Возвращённые')
    await waitFor(() => expect(lastQuery()).toMatchObject({ status: 'returned' }))
    await user.selectOptions(screen.getByDisplayValue('Все отделы'), 'Разработка')
    await waitFor(() => expect(lastQuery()).toMatchObject({ status: 'returned', department_id: 1 }))
  })
})
