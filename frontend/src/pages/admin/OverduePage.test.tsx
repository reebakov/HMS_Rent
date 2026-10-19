import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { OverduePage } from './OverduePage'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { OverdueItem } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

const makeItem = (over: Partial<OverdueItem> = {}): OverdueItem => ({
  kind: 'pc', id: 10, order_number: 77, name: 'PC-010', department: 'Разработка',
  requester_name: 'Пётр Петров', requester_nick: 'p.petrov', email: 'p.petrov@example.com',
  taken_at: '2026-09-01', due: '2026-10-01', days: 3, ...over,
})

let items: OverdueItem[]
const row = (name: string) => screen.getByText(name).closest('tr') as HTMLElement

beforeEach(() => {
  items = [
    makeItem(),
    makeItem({ kind: 'vm', id: 5, order_number: 12, name: 'vm-build-01', department: 'Аналитика', requester_name: 'Анна Смирнова', requester_nick: 'a.smirnova', email: null, days: 15 }),
  ]
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/overdue') return items
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({})
})

describe('OverduePage: таблица', () => {
  it('рисует ПК и виртуалку: тип, заказ, команда, арендатор, даты и дни просрочки', async () => {
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    expect(api.get).toHaveBeenCalledWith('/admin/overdue')

    const pc = within(row('PC-010'))
    expect(pc.getByText('Компьютер · заказ №77')).toBeInTheDocument()
    expect(pc.getByText('Разработка')).toBeInTheDocument()
    expect(pc.getByText('Пётр Петров (p.petrov) · p.petrov@example.com')).toBeInTheDocument()
    expect(pc.getByText(formatDate('2026-09-01'))).toBeInTheDocument()
    expect(pc.getByText(formatDate('2026-10-01'))).toBeInTheDocument()
    expect(pc.getByText('3 дня')).toBeInTheDocument()

    const vm = within(row('vm-build-01'))
    expect(vm.getByText('Виртуалка · заказ №12')).toBeInTheDocument()
    expect(vm.getByText('Анна Смирнова (a.smirnova)')).toBeInTheDocument()
    expect(vm.getByText('15 дней')).toBeInTheDocument()
  })

  it('до недели просрочки бейдж жёлтый, больше недели — красный; склонение дней', async () => {
    items = [makeItem({ id: 1, name: 'A', days: 1 }), makeItem({ id: 2, name: 'B', days: 7 }), makeItem({ id: 3, name: 'C', days: 8 }), makeItem({ id: 4, name: 'D', days: 21 })]
    renderWithProviders(<OverduePage />)
    await screen.findByText('A')
    const badge = (name: string, text: string) => within(row(name)).getByText(text)
    expect(badge('A', '1 день')).toHaveClass('text-warning')
    expect(badge('B', '7 дней')).toHaveClass('text-warning')
    expect(badge('C', '8 дней')).toHaveClass('text-danger')
    expect(badge('D', '21 день')).toHaveClass('text-danger')
  })

  it('заказ без номера — только тип', async () => {
    items = [makeItem({ order_number: null })]
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    expect(within(row('PC-010')).getByText('Компьютер')).toBeInTheDocument()
    expect(screen.queryByText(/заказ №/)).not.toBeInTheDocument()
  })

  it('«Написать» — mailto с темой и текстом про конкретную технику; без email ссылки нет', async () => {
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    const link = within(row('PC-010')).getByRole('link', { name: 'Написать' })
    const href = link.getAttribute('href')!
    expect(href.startsWith('mailto:p.petrov@example.com?')).toBe(true)
    const params = new URLSearchParams(href.split('?')[1])
    expect(params.get('subject')).toBe('HMS Rent: просрочен возврат PC-010 (заказ №77)')
    expect(params.get('body')).toContain(`Срок аренды PC-010 истёк ${formatDate('2026-10-01')}`)
    expect(within(row('vm-build-01')).queryByRole('link', { name: 'Написать' })).not.toBeInTheDocument()
  })
})

describe('OverduePage: состояния', () => {
  it('пока грузится — скелетоны, без таблицы и пустого состояния', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    const { container } = renderWithProviders(<OverduePage />)
    expect(screen.getByText('Просрочки')).toBeInTheDocument()
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText('Просрочек нет')).not.toBeInTheDocument()
  })

  it('пустой список — «Просрочек нет»', async () => {
    items = []
    renderWithProviders(<OverduePage />)
    expect(await screen.findByText('Просрочек нет')).toBeInTheDocument()
    expect(screen.getByText('Все вернули технику вовремя')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Просрочек нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/overdue')
    renderWithProviders(<OverduePage />)
    expect(await screen.findByText('Не удалось загрузить просрочки')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Просрочек нет')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('«Написать» — ссылка mailto, а не кнопка внутри ссылки', async () => {
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    const link = within(row('PC-010')).getByRole('link', { name: 'Написать' })
    expect(link.getAttribute('href')).toMatch(/^mailto:p\.petrov@example\.com\?subject=/)
    expect(link.querySelector('button')).toBeNull()
    expect(within(row('vm-build-01')).queryByRole('link', { name: 'Написать' })).not.toBeInTheDocument()
  })
})

describe('OverduePage: «Вернуть» / «Удалить»', () => {
  it('ПК: после подтверждения возвращает бронь администратором с комментарием', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    await user.click(within(row('PC-010')).getByRole('button', { name: 'Вернуть' }))
    expect(confirm).toHaveBeenCalledWith('Вернуть компьютер PC-010 без участия арендатора?')
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/10/return', { comment: 'Возврат администратором: просрочка' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('PC-010 возвращён'))
  })

  it('ВМ: после подтверждения освобождает виртуалку', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWithProviders(<OverduePage />)
    await screen.findByText('vm-build-01')
    await user.click(within(row('vm-build-01')).getByRole('button', { name: 'Удалить' }))
    expect(confirm).toHaveBeenCalledWith('Удалить виртуалку vm-build-01 без участия арендатора?')
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vms/5/release'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('vm-build-01 будет удалена'))
  })

  it('отказ в подтверждении — запросов нет', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    await user.click(within(row('PC-010')).getByRole('button', { name: 'Вернуть' }))
    expect(api.post).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('ошибка API — тост с текстом ошибки', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.post).mockRejectedValue(new Error('Бронь уже закрыта'))
    const user = userEvent.setup()
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    await user.click(within(row('PC-010')).getByRole('button', { name: 'Вернуть' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Бронь уже закрыта'))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('не-Error в ошибке — тост «Ошибка»', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.post).mockRejectedValue('boom')
    const user = userEvent.setup()
    renderWithProviders(<OverduePage />)
    await screen.findByText('vm-build-01')
    await user.click(within(row('vm-build-01')).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Ошибка'))
  })

  it('после действия список перезапрашивается', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWithProviders(<OverduePage />)
    await screen.findByText('PC-010')
    const before = vi.mocked(api.get).mock.calls.length
    await user.click(within(row('PC-010')).getByRole('button', { name: 'Вернуть' }))
    await waitFor(() => expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(before))
  })
})
