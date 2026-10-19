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

let client: QueryClient
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
)
const hook = <T,>(fn: () => T) => renderHook(fn, { wrapper })
const refetchInterval = (key: unknown[]) => client.getQueryCache().find({ queryKey: key })!.observers[0].options.refetchInterval

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset().mockResolvedValue(null as never)
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
