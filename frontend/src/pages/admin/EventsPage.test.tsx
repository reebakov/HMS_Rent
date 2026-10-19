import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EventsPage } from './EventsPage'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { AssetEvent } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const makeEvent = (over: Partial<AssetEvent> = {}): AssetEvent => ({
  id: 1, computer: { id: 10, name: 'PC-010' }, booking_id: null, event_type: 'booked',
  from_status: 'available', to_status: 'booked', message: 'Забронирован отделом', actor: null,
  created_at: '2024-03-01T10:00:00Z', ...over,
})

let events: AssetEvent[]
let total: number

const eventCalls = () =>
  vi.mocked(api.get).mock.calls.filter(([p]) => p === '/admin/events').map(([, q]) => q as Record<string, unknown>)
const lastQuery = () => eventCalls()[eventCalls().length - 1]

beforeEach(() => {
  events = [makeEvent(), makeEvent({ id: 2, computer: { id: 11, name: 'PC-011' }, event_type: 'returned', message: 'Возвращён' })]
  total = events.length
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/events') return { items: events, total }
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('EventsPage', () => {
  it('рисует события: компьютер, тип, сообщение, статусы, автора и диапазон записей', async () => {
    renderWithProviders(<EventsPage />)
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.getByText('Забронирован отделом')).toBeInTheDocument()
    expect(screen.getAllByText('[available ➔ booked]')).toHaveLength(2)
    expect(screen.getAllByText('Система')).toHaveLength(2)
    expect(screen.getByText('1–2 из 2')).toBeInTheDocument()
    expect(lastQuery()).toMatchObject({ limit: 100, offset: 0 })
  })

  it('пустая выдача — «Событий не найдено» и «0 записей»', async () => {
    events = []
    total = 0
    renderWithProviders(<EventsPage />)
    expect(await screen.findByText('Событий не найдено')).toBeInTheDocument()
    expect(screen.getByText('0 записей')).toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Событий не найдено» и «0 записей»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/events')
    renderWithProviders(<EventsPage />)
    expect(await screen.findByText('Не удалось загрузить события')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Событий не найдено')).not.toBeInTheDocument()
    expect(screen.queryByText('0 записей')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('поиск уходит в API с debounce и обрезает пробелы', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EventsPage />)
    await screen.findByText('PC-010')
    await user.type(screen.getByPlaceholderText(/ПК, текст события/), '  pc-7 ')
    await waitFor(() => expect(lastQuery()).toMatchObject({ q: 'pc-7' }))
    expect(new Set(eventCalls().map((q) => q.q).filter(Boolean))).toEqual(new Set(['pc-7']))
  })

  it('таймер поиска после открытия страницы не сбрасывает уже выбранную страницу', async () => {
    total = 750 // 8 страниц по 100
    const user = userEvent.setup()
    renderWithProviders(<EventsPage />)
    await screen.findByText('1–100 из 750')
    await user.click(screen.getByRole('button', { name: 'Следующая страница' }))
    await screen.findByText('101–200 из 750')
    await new Promise((r) => setTimeout(r, 400)) // дольше дебаунса поиска в 250 мс
    expect(screen.getByText('101–200 из 750')).toBeInTheDocument()
    expect(lastQuery()).toMatchObject({ offset: 100 })
  })

  it('поиск, тип события и даты доступны по подписи', async () => {
    renderWithProviders(<EventsPage />)
    await screen.findByText('PC-010')
    expect(screen.getByRole('textbox', { name: 'Поиск по логам' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Тип события' })).toBeInTheDocument()
    expect(screen.getByLabelText('Дата с')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Дата по')).toHaveAttribute('type', 'date')
  })

  it('пагинация: страница меняет запрос, текущая помечена aria-current', async () => {
    total = 750
    const user = userEvent.setup()
    renderWithProviders(<EventsPage />)
    await screen.findByText('1–100 из 750')
    expect(screen.getByRole('button', { name: '1' })).toHaveAttribute('aria-current', 'page')
    await user.click(screen.getByRole('button', { name: 'На последнюю страницу' }))
    await waitFor(() => expect(lastQuery()).toMatchObject({ offset: 700 }))
    expect(await screen.findByText('701–750 из 750')).toBeInTheDocument()
  })

  it('фильтр типа события попадает в запрос', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EventsPage />)
    await screen.findByText('PC-010')
    await user.selectOptions(screen.getByDisplayValue('Все типы событий'), 'Возврат')
    await waitFor(() => expect(lastQuery()).toMatchObject({ event_type: 'returned' }))
  })
})
