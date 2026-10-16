import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { ComputerHistorySheet } from './ComputerHistorySheet'
import { api } from '@/lib/api'
import { makeComputer, renderWithProviders } from '@/test/helpers'
import type { AssetEvent, Booking, ComputerHistory, InventoryRow } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeRow = (over: Partial<InventoryRow> = {}): InventoryRow => ({
  ...makeComputer({ id: 10, name: 'PC-010', insight_key: 'INS-10' }),
  serial_number: null,
  is_archived: false,
  tier_override: null,
  note: null,
  writeback_error: null,
  usage_until: null,
  order_number: null,
  pool: null,
  booking: null,
  issues: [],
  ...over,
})

const makeBooking = (over: Partial<Booking> = {}): Booking => ({
  id: 1, order_number: 5, status: 'returned',
  computer: { id: 10, name: 'PC-010', tier: 'medium', is_virtual: false, cpu: null, ram_gb: null, storage: null, gpu: null },
  department: { id: 5, name: 'Разработка' },
  user: { id: 2, display_name: 'Пётр Петров', username: 'p.petrov' } as never,
  requester_name: 'Пётр Петров', requester_nick: 'p.petrov', purpose: null,
  booked_at: '2024-03-01T10:00:00Z', expected_return_at: null, returned_at: '2024-03-05T10:00:00Z',
  returned_by: null, return_comment: null, ...over,
})

const makeEvent = (over: Partial<AssetEvent> = {}): AssetEvent => ({
  id: 1, computer: { id: 10, name: 'PC-010' }, booking_id: null, event_type: 'booked',
  from_status: null, to_status: null, message: 'Забронирован отделом', actor: null,
  created_at: '2024-03-01T10:00:00Z', ...over,
})

let history: ComputerHistory

beforeEach(() => {
  history = {
    computer: makeRow(),
    attributes: { 'IP address': '10.0.0.10', Vendor: 'Dell' },
    bookings: [],
    events: [],
  }
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/computers/10') return history
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.patch).mockResolvedValue({})
  vi.mocked(api.post).mockResolvedValue({})
})

const open = (onClose = vi.fn()) => {
  renderWithProviders(<ComputerHistorySheet computerId={10} onClose={onClose} />)
  return { onClose, user: userEvent.setup() }
}

describe('ComputerHistorySheet', () => {
  it('закрытая панель (computerId = null) ничего не рисует и не грузит данные', () => {
    renderWithProviders(<ComputerHistorySheet computerId={null} onClose={() => undefined} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalled()
  })

  it('пока данные грузятся — заглушка «Компьютер», затем имя и бейджи', async () => {
    open()
    expect(screen.getByRole('dialog', { name: 'Компьютер' })).toBeInTheDocument()
    expect(await screen.findByRole('dialog', { name: 'PC-010' })).toBeInTheDocument()
    expect(screen.getAllByText('Средний')).toHaveLength(2) // бейдж + пункт селекта категории
    expect(screen.getByText('Свободен')).toBeInTheDocument()
    expect(screen.getByText('Не в пуле')).toBeInTheDocument()
    expect(screen.getByText('INS-10')).toBeInTheDocument()
  })

  it('бейджи: пул и «Нет в Insight»', async () => {
    history.computer = makeRow({ pool: { id: 1, name: 'Аренда', is_published: true }, is_archived: true })
    open()
    expect(await screen.findByText('Пул: Аренда')).toBeInTheDocument()
    expect(screen.getByText('Нет в Insight')).toBeInTheDocument()
    expect(screen.queryByText('Не в пуле')).not.toBeInTheDocument()
  })

  it('обзор: проблемы ПК и «Не закреплён ни за одним отделом»', async () => {
    history.computer = makeRow({ issues: ['Статус в Insight не совпадает', 'Ошибка записи'] })
    open()
    expect(await screen.findByText('Статус в Insight не совпадает')).toBeInTheDocument()
    expect(screen.getByText('Ошибка записи')).toBeInTheDocument()
    expect(screen.getByText('Не закреплён ни за одним отделом')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Вернуть' })).not.toBeInTheDocument()
  })

  it('обзор: текущий держатель — отдел, ответственный, срок возврата', async () => {
    history.computer = makeRow({
      status: 'booked', department: { id: 5, name: 'Разработка' },
      booking: {
        id: 9, requester_name: 'Пётр Петров', requester_nick: 'p.petrov', booked_at: '2024-03-01T10:00:00Z',
        expected_return_at: '2024-04-01', user: { id: 2, display_name: 'Пётр Петров', username: 'p.petrov' } as never,
      },
    })
    open()
    expect(await screen.findByText('Разработка')).toBeInTheDocument()
    expect(screen.getByText(/Пётр Петров/)).toBeInTheDocument()
    expect(screen.getByText(/вернуть до/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Вернуть' })).toBeInTheDocument()
  })

  describe('принудительный возврат', () => {
    beforeEach(() => {
      history.computer = makeRow({
        status: 'booked', department: { id: 5, name: 'Разработка' },
        booking: {
          id: 9, requester_name: 'Пётр Петров', requester_nick: 'p.petrov', booked_at: '2024-03-01T10:00:00Z',
          expected_return_at: null, user: { id: 2, display_name: 'Пётр Петров', username: 'p.petrov' } as never,
        },
      })
    })

    it('с комментарием: POST /bookings/9/return, тост, диалог закрывается', async () => {
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'Вернуть' }))
      const dialog = screen.getByRole('dialog', { name: 'Вернуть PC-010 от отдела «Разработка»?' })
      await user.type(within(dialog).getByRole('textbox'), 'Всё работает')
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/9/return', { comment: 'Всё работает' }))
      expect(toast.success).toHaveBeenCalledWith('PC-010 возвращён')
      await waitFor(() => expect(screen.queryByRole('dialog', { name: /Вернуть PC-010/ })).not.toBeInTheDocument())
    })

    it('без комментария подставляет «Возврат администратором»', async () => {
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'Вернуть' }))
      const dialog = screen.getByRole('dialog', { name: /Вернуть PC-010/ })
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/bookings/9/return', { comment: 'Возврат администратором' }))
    })

    it('ошибка возврата — тост, диалог остаётся', async () => {
      vi.mocked(api.post).mockRejectedValue(new Error('Бронь уже закрыта'))
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'Вернуть' }))
      const dialog = screen.getByRole('dialog', { name: /Вернуть PC-010/ })
      await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Бронь уже закрыта'))
      expect(screen.getByRole('dialog', { name: /Вернуть PC-010/ })).toBeInTheDocument()
    })
  })

  describe('правка категории и заметки', () => {
    it('«Сохранить» неактивна, пока нет изменений; поля подставлены из ПК', async () => {
      history.computer = makeRow({ tier_override: 'powerful', note: 'шумит кулер' })
      open()
      expect(await screen.findByDisplayValue('Мощный')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('Например: шумит кулер')).toHaveValue('шумит кулер')
      expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
    })

    it('смена категории и заметки уходит PATCH-ом', async () => {
      const { user } = open()
      await screen.findByDisplayValue('Автоматически')
      await user.selectOptions(screen.getByDisplayValue('Автоматически'), 'Слабый')
      await user.type(screen.getByPlaceholderText('Например: шумит кулер'), 'ремонт')
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/computers/10', { tier_override: 'weak', note: 'ремонт' }))
      expect(toast.success).toHaveBeenCalledWith('Сохранено')
    })

    it('возврат к «Автоматически» и пустая заметка отправляются как null', async () => {
      history.computer = makeRow({ tier_override: 'weak', note: 'x' })
      const { user } = open()
      await user.selectOptions(await screen.findByDisplayValue('Слабый'), 'Автоматически')
      await user.clear(screen.getByPlaceholderText('Например: шумит кулер'))
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/computers/10', { tier_override: null, note: null }))
    })

    it('ошибка сохранения — тост', async () => {
      vi.mocked(api.patch).mockRejectedValue(new Error('Нет прав'))
      const { user } = open()
      await user.type(await screen.findByPlaceholderText('Например: шумит кулер'), 'a')
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Нет прав'))
    })
  })

  describe('вкладки', () => {
    it('«История выдачи»: пустое состояние', async () => {
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'История выдачи' }))
      expect(screen.getByText('Компьютер ещё ни разу не выдавался')).toBeInTheDocument()
    })

    it('«История выдачи»: активная и закрытая брони, комментарий возврата', async () => {
      history.bookings = [
        makeBooking({ id: 2, status: 'active', returned_at: null, department: { id: 6, name: 'Аналитика' } }),
        makeBooking({ id: 1, return_comment: 'Шумит кулер' }),
      ]
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'История выдачи' }))
      expect(screen.getByText('Аналитика')).toBeInTheDocument()
      expect(screen.getByText('Сейчас')).toBeInTheDocument()
      expect(screen.getByText('Возвращён')).toBeInTheDocument()
      expect(screen.getByText('«Шумит кулер»')).toBeInTheDocument()
      expect(screen.getByText(/по сей день/)).toBeInTheDocument()
    })

    it('«События»: пустое состояние и лента без имени ПК', async () => {
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'События' }))
      expect(screen.getByText('Событий пока нет')).toBeInTheDocument()
    })

    it('«События»: тип события, сообщение, автор; имя ПК не дублируется', async () => {
      history.events = [makeEvent({ event_type: 'returned', message: 'Возвращён отделом', actor: { id: 1, display_name: 'Админ', username: 'adm' } as never })]
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'События' }))
      expect(screen.getByText('Возврат')).toBeInTheDocument()
      expect(screen.getByText('Возвращён отделом')).toBeInTheDocument()
      expect(screen.getByText(/Админ/)).toBeInTheDocument()
      expect(screen.queryByText(/PC-010 ·/)).not.toBeInTheDocument()
    })

    it('«Insight»: атрибуты ключ-значение', async () => {
      const { user } = open()
      await user.click(await screen.findByRole('button', { name: 'Insight' }))
      expect(screen.getByText('IP address')).toBeInTheDocument()
      expect(screen.getByText('10.0.0.10')).toBeInTheDocument()
      expect(screen.getByText('Dell')).toBeInTheDocument()
    })

    it('при открытии другого ПК возвращается на вкладку «Обзор»', async () => {
      vi.mocked(api.get).mockImplementation(async (path: string) =>
        path === '/admin/computers/11' ? { ...history, computer: makeRow({ id: 11, name: 'PC-011' }) } : history,
      )
      // внешняя кнопка переключает computerId, как клик по другой строке инвентаризации
      function Host() {
        const [id, setId] = useState(10)
        return (
          <>
            <button onClick={() => setId(11)}>другой ПК</button>
            <ComputerHistorySheet computerId={id} onClose={() => undefined} />
          </>
        )
      }
      renderWithProviders(<Host />)
      const user = userEvent.setup()
      await user.click(await screen.findByRole('button', { name: 'Insight' }))
      expect(screen.getByText('IP address')).toBeInTheDocument()
      // модальное окно блокирует клик по внешней кнопке — вызываем напрямую
      await act(async () => screen.getByText('другой ПК').click())
      expect(await screen.findByRole('dialog', { name: 'PC-011' })).toBeInTheDocument()
      expect(screen.queryByText('IP address')).not.toBeInTheDocument()
      expect(screen.getByText('Заметка админа')).toBeInTheDocument()
    })
  })

  it('закрытие панели вызывает onClose', async () => {
    const { user, onClose } = open()
    await screen.findByRole('dialog', { name: 'PC-010' })
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('ошибка загрузки — остаётся скелетон, без падения', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('500'))
    open()
    expect(await screen.findByRole('dialog', { name: 'Компьютер' })).toBeInTheDocument()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Обзор' })).not.toBeInTheDocument()
  })
})
