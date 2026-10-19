import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from './AppShell'
import { api } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { OverdueItem, Session } from '@/lib/types'

let session: Session
vi.mock('@/auth/AuthProvider', () => ({
  useSession: () => session,
  useAuth: () => ({ session, loading: false, login: vi.fn(), logout: vi.fn() }),
}))
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const item = (id: number): OverdueItem => ({
  kind: 'pc', id, order_number: id, name: `PC-${id}`, department: 'Разработка', requester_name: 'Пётр', requester_nick: 'p',
  email: null, taken_at: null, due: '2026-10-01', days: 2,
})
let overdue: OverdueItem[]

const mountShell = (route = '/') =>
  renderWithProviders(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>страница-каталог</p>} />
        <Route path="admin/overdue" element={<p>страница-просрочки</p>} />
      </Route>
    </Routes>,
    { route },
  )

const overdueLink = () => screen.getByRole('link', { name: /^Просрочки/ })

beforeEach(() => {
  session = makeSession({ role: 'admin' })
  overdue = [item(1), item(2), item(3)]
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/overdue') return overdue
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('AppShell: «Просрочки»', () => {
  it('админ видит пункт «Просрочки», ведущий на /admin/overdue', async () => {
    mountShell()
    expect(overdueLink()).toHaveAttribute('href', '/admin/overdue')
    await screen.findByText('3')
  })

  it('счётчик берётся из длины списка просрочек', async () => {
    mountShell()
    expect(await within(overdueLink()).findByText('3')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/overdue')
  })

  it('счётчик красный (плашка bg-danger) и стоит внутри самой ссылки', async () => {
    mountShell()
    expect(await within(overdueLink()).findByText('3')).toHaveClass('bg-danger')
  })

  it('при нуле просрочек счётчика нет, пункт остаётся', async () => {
    overdue = []
    mountShell()
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/overdue'))
    expect(overdueLink()).toBeInTheDocument()
    expect(overdueLink().querySelector('.bg-danger')).toBeNull()
    expect(overdueLink()).toHaveTextContent(/^Просрочки$/)
  })

  it('ошибка загрузки просрочек: меню работает, счётчика нет', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('500'))
    mountShell()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(overdueLink().querySelector('.bg-danger')).toBeNull()
  })

  it('счётчик только у «Просрочки»: другие пункты без плашки', async () => {
    const { container } = mountShell()
    await within(overdueLink()).findByText('3')
    expect(container.querySelectorAll('nav .bg-danger')).toHaveLength(1)
  })

  it('большое число выводится как есть', async () => {
    overdue = Array.from({ length: 120 }, (_, i) => item(i + 1))
    mountShell()
    expect(await within(overdueLink()).findByText('120')).toBeInTheDocument()
  })

  it('мобильное меню тоже показывает счётчик', async () => {
    const user = userEvent.setup()
    mountShell()
    await within(overdueLink()).findByText('3')
    await user.click(screen.getAllByRole('button').find((b) => b.className.includes('lg:hidden'))!)
    const links = screen.getAllByRole('link', { name: /^Просрочки/ })
    expect(links).toHaveLength(2)
    for (const l of links) expect(within(l).getByText('3')).toBeInTheDocument()
  })

  it('переход по пункту открывает страницу и подсвечивает его', async () => {
    const user = userEvent.setup()
    mountShell()
    await user.click(overdueLink())
    expect(screen.getByText('страница-просрочки')).toBeInTheDocument()
    expect(overdueLink()).toHaveAttribute('aria-current', 'page')
  })

  it('сотрудник: пункта «Просрочки» нет и запрос просрочек не уходит', async () => {
    session = makeSession()
    mountShell()
    await screen.findByText('страница-каталог')
    expect(screen.queryByRole('link', { name: /Просрочки/ })).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalled()
  })
})
