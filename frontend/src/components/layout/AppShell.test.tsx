import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from './AppShell'
import { ThemeToggle } from './ThemeToggle'
import { api } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { ExtensionOut, OverdueItem, Session, TermRequestOut } from '@/lib/types'

let session: Session
const logout = vi.fn()
vi.mock('@/auth/AuthProvider', () => ({
  useSession: () => session,
  useAuth: () => ({ session, loading: false, login: vi.fn(), logout }),
}))
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const ADMIN_LINKS = [
  'Обзор', 'Инвентаризация', 'Пулы выдачи', 'Журнал выдачи', 'Виртуалки',
  'Сотрудники и отделы', 'Логи системы', 'Синхронизация', 'Настройки',
]

const mountShell = (route = '/') =>
  renderWithProviders(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>страница-каталог</p>} />
        <Route path="my" element={<p>страница-аренда</p>} />
        <Route path="admin" element={<p>страница-обзор</p>} />
        <Route path="admin/people" element={<p>страница-сотрудники</p>} />
        <Route path="admin/overdue" element={<p>страница-просрочки</p>} />
      </Route>
    </Routes>,
    { route },
  )

const item = (id: number): OverdueItem => ({
  kind: 'pc', id, order_number: id, name: `PC-${id}`, department: 'Разработка', requester_name: 'Пётр', requester_nick: 'p',
  email: null, taken_at: null, due: '2026-10-01', days: 2,
})
let overdue: OverdueItem[]
const extension = (id: number, acknowledged: boolean, kind: ExtensionOut['kind'] = 'pc') =>
  ({ id, kind, acknowledged_at: acknowledged ? '2026-10-02T10:00:00Z' : null }) as ExtensionOut
let extensions: ExtensionOut[]
const termRequest = (id: number) => ({ id }) as TermRequestOut
let termRequests: TermRequestOut[]

beforeEach(() => {
  session = makeSession()
  overdue = []
  extensions = []
  termRequests = []
  logout.mockReset()
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  // меню админа запрашивает просрочки, заявки на срок и продления для счётчика
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/overdue') return overdue
    if (path === '/admin/extensions') return extensions
    if (path === '/admin/term-requests') return termRequests
    if (path === '/notifications') return { items: [], unread: 0 }
    throw new Error(`неожиданный GET ${path}`)
  })
  document.documentElement.classList.remove('dark')
})

describe('AppShell: меню по роли', () => {
  it('сотрудник видит только «Каталог» и «Моя аренда», админ-меню нет', () => {
    mountShell()
    expect(screen.getByRole('link', { name: 'Каталог' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'Моя аренда' })).toHaveAttribute('href', '/my')
    expect(screen.queryByText('Администрирование')).not.toBeInTheDocument()
    for (const label of ADMIN_LINKS) expect(screen.queryByRole('link', { name: label })).not.toBeInTheDocument()
    expect(screen.getByText(/сотрудник$/)).toBeInTheDocument()
  })

  it('админ дополнительно видит блок «Администрирование» со всеми разделами', () => {
    session = makeSession({ role: 'admin' })
    mountShell()
    expect(screen.getByText('Администрирование')).toBeInTheDocument()
    for (const label of ADMIN_LINKS) expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Обзор' })).toHaveAttribute('href', '/admin')
    expect(screen.getByRole('link', { name: 'Настройки' })).toHaveAttribute('href', '/admin/settings')
    expect(screen.getByText(/администратор$/)).toBeInTheDocument()
  })

  it('подсвечивается только активный пункт: /admin не активирует вложенные и «Каталог»', () => {
    session = makeSession({ role: 'admin' })
    mountShell('/admin/people')
    expect(screen.getByRole('link', { name: 'Сотрудники и отделы' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Обзор' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('link', { name: 'Каталог' })).not.toHaveAttribute('aria-current')
  })

  it('переход по ссылке меняет страницу в Outlet', async () => {
    mountShell()
    expect(screen.getByText('страница-каталог')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Моя аренда' }))
    expect(screen.getByText('страница-аренда')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Моя аренда' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('AppShell: профиль и шапка', () => {
  it('показывает название приложения, ФИО, логин и инициалы без аватара', () => {
    mountShell()
    expect(screen.getByText('HMS Rent')).toBeInTheDocument()
    expect(screen.getByText('Аренда техники')).toBeInTheDocument()
    expect(screen.getByText('Иван Иванов')).toBeInTheDocument()
    expect(screen.getByText('ИИ')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('с avatar_url рисует картинку вместо инициалов', () => {
    session = makeSession({ avatar_url: 'https://cdn.example/a.png' })
    const { container } = mountShell()
    const img = container.querySelector('img[src="https://cdn.example/a.png"]')
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(screen.queryByText('ИИ')).not.toBeInTheDocument()
  })

  it('плашки: «Демо-данные» при insight_mode=mock и «Dev-вход» при auth_source=dev', () => {
    mountShell()
    expect(screen.getByText('Демо-данные: Insight не подключён')).toBeInTheDocument()
    expect(screen.getByText('Dev-вход')).toBeInTheDocument()
  })

  it('плашек нет в боевом режиме', () => {
    session = { ...makeSession({ auth_source: 'microsoft' }), insight_mode: 'live' } as Session
    mountShell()
    expect(screen.queryByText(/Демо-данные/)).not.toBeInTheDocument()
    expect(screen.queryByText('Dev-вход')).not.toBeInTheDocument()
  })

  it('кнопка «Выйти» вызывает logout', async () => {
    mountShell()
    await userEvent.click(screen.getByTitle('Выйти'))
    expect(logout).toHaveBeenCalledTimes(1)
  })
})

describe('AppShell: мобильное меню', () => {
  const burger = () => screen.getByRole('button', { name: /(Открыть|Закрыть) меню/ })

  it('по умолчанию меню одно (десктопный сайдбар); бургер открывает второе', async () => {
    mountShell()
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(1)
    await userEvent.click(burger())
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(2)
  })

  it('бургер подписан и сообщает состояние меню через aria-expanded', async () => {
    mountShell()
    const button = screen.getByRole('button', { name: 'Открыть меню' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(button)
    expect(screen.getByRole('button', { name: 'Закрыть меню' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('выбор пункта закрывает мобильное меню', async () => {
    mountShell()
    await userEvent.click(burger())
    const links = screen.getAllByRole('link', { name: 'Моя аренда' })
    await userEvent.click(links[1])
    expect(screen.getAllByRole('link', { name: 'Моя аренда' })).toHaveLength(1)
  })

  it('при открытии фокус уходит в меню, Esc закрывает его и возвращает фокус на бургер', async () => {
    const user = userEvent.setup()
    mountShell()
    await user.click(burger())
    expect(screen.getAllByRole('link', { name: 'Каталог' })[1]).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Открыть меню' })).toHaveFocus()
  })

  it('Esc при закрытом меню ничего не делает', async () => {
    mountShell()
    await userEvent.keyboard('{Escape}')
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(1)
  })

  it('выбор пункта с клавиатуры (Enter) закрывает меню и возвращает фокус на бургер', async () => {
    const user = userEvent.setup()
    mountShell()
    await user.click(burger())
    await user.tab() // следующий пункт после «Каталога»
    await user.keyboard('{Enter}')
    expect(screen.getByText('страница-аренда')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Открыть меню' })).toHaveFocus()
  })

  it('клик по подложке закрывает меню', async () => {
    const { container } = mountShell()
    await userEvent.click(burger())
    const overlay = container.querySelector('.bg-slate-950\\/40')!
    fireEvent.click(overlay)
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(1)
  })
})

describe('AppShell: клавиатура', () => {
  it('«Перейти к содержимому» — первая остановка Tab; Enter переносит фокус на содержимое без смены адреса', async () => {
    const user = userEvent.setup()
    mountShell()
    await user.tab()
    const skip = screen.getByRole('link', { name: 'Перейти к содержимому' })
    expect(skip).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('main')).toHaveFocus()
    expect(window.location.hash).toBe('')
  })

  it('в шапке есть кнопка «Горячие клавиши»: открывает окно, Esc закрывает и возвращает фокус', async () => {
    const user = userEvent.setup()
    mountShell()
    const button = screen.getByRole('button', { name: 'Горячие клавиши' })
    await user.click(button)
    expect(screen.getByRole('dialog', { name: 'Горячие клавиши' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(button).toHaveFocus())
  })

  it('«?» на странице открывает окно горячих клавиш', async () => {
    mountShell()
    await userEvent.keyboard('?')
    expect(screen.getByRole('dialog', { name: 'Горячие клавиши' })).toBeInTheDocument()
  })
})

describe('ThemeToggle', () => {
  it('по умолчанию светлая тема, в localStorage пишется light', () => {
    renderWithProviders(<ThemeToggle />)
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('theme')).toBe('light')
    expect(screen.getByTitle('Тёмная тема')).toBeInTheDocument()
  })

  it('клик включает тёмную тему: класс на <html>, localStorage, подсказка меняется', async () => {
    renderWithProviders(<ThemeToggle />)
    await userEvent.click(screen.getByTitle('Тёмная тема'))
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
    expect(screen.getByTitle('Светлая тема')).toBeInTheDocument()
  })

  it('повторный клик возвращает светлую тему', async () => {
    renderWithProviders(<ThemeToggle />)
    await userEvent.click(screen.getByTitle('Тёмная тема'))
    await userEvent.click(screen.getByTitle('Светлая тема'))
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('стартует в тёмной, если <html> уже помечен dark (тема восстановлена до рендера)', () => {
    document.documentElement.classList.add('dark')
    renderWithProviders(<ThemeToggle />)
    expect(screen.getByTitle('Светлая тема')).toBeInTheDocument()
    expect(localStorage.getItem('theme')).toBe('dark')
  })
})

const overdueLink = () => screen.getByRole('link', { name: /^Сроки аренды/ })

describe('AppShell: «Сроки аренды»', () => {
  beforeEach(() => {
    session = makeSession({ role: 'admin' })
    overdue = [item(1), item(2), item(3)]
  })
  it('админ видит пункт «Сроки аренды», ведущий на /admin/overdue', async () => {
    mountShell()
    expect(overdueLink()).toHaveAttribute('href', '/admin/overdue')
    await screen.findByText('3')
  })

  it('счётчик берётся из длины списка просрочек', async () => {
    mountShell()
    expect(await within(overdueLink()).findByText('3')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/overdue')
  })

  it('к просрочкам добавляются только непринятые продления', async () => {
    extensions = [extension(1, false), extension(2, false), extension(3, true)]
    mountShell()
    expect(await within(overdueLink()).findByText('5')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/extensions')
  })

  it('непринятые продления ВМ считаются так же, как продления ПК', async () => {
    extensions = [extension(1, false, 'vm'), extension(2, true, 'vm'), extension(3, false)]
    mountShell()
    expect(await within(overdueLink()).findByText('5')).toBeInTheDocument()
  })

  it('заявки на срок дольше лимита тоже в счётчике', async () => {
    termRequests = [termRequest(1), termRequest(2)]
    extensions = [extension(1, false)]
    mountShell()
    expect(await within(overdueLink()).findByText('6')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/term-requests')
  })

  it('без просрочек счётчик показывает новые продления', async () => {
    overdue = []
    extensions = [extension(1, false)]
    mountShell()
    expect(await within(overdueLink()).findByText('1')).toBeInTheDocument()
  })

  it('счётчик красный (плашка bg-danger) и стоит внутри самой ссылки', async () => {
    mountShell()
    expect(await within(overdueLink()).findByText('3')).toHaveClass('bg-danger')
  })

  it('без просрочек и новых продлений счётчика нет, пункт остаётся', async () => {
    overdue = []
    extensions = [extension(1, true)]
    mountShell()
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/extensions'))
    expect(overdueLink()).toBeInTheDocument()
    expect(overdueLink().querySelector('.bg-danger')).toBeNull()
    expect(overdueLink()).toHaveTextContent(/^Сроки аренды$/)
  })

  it('ошибка загрузки просрочек: меню работает, счётчика нет', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('500'))
    mountShell()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(overdueLink().querySelector('.bg-danger')).toBeNull()
  })

  it('счётчик только у «Сроки аренды»: другие пункты без плашки', async () => {
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
    await user.click(screen.getByRole('button', { name: 'Открыть меню' }))
    const links = screen.getAllByRole('link', { name: /^Сроки аренды/ })
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

  it('сотрудник: пункта «Сроки аренды» нет и запрос просрочек не уходит', async () => {
    session = makeSession()
    mountShell()
    await screen.findByText('страница-каталог')
    expect(screen.queryByRole('link', { name: /Сроки аренды/ })).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith('/admin/overdue')
    expect(api.get).not.toHaveBeenCalledWith('/admin/term-requests')
    expect(api.get).not.toHaveBeenCalledWith('/admin/extensions')
  })
})
