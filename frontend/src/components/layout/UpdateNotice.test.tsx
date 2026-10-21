import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UpdateNotice } from './UpdateNotice'
import { api, ApiError } from '@/lib/api'
import { shouldRetry } from '@/lib/queryRetry'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn(), serverVersion: vi.fn() },
}))
const version = vi.hoisted(() => ({ APP_VERSION: 'abc1234' }))
vi.mock('@/lib/version', () => version)

function renderNotice(client = new QueryClient({ defaultOptions: { queries: { retry: false } } }), extra?: React.ReactNode) {
  return render(
    <QueryClientProvider client={client}>
      {extra}
      <UpdateNotice />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  version.APP_VERSION = 'abc1234'
  vi.mocked(api.serverVersion).mockReset()
})

describe('UpdateNotice: новая версия', () => {
  it('версия сервера та же — плашки нет', async () => {
    vi.mocked(api.serverVersion).mockResolvedValue('abc1234')
    renderNotice()
    await waitFor(() => expect(api.serverVersion).toHaveBeenCalled())
    expect(screen.queryByText(/Доступна новая версия/)).not.toBeInTheDocument()
  })

  it('сервер отдаёт другую версию — плашка с кнопкой «Обновить», которая перезагружает страницу', async () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    vi.mocked(api.serverVersion).mockResolvedValue('def5678')
    renderNotice()
    expect(await screen.findByText('Доступна новая версия портала')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Обновить' }))
    expect(reload).toHaveBeenCalledOnce()
    vi.unstubAllGlobals()
  })

  it.each([
    ['в разработке (dev) у страницы', 'dev', 'def5678'],
    ['в разработке (dev) у сервера', 'abc1234', 'dev'],
    ['старый backend без версии', 'abc1234', undefined],
  ])('%s — плашки нет', async (_title, app, server) => {
    version.APP_VERSION = app
    vi.mocked(api.serverVersion).mockResolvedValue(server)
    renderNotice()
    await waitFor(() => expect(api.serverVersion).toHaveBeenCalled())
    expect(screen.queryByText(/Доступна новая версия/)).not.toBeInTheDocument()
  })

  it('ошибка проверки версии молчит: плашки нет, ничего не падает', async () => {
    vi.mocked(api.serverVersion).mockRejectedValue(new ApiError(503, 'x'))
    renderNotice()
    await waitFor(() => expect(api.serverVersion).toHaveBeenCalled())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

describe('UpdateNotice: сервис обновляется', () => {
  function Probe({ fn }: { fn: () => Promise<string> }) {
    useQuery({ queryKey: ['probe'], queryFn: fn })
    return null
  }

  it('пока запрос повторяется после 503 — «Сервис обновляется», после успеха плашка уходит', async () => {
    vi.mocked(api.serverVersion).mockResolvedValue('abc1234')
    const client = new QueryClient({ defaultOptions: { queries: { retry: shouldRetry, retryDelay: 30 } } })
    let calls = 0
    const probe = async () => {
      calls += 1
      if (calls < 3) throw new ApiError(503, 'Service Unavailable')
      return 'ok'
    }
    renderNotice(client, <Probe fn={probe} />)
    expect(await screen.findByText('Сервис обновляется, повторяем запрос…')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/Сервис обновляется/)).not.toBeInTheDocument())
    expect(calls).toBe(3)
  })

  it('обычная ошибка (404) не выдаёт себя за обновление', async () => {
    vi.mocked(api.serverVersion).mockResolvedValue('abc1234')
    const client = new QueryClient({ defaultOptions: { queries: { retry: shouldRetry, retryDelay: 10 } } })
    renderNotice(client, <Probe fn={async () => { throw new ApiError(404, 'нет') }} />)
    await waitFor(() => expect(api.serverVersion).toHaveBeenCalled())
    expect(screen.queryByText(/Сервис обновляется/)).not.toBeInTheDocument()
  })
})
