import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { api } from './api'
import * as q from './queries'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

let client: QueryClient
const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
const hook = <T,>(fn: () => T) => renderHook(fn, { wrapper })
const keys = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.map(([f]) => (f as { queryKey: unknown[] }).queryKey)
const options = (queryKey: unknown[]) => client.getQueryCache().find({ queryKey })!.observers[0].options

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset().mockResolvedValue(null as never)
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
