import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ExecutorProblemsPage } from './ExecutorProblemsPage'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { ExecutorProblem } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const makeProblem = (over: Partial<ExecutorProblem> = {}): ExecutorProblem => ({
  id: 1,
  issue_key: 'DR-501',
  issue_url: 'https://jira.test/browse/DR-501',
  status: 'In Progress',
  status_category: 'indeterminate',
  error: null,
  message: 'Не включается\nпосле обновления',
  created_at: '2026-10-21T09:00:00Z',
  reporter: { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' },
  department: { id: 1, name: 'Builder Studio' },
  order_number: 1042,
  target_name: 'A032',
  is_vm: false,
  booking_id: 7,
  ...over,
})

let problems: ExecutorProblem[]

const mount = () =>
  renderWithProviders(
    <Routes>
      <Route path="/problems" element={<ExecutorProblemsPage />} />
      <Route path="/executor/orders/:id" element={<p>страница-заказа</p>} />
    </Routes>,
    { route: '/problems' },
  )

beforeEach(() => {
  problems = [makeProblem()]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/problems') return problems
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('ExecutorProblemsPage', () => {
  it('показывает задачу Jira, ПК, заказ, команду, заказчика, текст и статус', async () => {
    mount()
    const row = (await screen.findByRole('link', { name: 'DR-501' })).closest('tr')!
    expect(screen.getByRole('link', { name: 'DR-501' })).toHaveAttribute('href', 'https://jira.test/browse/DR-501')
    expect(screen.getByRole('link', { name: 'DR-501' })).toHaveAttribute('target', '_blank')
    const r = within(row)
    expect(r.getByText('ПК · заказ №1042')).toBeInTheDocument()
    expect(r.getByText('Builder Studio')).toBeInTheDocument()
    expect(r.getByText('Пётр Петров')).toBeInTheDocument()
    expect(r.getByText(/Не включается/)).toBeInTheDocument()
    expect(r.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Открыто: 1 проблема')).toBeInTheDocument()
  })

  it('имя ПК ведёт на страницу заказа исполнителя', async () => {
    mount()
    await userEvent.click(await screen.findByRole('link', { name: 'A032' }))
    expect(screen.getByText('страница-заказа')).toBeInTheDocument()
  })

  it('у ВМ страницы заказа нет — имя без ссылки, пометка «ВМ»', async () => {
    problems = [makeProblem({ is_vm: true, booking_id: null, target_name: 'A1007', order_number: 555 })]
    mount()
    expect(await screen.findByText('A1007')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'A1007' })).not.toBeInTheDocument()
    expect(screen.getByText('ВМ · заказ №555')).toBeInTheDocument()
  })

  it('заявка в Jira не создалась — об этом сказано, ссылки нет', async () => {
    problems = [makeProblem({ issue_key: null, issue_url: null, status: null, status_category: null, error: 'Service Desk недоступен' })]
    mount()
    expect(await screen.findByText('Заявка в Jira не создана')).toHaveAttribute('title', 'Service Desk недоступен')
    expect(screen.getByText('Не создана')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /DR-/ })).not.toBeInTheDocument()
  })

  it('закрытая проблема не считается открытой', async () => {
    problems = [makeProblem({ status: 'Done', status_category: 'done' })]
    mount()
    expect(await screen.findByText('Открытых проблем нет')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('проблем нет — пустое состояние', async () => {
    problems = []
    mount()
    expect(await screen.findByText('Проблем нет')).toBeInTheDocument()
  })

  it('ошибка загрузки — сообщение и «Повторить», не пустой список', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/problems')
    mount()
    expect(await screen.findByText('Не удалось загрузить проблемы')).toBeInTheDocument()
    expect(screen.queryByText('Проблем нет')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('link', { name: 'DR-501' })).toBeInTheDocument()
  })
})
