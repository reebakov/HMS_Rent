// Тонкая обёртка над fetch: cookie-сессия, JSON, понятные ошибки

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

const BASE = '/api/v1'

type Query = Record<string, string | number | boolean | null | undefined>

function buildUrl(path: string, query?: Query) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value))
  })
  return url.pathname + url.search
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const res = await fetch(buildUrl(path, query), {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event('auth:expired'))
  }
  if (!res.ok) {
    let message = `Ошибка ${res.status}`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* тело не JSON — оставляем код ошибки */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

/** Версия backend из /api/health (sha коммита, «dev» в разработке; пусто у старого backend) */
async function serverVersion(): Promise<string | undefined> {
  const res = await fetch('/api/health', { cache: 'no-store' })
  if (!res.ok) throw new ApiError(res.status, `Ошибка ${res.status}`)
  return ((await res.json()) as { version?: string }).version
}

export const api = {
  serverVersion,
  get: <T>(path: string, query?: Query) => request<T>('GET', path, undefined, query),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T = void>(path: string) => request<T>('DELETE', path),
  url: buildUrl,
}
