import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppShell } from './AppShell'
import { ThemeToggle } from './ThemeToggle'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { Session } from '@/lib/types'

let session: Session
const logout = vi.fn()
vi.mock('@/auth/AuthProvider', () => ({
  useSession: () => session,
  useAuth: () => ({ session, loading: false, login: vi.fn(), logout }),
}))

const ADMIN_LINKS = [
  'Обзор', 'Инвентаризация', 'Пулы выдачи', 'Журнал выдачи', 'Виртуалки',
  'Отделы', 'Сотрудники', 'Логи системы', 'Синхронизация', 'Настройки',
]

const mountShell = (route = '/') =>
  renderWithProviders(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>страница-каталог</p>} />
        <Route path="my" element={<p>страница-аренда</p>} />
        <Route path="admin" element={<p>страница-обзор</p>} />
        <Route path="admin/users" element={<p>страница-сотрудники</p>} />
      </Route>
    </Routes>,
    { route },
  )

beforeEach(() => {
  session = makeSession()
  logout.mockReset()
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
    mountShell('/admin/users')
    expect(screen.getByRole('link', { name: 'Сотрудники' })).toHaveAttribute('aria-current', 'page')
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
  const burger = () => screen.getAllByRole('button').find((b) => b.className.includes('lg:hidden'))!

  it('по умолчанию меню одно (десктопный сайдбар); бургер открывает второе', async () => {
    mountShell()
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(1)
    await userEvent.click(burger())
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(2)
  })

  it('выбор пункта закрывает мобильное меню', async () => {
    mountShell()
    await userEvent.click(burger())
    const links = screen.getAllByRole('link', { name: 'Моя аренда' })
    await userEvent.click(links[1])
    expect(screen.getAllByRole('link', { name: 'Моя аренда' })).toHaveLength(1)
  })

  it('клик по подложке закрывает меню', async () => {
    const { container } = mountShell()
    await userEvent.click(burger())
    const overlay = container.querySelector('.bg-slate-950\\/40')!
    fireEvent.click(overlay)
    expect(screen.getAllByRole('link', { name: 'Каталог' })).toHaveLength(1)
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
