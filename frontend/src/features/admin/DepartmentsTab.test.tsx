import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { DepartmentsTab } from './DepartmentsTab'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { DepartmentUsage } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeUsage = (over: Partial<DepartmentUsage> = {}): DepartmentUsage => ({
  department_id: 1, name: 'Разработка', code: 'DEV', head_name: 'Пётр Петров', is_active: true,
  active: 3, by_tier: { medium: 2, powerful: 1 }, total_bookings: 12, last_booked_at: '2024-03-01T10:00:00Z', ...over,
})

let usage: DepartmentUsage[]

beforeEach(() => {
  usage = [makeUsage(), makeUsage({ department_id: 2, name: 'Аналитика', code: null, head_name: null, is_active: false, active: 0, by_tier: {} })]
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/departments') return usage
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({})
  vi.mocked(api.patch).mockResolvedValue({})
})

describe('DepartmentsTab', () => {
  it('рисует отделы: код, руководителя, число ПК; скрытый помечен', async () => {
    renderWithProviders(<DepartmentsTab />)
    const row = (await screen.findByText('Разработка')).closest('tr')!
    expect(within(row).getByText('DEV')).toBeInTheDocument()
    expect(within(row).getByText('Пётр Петров')).toBeInTheDocument()
    expect(within(row).getByText('12')).toBeInTheDocument()
    expect(within(screen.getByText('Аналитика').closest('tr')!).getByText('скрыт')).toBeInTheDocument()
  })

  it('пустой справочник — «Отделов пока нет»', async () => {
    usage = []
    renderWithProviders(<DepartmentsTab />)
    expect(await screen.findByText('Отделов пока нет')).toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Отделов пока нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/departments')
    renderWithProviders(<DepartmentsTab />)
    expect(await screen.findByText('Не удалось загрузить отделы')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Отделов пока нет')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Добавить первый' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Разработка')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('«Скрыть» отправляет is_active=false', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DepartmentsTab />)
    const row = (await screen.findByText('Разработка')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Скрыть' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/departments/1', { is_active: false }))
  })

  it('новый отдел: название короче двух символов не сохраняется, затем POST', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DepartmentsTab />)
    await screen.findByText('Разработка')
    await user.click(screen.getByRole('button', { name: 'Добавить отдел' }))
    const dialog = await screen.findByRole('dialog')
    const save = within(dialog).getByRole('button', { name: 'Сохранить' })
    await user.type(within(dialog).getByLabelText(/Название/), 'Q')
    expect(save).toBeDisabled()
    await user.type(within(dialog).getByLabelText(/Название/), 'A')
    await user.click(save)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/departments', { name: 'QA', code: null, head_name: null }))
  })
})
