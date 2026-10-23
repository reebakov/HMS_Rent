import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { BuildsCard } from './BuildsCard'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, makeExecutorOrder, renderWithProviders } from '@/test/helpers'
import type { ExecutorBuild } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeBuild = (over: Partial<ExecutorBuild> = {}): ExecutorBuild => ({
  id: 40,
  order_number: 2001,
  configuration: 'A — i9, 64 ГБ, RTX 4090',
  os_label: 'Debian 12',
  department: { id: 1, name: 'Builder Studio' },
  user: { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' },
  requester_nick: 'petrov',
  purpose: 'Нагрузочные тесты',
  expected_return_at: '2026-12-31',
  wanted_by: '2026-11-20',
  created_at: '2026-10-22T09:00:00Z',
  request_key: 'DR-40',
  request_url: 'https://jira.test/browse/DR-40',
  request_status: 'Backlog',
  request_error: null,
  request_done: false,
  ...over,
})

let builds: ExecutorBuild[]

beforeEach(() => {
  builds = [makeBuild()]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/builds') return builds
    if (path === '/executor/pools') return [{ id: 7, name: 'Сборки' }, { id: 8, name: 'Тесты' }]
    throw new Error(`неожиданный GET ${path}`)
  })
})

const row = async () => (await screen.findByText('A — i9, 64 ГБ, RTX 4090')).closest('tr')!

describe('BuildsCard', () => {
  it('показывает заказ: конфигурацию, ОС, команду, заказчика, цель, сроки и ссылку на задачу', async () => {
    renderWithProviders(<BuildsCard />)
    const r = within(await row())
    expect(r.getByText('№2001')).toBeInTheDocument()
    expect(r.getByText('Debian 12')).toBeInTheDocument()
    expect(r.getByText('Builder Studio')).toBeInTheDocument()
    expect(r.getByText('Пётр Петров (petrov)')).toBeInTheDocument()
    expect(r.getByText('Нагрузочные тесты')).toBeInTheDocument()
    expect(r.getByRole('link', { name: 'DR-40' })).toHaveAttribute('href', 'https://jira.test/browse/DR-40')
  })

  it('задача закрыта в Jira, а ПК не выдан — подсказка', async () => {
    builds = [makeBuild({ request_done: true })]
    renderWithProviders(<BuildsCard />)
    expect(await screen.findByText('Задача закрыта в Jira — выдайте ПК или отклоните заказ')).toBeInTheDocument()
  })

  describe('выдача', () => {
    const open = async (over: Partial<ExecutorBuild> = {}) => {
      builds = [makeBuild(over)]
      const user = userEvent.setup()
      renderWithProviders(<BuildsCard />)
      await user.click(within(await row()).getByRole('button', { name: 'Выдать ПК…' }))
      return { user, dialog: await screen.findByRole('dialog', { name: 'Выдать ПК по заказу №2001' }) }
    }

    it('кнопка недоступна без имени и пула; имя хоста следует за именем ПК, способ — по ОС', async () => {
      const { user, dialog } = await open()
      const submit = within(dialog).getByRole('button', { name: 'Выдать' })
      expect(submit).toBeDisabled()
      await user.type(within(dialog).getByLabelText(/Имя ПК/), 'A500')
      expect(submit).toBeDisabled()
      expect(within(dialog).getByLabelText(/Доменное имя/)).toHaveValue('A500.ff.local')
      expect(within(dialog).getByLabelText(/Способ подключения/)).toHaveValue('VNC') // Debian
      await user.selectOptions(await within(dialog).findByLabelText(/Пул/), 'Сборки')
      expect(submit).toBeEnabled()
    })

    it('отправка: POST с именем, пулом и данными подключения, тост, окно закрыто', async () => {
      vi.mocked(api.post).mockResolvedValue(makeExecutorOrder())
      const { user, dialog } = await open({ os_label: 'Windows 11' })
      await user.type(within(dialog).getByLabelText(/Имя ПК/), ' A500 ')
      await user.selectOptions(await within(dialog).findByLabelText(/Пул/), 'Тесты')
      await user.type(within(dialog).getByLabelText(/IP-адрес/), '10.5.0.5')
      await user.click(within(dialog).getByRole('button', { name: 'Выдать' }))
      expect(api.post).toHaveBeenCalledWith('/executor/builds/40/issue', {
        computer_name: 'A500', pool_id: 8, host: 'A500.ff.local', ip: '10.5.0.5', method: 'RDP',
      })
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('A500 выдан, заказчик получил данные для подключения'))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('вручную заданное имя хоста не затирается именем ПК', async () => {
      const { user, dialog } = await open()
      await user.type(within(dialog).getByLabelText(/Доменное имя/), 'my.host')
      await user.type(within(dialog).getByLabelText(/Имя ПК/), 'A500')
      expect(within(dialog).getByLabelText(/Доменное имя/)).toHaveValue('my.host')
    })

    it('ошибка сервера показана в окне, оно остаётся открытым', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(404, 'ПК A999 не найден в портале'))
      const { user, dialog } = await open()
      await user.type(within(dialog).getByLabelText(/Имя ПК/), 'A999')
      await user.selectOptions(await within(dialog).findByLabelText(/Пул/), 'Сборки')
      await user.type(within(dialog).getByLabelText(/IP-адрес/), '10.5.0.5')
      await user.click(within(dialog).getByRole('button', { name: 'Выдать' }))
      expect(await within(dialog).findByText('ПК A999 не найден в портале')).toBeInTheDocument()
      expect(toast.success).not.toHaveBeenCalled()
    })

    it('«Отмена» закрывает окно и очищает поля', async () => {
      const { user, dialog } = await open()
      await user.type(within(dialog).getByLabelText(/Имя ПК/), 'A500')
      await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      await user.click(within(await row()).getByRole('button', { name: 'Выдать ПК…' }))
      expect(screen.getByLabelText(/Имя ПК/)).toHaveValue('')
    })
  })

  describe('отклонение', () => {
    const open = async () => {
      const user = userEvent.setup()
      renderWithProviders(<BuildsCard />)
      await user.click(within(await row()).getByRole('button', { name: 'Отклонить…' }))
      return { user, dialog: screen.getByRole('dialog', { name: 'Отклонить заказ №2001?' }) }
    }

    it('кнопка недоступна без основания и комментария; основания — по регламенту', async () => {
      const { user, dialog } = await open()
      const submit = within(dialog).getByRole('button', { name: 'Отклонить' })
      expect(submit).toBeDisabled()
      expect(within(dialog).getAllByRole('option').map((o) => o.textContent)).toEqual([
        'Выберите основание', 'Нет комплектующих', 'Несовместимая конфигурация', 'Заказчик не ответил', 'Некорректный заказ',
      ])
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Нет комплектующих')
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), '   ')
      expect(submit).toBeDisabled()
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), 'Нет плат')
      expect(submit).toBeEnabled()
    })

    it('отправка: POST с основанием и обрезанным комментарием, тост, окно закрыто', async () => {
      vi.mocked(api.post).mockResolvedValue(undefined)
      const { user, dialog } = await open()
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Несовместимая конфигурация')
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), '  Плата не подходит  ')
      await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }))
      expect(api.post).toHaveBeenCalledWith('/executor/builds/40/reject', { reason: 'Несовместимая конфигурация', comment: 'Плата не подходит' })
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Заказ №2001 отклонён, заказчик получил уведомление'))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('ошибка сервера показана в окне', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Заказ на сборку уже обработан'))
      const { user, dialog } = await open()
      await user.selectOptions(within(dialog).getByLabelText(/Основание/), 'Некорректный заказ')
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), 'Дубль')
      await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }))
      expect(await within(dialog).findByText('Заказ на сборку уже обработан')).toBeInTheDocument()
    })
  })

  it('нет заказов — понятная заглушка', async () => {
    builds = []
    renderWithProviders(<BuildsCard />)
    expect(await screen.findByText('Заказов на сборку нет')).toBeInTheDocument()
  })

  it('ошибка загрузки — сообщение и «Повторить», а не пустой список', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/builds')
    renderWithProviders(<BuildsCard />)
    expect(await screen.findByText('Не удалось загрузить сборки')).toBeInTheDocument()
    expect(screen.queryByText('Заказов на сборку нет')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('A — i9, 64 ГБ, RTX 4090')).toBeInTheDocument()
  })
})
