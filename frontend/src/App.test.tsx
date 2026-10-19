import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import App from './App'
import { AuthProvider } from '@/auth/AuthProvider'
import { api, ApiError } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

// Тяжёлые страницы заменяем заглушками — проверяем только маршрутизацию и гарды
vi.mock('@/pages/LoginPage', () => ({ LoginPage: () => <h1>stub:login</h1> }))
vi.mock('@/pages/CatalogPage', () => ({ CatalogPage: () => <h1>stub:catalog</h1> }))
vi.mock('@/pages/MyBookingsPage', () => ({ MyBookingsPage: () => <h1>stub:my</h1> }))
vi.mock('@/pages/admin/AdminOverviewPage', () => ({ AdminOverviewPage: () => <h1>stub:admin-overview</h1> }))
vi.mock('@/pages/admin/InventoryPage', () => ({ InventoryPage: () => <h1>stub:admin-inventory</h1> }))
vi.mock('@/pages/admin/JournalPage', () => ({ JournalPage: () => <h1>stub:admin-journal</h1> }))
vi.mock('@/pages/admin/DepartmentsPage', () => ({ DepartmentsPage: () => <h1>stub:admin-departments</h1> }))
vi.mock('@/pages/admin/SyncPage', () => ({ SyncPage: () => <h1>stub:admin-sync</h1> }))
vi.mock('@/pages/admin/PoolsPage', () => ({ PoolsPage: () => <h1>stub:admin-pools</h1> }))
vi.mock('@/pages/admin/EventsPage', () => ({ EventsPage: () => <h1>stub:admin-events</h1> }))
vi.mock('@/pages/admin/SettingsPage', () => ({ SettingsPage: () => <h1>stub:admin-settings</h1> }))
vi.mock('@/pages/admin/UsersPage', () => ({ UsersPage: () => <h1>stub:admin-users</h1> }))
vi.mock('@/pages/admin/VmsPage', () => ({ VmsPage: () => <h1>stub:admin-vms</h1> }))
vi.mock('@/pages/admin/OverduePage', () => ({ OverduePage: () => <h1>stub:admin-overdue</h1> }))

const admin = () => makeSession({ username: 'admin', display_name: 'Админ', role: 'admin' })
const employee = () => makeSession()

/** Монтирует приложение с настоящим AuthProvider; /auth/me отвечает заданной сессией (null -> 401) */
function mount(route: string, session: ReturnType<typeof makeSession> | null) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/auth/me') {
      if (!session) throw new ApiError(401, 'нет сессии')
      return session
    }
    if (path === '/admin/overdue') return [] // счётчик просрочек в меню админа
    throw new Error(`неожиданный GET ${path}`)
  })
  return renderWithProviders(
    <AuthProvider>
      <App />
    </AuthProvider>,
    { route },
  )
}

beforeEach(() => {
  for (const m of [api.get, api.post]) vi.mocked(m).mockReset()
})

describe('App: загрузка', () => {
  it('пока /auth/me не ответил, виден спиннер, а не страница и не редирект', async () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    const { container } = renderWithProviders(
      <AuthProvider>
        <App />
      </AuthProvider>,
      { route: '/my' },
    )
    expect(container.querySelector('.animate-spin')).toBeInTheDocument()
    expect(screen.queryByText(/^stub:/)).not.toBeInTheDocument()
  })
})

describe('App: аноним', () => {
  it.each(['/', '/my', '/admin', '/admin/users'])('%s -> редирект на логин', async (route) => {
    mount(route, null)
    expect(await screen.findByText('stub:login')).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('/login доступен без сессии', async () => {
    mount('/login', null)
    expect(await screen.findByText('stub:login')).toBeInTheDocument()
  })

  it('неизвестный путь -> на главную -> на логин', async () => {
    mount('/нет-такой-страницы', null)
    expect(await screen.findByText('stub:login')).toBeInTheDocument()
  })
})

describe('App: сотрудник', () => {
  it('видит каталог и «Моя аренда» внутри оболочки с навигацией', async () => {
    mount('/', employee())
    expect(await screen.findByText('stub:catalog')).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })

  it('/my открывает мои брони', async () => {
    mount('/my', employee())
    expect(await screen.findByText('stub:my')).toBeInTheDocument()
  })

  it.each([
    '/admin', '/admin/inventory', '/admin/pools', '/admin/journal', '/admin/departments',
    '/admin/events', '/admin/sync', '/admin/vms', '/admin/users', '/admin/settings',
  ])('%s не пускает: редирект в каталог', async (route) => {
    mount(route, employee())
    expect(await screen.findByText('stub:catalog')).toBeInTheDocument()
    expect(screen.queryByText(/stub:admin/)).not.toBeInTheDocument()
  })

  // сам маршрут /login не защищён: редирект вошедшего делает LoginPage (см. LoginPage.test.tsx), здесь она — заглушка
  it('маршрут /login не закрыт гардом — отдаёт страницу входа', async () => {
    mount('/login', employee())
    expect(await screen.findByText('stub:login')).toBeInTheDocument()
  })

  it('неизвестный путь -> каталог', async () => {
    mount('/что-то/не/то', employee())
    expect(await screen.findByText('stub:catalog')).toBeInTheDocument()
  })
})

describe('App: администратор', () => {
  it.each([
    ['/admin', 'stub:admin-overview'],
    ['/admin/inventory', 'stub:admin-inventory'],
    ['/admin/pools', 'stub:admin-pools'],
    ['/admin/journal', 'stub:admin-journal'],
    ['/admin/departments', 'stub:admin-departments'],
    ['/admin/events', 'stub:admin-events'],
    ['/admin/sync', 'stub:admin-sync'],
    ['/admin/vms', 'stub:admin-vms'],
    ['/admin/users', 'stub:admin-users'],
    ['/admin/settings', 'stub:admin-settings'],
  ])('%s -> %s', async (route, stub) => {
    mount(route, admin())
    expect(await screen.findByText(stub)).toBeInTheDocument()
  })

  it('обычные страницы тоже доступны', async () => {
    mount('/my', admin())
    expect(await screen.findByText('stub:my')).toBeInTheDocument()
  })
})

describe('App: истечение сессии', () => {
  it('auth:expired на закрытой странице выкидывает на логин', async () => {
    mount('/my', employee())
    expect(await screen.findByText('stub:my')).toBeInTheDocument()
    act(() => {
      window.dispatchEvent(new Event('auth:expired'))
    })
    expect(await screen.findByText('stub:login')).toBeInTheDocument()
    expect(screen.queryByText('stub:my')).not.toBeInTheDocument()
  })

  it('выход из оболочки ведёт на логин', async () => {
    vi.mocked(api.post).mockResolvedValue(undefined)
    mount('/', employee())
    await screen.findByText('stub:catalog')
    act(() => screen.getByTitle('Выйти').click())
    await waitFor(() => expect(screen.getByText('stub:login')).toBeInTheDocument())
    expect(api.post).toHaveBeenCalledWith('/auth/logout')
  })
})

describe('маршрут /admin/overdue', () => {
  it('админ попадает на страницу просрочек внутри AppShell', async () => {
    mount('/admin/overdue', admin())
    expect(await screen.findByText('stub:admin-overdue')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Просрочки/ })).toHaveAttribute('aria-current', 'page')
  })

  it('сотрудника гард отправляет в каталог', async () => {
    mount('/admin/overdue', employee())
    expect(await screen.findByText('stub:catalog')).toBeInTheDocument()
    expect(screen.queryByText('stub:admin-overdue')).not.toBeInTheDocument()
  })
})
