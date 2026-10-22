import type { ReactElement } from 'react'
import { vi, type Mock } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'
import type { QueryLike } from '@/components/ui/data-state'
import type { Booking, Computer, ExecutorOrder, ServiceRequest, Session } from '@/lib/types'

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

/** Поля брони, которые заполняет исполнитель: у неподготовленного ПК все пусты */
export const unprepared = {
  connection_host: null,
  connection_ip: null,
  connection_method: null,
  connection_login: null,
  prepared_at: null,
} satisfies Partial<Booking>

/** Те же поля у подготовленного ПК: исполнитель внёс данные подключения */
export const prepared = {
  connection_host: 'A032.ff.local',
  connection_ip: '10.1.2.3',
  connection_method: 'RDP',
  connection_login: 'user',
  prepared_at: '2026-10-21T10:00:00Z',
} satisfies Partial<Booking>

/** Заказ в разделе «Исполнитель»: по умолчанию активный и ещё не подготовленный */
export const makeExecutorOrder = (over: Partial<ExecutorOrder> = {}): ExecutorOrder => ({
  id: 7,
  order_number: 1042,
  status: 'active',
  computer: { id: 10, name: 'A032', tier: 'medium', is_virtual: false, cpu: 'Intel Core i5', ram_gb: 16, storage: null, gpu: null },
  department: { id: 1, name: 'Builder Studio' },
  user: { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' },
  requester_name: 'Пётр Петров',
  requester_nick: 'petrov',
  purpose: null,
  os_label: 'Windows 11 26H2',
  booked_at: '2026-10-20T09:00:00Z',
  expected_return_at: '2026-12-31',
  requested_return_at: null,
  returned_at: null,
  returned_by: null,
  return_comment: null,
  ...unprepared,
  prepared_by: null,
  insight_ip: null,
  request_key: null,
  request_url: null,
  request_status: null,
  request_error: null,
  request_done: false,
  ...over,
})

/** Заявка Service Desk; статус для заказчика по умолчанию совпадает со статусом из Jira */
export const makeServiceRequest = (over: Partial<ServiceRequest> = {}): ServiceRequest => ({
  id: 5,
  kind: 'problem',
  booking_id: 1,
  vm_id: null,
  department_id: null,
  issue_key: 'HMS-101',
  summary: 'Не включается',
  status: 'В работе',
  status_category: 'indeterminate',
  customer_status: over.status === undefined ? 'В работе' : over.status,
  customer_note: null,
  error: null,
  created_at: '2024-01-10T09:00:00Z',
  url: null,
  ...over,
})
