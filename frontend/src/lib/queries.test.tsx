import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { api, ApiError } from './api'
import * as q from './queries'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
// queries.ts импортирует './api' — тот же модуль, мок по алиасу его подменяет

let client: QueryClient
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
)
const hook = <T,>(fn: () => T) => renderHook(fn, { wrapper })

/** Ключи, которые инвалидировались после мутации */
const invalidated = (spy: { mock: { calls: unknown[][] } }) =>
  spy.mock.calls.map(([f]) => (f as { queryKey: unknown[] }).queryKey[0]).sort()
const keys = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.map(([f]) => (f as { queryKey: unknown[] }).queryKey)
const options = (queryKey: unknown[]) => client.getQueryCache().find({ queryKey })!.observers[0].options
const refetchInterval = (key: unknown[]) => options(key).refetchInterval
const ALL_BOOKING_KEYS = ['admin', 'catalog-summary', 'computer', 'computers', 'my-bookings']

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset().mockResolvedValue(null as never)
})

describe('запросы на чтение', () => {
  it('useAuthConfig: GET /auth/config', async () => {
    vi.mocked(api.get).mockResolvedValue({ app_name: 'HMS Rent', bouncer_enabled: true })
    const { result } = hook(() => q.useAuthConfig())
    await waitFor(() => expect(result.current.data).toEqual({ app_name: 'HMS Rent', bouncer_enabled: true }))
    expect(api.get).toHaveBeenCalledWith('/auth/config')
  })

  it('inventoryExportUrl: берёт из фильтров только отдел и пул', () => {
    vi.mocked(api.url).mockReturnValue('/export')
    expect(q.inventoryExportUrl({ q: 'pc', department_id: 3, pool_id: 'none', status: 'available' })).toBe('/export')
    expect(api.url).toHaveBeenCalledWith('/admin/inventory/export', { department_id: 3, pool_id: 'none' })
  })

  it('useCatalogSummary: берёт /catalog/summary, ключ и интервал из refreshSec', async () => {
    vi.mocked(api.get).mockResolvedValue([{ tier: 'weak' }])
    const { result } = hook(() => q.useCatalogSummary(7))
    await waitFor(() => expect(result.current.data).toEqual([{ tier: 'weak' }]))
    expect(api.get).toHaveBeenCalledWith('/catalog/summary')
    const query = client.getQueryCache().find({ queryKey: ['catalog-summary'] })!
    expect(query.observers[0].options.refetchInterval).toBe(7000)
  })

  it('useCatalogSummary: интервал по умолчанию 15 секунд', async () => {
    hook(() => q.useCatalogSummary())
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(client.getQueryCache().find({ queryKey: ['catalog-summary'] })!.observers[0].options.refetchInterval).toBe(15_000)
  })

  it('useComputers: фильтры уходят query-параметрами, ключ зависит от фильтров', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    const filters: q.ComputerFilters = { tier: 'powerful', q: 'rtx', min_ram: 32, gpu: 'discrete', sort: 'ram_desc' }
    const { result } = hook(() => q.useComputers(filters))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.get).toHaveBeenCalledWith('/computers', filters)
    expect(client.getQueryCache().find({ queryKey: ['computers', filters] })).toBeDefined()
    // в API уходит копия, а не тот же объект, что лежит в ключе кэша
    expect(vi.mocked(api.get).mock.calls[0][1]).not.toBe(filters)
  })

  it('useComputers: при смене фильтра пока грузится новый список, показывается прежний (placeholderData)', async () => {
    let resolveSecond!: (v: unknown[]) => void
    vi.mocked(api.get)
      .mockResolvedValueOnce([{ id: 1 }])
      .mockImplementationOnce(() => new Promise((r) => (resolveSecond = r as never)))
    const { result, rerender } = renderHook(({ f }: { f: q.ComputerFilters }) => q.useComputers(f), {
      wrapper,
      initialProps: { f: { tier: 'weak' } as q.ComputerFilters },
    })
    await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
    rerender({ f: { tier: 'medium' } })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(result.current.data).toEqual([{ id: 1 }])
    expect(result.current.isPlaceholderData).toBe(true)
    resolveSecond([{ id: 2 }])
    await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
  })

  it('useComputer: при id=null запрос не отправляется, при id — идёт на /computers/{id}', async () => {
    const { result, rerender } = renderHook(({ id }: { id: number | null }) => q.useComputer(id), {
      wrapper,
      initialProps: { id: null as number | null },
    })
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
    rerender({ id: 42 })
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/computers/42'))
  })

  it.each([
    ['useDepartments', () => q.useDepartments(), '/departments'],
    ['useMyBookings', () => q.useMyBookings(), '/bookings/my'],
    ['useStats', () => q.useStats(), '/admin/stats'],
    ['useDepartmentUsage', () => q.useDepartmentUsage(), '/admin/departments'],
    ['useSyncInfo', () => q.useSyncInfo(), '/admin/sync'],
    ['usePools', () => q.usePools(), '/admin/pools'],
    ['useMyVms', () => q.useMyVms(), '/vms/my'],
    ['useAppSettings', () => q.useAppSettings(), '/admin/settings'],
    ['useAdminUsers', () => q.useAdminUsers(), '/admin/users'],
    ['useVmOptions', () => q.useVmOptions(), '/vms/options'],
  ] as [string, () => unknown, string][])('%s: GET %s', async (_n, useIt, path) => {
    hook(useIt)
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(path))
  })

  it('useDepartments: справочник кэшируется 5 минут', async () => {
    hook(() => q.useDepartments())
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(client.getQueryCache().find({ queryKey: ['departments'] })!.observers[0].options.staleTime).toBe(300_000)
  })

  it('useVmOptions(false): запрос не отправляется', () => {
    const { result } = hook(() => q.useVmOptions(false))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('админские списки передают фильтры как query-параметры', async () => {
    const inv: q.InventoryFilters = { q: 'pc', status: 'busy', pool_id: 'none', issues_only: true, limit: 20, offset: 40 }
    const jr: q.JournalFilters = { status: 'active', department_id: 3, date_from: '2024-01-01' }
    const ev: q.EventFilters = { event_type: 'sync', limit: 5, offset: 10 }
    hook(() => q.useInventory(inv))
    hook(() => q.useJournal(jr))
    hook(() => q.useEvents(ev))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3))
    expect(api.get).toHaveBeenCalledWith('/admin/inventory', inv)
    expect(api.get).toHaveBeenCalledWith('/admin/bookings', jr)
    expect(api.get).toHaveBeenCalledWith('/admin/events', ev)
  })

  it('useEvents: без аргументов — первая страница из 12 записей', async () => {
    hook(() => q.useEvents())
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/events', { limit: 12, offset: 0 }))
  })

  it('useComputerHistory: null — не грузим, id — /admin/computers/{id}', async () => {
    const { result, rerender } = renderHook(({ id }: { id: number | null }) => q.useComputerHistory(id), {
      wrapper,
      initialProps: { id: null as number | null },
    })
    expect(result.current.fetchStatus).toBe('idle')
    rerender({ id: 7 })
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/admin/computers/7'))
  })

  it('useAdminVms: include_deleted передаётся в запрос и в ключ, опрос раз в 10 с', async () => {
    hook(() => q.useAdminVms())
    hook(() => q.useAdminVms(true))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(api.get).toHaveBeenCalledWith('/admin/vms', { include_deleted: false })
    expect(api.get).toHaveBeenCalledWith('/admin/vms', { include_deleted: true })
    const query = client.getQueryCache().find({ queryKey: ['admin', 'vms', true] })!
    expect(query.observers[0].options.refetchInterval).toBe(10_000)
  })

  it('ошибка API попадает в error хука', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(500, 'Сервер недоступен'))
    const { result } = hook(() => q.useMyBookings())
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(ApiError)
    expect(result.current.error?.message).toBe('Сервер недоступен')
  })
})

describe('useMyVms: частота опроса', () => {
  const interval = async (vms: unknown) => {
    vi.mocked(api.get).mockResolvedValue(vms)
    const { result } = hook(() => q.useMyVms())
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const query = client.getQueryCache().find({ queryKey: ['my-vms'] })!
    return (query.observers[0].options.refetchInterval as (qq: unknown) => unknown)(query)
  }

  it.each(['queued', 'creating', 'deleting'])('ВМ в статусе %s — опрос каждые 5 с', async (status) => {
    expect(await interval([{ id: 1, status, ip_address: null }])).toBe(5000)
  })
  it('ready, но IP ещё нет — продолжаем опрашивать', async () => {
    expect(await interval([{ id: 1, status: 'ready', ip_address: null }])).toBe(5000)
  })
  it('ready с IP — опрос выключен', async () => {
    expect(await interval([{ id: 1, status: 'ready', ip_address: '10.0.0.5' }])).toBe(false)
  })
  it('пустой список — опрос выключен', async () => {
    expect(await interval([])).toBe(false)
  })
})

describe('мутации броней: вызов API и инвалидация кэша', () => {
  it('useCreateBooking: POST /bookings и инвалидация всех связанных ключей', async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 5 })
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateBooking())
    await act(() => result.current.mutateAsync({ computer_id: 1 } as never))
    expect(api.post).toHaveBeenCalledWith('/bookings', { computer_id: 1 })
    await waitFor(() => expect(invalidated(spy)).toEqual(ALL_BOOKING_KEYS))
  })

  it('useCreateBooking: при ошибке (409) кэш всё равно обновляется — ПК уже мог занять другой', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Уже забронирован'))
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateBooking())
    await act(async () => {
      await expect(result.current.mutateAsync({ computer_id: 1 } as never)).rejects.toThrow('Уже забронирован')
    })
    await waitFor(() => expect(invalidated(spy)).toEqual(ALL_BOOKING_KEYS))
    expect(result.current.error?.message).toBe('Уже забронирован')
  })

  it('инвалидация реально помечает кэш каталога устаревшим и перезапрашивает активные запросы', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    const { result: list } = hook(() => q.useComputers({ tier: 'weak' }))
    await waitFor(() => expect(list.current.isSuccess).toBe(true))
    expect(api.get).toHaveBeenCalledTimes(1)
    const { result } = hook(() => q.useCreateBooking())
    await act(() => result.current.mutateAsync({ computer_id: 1 } as never))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
  })

  it('useReturnBooking: POST /bookings/{id}/return с комментарием', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useReturnBooking())
    await act(() => result.current.mutateAsync({ id: 9, comment: 'всё ок' }))
    expect(api.post).toHaveBeenCalledWith('/bookings/9/return', { comment: 'всё ок' })
    await waitFor(() => expect(invalidated(spy)).toEqual(ALL_BOOKING_KEYS))
  })

  it('useExtendBooking: POST /bookings/{id}/extend с новым сроком и причиной', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useExtendBooking())
    await act(() => result.current.mutateAsync({ id: 9, expected_return_at: '2099-12-31', comment: 'тесты' }))
    expect(api.post).toHaveBeenCalledWith('/bookings/9/extend', { expected_return_at: '2099-12-31', comment: 'тесты' })
    await waitFor(() => expect(invalidated(spy)).toEqual(ALL_BOOKING_KEYS))
  })

  it('useRunSync: POST /admin/sync и инвалидация', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useRunSync())
    await act(() => result.current.mutateAsync())
    expect(api.post).toHaveBeenCalledWith('/admin/sync')
    await waitFor(() => expect(invalidated(spy)).toEqual(ALL_BOOKING_KEYS))
  })

  it('useUpdateComputer: PATCH без id в теле', async () => {
    const { result } = hook(() => q.useUpdateComputer())
    await act(() => result.current.mutateAsync({ id: 4, tier_override: 'weak', note: null }))
    expect(api.patch).toHaveBeenCalledWith('/admin/computers/4', { tier_override: 'weak', note: null })
  })
})

describe('сохранение сущностей: создание или обновление по наличию id', () => {
  it('useSaveDepartment: без id — POST, с id — PATCH; инвалидирует admin и departments', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useSaveDepartment())
    await act(() => result.current.mutateAsync({ name: 'HMS', code: 'H' }))
    expect(api.post).toHaveBeenCalledWith('/admin/departments', { name: 'HMS', code: 'H' })
    await act(() => result.current.mutateAsync({ id: 2, is_active: false }))
    expect(api.patch).toHaveBeenCalledWith('/admin/departments/2', { is_active: false })
    await waitFor(() => expect(invalidated(spy)).toEqual(['admin', 'admin', 'departments', 'departments']))
  })

  it('useSavePool: POST/PATCH и полная инвалидация', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useSavePool())
    await act(() => result.current.mutateAsync({ name: 'Пул', department_ids: [1, 2] }))
    expect(api.post).toHaveBeenCalledWith('/admin/pools', { name: 'Пул', department_ids: [1, 2] })
    await act(() => result.current.mutateAsync({ id: 3, is_published: true }))
    expect(api.patch).toHaveBeenCalledWith('/admin/pools/3', { is_published: true })
    expect(new Set(invalidated(spy))).toEqual(new Set(ALL_BOOKING_KEYS))
  })

  it('useDeletePool: DELETE /admin/pools/{id}', async () => {
    const { result } = hook(() => q.useDeletePool())
    await act(() => result.current.mutateAsync(5))
    expect(api.del).toHaveBeenCalledWith('/admin/pools/5')
  })

  it('useAssignPool: POST /admin/pools/assign', async () => {
    const { result } = hook(() => q.useAssignPool())
    await act(() => result.current.mutateAsync({ pool_id: null, names: 'PC-1' }))
    expect(api.post).toHaveBeenCalledWith('/admin/pools/assign', { pool_id: null, names: 'PC-1' })
  })

  it('useSaveUser: POST/PATCH, обновляется только список сотрудников', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useSaveUser())
    await act(() => result.current.mutateAsync({ email: 'a@b.c' }))
    expect(api.post).toHaveBeenCalledWith('/admin/users', { email: 'a@b.c' })
    await act(() => result.current.mutateAsync({ id: 8, department_id: null }))
    expect(api.patch).toHaveBeenCalledWith('/admin/users/8', { department_id: null })
    expect(spy.mock.calls.map(([f]) => (f as { queryKey: unknown[] }).queryKey)).toEqual([['admin', 'users'], ['admin', 'users']])
  })

  it('useSaveSettings: PATCH и инвалидация admin + vm-options', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useSaveSettings())
    await act(() => result.current.mutateAsync({ catalog_refresh_sec: 60 } as never))
    expect(api.patch).toHaveBeenCalledWith('/admin/settings', { catalog_refresh_sec: 60 })
    await waitFor(() => expect(invalidated(spy)).toEqual(['admin', 'vm-options']))
  })
})

describe('виртуалки и vSphere', () => {
  it('useCreateVm / useReleaseVm: API и инвалидация my-vms, vm-options, admin', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const create = hook(() => q.useCreateVm())
    await act(() => create.result.current.mutateAsync({ template: 't' } as never))
    expect(api.post).toHaveBeenCalledWith('/vms', { template: 't' })
    await waitFor(() => expect(invalidated(spy)).toEqual(['admin', 'my-vms', 'vm-options']))

    spy.mockClear()
    const release = hook(() => q.useReleaseVm())
    await act(() => release.result.current.mutateAsync(12))
    expect(api.post).toHaveBeenCalledWith('/vms/12/release')
    await waitFor(() => expect(invalidated(spy)).toEqual(['admin', 'my-vms', 'vm-options']))
  })

  it('useExtendVm: POST /vms/{id}/extend со сроком и причиной, обновляет my-vms и admin', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useExtendVm())
    await act(() => result.current.mutateAsync({ id: 12, expected_return_at: '2099-12-31', comment: 'тесты' }))
    expect(api.post).toHaveBeenCalledWith('/vms/12/extend', { expected_return_at: '2099-12-31', comment: 'тесты' })
    await waitFor(() => expect(invalidated(spy)).toEqual(['admin', 'my-vms']))
  })

  it('useVsphereCheck: POST /admin/vsphere/check без инвалидации', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useVsphereCheck())
    await act(() => result.current.mutateAsync())
    expect(api.post).toHaveBeenCalledWith('/admin/vsphere/check')
    await waitFor(() => expect(result.current.data).toEqual({ ok: true }))
    expect(spy).not.toHaveBeenCalled()
  })
})

describe('просрочки и детали синхронизации', () => {
  it('useOverdue: GET /admin/overdue, ключ [admin, overdue], опрос раз в минуту', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 1 }])
    const { result } = hook(() => q.useOverdue())
    await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
    expect(api.get).toHaveBeenCalledWith('/admin/overdue')
    expect(options(['admin', 'overdue']).refetchInterval).toBe(60_000)
  })

  it('useOverdue(false): запрос не уходит (для не-админа), данных нет', async () => {
    const { result } = hook(() => q.useOverdue(false))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })

  it('useExtensions: GET /admin/extensions, ключ [admin, extensions], опрос раз в минуту', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 1 }])
    const { result } = hook(() => q.useExtensions())
    await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
    expect(api.get).toHaveBeenCalledWith('/admin/extensions')
    expect(refetchInterval(['admin', 'extensions'])).toBe(60_000)
  })

  it('useExtensions(false): запрос не уходит', () => {
    const { result } = hook(() => q.useExtensions(false))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('useAckExtension: POST /admin/extensions/{id}/ack и обновление списка продлений', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useAckExtension())
    await act(() => result.current.mutateAsync(4))
    expect(api.post).toHaveBeenCalledWith('/admin/extensions/4/ack')
    await waitFor(() => expect(keys(spy)).toEqual([['admin', 'extensions']]))
  })

  it('useTermRequests: GET /admin/term-requests, ключ [admin, term-requests], опрос раз в минуту', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 1 }])
    const { result } = hook(() => q.useTermRequests())
    await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
    expect(api.get).toHaveBeenCalledWith('/admin/term-requests')
    expect(refetchInterval(['admin', 'term-requests'])).toBe(60_000)
  })

  it('useTermRequests(false): запрос не уходит', () => {
    const { result } = hook(() => q.useTermRequests(false))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('useApproveTermRequest: POST со сроком админа и обновление админки и броней', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useApproveTermRequest())
    await act(() => result.current.mutateAsync({ id: 4, approved_return_at: '2027-01-31' }))
    expect(api.post).toHaveBeenCalledWith('/admin/term-requests/4/approve', { approved_return_at: '2027-01-31' })
    await waitFor(() => expect(keys(spy)).toContainEqual(['admin']))
  })

  it('useRejectTermRequest: POST отказа и обновление списка заявок', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useRejectTermRequest())
    await act(() => result.current.mutateAsync(4))
    expect(api.post).toHaveBeenCalledWith('/admin/term-requests/4/reject')
    await waitFor(() => expect(keys(spy)).toEqual([['admin', 'term-requests']]))
  })

  it('useOrderOptions: GET /catalog/order-options; выключенный не запрашивает', async () => {
    vi.mocked(api.get).mockResolvedValue({ os: [], builds: [] })
    const off = hook(() => q.useOrderOptions(false))
    expect(off.result.current.fetchStatus).toBe('idle')
    hook(() => q.useOrderOptions())
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/catalog/order-options'))
  })

  it('useCreateBuild: POST /requests/build и обновление моих заявок', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateBuild())
    const body = { custom: 'Ryzen 9', os_label: 'Debian 12', department_id: 1,
                   requester_nick: 'ivan', expected_return_at: '2099-01-01' }
    await act(() => result.current.mutateAsync(body))
    expect(api.post).toHaveBeenCalledWith('/requests/build', body)
    await waitFor(() => expect(keys(spy)).toEqual([['my-requests']]))
  })

  it('useOverdue: ключ под префиксом admin — инвалидация admin обновляет и просрочки', async () => {
    const { result } = hook(() => q.useOverdue())
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    await act(() => client.invalidateQueries({ queryKey: ['admin'] }))
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('useSyncRunDetails(id): GET /admin/sync/runs/{id}, ключ содержит id', async () => {
    vi.mocked(api.get).mockResolvedValue({ id: 5 })
    const { result } = hook(() => q.useSyncRunDetails(5))
    await waitFor(() => expect(result.current.data).toEqual({ id: 5 }))
    expect(api.get).toHaveBeenCalledWith('/admin/sync/runs/5')
    expect(client.getQueryCache().find({ queryKey: ['admin', 'sync-run', 5] })).toBeDefined()
  })

  it('useSyncRunDetails(null): запрос отключён', () => {
    const { result } = hook(() => q.useSyncRunDetails(null))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('useSyncRunDetails: смена id — отдельный запрос и отдельный ключ кэша', async () => {
    vi.mocked(api.get).mockImplementation(async (p: string) => ({ path: p }))
    const { result, rerender } = renderHook(({ id }: { id: number | null }) => q.useSyncRunDetails(id), { wrapper, initialProps: { id: 1 as number | null } })
    await waitFor(() => expect(result.current.data).toEqual({ path: '/admin/sync/runs/1' }))
    rerender({ id: 2 })
    await waitFor(() => expect(result.current.data).toEqual({ path: '/admin/sync/runs/2' }))
    expect(client.getQueryCache().find({ queryKey: ['admin', 'sync-run', 1] })).toBeDefined()
    expect(client.getQueryCache().find({ queryKey: ['admin', 'sync-run', 2] })).toBeDefined()
  })

  it('useSyncRunDetails: ошибка API попадает в error', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('404'))
    const { result } = hook(() => q.useSyncRunDetails(9))
    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('Service Desk: заявки', () => {
  it('useSdConfig: GET /requests/config, кэш 5 минут', async () => {
    vi.mocked(api.get).mockResolvedValue({ enabled: true })
    const { result } = hook(() => q.useSdConfig())
    await waitFor(() => expect(result.current.data).toEqual({ enabled: true }))
    expect(api.get).toHaveBeenCalledWith('/requests/config')
    expect(options(['sd-config']).staleTime).toBe(300_000)
  })

  it('useMyRequests: GET /requests/my, опрос раз в 30 секунд', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    const { result } = hook(() => q.useMyRequests())
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.get).toHaveBeenCalledWith('/requests/my')
    expect(options(['my-requests']).refetchInterval).toBe(30_000)
  })

  it('useRequestDetail(id): GET /requests/{id}, опрос раз в 15 секунд; null — запрос отключён', async () => {
    vi.mocked(api.get).mockResolvedValue({ request: { id: 4 }, comments: [] })
    const { result } = hook(() => q.useRequestDetail(4))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.get).toHaveBeenCalledWith('/requests/4')
    expect(options(['request', 4]).refetchInterval).toBe(15_000)

    vi.mocked(api.get).mockClear()
    const off = hook(() => q.useRequestDetail(null))
    expect(off.result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('useCreateRequest: POST /requests и инвалидация my-requests', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateRequest())
    await act(() => result.current.mutateAsync({ booking_id: 3, message: 'Не включается' }))
    expect(api.post).toHaveBeenCalledWith('/requests', { booking_id: 3, message: 'Не включается' })
    await waitFor(() => expect(keys(spy)).toEqual([['my-requests']]))
  })

  it('useCreateRequest: по ВМ — vm_id в теле; при ошибке список всё равно перезапрашивается', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('500'))
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateRequest())
    await act(async () => { await result.current.mutateAsync({ vm_id: 8, message: 'Тормозит' }).catch(() => undefined) })
    expect(api.post).toHaveBeenCalledWith('/requests', { vm_id: 8, message: 'Тормозит' })
    await waitFor(() => expect(keys(spy)).toEqual([['my-requests']]))
  })

  it('useAddComment: POST /requests/{id}/comments с текстом и инвалидация только этой заявки', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useAddComment())
    await act(() => result.current.mutateAsync({ id: 4, message: 'Уточняю' }))
    expect(api.post).toHaveBeenCalledWith('/requests/4/comments', { message: 'Уточняю' })
    await waitFor(() => expect(keys(spy)).toEqual([['request', 4]]))
  })
})

describe('Service Desk: чтение', () => {
  it('useSdConfig: GET /requests/config, кэш на 5 минут', async () => {
    vi.mocked(api.get).mockResolvedValue({ enabled: true })
    const { result } = hook(() => q.useSdConfig())
    await waitFor(() => expect(result.current.data).toEqual({ enabled: true }))
    expect(api.get).toHaveBeenCalledWith('/requests/config')
    expect(client.getQueryCache().find({ queryKey: ['sd-config'] })!.observers[0].options.staleTime).toBe(300_000)
  })

  it('useMyRequests: GET /requests/my, опрос раз в 30 секунд', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 1 }])
    const { result } = hook(() => q.useMyRequests())
    await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
    expect(api.get).toHaveBeenCalledWith('/requests/my')
    expect(refetchInterval(['my-requests'])).toBe(30_000)
  })

  it('useRequestDetail: при id=null запрос не уходит', async () => {
    const { result } = hook(() => q.useRequestDetail(null))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('useRequestDetail: GET /requests/{id}, опрос раз в 15 секунд, ключ зависит от id', async () => {
    vi.mocked(api.get).mockResolvedValue({ request: { id: 5 }, comments: [] })
    const { result, rerender } = renderHook(({ id }: { id: number | null }) => q.useRequestDetail(id), {
      wrapper,
      initialProps: { id: null as number | null },
    })
    rerender({ id: 5 })
    await waitFor(() => expect(result.current.data).toEqual({ request: { id: 5 }, comments: [] }))
    expect(api.get).toHaveBeenCalledWith('/requests/5')
    expect(refetchInterval(['request', 5])).toBe(15_000)
    rerender({ id: 6 })
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/requests/6'))
  })

  it('ошибка API доходит до хука', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(404, 'Заявка не найдена'))
    const { result } = hook(() => q.useRequestDetail(9))
    await waitFor(() => expect(result.current.error?.message).toBe('Заявка не найдена'))
  })
})

describe('Service Desk: мутации', () => {
  it('useCreateRequest: POST /requests и обновление списка заявок', async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 7 })
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateRequest())
    const data = { booking_id: 1, message: 'Не включается' }
    await act(() => result.current.mutateAsync(data))
    expect(api.post).toHaveBeenCalledWith('/requests', data)
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['my-requests'] }))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('useCreateRequest: для ВМ уходит vm_id', async () => {
    const { result } = hook(() => q.useCreateRequest())
    await act(() => result.current.mutateAsync({ vm_id: 3, message: 'Нет сети' }))
    expect(api.post).toHaveBeenCalledWith('/requests', { vm_id: 3, message: 'Нет сети' })
  })

  it('useCreateRequest: при ошибке список всё равно обновляется (заявка могла создаться)', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'Jira недоступна'))
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useCreateRequest())
    await act(async () => {
      await expect(result.current.mutateAsync({ booking_id: 1, message: 'Не включается' })).rejects.toThrow('Jira недоступна')
    })
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['my-requests'] }))
  })

  it('useAddComment: POST /requests/{id}/comments и обновление именно этой заявки', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useAddComment())
    await act(() => result.current.mutateAsync({ id: 5, message: 'Спасибо' }))
    expect(api.post).toHaveBeenCalledWith('/requests/5/comments', { message: 'Спасибо' })
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['request', 5] }))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('useAddComment: ошибка пробрасывается, детали заявки всё равно перезапрашиваются', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'Jira недоступна'))
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = hook(() => q.useAddComment())
    await act(async () => {
      await expect(result.current.mutateAsync({ id: 5, message: 'Спасибо' })).rejects.toThrow('Jira недоступна')
    })
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['request', 5] }))
  })

  it('инвалидация перезапрашивает открытую переписку, но не чужую', async () => {
    vi.mocked(api.get).mockResolvedValue({ request: {}, comments: [] })
    hook(() => q.useRequestDetail(5))
    hook(() => q.useRequestDetail(6))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    const { result } = hook(() => q.useAddComment())
    await act(() => result.current.mutateAsync({ id: 5, message: 'Спасибо' }))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3))
    expect(vi.mocked(api.get).mock.calls.filter(([p]) => p === '/requests/5')).toHaveLength(2)
    expect(vi.mocked(api.get).mock.calls.filter(([p]) => p === '/requests/6')).toHaveLength(1)
  })
})

describe('просрочки и детали синхронизации', () => {
  it('useOverdue: GET /admin/overdue, опрос раз в минуту', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 1 }])
    const { result } = hook(() => q.useOverdue())
    await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
    expect(api.get).toHaveBeenCalledWith('/admin/overdue')
    expect(refetchInterval(['admin', 'overdue'])).toBe(60_000)
  })

  it('useOverdue(false): запрос не уходит', () => {
    const { result } = hook(() => q.useOverdue(false))
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('useSyncRunDetails: при id=null запрос не уходит, при id — GET /admin/sync/runs/{id}', async () => {
    const { result, rerender } = renderHook(({ id }: { id: number | null }) => q.useSyncRunDetails(id), {
      wrapper,
      initialProps: { id: null as number | null },
    })
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
    vi.mocked(api.get).mockResolvedValue({ id: 4 })
    rerender({ id: 4 })
    await waitFor(() => expect(result.current.data).toEqual({ id: 4 }))
    expect(api.get).toHaveBeenCalledWith('/admin/sync/runs/4')
  })
})
