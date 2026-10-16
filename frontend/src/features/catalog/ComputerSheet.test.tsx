import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ComputerSheet } from './ComputerSheet'
import { api, ApiError } from '@/lib/api'
import { makeComputer, makeSession, renderWithProviders } from '@/test/helpers'
import type { ComputerDetail } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

let session = makeSession()
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => session }))

const makeDetail = (over: Partial<ComputerDetail> = {}): ComputerDetail => ({
  ...makeComputer({ id: 10, name: 'PC-010' }),
  serial_number: 'SN-1',
  ip_address: '10.1.2.3',
  note: null,
  attributes: { Manufacturer: 'Dell', 'Model': 'OptiPlex 7090' },
  ...over,
})

let detail: ComputerDetail

function setup(computerId: number | null = 10) {
  const onClose = vi.fn()
  const onBook = vi.fn()
  renderWithProviders(<ComputerSheet computerId={computerId} onClose={onClose} onBook={onBook} />)
  return { onClose, onBook, user: userEvent.setup() }
}

beforeEach(() => {
  session = makeSession()
  detail = makeDetail()
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === `/computers/${detail.id}`) return detail
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('ComputerSheet', () => {
  it('computerId = null — панель закрыта, запрос не уходит', () => {
    setup(null)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalled()
  })

  it('пока данные грузятся — заголовок «Компьютер», без кнопки брони', () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => undefined))
    setup()
    expect(screen.getByRole('dialog', { name: 'Компьютер' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Забронировать' })).not.toBeInTheDocument()
  })

  it('рисует шапку: имя, категория, статус, ключ Insight', async () => {
    setup()
    const dialog = await screen.findByRole('dialog', { name: 'PC-010' })
    expect(await within(dialog).findByText('Средний')).toBeInTheDocument()
    expect(within(dialog).getByText('Свободен')).toBeInTheDocument()
    expect(within(dialog).getByText('INS-10')).toBeInTheDocument()
  })

  it('без ключа Insight его в шапке нет', async () => {
    detail = makeDetail({ insight_key: null })
    setup()
    await screen.findByText('Свободен')
    expect(screen.queryByText('INS-10')).not.toBeInTheDocument()
  })

  it('показывает характеристики и блок реквизитов', async () => {
    detail = makeDetail({ gpu: 'RTX 3060', insight_status: 'In use', synced_at: null })
    setup()
    await screen.findByText('Intel Core i5 · 6 ядер')
    expect(screen.getByText('16 ГБ')).toBeInTheDocument()
    expect(screen.getByText('SSD 512 ГБ')).toBeInTheDocument()
    expect(screen.getByText('RTX 3060')).toBeInTheDocument()
    expect(screen.getByText('pc-010.local')).toBeInTheDocument()
    expect(screen.getByText('Windows 11')).toBeInTheDocument()
    expect(screen.getByText('Офис, 3 этаж')).toBeInTheDocument()
    expect(screen.getByText('10.1.2.3')).toBeInTheDocument()
    expect(screen.getByText('In use')).toBeInTheDocument()
  })

  it('пустые поля заменяются прочерком', async () => {
    detail = makeDetail({ hostname: null, os: null, location: null, ip_address: null, insight_status: null, synced_at: null })
    setup()
    await screen.findByText('Hostname')
    const dd = (label: string) => screen.getByText(label).parentElement!.querySelector('dd')!
    for (const label of ['Hostname', 'ОС', 'Расположение', 'IP-адрес', 'Статус в Insight', 'Обновлено']) {
      expect(dd(label)).toHaveTextContent('—')
    }
  })

  it('«Обновлено» — относительное время', async () => {
    detail = makeDetail({ synced_at: new Date(Date.now() - 5 * 60_000).toISOString() })
    setup()
    expect(await screen.findByText('5 мин назад')).toBeInTheDocument()
  })

  it('у виртуалки без GPU — «Виртуальный адаптер»', async () => {
    detail = makeDetail({ is_virtual: true, tier: 'vm', gpu: null })
    setup()
    expect(await screen.findByText('Виртуальный адаптер')).toBeInTheDocument()
  })

  it('без GPU и числа ядер — прочерк и только название процессора', async () => {
    detail = makeDetail({ gpu: null, cpu_cores: null })
    setup()
    expect(await screen.findByText('Intel Core i5')).toBeInTheDocument()
    expect(screen.getByText('Видеокарта').nextElementSibling).toHaveTextContent('—')
  })

  describe('кнопка брони', () => {
    it('свободный ПК — кнопка есть, клик отдаёт загруженный компьютер в onBook', async () => {
      const { onBook, user } = setup()
      await user.click(await screen.findByRole('button', { name: 'Забронировать' }))
      expect(onBook).toHaveBeenCalledOnce()
      expect(onBook).toHaveBeenCalledWith(expect.objectContaining({ id: 10, name: 'PC-010', status: 'available' }))
    })

    it.each(['booked', 'in_use', 'maintenance', 'retired', 'unknown'] as const)('при статусе %s кнопки нет', async (status) => {
      detail = makeDetail({ status })
      setup()
      await screen.findByText('Hostname')
      expect(screen.queryByRole('button', { name: 'Забронировать' })).not.toBeInTheDocument()
    })
  })

  describe('атрибуты Insight', () => {
    it('обычному пользователю не показываются', async () => {
      setup()
      await screen.findByText('Hostname')
      expect(screen.queryByText('Все атрибуты Insight')).not.toBeInTheDocument()
      expect(screen.queryByText('Manufacturer')).not.toBeInTheDocument()
    })

    it('администратору — все пары ключ/значение', async () => {
      session = makeSession({ role: 'admin' })
      detail = makeDetail({ attributes: { Manufacturer: 'Dell', Slots: '4' } })
      setup()
      expect(await screen.findByText('Все атрибуты Insight')).toBeInTheDocument()
      expect(screen.getByText('Manufacturer').nextElementSibling).toHaveTextContent('Dell')
      expect(screen.getByText('Slots').nextElementSibling).toHaveTextContent('4')
    })

    it('администратору с пустыми атрибутами — заголовок без строк', async () => {
      session = makeSession({ role: 'admin' })
      detail = makeDetail({ attributes: {} })
      setup()
      expect(await screen.findByText('Все атрибуты Insight')).toBeInTheDocument()
    })
  })

  it('закрытие панели (Escape) вызывает onClose', async () => {
    const { onClose, user } = setup()
    await screen.findByText('Hostname')
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('ошибка загрузки — остаётся скелетон, кнопки брони нет', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(404, 'Не найден'))
    setup()
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(screen.getByRole('dialog', { name: 'Компьютер' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Забронировать' })).not.toBeInTheDocument()
  })
})
