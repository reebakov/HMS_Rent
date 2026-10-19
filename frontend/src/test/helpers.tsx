import type { ReactElement } from 'react'
import { vi, type Mock } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'
import type { QueryLike } from '@/components/ui/data-state'
import type { Computer, Session } from '@/lib/types'

export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Результат запроса для компонентов, которые принимают query пропсом: по умолчанию — загрузка */
export const stubQuery = <T,>(over: Partial<QueryLike<T>> = {}): QueryLike<T> => ({
  data: undefined,
  isError: false,
  error: null,
  refetch: vi.fn(),
  ...over,
})

/** GET по path один раз падает с ошибкой, дальше работает прежняя подмена: для проверки «Повторить» */
export function failGetOnce(get: Mock, path: string, message = 'Сервер недоступен') {
  const base = get.getMockImplementation()
  let failed = false
  get.mockImplementation(async (...args: unknown[]) => {
    if (args[0] === path && !failed) {
      failed = true
      throw new Error(message)
    }
    return base?.(...args)
  })
}

export const makeSession = (over: Partial<Session['user']> = {}): Session => ({
  user: {
    id: 1,
    username: 'i.ivanov',
    display_name: 'Иван Иванов',
    email: 'i.ivanov@example.com',
    avatar_url: null,
    auth_source: 'dev',
    role: 'user',
    department_id: null,
    ...over,
  },
  app_name: 'HMS Rent',
  app_subtitle: 'Аренда техники',
  insight_mode: 'mock',
  catalog_refresh_sec: 3600,
})

export const makeComputer = (over: Partial<Computer> = {}): Computer => ({
  id: 10,
  name: 'PC-010',
  hostname: 'pc-010.local',
  insight_key: 'INS-10',
  is_virtual: false,
  tier: 'medium',
  cpu: 'Intel Core i5',
  cpu_cores: 6,
  ram_gb: 16,
  storage: 'SSD 512 ГБ',
  storage_gb: 512,
  gpu: null,
  os: 'Windows 11',
  location: 'Офис, 3 этаж',
  status: 'available',
  insight_status: null,
  department: null,
  synced_at: null,
  ...over,
})
