import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { DiagnosticsCard } from './DiagnosticsCard'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { ExecutorDiagnostic } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeDiagnostic = (over: Partial<ExecutorDiagnostic> = {}): ExecutorDiagnostic => ({
  id: 4,
  computer: { id: 10, name: 'A001', tier: 'medium', is_virtual: false, cpu: 'Intel Core i5', ram_gb: 16, storage: null, gpu: null },
  pool_name: 'Main',
  comment: 'Не включается, пищит БП',
  created_at: '2026-10-22T09:00:00Z',
  issue_key: 'DR-700',
  issue_url: 'https://jira.test/browse/DR-700',
  status: 'In Progress',
  error: null,
  request_done: false,
  ...over,
})

let items: ExecutorDiagnostic[]

beforeEach(() => {
  items = [makeDiagnostic()]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/diagnostics') return items
    throw new Error(`неожиданный GET ${path}`)
  })
})

const row = async () => (await screen.findByText('A001')).closest('tr')!

describe('DiagnosticsCard', () => {
  it('показывает ПК, прежний пул, что случилось и задачу в Jira', async () => {
    renderWithProviders(<DiagnosticsCard />)
    const r = within(await row())
    expect(r.getByText('Main')).toBeInTheDocument()
    expect(r.getByText('Не включается, пищит БП')).toBeInTheDocument()
    expect(r.getByRole('link', { name: 'DR-700' })).toHaveAttribute('href', 'https://jira.test/browse/DR-700')
  })

  it('прежний пул не известен — об этом сказано', async () => {
    items = [makeDiagnostic({ pool_name: null, comment: '' })]
    renderWithProviders(<DiagnosticsCard />)
    const r = within(await row())
    expect(r.getByText('не известен')).toBeInTheDocument()
    expect(r.getByText('—')).toBeInTheDocument()
  })

  it('«Вернуть в пул» идёт через подтверждение с названием пула', async () => {
    vi.mocked(api.post).mockResolvedValue(makeDiagnostic())
    renderWithProviders(<DiagnosticsCard />)
    const user = userEvent.setup()
    await user.click(within(await row()).getByRole('button', { name: 'Вернуть в пул' }))
    expect(api.post).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog', { name: 'Вернуть A001 в пул?' })
    expect(within(dialog).getByText(/вернётся в пул «Main»/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }))
    expect(api.post).toHaveBeenCalledWith('/executor/diagnostics/4/repaired')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('A001 вернулся в пул «Main»'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('без известного пула предупреждает, что вернуть в пул придётся вручную', async () => {
    items = [makeDiagnostic({ pool_name: null })]
    vi.mocked(api.post).mockResolvedValue(makeDiagnostic({ pool_name: null }))
    renderWithProviders(<DiagnosticsCard />)
    const user = userEvent.setup()
    await user.click(within(await row()).getByRole('button', { name: 'Вернуть в пул' }))
    expect(within(screen.getByRole('dialog')).getByText(/в пул его придётся вернуть вручную/)).toBeInTheDocument()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Вернуть' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('A001 вернулся в работу'))
  })

  it('ошибка сервера показана тостом, окно остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'A001 уже не на диагностике'))
    renderWithProviders(<DiagnosticsCard />)
    const user = userEvent.setup()
    await user.click(within(await row()).getByRole('button', { name: 'Вернуть в пул' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Вернуть' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('A001 уже не на диагностике'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('нет ПК на диагностике — понятная заглушка', async () => {
    items = []
    renderWithProviders(<DiagnosticsCard />)
    expect(await screen.findByText('Нет ПК на диагностике')).toBeInTheDocument()
  })

  it('ошибка загрузки — сообщение и «Повторить», а не пустой список', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/diagnostics')
    renderWithProviders(<DiagnosticsCard />)
    expect(await screen.findByText('Не удалось загрузить ПК на диагностике')).toBeInTheDocument()
    expect(screen.queryByText('Нет ПК на диагностике')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('A001')).toBeInTheDocument()
  })
})
