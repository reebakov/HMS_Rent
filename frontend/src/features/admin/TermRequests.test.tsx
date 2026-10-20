import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { TermRequests } from './TermRequests'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import { addDays, formatDate, todayLocal } from '@/lib/utils'
import type { TermRequestOut } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const today = todayLocal()
const CURRENT = addDays(today, 90)
const REQUESTED = addDays(today, 240)

const makeRequest = (over: Partial<TermRequestOut> = {}): TermRequestOut => ({
  id: 3, kind: 'pc', name: 'PC-010', order_number: 77, department: { id: 1, name: 'Разработка' },
  requester_name: 'Пётр Петров', requester_nick: 'p.petrov', user: { id: 4, username: 'p.petrov', display_name: 'Пётр Петров' },
  current_return_at: CURRENT, requested_return_at: REQUESTED, comment: 'Проект затянулся', created_at: '2026-10-19T09:00:00Z', ...over,
})

let requests: TermRequestOut[]

beforeEach(() => {
  requests = [makeRequest(), makeRequest({ id: 4, kind: 'vm', name: 'rent-vm-01', order_number: 12, comment: null })]
  for (const m of [api.get, api.post]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/term-requests') return requests
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({})
})

const row = (name: string) => screen.getByText(name).closest('tr') as HTMLElement

describe('TermRequests: список', () => {
  it('рисует ПК и ВМ: тип, заказ, команда, арендатор, срок «сейчас → просят», причину, кто просит', async () => {
    renderWithProviders(<TermRequests />)
    await screen.findByText('PC-010')

    const pc = within(row('PC-010'))
    expect(pc.getByText('Компьютер · заказ №77')).toBeInTheDocument()
    expect(pc.getByText('Разработка')).toBeInTheDocument()
    expect(pc.getByText('Пётр Петров (p.petrov)')).toBeInTheDocument()
    expect(pc.getByText(formatDate(REQUESTED))).toBeInTheDocument()
    expect(pc.getByText(/→/)).toHaveTextContent(`${formatDate(CURRENT)} → ${formatDate(REQUESTED)}`)
    expect(pc.getByText('Проект затянулся')).toBeInTheDocument()

    const vm = within(row('rent-vm-01'))
    expect(vm.getByText('Виртуалка · заказ №12')).toBeInTheDocument()
    expect(vm.getByText('—')).toBeInTheDocument() // причины нет
  })

  it('заявок нет — «Заявок нет»', async () => {
    requests = []
    renderWithProviders(<TermRequests />)
    expect(await screen.findByText('Заявок нет')).toBeInTheDocument()
  })

  it('ошибка загрузки: текст и «Повторить» вместо «Заявок нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/term-requests')
    renderWithProviders(<TermRequests />)
    expect(await screen.findByText('Не удалось загрузить заявки на срок')).toBeInTheDocument()
    expect(screen.queryByText('Заявок нет')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-010')).toBeInTheDocument()
  })
})

describe('TermRequests: согласование', () => {
  const open = async () => {
    const user = userEvent.setup()
    renderWithProviders(<TermRequests />)
    await screen.findByText('PC-010')
    await user.click(within(row('PC-010')).getByRole('button', { name: 'Согласовать' }))
    const dialog = await screen.findByRole('dialog', { name: 'Согласовать срок PC-010' })
    return { user, dialog }
  }

  it('окно предлагает запрошенный срок; min — день после текущего срока', async () => {
    const { dialog } = await open()
    const input = within(dialog).getByLabelText(/Срок возврата/)
    expect(input).toHaveValue(REQUESTED)
    expect(input).toHaveAttribute('min', addDays(CURRENT, 1))
    expect(within(dialog).getByText(`Сейчас — до ${formatDate(CURRENT)}, просят — до ${formatDate(REQUESTED)}.`)).toBeInTheDocument()
  })

  it('«Согласовать» отправляет запрошенный срок, показывает тост и закрывает окно', async () => {
    const { user, dialog } = await open()
    await user.click(within(dialog).getByRole('button', { name: 'Согласовать' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(api.post).toHaveBeenCalledWith('/admin/term-requests/3/approve', { approved_return_at: REQUESTED })
    expect(toast.success).toHaveBeenCalledWith(`Срок PC-010 согласован до ${formatDate(REQUESTED)}`)
  })

  it('админ может поставить свою дату', async () => {
    const { user, dialog } = await open()
    const own = addDays(CURRENT, 30)
    const input = within(dialog).getByLabelText(/Срок возврата/)
    await user.clear(input)
    await user.type(input, own)
    await user.click(within(dialog).getByRole('button', { name: 'Согласовать' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/term-requests/3/approve', { approved_return_at: own }))
  })

  it.each([
    ['не позже текущего срока', () => CURRENT],
    ['очищена', () => ''],
  ])('дата %s — кнопка отключена', async (_, value) => {
    const { user, dialog } = await open()
    const input = within(dialog).getByLabelText(/Срок возврата/)
    await user.clear(input)
    if (value()) await user.type(input, value())
    expect(within(dialog).getByRole('button', { name: 'Согласовать' })).toBeDisabled()
  })

  it('у просроченного заказа min — сегодня', async () => {
    requests = [makeRequest({ current_return_at: addDays(today, -10), requested_return_at: addDays(today, 30) })]
    const { dialog } = await open()
    expect(within(dialog).getByLabelText(/Срок возврата/)).toHaveAttribute('min', today)
  })

  it('ошибка API показывается в окне, окно остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Бронирование уже закрыто'))
    const { user, dialog } = await open()
    await user.click(within(dialog).getByRole('button', { name: 'Согласовать' }))
    expect(await within(dialog).findByText('Бронирование уже закрыто')).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('Esc закрывает окно без запроса', async () => {
    const { user } = await open()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(api.post).not.toHaveBeenCalled()
  })
})

describe('TermRequests: отказ', () => {
  const open = async () => {
    const user = userEvent.setup()
    renderWithProviders(<TermRequests />)
    await screen.findByText('PC-010')
    await user.click(within(row('PC-010')).getByRole('button', { name: 'Отклонить' }))
    const dialog = await screen.findByRole('dialog', { name: 'Отклонить заявку по PC-010?' })
    return { user, dialog }
  }

  it('подтверждение отправляет отказ и закрывает окно', async () => {
    const { user, dialog } = await open()
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/term-requests/3/reject'))
    expect(toast.success).toHaveBeenCalledWith(`Заявка по PC-010 отклонена — срок остался ${formatDate(CURRENT)}`)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('ошибка отказа — тост с текстом, окно остаётся', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Заявка уже обработана'))
    const { user, dialog } = await open()
    await user.click(within(dialog).getByRole('button', { name: 'Отклонить' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Заявка уже обработана'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('«Отмена» закрывает окно без запроса', async () => {
    const { user, dialog } = await open()
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
    expect(api.post).not.toHaveBeenCalled()
  })
})
