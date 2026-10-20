import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { VmsPage } from './VmsPage'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { Vm } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeVm = (over: Partial<Vm> = {}): Vm => ({
  id: 1, order_number: 200, name: 'A1001', cpu: 4, ram_gb: 8, disk_gb: 80, template_key: null, os_label: null,
  status: 'ready', error: null, department: { id: 1, name: 'Разработка' },
  user: { id: 1, username: 'i.ivanov', display_name: 'Иван Иванов' }, requester_name: 'Иван Иванов', requester_nick: 'iivanov',
  purpose: null, expected_return_at: null, requested_return_at: null, ip_address: '10.0.0.15', connection_login: 'user', connection_method: 'RDP', power_state: 'on', created_at: '2024-01-10T09:00:00Z',
  ready_at: '2024-01-10T09:10:00Z', released_at: null, deleted_at: null, ...over,
})

let vms: Vm[]

beforeEach(() => {
  vms = [makeVm(), makeVm({ id: 2, order_number: 201, name: 'A1002', cpu: 2, ram_gb: 4, disk_gb: 50, status: 'failed', error: 'Нет места', ip_address: null })]
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/vms') return vms
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({})
})

describe('VmsPage', () => {
  it('рисует виртуалки и суммарные ресурсы только работающих', async () => {
    renderWithProviders(<VmsPage />)
    expect(await screen.findByText('A1001')).toBeInTheDocument()
    expect(screen.getByText('Работают сейчас: 4 ядер, 8 ГБ памяти, 80 ГБ дисков')).toBeInTheDocument()
    expect(screen.getByText('Нет места')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/vms', { include_deleted: false })
  })

  it('пустой список — «Виртуалок пока нет»', async () => {
    vms = []
    renderWithProviders(<VmsPage />)
    expect(await screen.findByText('Виртуалок пока нет')).toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Виртуалок пока нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/vms')
    renderWithProviders(<VmsPage />)
    expect(await screen.findByText('Не удалось загрузить виртуалки')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Виртуалок пока нет')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('A1001')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('«Показать удалённые» перезапрашивает список с include_deleted', async () => {
    const user = userEvent.setup()
    renderWithProviders(<VmsPage />)
    await screen.findByText('A1001')
    await user.click(screen.getByLabelText('Показать удалённые'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/vms', { include_deleted: true }))
  })

  it('удаление после подтверждения: POST /vms/{id}/release', async () => {
    const user = userEvent.setup()
    renderWithProviders(<VmsPage />)
    const row = (await screen.findByText('A1001')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Удалить' }))
    const dialog = screen.getByRole('dialog', {
      name: 'Удалить виртуалку A1001?',
      description: 'Она будет выключена и удалена вместе с диском.',
    })
    expect(api.post).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Удалить' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vms/1/release'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('«Отмена» закрывает окно без запроса', async () => {
    const user = userEvent.setup()
    renderWithProviders(<VmsPage />)
    const row = (await screen.findByText('A1001')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Удалить' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отмена' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })
})
