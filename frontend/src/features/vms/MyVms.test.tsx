import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { MyVms, VM_STATUS } from './MyVms'
import { api, ApiError } from '@/lib/api'
import { renderWithProviders } from '@/test/helpers'
import type { Vm } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeVm = (over: Partial<Vm> = {}): Vm => ({
  id: 1,
  order_number: 200,
  name: 'rent-design-01',
  cpu: 4,
  ram_gb: 8,
  disk_gb: 80,
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

let vms: Vm[]

beforeEach(() => {
  vms = []
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/vms/my') return vms
    throw new Error(`неожиданный GET ${path}`)
  })
})

const renderVms = async (list: Vm[]) => {
  vms = list
  renderWithProviders(<MyVms />)
  if (list.some((v) => v.status !== 'deleted')) await screen.findByText(list[0].name, { exact: false })
  else await waitFor(() => expect(api.get).toHaveBeenCalledWith('/vms/my'))
}

describe('MyVms', () => {
  it('ошибка загрузки — сообщение и «Повторить», а не пустой блок', async () => {
    const user = userEvent.setup()
    let fail = true
    vi.mocked(api.get).mockImplementation(async () => {
      if (fail) throw new ApiError(500, 'Сервер недоступен')
      return [makeVm()]
    })
    renderWithProviders(<MyVms />)
    expect(await screen.findByText(/Не удалось загрузить виртуальные машины: Сервер недоступен/)).toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('rent-design-01')).toBeInTheDocument()
    expect(screen.queryByText(/Не удалось загрузить/)).not.toBeInTheDocument()
  })

  it('нет виртуалок — блок не рисуется', async () => {
    await renderVms([])
    expect(screen.queryByText('Виртуальные машины')).not.toBeInTheDocument()
  })

  it('удалённые виртуалки скрыты; если остались только они — блока нет', async () => {
    await renderVms([makeVm({ status: 'deleted' })])
    await new Promise((r) => setTimeout(r, 20)) // даём react-query применить ответ
    expect(screen.queryByText('Виртуальные машины')).not.toBeInTheDocument()
  })

  it('рисует параметры, заказ, отдел и срок возврата', async () => {
    await renderVms([makeVm({ expected_return_at: '2099-12-31' })])
    expect(screen.getByText('Виртуальные машины')).toBeInTheDocument()
    expect(screen.getByText('Заказ №200')).toBeInTheDocument()
    expect(screen.getByText('4 ядра · 8 ГБ · 80 ГБ · Разработка')).toBeInTheDocument()
    expect(screen.getByText(/· до /)).toBeInTheDocument()
  })

  it('без срока возврата «до …» не показывается', async () => {
    await renderVms([makeVm()])
    expect(screen.queryByText(/· до /)).not.toBeInTheDocument()
  })

  describe('статусы', () => {
    it.each([
      ['queued', 'В очереди', true],
      ['creating', 'Создаётся', true],
      ['ready', 'Готова', false],
      ['failed', 'Ошибка', false],
      ['deleting', 'Удаляется', true],
    ] as const)('%s — «%s»', async (status, label, busy) => {
      await renderVms([makeVm({ status, ip_address: null })])
      const badge = screen.getByText(label)
      expect(badge).toBeInTheDocument()
      // занятые статусы — со спиннером, остальные — с точкой
      expect(!!badge.querySelector('svg.animate-spin')).toBe(busy)
      expect(!!badge.querySelector('span.rounded-full')).toBe(!busy)
    })

    it('словарь подписей содержит все статусы ВМ', () => {
      expect(Object.keys(VM_STATUS).sort()).toEqual(['creating', 'deleted', 'deleting', 'failed', 'queued', 'ready'])
    })

    it('failed показывает текст ошибки vSphere', async () => {
      await renderVms([makeVm({ status: 'failed', ip_address: null, error: 'Нет места на datastore' })])
      expect(screen.getByText('Нет места на datastore')).toBeInTheDocument()
    })

    it('failed без текста ошибки — блока ошибки нет', async () => {
      await renderVms([makeVm({ status: 'failed', ip_address: null, error: null })])
      expect(screen.getByText('Ошибка')).toBeInTheDocument()
      expect(screen.queryByText('Нет места на datastore')).not.toBeInTheDocument()
    })

    it('ready без IP — «Windows загружается…»', async () => {
      await renderVms([makeVm({ status: 'ready', ip_address: null })])
      expect(screen.getByText('Windows загружается…')).toBeInTheDocument()
    })

    it('creating без IP — ни IP, ни «загружается»', async () => {
      await renderVms([makeVm({ status: 'creating', ip_address: null })])
      expect(screen.queryByText('Windows загружается…')).not.toBeInTheDocument()
      expect(screen.queryByTitle('Скопировать')).not.toBeInTheDocument()
    })
  })

  describe('кнопка отказа', () => {
    it.each([
      ['ready', 'Отказаться'],
      ['failed', 'Отказаться'],
      ['queued', 'Отменить'],
    ] as const)('для %s — «%s»', async (status, label) => {
      await renderVms([makeVm({ status })])
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    })

    it.each(['creating', 'deleting'] as const)('для %s кнопки нет', async (status) => {
      await renderVms([makeVm({ status })])
      expect(screen.queryByRole('button', { name: /Отказаться|Отменить/ })).not.toBeInTheDocument()
    })
  })

  it('клик по IP копирует его в буфер и показывает toast', async () => {
    const user = userEvent.setup()
    const write = vi.spyOn(navigator.clipboard, 'writeText')
    await renderVms([makeVm({ ip_address: '10.0.0.15' })])
    await user.click(screen.getByTitle('Скопировать'))
    expect(write).toHaveBeenCalledWith('10.0.0.15')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('IP скопирован'))
  })

  describe('удаление', () => {
    it('просит подтверждение, и только потом шлёт запрос; затем toast и закрытие окна', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms([makeVm({ id: 9 })])
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))

      const dialog = screen.getByRole('dialog', { name: 'Отказаться от rent-design-01?' })
      expect(dialog).toHaveTextContent('Отменить удаление после подтверждения будет нельзя.')
      expect(api.post).not.toHaveBeenCalled()

      await user.click(within(dialog).getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).toHaveBeenCalledWith('/vms/9/release')
      expect(toast.success).toHaveBeenCalledWith('rent-design-01 будет удалена')
    })

    it('после удаления список перезапрашивается', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms([makeVm()])
      const before = vi.mocked(api.get).mock.calls.filter(([p]) => p === '/vms/my').length
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() =>
        expect(vi.mocked(api.get).mock.calls.filter(([p]) => p === '/vms/my').length).toBeGreaterThan(before),
      )
    })

    it('«Отмена» закрывает окно без запроса', async () => {
      const user = userEvent.setup()
      await renderVms([makeVm()])
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Отмена' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).not.toHaveBeenCalled()
    })

    it('ошибка API — toast с текстом, окно подтверждения остаётся', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'vCenter недоступен'))
      const user = userEvent.setup()
      await renderVms([makeVm()])
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('vCenter недоступен'))
      expect(toast.success).not.toHaveBeenCalled()
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('для queued заголовок/кнопка «Отменить», а подтверждение то же', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms([makeVm({ id: 3, status: 'queued', ip_address: null })])
      await user.click(screen.getByRole('button', { name: 'Отменить' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vms/3/release'))
    })
  })
})
