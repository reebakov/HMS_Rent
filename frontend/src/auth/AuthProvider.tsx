import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/lib/api'
import type { Session } from '@/lib/types'

interface AuthContextValue {
  session: Session | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Администратор открывает портал глазами сотрудника (только просмотр); stop — возврат к своей учётке */
  viewAs: (userId: number) => Promise<void>
  stopViewAs: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const qc = useQueryClient()

  useEffect(() => {
    api
      .get<Session>('/auth/me')
      .then(setSession)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e)
      })
      .finally(() => setLoading(false))

    // любой 401 от API (истекла сессия) — выкидываем на экран входа
    const onExpired = () => setSession(null)
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setSession(await api.post<Session>('/auth/login', { username, password }))
  }, [])

  const logout = useCallback(async () => {
    await api.post('/auth/logout').catch(() => undefined)
    qc.clear()
    setSession(null)
  }, [qc])

  // данные в кэше принадлежали другому пользователю: после переключения их нужно загрузить заново
  const viewAs = useCallback(async (userId: number) => {
    setSession(await api.post<Session>('/auth/view-as', { user_id: userId }))
    qc.clear()
  }, [qc])

  const stopViewAs = useCallback(async () => {
    setSession(await api.del<Session>('/auth/view-as'))
    qc.clear()
  }, [qc])

  return <AuthContext.Provider value={{ session, loading, login, logout, viewAs, stopViewAs }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth вне AuthProvider')
  return ctx
}

export function useSession() {
  const { session } = useAuth()
  if (!session) throw new Error('useSession без сессии')
  return session
}
