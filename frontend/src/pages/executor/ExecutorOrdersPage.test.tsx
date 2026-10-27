import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { ExecutorOrdersPage } from './ExecutorOrdersPage'
import { toast } from 'sonner'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, makeExecutorOrder, renderWithProviders } from '@/test/helpers'
import type { ExecutorOrder, NormInfo } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let norms: NormInfo[]
let orders: ExecutorOrder[]
let returns: ExecutorOrder[]

const mount = () =>
  renderWithProviders(
    <Routes>
      <Route path="/executor" element={<ExecutorOrdersPage />} />
      <Route path="/executor/orders/:id" element={<p>страница-заказа</p>} />
    </Routes>,
    { route: '/executor' },
  )

beforeEach(() => {
  orders = [
    makeExecutorOrder(),
    makeExecutorOrder({ id: 8, order_number: 1043, computer: { ...makeExecutorOrder().computer, name: 'A065' }, prepared_at: '2026-10-21T10:00:00Z' }),
  ]
  returns = []
  norms = []
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/orders') return orders
    if (path === '/executor/returns') return returns
    if (path === '/executor/vms') return []
    if (path === '/executor/builds') return []
    if (path === '/executor/norms') return norms
    if (path === '/executor/diagnostics') return []
    throw new Error(`неожиданный GET ${path}`)
  })
})

const norm = (over: Partial<NormInfo> = {}): NormInfo => ({
  issue_key: 'DR-501', spent_seconds: 3 * 3600, limit_seconds: 8 * 3600, limit_name: '1 рабочий день', state: 'ok',
  frozen: false, taken: true, not_taken_late: false, ...over,
})

describe('ExecutorOrdersPage: нормативы', () => {
  const rowWithKey = async () => (await screen.findByRole('link', { name: 'DR-501' })).closest('tr') as HTMLElement

  it('под ссылкой на задачу — сколько рабочих часов потрачено из положенных', async () => {
    orders = [makeExecutorOrder({ request_key: 'DR-501', request_url: 'https://jira.test/browse/DR-501' })]
    norms = [norm({ spent_seconds: 12600 })]
    mount()
    expect(await within(await rowWithKey()).findByText('Норматив: 3,5 из 8 ч')).toBeInTheDocument()
  })

  it('просроченная задача и не взятая за срок помечены, в заголовке — число просрочек', async () => {
    orders = [makeExecutorOrder({ request_key: 'DR-501', request_url: 'https://jira.test/browse/DR-501' })]
    norms = [norm({ state: 'overdue', spent_seconds: 9 * 3600, not_taken_late: true, taken: false })]
    mount()
    const row = within(await rowWithKey())
    expect(await row.findByText('Просрочено: 9 из 8 ч')).toBeInTheDocument()
    expect(row.getByText('Не взята')).toBeInTheDocument()
    expect(screen.getByText(/просрочено по нормативу: 1/)).toBeInTheDocument()
  })

  it('на паузе — пометка заморозки, у вида задачи без норматива часов нет', async () => {
    orders = [makeExecutorOrder({ request_key: 'DR-501', request_url: 'https://jira.test/browse/DR-501' })]
    norms = [norm({ frozen: true, limit_seconds: null, limit_name: null })]
    mount()
    const row = within(await rowWithKey())
    expect(await row.findByText('· пауза (Frozen)')).toBeInTheDocument()
    expect(row.queryByText(/Норматив:/)).not.toBeInTheDocument()
  })

  it('нормативы не загрузились — страница работает без них', async () => {
    orders = [makeExecutorOrder({ request_key: 'DR-501', request_url: 'https://jira.test/browse/DR-501' })]
    failGetOnce(vi.mocked(api.get), '/executor/norms')
    mount()
    expect(await rowWithKey()).toBeInTheDocument()
    expect(screen.queryByText(/просрочено по нормативу/)).not.toBeInTheDocument()
  })
})

describe('ExecutorOrdersPage', () => {
  it('задача закрыта в Jira, а данных нет — подсказка внести данные; у подготовленного заказа подсказки нет', async () => {
    orders = [makeExecutorOrder({ request_done: true }), makeExecutorOrder({ id: 8, order_number: 1043, request_done: true, prepared_at: '2026-10-21T10:00:00Z' })]
    mount()
    await screen.findAllByRole('row')
    await userEvent.click(screen.getByRole('button', { name: /Архив заказов/ }))
    expect(await screen.findAllByText('Задача закрыта в Jira — внесите данные подключения')).toHaveLength(1)
  })

  it('раздел называется «Задачи исполнителя», а выданные ПК — блок «Заказы на подготовку»', async () => {
    mount()
    expect(await screen.findByRole('heading', { name: 'Задачи исполнителя' })).toBeInTheDocument()
    expect(screen.getByText('Заказы на подготовку')).toBeInTheDocument()
  })

  it('показывает заказы со статусом подготовки и число ждущих', async () => {
    mount()
    const waiting = (await screen.findByRole('link', { name: 'A032' })).closest('tr')!
    expect(within(waiting).getByText('Ждёт подготовки')).toBeInTheDocument()
    expect(within(waiting).getByText('Windows 11 26H2')).toBeInTheDocument()
    expect(within(waiting).getByText('Пётр Петров (petrov)')).toBeInTheDocument()
    expect(screen.getByText('Ждут подготовки: 1 заказ')).toBeInTheDocument()
  })

  it('подготовленные заказы скрыты в «Архиве заказов», который раскрывается кнопкой снизу', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByRole('link', { name: 'A032' })
    expect(screen.queryByRole('link', { name: 'A065' })).not.toBeInTheDocument()
    const archive = screen.getByRole('button', { name: 'Архив заказов (1)' })
    expect(archive).toHaveAttribute('aria-expanded', 'false')

    await user.click(archive)
    const done = screen.getByRole('link', { name: 'A065' }).closest('tr')!
    expect(within(done).getByText('Подготовлен')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Архив заказов (1)' })).toHaveAttribute('aria-expanded', 'true')

    await user.click(screen.getByRole('button', { name: 'Архив заказов (1)' }))
    expect(screen.queryByRole('link', { name: 'A065' })).not.toBeInTheDocument()
  })

  it('нет подготовленных — кнопки архива нет', async () => {
    orders = [makeExecutorOrder()]
    mount()
    await screen.findByRole('link', { name: 'A032' })
    expect(screen.queryByRole('button', { name: /Архив заказов/ })).not.toBeInTheDocument()
  })

  it('в очереди у каждого заказа ссылка на его заявку в Jira', async () => {
    orders[0] = makeExecutorOrder({ request_key: 'HMS-77', request_url: 'https://jira.test/browse/HMS-77', request_status: 'Ожидает поддержки' })
    mount()
    const row = (await screen.findByRole('link', { name: 'A032' })).closest('tr')!
    expect(within(row).getByRole('link', { name: 'HMS-77' })).toHaveAttribute('href', 'https://jira.test/browse/HMS-77')
    expect(within(row).getByText('· Ожидает поддержки')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Архив заказов/ }))
    const other = screen.getByRole('link', { name: 'A065' }).closest('tr')!
    expect(within(other).getByText('Заявки нет')).toBeInTheDocument()
  })

  it('ссылка ПК ведёт на страницу заказа', async () => {
    mount()
    await userEvent.click(await screen.findByRole('link', { name: 'A032' }))
    expect(screen.getByText('страница-заказа')).toBeInTheDocument()
  })

  it('все подготовлены — об этом сказано в заголовке', async () => {
    orders = [makeExecutorOrder({ prepared_at: '2026-10-21T10:00:00Z' })]
    mount()
    expect(await screen.findByText('Все выданные ПК подготовлены')).toBeInTheDocument()
    expect(screen.getByText('Нет заказов на подготовку')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Архив заказов (1)' })).toBeInTheDocument()
  })

  it('пустая очередь — понятная заглушка', async () => {
    orders = []
    mount()
    expect(await screen.findByText('Выданных ПК нет')).toBeInTheDocument()
  })

  it('ошибка загрузки не выглядит как пустой список: «Повторить» загружает снова', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/orders')
    mount()
    expect(await screen.findByText('Не удалось загрузить заказы')).toBeInTheDocument()
    expect(screen.queryByText('Выданных ПК нет')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('link', { name: 'A032' })).toBeInTheDocument()
  })
})

describe('ExecutorOrdersPage: ждут очистки', () => {
  const returned = (over: Partial<ExecutorOrder> = {}) =>
    makeExecutorOrder({
      id: 20, order_number: 900, status: 'returned', returned_at: '2026-10-21T12:00:00Z', return_comment: 'Шумит кулер',
      computer: { ...makeExecutorOrder().computer, name: 'A077' }, ...over,
    })

  it('вернувшиеся ПК: данные заказа, заявка «Возврат ПК» и кнопка «Диск очищен»', async () => {
    returns = [returned({ request_key: 'HMS-90', request_url: 'https://jira.test/browse/HMS-90' })]
    mount()
    const row = (await screen.findByText('A077')).closest('tr')!
    expect(within(row).getByText('№900')).toBeInTheDocument()
    expect(within(row).getByText('«Шумит кулер»')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'HMS-90' })).toHaveAttribute('href', 'https://jira.test/browse/HMS-90')
  })

  it('«Диск очищен»: POST, тост, ПК уходит из списка', async () => {
    returns = [returned()]
    vi.mocked(api.post).mockImplementation(async () => {
      returns = []
      return returned()
    })
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Диск очищен' }))
    expect(api.post).toHaveBeenCalledWith('/executor/returns/20/cleaned')
    expect(toast.success).toHaveBeenCalledWith('A077 очищен и снова свободен')
    await waitFor(() => expect(screen.getByText('Все вернувшиеся ПК очищены')).toBeInTheDocument())
  })

  it('ошибка подтверждения показывается тостом, ПК остаётся в списке', async () => {
    returns = [returned()]
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'A077 не ждёт очистки'))
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Диск очищен' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('A077 не ждёт очистки'))
    expect(screen.getByText('A077')).toBeInTheDocument()
  })

  it('нет вернувшихся — так и написано', async () => {
    mount()
    expect(await screen.findByText('Все вернувшиеся ПК очищены')).toBeInTheDocument()
  })

  it('ошибка загрузки возвратов — «Повторить», а не пустой список', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/returns')
    mount()
    expect(await screen.findByText('Не удалось загрузить возвраты')).toBeInTheDocument()
  })
})
