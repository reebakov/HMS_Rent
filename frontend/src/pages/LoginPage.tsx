import React, { useEffect, useState, type FormEvent, useMemo } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { ChevronDown, Cloud, LockKeyhole, Monitor, MonitorSmartphone, ShieldCheck, Zap, KeyRound } from 'lucide-react'
import { useAuth } from '@/auth/AuthProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { AuthConfig } from '@/lib/types'
import { cn } from '@/lib/utils'

const FEATURES = [
  { icon: Monitor, title: 'Компьютеры', text: 'От офисных до мощных — под любые задачи' },
  { icon: Cloud, title: 'Виртуальные машины', text: 'Соберите свою: ядра, память, диск' },
  { icon: Zap, title: 'В пару кликов', text: 'Выбрали, нажали «Забронировать» — готово' },
]

// Добавили больше слов для плотности
const RAW_WORDS = [
  'HMS RENT', 'RENT', 'HMS', 'vSphere', 'RTX 4070', 'Intel', 'Xeon',
  'Automat', 'Linked Clone', 'AMD', 'Godzen', 'Jira', 'Insight', 'NVMe', 
  'RAM', 'VNC', 'vCenter', 'Ryzen 7', 'ESXi Host', 'Fast Provision',
  'Linux', 'Bash', 'Python', 'Docker', 'Core', 'Server', 'Data Center',
  'SSD', 'Network', 'Deploy', 'Cluster', 'Node', 'Gateway', 'Proxy'
]

function generateSpotlightGrid(count: number) {
  const result = []
  const cols = 6 // Увеличили количество колонок
  const rows = Math.ceil(count / cols)
  
  for (let i = 0; i < count; i++) {
    const col = i % cols
    const row = Math.floor(i / cols)
    
    const baseX = (col / (cols - 1)) * 90 + 5
    const baseY = (row / (rows - 1)) * 85 + 5
    
    const randomX = baseX + (Math.random() * 6 - 3)
    const randomY = baseY + (Math.random() * 6 - 3)
    
    const angles = ['rotate-0', '-rotate-6', 'rotate-6', '-rotate-12', 'rotate-12', '-rotate-45', 'rotate-90']
    const rotate = angles[Math.floor(Math.random() * angles.length)]
    
    // Шрифты стали ЗНАЧИТЕЛЬНО крупнее и разнообразнее
    const sizes = [
      'text-sm opacity-60', 
      'text-lg font-medium opacity-80', 
      'text-xl font-bold opacity-90', 
      'text-2xl font-black', 
      'text-3xl font-black tracking-tighter'
    ]
    const size = sizes[Math.floor(Math.random() * sizes.length)]
    const text = RAW_WORDS[Math.floor(Math.random() * RAW_WORDS.length)]

    result.push({ text, x: `${randomX}%`, y: `${randomY}%`, rotate, size })
  }
  return result
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

  // Генерируем 60 слов вместо 30 для плотности
  const spotlightWords = useMemo(() => generateSpotlightGrid(60), [])

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    e.currentTarget.style.setProperty('--spotlight-x', `${x}px`)
    e.currentTarget.style.setProperty('--spotlight-y', `${y}px`)
  }

  useEffect(() => {
    api.get<AuthConfig>('/auth/config').then((c) => {
      setConfig(c)
      if (!c.bouncer_enabled) setAdminOpen(true)
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
      {/* Левая панель */}
      <div
        onMouseMove={handleMouseMove}
        className="relative hidden overflow-hidden bg-sidebar p-12 text-sidebar-foreground lg:flex lg:flex-col"
        style={{
          ['--spotlight-x' as string]: '-1000px',
          ['--spotlight-y' as string]: '-1000px',
        }}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              'linear-gradient(to right, white 1px, transparent 1px), linear-gradient(to bottom, white 1px, transparent 1px)',
            backgroundSize: '44px 44px',
          }}
        />
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-primary/30 blur-3xl" />

        {/* Скрытый слой со словами */}
        <div
          className="pointer-events-none absolute inset-0 z-0 transition-opacity duration-300"
          style={{
            maskImage: 'radial-gradient(circle 280px at var(--spotlight-x) var(--spotlight-y), black 0%, rgba(0,0,0,0.5) 50%, transparent 100%)',
            WebkitMaskImage: 'radial-gradient(circle 280px at var(--spotlight-x) var(--spotlight-y), black 0%, rgba(0,0,0,0.5) 50%, transparent 100%)',
          }}
        >
          {spotlightWords.map((w, idx) => (
            <span
              key={idx}
              className={cn(
                'absolute select-none font-sans text-blue-400/80 drop-shadow-[0_0_15px_rgba(96,165,250,0.8)]',
                w.rotate,
                w.size,
              )}
              style={{ left: w.x, top: w.y, transform: `translate(-50%, -50%) ${w.rotate === 'rotate-0' ? '' : 'rotate(' + w.rotate.replace('rotate-', '').replace('-','') + (w.rotate.startsWith('-') ? 'deg)' : 'deg)')}` }}
            >
              {w.text}
            </span>
          ))}
        </div>

        <div className="relative z-10 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-white">
            <MonitorSmartphone className="h-5 w-5" />
          </div>
          <span className="text-lg font-semibold text-white">{config?.app_name ?? 'HMS Rent'}</span>
        </div>

        <div className="relative z-10 mt-auto max-w-md">
          <h1 className="text-[34px] font-semibold leading-tight tracking-tight text-white drop-shadow-md">
            Компьютеры и виртуалки для работы
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-sidebar-muted drop-shadow-md">
            Берите нужную мощность, когда нужно, и возвращайте, когда закончили.
          </p>
          <div className="mt-10 space-y-5">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <div key={title} className="flex gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/5 ring-1 ring-white/10 backdrop-blur-sm">
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
        <p className="relative z-10 mt-16 text-xs text-sidebar-muted">Внутренний сервис HMS</p>
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
              {config?.bouncer_enabled
                ? 'Используйте корпоративный аккаунт (SSO)'
                : 'Войдите, чтобы арендовать технику'}
            </p>
          </div>

          {error && (
            <div className="mb-4 rounded-lg border border-danger/20 bg-danger/5 px-3 py-2.5 text-[13px] text-danger">{error}</div>
          )}

          {config?.bouncer_enabled && (
            <a
              href={api.url('/auth/bouncer/login', { next: '/' })}
              className="flex h-11 w-full items-center justify-center gap-3 rounded-lg border border-primary/20 bg-primary/5 text-primary text-[15px] font-medium shadow-sm transition-colors hover:bg-primary/10"
            >
              <KeyRound className="h-5 w-5" />
              Корпоративный вход
            </a>
          )}

          {config && !config.bouncer_enabled && config.dev_enabled && (
            <div className="mb-4 rounded-lg border border-warning/25 bg-warning/5 px-3 py-2.5 text-[13px] text-warning">
              Кнопка корпоративного входа появится, когда в .env будут заданы BOUNCER_AUTHORIZE_URL,
              BOUNCER_TOKEN_URL и BOUNCER_CLIENT_ID.
            </div>
          )}

          {showForm && (
            <div className={cn(config?.bouncer_enabled && 'mt-6 border-t pt-4')}>
              {config?.bouncer_enabled && (
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
        </div>
      </div>
    </div>
  )
}