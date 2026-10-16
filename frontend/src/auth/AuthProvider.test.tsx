import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth, useSession } from './AuthProvider'
import { api, ApiError } from '@/lib/api'
import { makeSession } from '@/test/helpers'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

let client: QueryClient

/** Показывает состояние провайдера и кнопки действий */
function Probe() {
  const { session, loading, login, logout } = useAuth()
  return (
    <div>
      <p data-testid="state">{loading ? 'loading' : session ? `user:${session.user.username}` : 'anon'}</p>
      <button onClick={() => login('admin', 'secret').catch(() => undefined)}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  )
}

const mountProbe = () =>
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  )

beforeEach(() => {
  client = new QueryClient()
  for (const m of [api.get, api.post]) vi.mocked(m).mockReset()
})

describe('AuthProvider: начальная загрузка', () => {
  it('пока /auth/me не ответил — loading, потом сессия', async () => {
    vi.mocked(api.get).mockResolvedValue(makeSession())
    mountProbe()
    expect(screen.getByTestId('state')).toHaveTextContent('loading')
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('user:i.ivanov'))
    expect(api.get).toHaveBeenCalledWith('/auth/me')
  })

  it('401 — штатная ситуация: аноним, ошибка в консоль не пишется', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(api.get).mockRejectedValue(new ApiError(401, 'нет сессии'))
    mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('anon'))
    expect(err).not.toHaveBeenCalled()
  })

  it('прочая ошибка (500/сеть) — тоже аноним, но логируется', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(api.get).mockRejectedValue(new ApiError(500, 'boom'))
    mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('anon'))
    expect(err).toHaveBeenCalledTimes(1)
  })
})

describe('AuthProvider: вход, выход, истечение сессии', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(401, 'нет сессии'))
  })

  it('login отправляет логин/пароль и сохраняет сессию из ответа', async () => {
    vi.mocked(api.post).mockResolvedValue(makeSession({ username: 'admin', role: 'admin' }))
    mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('anon'))
    await userEvent.click(screen.getByText('login'))
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('user:admin'))
    expect(api.post).toHaveBeenCalledWith('/auth/login', { username: 'admin', password: 'secret' })
  })

  it('неудачный login пробрасывает ошибку и оставляет анонимом', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(401, 'Неверный пароль'))
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>
          <AuthProvider>{children}</AuthProvider>
        </QueryClientProvider>
      ),
    })
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(async () => {
      await expect(result.current.login('a', 'b')).rejects.toThrow('Неверный пароль')
    })
    expect(result.current.session).toBeNull()
  })

  it('logout сбрасывает сессию и очищает кэш react-query', async () => {
    vi.mocked(api.get).mockResolvedValue(makeSession())
    vi.mocked(api.post).mockResolvedValue(undefined)
    client.setQueryData(['my-bookings'], [{ id: 1 }])
    mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('user:i.ivanov'))
    await userEvent.click(screen.getByText('logout'))
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('anon'))
    expect(api.post).toHaveBeenCalledWith('/auth/logout')
    expect(client.getQueryData(['my-bookings'])).toBeUndefined()
  })

  it('logout выходит локально, даже если сервер вернул ошибку', async () => {
    vi.mocked(api.get).mockResolvedValue(makeSession())
    vi.mocked(api.post).mockRejectedValue(new ApiError(500, 'boom'))
    mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('user:i.ivanov'))
    await userEvent.click(screen.getByText('logout'))
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('anon'))
  })

  it('событие auth:expired сбрасывает сессию', async () => {
    vi.mocked(api.get).mockResolvedValue(makeSession())
    mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('user:i.ivanov'))
    act(() => {
      window.dispatchEvent(new Event('auth:expired'))
    })
    expect(screen.getByTestId('state')).toHaveTextContent('anon')
  })

  it('после размонтирования слушатель auth:expired снимается', async () => {
    const remove = vi.spyOn(window, 'removeEventListener')
    vi.mocked(api.get).mockResolvedValue(makeSession())
    const { unmount } = mountProbe()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('user:i.ivanov'))
    unmount()
    expect(remove).toHaveBeenCalledWith('auth:expired', expect.any(Function))
  })
})

describe('useAuth / useSession', () => {
  it('useAuth вне провайдера бросает понятную ошибку', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    expect(() => renderHook(() => useAuth())).toThrow('useAuth вне AuthProvider')
  })

  it('useSession без сессии бросает, с сессией возвращает её', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(api.get).mockResolvedValue(makeSession())
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    )
    // пока идёт загрузка, сессии нет
    expect(() => renderHook(() => useSession(), { wrapper })).toThrow('useSession без сессии')

    function Name() {
      return <p>{useSession().user.display_name}</p>
    }
    function Gate() {
      const { session } = useAuth()
      return session ? <Name /> : null
    }
    render(<Gate />, { wrapper })
    expect(await screen.findByText('Иван Иванов')).toBeInTheDocument()
  })
})
