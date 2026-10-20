import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PeoplePage } from './PeoplePage'
import { api } from '@/lib/api'
import { renderWithProviders } from '@/test/helpers'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

beforeEach(() => {
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (['/admin/users', '/admin/departments', '/departments'].includes(path)) return []
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('PeoplePage', () => {
  it('по умолчанию открыты сотрудники: поиск и «Добавить заранее», отделов нет', async () => {
    renderWithProviders(<PeoplePage />)
    expect(screen.getByRole('heading', { name: 'Сотрудники и отделы' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сотрудники' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('textbox', { name: 'Поиск сотрудника' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Добавить заранее' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Добавить отдел' })).not.toBeInTheDocument()
  })

  it('вкладка «Отделы» показывает справочник отделов вместо сотрудников и переключается обратно', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PeoplePage />)
    await user.click(screen.getByRole('button', { name: 'Отделы' }))
    expect(await screen.findByText('Отделов пока нет')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Добавить отдел' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Поиск сотрудника' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Сотрудники' }))
    expect(screen.getByRole('textbox', { name: 'Поиск сотрудника' })).toBeInTheDocument()
  })

  it('адрес ?tab=departments сразу открывает отделы (ссылка с обзора)', async () => {
    renderWithProviders(<PeoplePage />, { route: '/admin/people?tab=departments' })
    expect(await screen.findByText('Отделов пока нет')).toBeInTheDocument()
  })
})
