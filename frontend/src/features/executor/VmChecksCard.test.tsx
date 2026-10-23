import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { VmChecksCard } from './VmChecksCard'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { ExecutorVm } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeVm = (over: Partial<ExecutorVm> = {}): ExecutorVm => ({
  id: 3,
  order_number: 555,
  name: 'A1007',
  cpu: 4,
  ram_gb: 8,
  disk_gb: 100,
  os_label: 'Windows 11 26H2',
  status: 'checking',
  ip_address: '10.0.0.5',
  connection_login: 'user',
  connection_method: 'RDP',
  power_state: 'poweredOn',
  department: { id: 1, name: 'Builder Studio' },
  user: { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' },
  requester_name: 'Пётр Петров',
  requester_nick: 'petrov',
  purpose: 'Сборка билдов',
  expected_return_at: '2026-12-31',
  created_at: '2026-10-22T09:00:00Z',
  request_key: 'DR-600',
  request_url: 'https://jira.test/browse/DR-600',
  request_status: 'Backlog',
  request_error: null,
  request_done: false,
  ...over,
})

let vms: ExecutorVm[]

beforeEach(() => {
  vms = [makeVm()]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/vms') return vms
    throw new Error(`неожиданный GET ${path}`)
  })
})

const row = async () => (await screen.findByText('A1007')).closest('tr')!

describe('VmChecksCard', () => {
  it('показывает ВМ, ресурсы, IP, способ, команду, заказчика и ссылку на задачу в Jira', async () => {
    renderWithProviders(<VmChecksCard />)
    const r = within(await row())
    expect(r.getByText('№555')).toBeInTheDocument()
    expect(r.getByText('Windows 11 26H2 · 4 ядра · 8 ГБ · 100 ГБ')).toBeInTheDocument()
    expect(r.getByText('10.0.0.5')).toBeInTheDocument()
    expect(r.getByText('RDP')).toBeInTheDocument()
    expect(r.getByText('Builder Studio')).toBeInTheDocument()
    expect(r.getByText('Пётр Петров (petrov)')).toBeInTheDocument()
    expect(r.getByRole('link', { name: 'DR-600' })).toHaveAttribute('href', 'https://jira.test/browse/DR-600')
  })

  it('нет IP и нет ОС — об этом сказано', async () => {
    vms = [makeVm({ ip_address: null, os_label: null, connection_method: null })]
    renderWithProviders(<VmChecksCard />)
    const r = within(await row())
    expect(r.getByText('пока нет')).toBeInTheDocument()
    expect(r.getByText(/ОС не указана/)).toBeInTheDocument()
  })

  it('задача в Jira закрыта, а ВМ не решена — подсказка', async () => {
    vms = [makeVm({ request_done: true })]
    renderWithProviders(<VmChecksCard />)
    expect(await screen.findByText('Задача закрыта в Jira — подтвердите или отклоните ВМ')).toBeInTheDocument()
  })

  it('«Подтвердить»: POST, тост, повтор запроса списка', async () => {
    vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'ready' }))
    renderWithProviders(<VmChecksCard />)
    await userEvent.click(within(await row()).getByRole('button', { name: 'Подтвердить' }))
    expect(api.post).toHaveBeenCalledWith('/executor/vms/3/confirm', undefined)
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('A1007 подтверждена, заказчик получил данные для подключения'))
  })

  it('«Подтвердить»: ошибка сервера показана тостом', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'ВМ уже не на проверке'))
    renderWithProviders(<VmChecksCard />)
    await userEvent.click(within(await row()).getByRole('button', { name: 'Подтвердить' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('ВМ уже не на проверке'))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('«Пересоздать» идёт через подтверждение', async () => {
    vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
    renderWithProviders(<VmChecksCard />)
    const user = userEvent.setup()
    await user.click(within(await row()).getByRole('button', { name: 'Пересоздать' }))
    expect(api.post).not.toHaveBeenCalled() // пока не подтвердили
    const dialog = screen.getByRole('dialog', { name: 'Пересоздать A1007?' })
    await user.click(within(dialog).getByRole('button', { name: 'Пересоздать' }))
    expect(api.post).toHaveBeenCalledWith('/executor/vms/3/recreate', undefined)
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('A1007 будет пересоздана'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('«Пересоздать»: ошибка остаётся в тосте, окно открыто', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'ВМ уже не на проверке'))
    renderWithProviders(<VmChecksCard />)
    const user = userEvent.setup()
    await user.click(within(await row()).getByRole('button', { name: 'Пересоздать' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Пересоздать' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('ВМ уже не на проверке'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  describe('отклонение', () => {
    const open = async () => {
      const user = userEvent.setup()
      renderWithProviders(<VmChecksCard />)
      await user.click(within(await row()).getByRole('button', { name: 'Отклонить…' }))
      return { user, dialog: screen.getByRole('dialog', { name: 'Отклонить A1007?' }) }
    }

    it('кнопка недоступна, пока нет основания и комментария; основания — по регламенту', async () => {
      const { user, dialog } = await open()
      const submit = within(dialog).getByRole('button', { name: 'Отклонить' })
      expect(submit).toBeDisabled()
      const options = within(dialog).getAllByRole('option').map((o) => o.textContent)
      expect(options).toEqual(['Выберите основание', 'Не удалось подготовить ВМ', 'Недостаточно мощностей кластера', 'Заказчик не ответил', 'Некорректный заказ'])
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Некорректный заказ')
      expect(submit).toBeDisabled()
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), '   ')
      expect(submit).toBeDisabled()
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), 'Дубль заказа')
      expect(submit).toBeEnabled()
    })

    it('отправка: POST с основанием и обрезанным комментарием, тост, окно закрыто', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const { user, dialog } = await open()
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Не удалось подготовить ВМ')
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), '  Не стартует  ')
      await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }))
      expect(api.post).toHaveBeenCalledWith('/executor/vms/3/reject', { reason: 'Не удалось подготовить ВМ', comment: 'Не стартует' })
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('A1007 отклонена, заказчик получил уведомление'))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('ошибка сервера показана в окне, оно остаётся открытым', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'ВМ уже не на проверке'))
      const { user, dialog } = await open()
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Некорректный заказ')
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), 'Дубль')
      await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }))
      expect(await within(dialog).findByText('ВМ уже не на проверке')).toBeInTheDocument()
      expect(toast.success).not.toHaveBeenCalled()
    })

    it('«Отмена» закрывает окно и очищает поля', async () => {
      const { user, dialog } = await open()
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Некорректный заказ')
      await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      await user.click(within(await row()).getByRole('button', { name: 'Отклонить…' }))
      expect(screen.getByLabelText(/Основание/)).toHaveValue('')
    })
  })

  it('нет ВМ на проверке — понятная заглушка', async () => {
    vms = []
    renderWithProviders(<VmChecksCard />)
    expect(await screen.findByText('Все созданные ВМ проверены')).toBeInTheDocument()
  })

  it('ошибка загрузки — сообщение и «Повторить», а не пустой список', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/vms')
    renderWithProviders(<VmChecksCard />)
    expect(await screen.findByText('Не удалось загрузить ВМ на проверке')).toBeInTheDocument()
    expect(screen.queryByText('Все созданные ВМ проверены')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('A1007')).toBeInTheDocument()
  })
})
