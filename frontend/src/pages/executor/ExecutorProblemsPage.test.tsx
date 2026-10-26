import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ExecutorProblemsPage } from './ExecutorProblemsPage'
import { toast } from 'sonner'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { ExecutorProblem, ProblemTransition } from '@/lib/types'

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

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let problems: ExecutorProblem[]
let transitions: ProblemTransition[]

const mount = () =>
  renderWithProviders(
    <Routes>
      <Route path="/problems" element={<ExecutorProblemsPage />} />
      <Route path="/executor/orders/:id" element={<p>страница-заказа</p>} />
    </Routes>,
    { route: '/problems' },
  )

beforeEach(() => {
  localStorage.clear()
  problems = [makeProblem()]
  transitions = [
    { id: '161', name: 'In Progress', to_status: 'В работе', closes: false },
    { id: '151', name: 'Done', to_status: 'Готово', closes: true },
  ]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/problems') return problems
    if (path === '/executor/problems/1/transitions') return transitions
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

describe('ExecutorProblemsPage: новые проблемы', () => {
  it('непросмотренная открытая проблема помечена «Новая», после просмотра пометка запоминается как просмотренная', async () => {
    problems = [makeProblem({ id: 4 }), makeProblem({ id: 3, issue_key: 'DR-502', status: 'Done', status_category: 'done' })]
    mount()
    expect(await screen.findAllByText('Новая')).toHaveLength(1) // закрытая не «новая»
    await waitFor(() => expect(localStorage.getItem('hmsrent:problems-seen')).toBe('4'))
  })

  it('уже просмотренные проблемы без пометки', async () => {
    localStorage.setItem('hmsrent:problems-seen', '1')
    mount()
    await screen.findByRole('link', { name: 'DR-501' })
    expect(screen.queryByText('Новая')).not.toBeInTheDocument()
  })
})

describe('ExecutorProblemsPage: смена статуса', () => {
  const open = async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Сменить статус' }))
    return user
  }

  it('кнопка раскрывает переходы из Jira; переходы грузятся только по клику', async () => {
    mount()
    await screen.findByRole('link', { name: 'DR-501' })
    expect(api.get).not.toHaveBeenCalledWith('/executor/problems/1/transitions')
    await userEvent.click(screen.getByRole('button', { name: 'Сменить статус' }))
    expect(await screen.findByRole('button', { name: 'В работе' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Готово' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сменить статус' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('переходы идут столбцом ограниченной ширины и не раздвигают таблицу', async () => {
    await open()
    await screen.findByRole('button', { name: 'Готово' })
    const group = screen.getByRole('group', { name: 'Переходы статуса' })
    expect(group).toHaveClass('flex-col', 'w-48')
  })

  it('выбор перехода: POST, тост, меню закрывается', async () => {
    vi.mocked(api.post).mockResolvedValue(makeProblem({ status: 'В работе' }))
    const user = await open()
    await user.click(await screen.findByRole('button', { name: 'В работе' }))
    expect(api.post).toHaveBeenCalledWith('/executor/problems/1/transition', { transition_id: '161' })
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Задача DR-501: В работе'))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Готово' })).not.toBeInTheDocument())
  })

  it('ошибка Jira при обычном переходе показана тостом, меню остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(400, 'Не удалось сменить статус: Service Desk недоступен'))
    const user = await open()
    await user.click(await screen.findByRole('button', { name: 'В работе' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Не удалось сменить статус: Service Desk недоступен'))
    expect(screen.getByRole('button', { name: 'Готово' })).toBeInTheDocument()
  })

  describe('закрытие задачи', () => {
    const openClose = async () => {
      const user = await open()
      await user.click(await screen.findByRole('button', { name: 'Готово' }))
      return { user, dialog: await screen.findByRole('dialog', { name: 'Закрыть задачу DR-501?' }) }
    }

    it('переход в закрытый статус просит подтверждение и без него ничего не отправляет', async () => {
      const { user, dialog } = await openClose()
      expect(api.post).not.toHaveBeenCalled()
      await user.click(within(dialog).getByRole('button', { name: 'Отмена' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(api.post).not.toHaveBeenCalled()
    })

    it('подтверждение без комментария: POST без comment', async () => {
      vi.mocked(api.post).mockResolvedValue(makeProblem({ status: 'Готово', status_category: 'done' }))
      const { user, dialog } = await openClose()
      await user.click(within(dialog).getByRole('button', { name: 'Закрыть задачу' }))
      expect(api.post).toHaveBeenCalledWith('/executor/problems/1/transition', { transition_id: '151' })
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Задача DR-501: Готово'))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('свой комментарий уходит вместе с переходом, пробелы по краям обрезаются', async () => {
      vi.mocked(api.post).mockResolvedValue(makeProblem({ status: 'Готово', status_category: 'done' }))
      const { user, dialog } = await openClose()
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), '  Заменили кабель  ')
      await user.click(within(dialog).getByRole('button', { name: 'Закрыть задачу' }))
      expect(api.post).toHaveBeenCalledWith('/executor/problems/1/transition', { transition_id: '151', comment: 'Заменили кабель' })
    })

    it('ошибка показана в окне, оно остаётся открытым с введённым комментарием', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(400, 'Не удалось отправить комментарий: Service Desk недоступен'))
      const { user, dialog } = await openClose()
      await user.type(within(dialog).getByLabelText(/Комментарий для заказчика/), 'Готово')
      await user.click(within(dialog).getByRole('button', { name: 'Закрыть задачу' }))
      expect(await within(dialog).findByText('Не удалось отправить комментарий: Service Desk недоступен')).toBeInTheDocument()
      expect(within(dialog).getByLabelText(/Комментарий для заказчика/)).toHaveValue('Готово')
    })
  })

  it('переходов нет — об этом сказано', async () => {
    transitions = []
    await open()
    expect(await screen.findByText('Из этого статуса переходов нет')).toBeInTheDocument()
  })

  it('переходы не загрузились — ошибка и «Повторить»', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/problems/1/transitions', 'Jira недоступна')
    const user = await open()
    expect(await screen.findByText('Jira недоступна')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('button', { name: 'Готово' })).toBeInTheDocument()
  })

  it('у проблемы без задачи в Jira кнопки смены статуса нет', async () => {
    problems = [makeProblem({ issue_key: null, issue_url: null, status: null, status_category: null, error: 'Service Desk недоступен' })]
    mount()
    await screen.findByText('Заявка в Jira не создана')
    expect(screen.queryByRole('button', { name: 'Сменить статус' })).not.toBeInTheDocument()
  })
})
