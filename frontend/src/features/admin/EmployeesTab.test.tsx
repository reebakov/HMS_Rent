import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { EmployeesTab } from './EmployeesTab'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { AdminUserRow } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeUser = (over: Partial<AdminUserRow> = {}): AdminUserRow => ({
  id: 1, username: 'i.ivanov', display_name: 'Иван Иванов', email: 'i.ivanov@example.com', auth_source: 'bouncer',
  role: 'user', is_active: true, department: { id: 5, name: 'Разработка' }, last_login_at: null, ...over,
})
const departments = [
  { id: 5, name: 'Разработка', code: 'DEV', head_name: null, is_active: true },
  { id: 6, name: 'Аналитика', code: null, head_name: null, is_active: true },
]

let users: AdminUserRow[]

beforeEach(() => {
  users = [
    makeUser(),
    makeUser({ id: 2, username: 'admin', display_name: 'Админ', email: null, auth_source: 'local', role: 'admin', department: null }),
    makeUser({ id: 3, username: 'new@example.com', display_name: 'new', email: 'new@example.com', auth_source: 'microsoft', is_active: false }),
  ]
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/users') return users
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({})
  vi.mocked(api.patch).mockResolvedValue({})
})

const rowOf = (name: string) => screen.getByText(name).closest('tr') as HTMLElement

describe('EmployeesTab', () => {
  it('рисует сотрудников: источник входа, роль, отдел; заранее заведённый (microsoft) — «Bouncer»', async () => {
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Иван Иванов')
    expect(within(rowOf('Иван Иванов')).getByText('Bouncer')).toBeInTheDocument()
    expect(within(rowOf('Админ')).getByText('админ')).toBeInTheDocument()
    expect(within(rowOf('Админ')).getByText('Локальная учётка')).toBeInTheDocument()
    expect(within(rowOf('new')).getByText('Bouncer')).toBeInTheDocument()
    expect(within(rowOf('new')).getByRole('button', { name: 'Разблокировать' })).toBeInTheDocument()
  })

  it.each([
    ['имени без учёта регистра', 'иВАН'],
    ['нику (логину)', 'i.ivan'],
    ['почте', 'IVANOV@example'],
  ])('поиск по %s оставляет только подходящего сотрудника', async (_, query) => {
    const user = userEvent.setup()
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Админ')
    await user.type(screen.getByRole('textbox', { name: 'Поиск сотрудника' }), query)
    expect(screen.getByText('Иван Иванов')).toBeInTheDocument()
    expect(screen.queryByText('Админ')).not.toBeInTheDocument()
    expect(screen.queryByText('new')).not.toBeInTheDocument()
  })

  it('поиск без совпадений — «Никого не найдено», очистка возвращает всех', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Админ')
    const search = screen.getByRole('textbox', { name: 'Поиск сотрудника' })
    await user.type(search, 'нет такого')
    expect(screen.getByText('Никого не найдено')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await user.clear(search)
    expect(screen.getByText('Админ')).toBeInTheDocument()
    expect(screen.getByText('Иван Иванов')).toBeInTheDocument()
  })

  it('пока грузится — скелетоны, таблицы нет', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    renderWithProviders(<EmployeesTab />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо пустой таблицы; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/users')
    renderWithProviders(<EmployeesTab />)
    expect(await screen.findByText('Не удалось загрузить сотрудников')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Иван Иванов')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ошибка загрузки отделов: сообщение и «Повторить», чтобы пустой выбор отдела не выглядел как «без отдела»', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/departments')
    renderWithProviders(<EmployeesTab />)
    expect(await screen.findByText('Не удалось загрузить отделы')).toBeInTheDocument()
    expect(screen.getByText('Иван Иванов')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() => expect(screen.queryByText('Не удалось загрузить отделы')).not.toBeInTheDocument())
    expect(await within(rowOf('Иван Иванов')).findByRole('option', { name: 'Аналитика' })).toBeInTheDocument()
  })

  it('выбор отдела в строке подписан именем сотрудника', async () => {
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Иван Иванов')
    expect(screen.getByRole('combobox', { name: 'Отдел: Иван Иванов' })).toHaveValue('5')
    expect(screen.getByRole('combobox', { name: 'Отдел: Админ' })).toHaveValue('')
  })

  it('смена отдела отправляет PATCH с department_id', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Иван Иванов')
    await within(rowOf('Иван Иванов')).findByRole('option', { name: 'Аналитика' })
    await user.selectOptions(within(rowOf('Иван Иванов')).getByRole('combobox'), 'Аналитика')
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/users/1', { department_id: 6 }))
  })

  it('блокировка отправляет is_active=false', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Иван Иванов')
    await user.click(within(rowOf('Иван Иванов')).getByRole('button', { name: 'Заблокировать' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/users/1', { is_active: false }))
  })

  it('добавление заранее: без «@» в почте кнопка неактивна, затем POST с почтой и отделом', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Иван Иванов')
    await user.click(screen.getByRole('button', { name: 'Добавить заранее' }))
    const dialog = await screen.findByRole('dialog')
    const add = within(dialog).getByRole('button', { name: 'Добавить' })
    await user.type(within(dialog).getByLabelText(/Рабочая почта/), 'petya')
    expect(add).toBeDisabled()
    await user.type(within(dialog).getByLabelText(/Рабочая почта/), '@example.com')
    await within(dialog).findByRole('option', { name: 'Аналитика' })
    await user.selectOptions(within(dialog).getByLabelText('Отдел'), 'Аналитика')
    await user.click(add)
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/users', { email: 'petya@example.com', department_id: 6 }),
    )
  })

  it('Enter в поле почты добавляет сотрудника, пока почта без «@» — нет', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EmployeesTab />)
    await screen.findByText('Иван Иванов')
    await user.click(screen.getByRole('button', { name: 'Добавить заранее' }))
    const email = await screen.findByLabelText(/Рабочая почта/)
    await user.type(email, 'petya{Enter}')
    expect(api.post).not.toHaveBeenCalled()
    await user.type(email, '@example.com{Enter}')
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/admin/users', { email: 'petya@example.com', department_id: null }),
    )
  })
})
