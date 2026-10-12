import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { ChevronDown, History, LockKeyhole, MonitorSmartphone, Radar, ShieldCheck, Users } from 'lucide-react'
import { useAuth } from '@/auth/AuthProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { AuthConfig } from '@/lib/types'
import { cn } from '@/lib/utils'

const FEATURES = [
  { icon: Radar, title: 'Актуальные данные', text: 'Статусы и характеристики ПК подтягиваются из Insight' },
  { icon: Users, title: 'Закрепление за отделом', text: 'Бронь в пару кликов: выбрали ПК, указали отдел' },
  { icon: History, title: 'Прозрачный учёт', text: 'Кто, когда и какой компьютер взял и вернул' },
]

function GoogleIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-5 w-5" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.1 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.2-.1-2.3-.4-3.5z" />
    </svg>
  )
}

export function LoginPage() {
  const { session, login } = useAuth()
  const [params] = useSearchParams()
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [adminOpen, setAdminOpen] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(params.get('error'))
  const [pending, setPending] = useState(false)

  useEffect(() => {
    api.get<AuthConfig>('/auth/config').then((c) => {
      setConfig(c)
      if (!c.google_enabled) setAdminOpen(true) // без Google форма логина — основной способ
    }).catch(() => undefined)
  }, [])

  if (session) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось войти')
    } finally {
      setPending(false)
    }
  }

  const showForm = config && (config.local_enabled || config.dev_enabled)

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* Левая панель — бренд */}
      <div className="relative hidden overflow-hidden bg-sidebar p-12 text-sidebar-foreground lg:flex lg:flex-col">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              'linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)',
            backgroundSize: '44px 44px',
          }}
        />
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-primary/30 blur-3xl" />

        <div className="relative flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-white">
            <MonitorSmartphone className="h-5 w-5" />
          </div>
          <span className="text-lg font-semibold text-white">{config?.app_name ?? 'HMS Rent'}</span>
        </div>

        <div className="relative mt-auto max-w-md">
          <h1 className="text-[34px] font-semibold leading-tight tracking-tight text-white">
            Рабочие компьютеры для вашей команды
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-sidebar-muted">
            Подберите свободный ПК или виртуальную машину нужной мощности и закрепите за своим отделом.
          </p>
          <div className="mt-10 space-y-5">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <div key={title} className="flex gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/5 ring-1 ring-white/10">
                  <Icon className="h-5 w-5 text-blue-300" />
                </div>
                <div>
                  <p className="font-medium text-white">{title}</p>
                  <p className="text-[13px] text-sidebar-muted">{text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="relative mt-16 text-xs text-sidebar-muted">Внутренний сервис ИТ-отдела</p>
      </div>

      {/* Правая панель — вход */}
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <LockKeyhole className="h-5 w-5" />
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">Вход</h2>
            <p className="mt-1.5 text-muted-foreground">
              {config?.google_enabled
                ? `Используйте рабочий Google-аккаунт${config.google_domains.length ? ` (@${config.google_domains.join(', @')})` : ''}`
                : 'Войдите, чтобы забронировать компьютер'}
            </p>
          </div>

          {error && (
            <div className="mb-4 rounded-lg border border-danger/20 bg-danger/5 px-3 py-2.5 text-[13px] text-danger">{error}</div>
          )}

          {config?.google_enabled && (
            <a
              href={api.url('/auth/google/login', { next: '/' })}
              className="flex h-11 w-full items-center justify-center gap-3 rounded-lg border bg-card text-[15px] font-medium shadow-sm transition-colors hover:bg-muted/60"
            >
              <GoogleIcon />
              Войти через Google
            </a>
          )}

          {config && !config.google_enabled && config.dev_enabled && (
            <div className="mb-4 rounded-lg border border-warning/25 bg-warning/5 px-3 py-2.5 text-[13px] text-warning">
              Кнопка «Войти через Google» появится, когда в .env будут заданы GOOGLE_CLIENT_ID и
              GOOGLE_CLIENT_SECRET (инструкция — docs/GOOGLE_SSO.md). Подсказка видна только в dev-режиме.
            </div>
          )}

          {showForm && (
            <div className={cn(config?.google_enabled && 'mt-6 border-t pt-4')}>
              {config?.google_enabled && (
                <button
                  type="button"
                  onClick={() => setAdminOpen((v) => !v)}
                  className="flex w-full items-center justify-between py-1 text-[13px] font-medium text-muted-foreground hover:text-foreground"
                >
                  <span className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4" />
                    Вход для администраторов
                  </span>
                  <ChevronDown className={cn('h-4 w-4 transition-transform', adminOpen && 'rotate-180')} />
                </button>
              )}
              {adminOpen && (
                <form onSubmit={submit} className="mt-4 space-y-4 animate-fade-in">
                  <Field label="Логин">
                    <Input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
                  </Field>
                  <Field label="Пароль" hint={config?.dev_enabled ? 'Dev-режим: любой логин без пароля, «admin» — администратор' : undefined}>
                    <Input
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </Field>
                  <Button type="submit" size="lg" className="w-full" loading={pending} disabled={!username}>
                    Войти
                  </Button>
                </form>
              )}
            </div>
          )}

          <p className="mt-8 text-center text-xs text-muted-foreground">
            Нет доступа? Напишите в ИТ-отдел.
          </p>
        </div>
      </div>
    </div>
  )
}
