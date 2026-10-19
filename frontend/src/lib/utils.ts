import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
})

export const formatDate = (value?: string | null) => (value ? dateFmt.format(new Date(value)) : '—')
export const formatDateTime = (value?: string | null) => (value ? dateTimeFmt.format(new Date(value)) : '—')

export function formatRelative(value?: string | null) {
  if (!value) return '—'
  const diff = (Date.now() - new Date(value).getTime()) / 1000
  if (diff < 60) return 'только что'
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`
  return formatDate(value)
}

/** «3 дня», «1 месяц» — для длительности бронирования */
export function formatDuration(from: string, to?: string | null) {
  const days = Math.max(0, Math.floor(((to ? new Date(to) : new Date()).getTime() - new Date(from).getTime()) / 86400000))
  if (days === 0) return 'меньше дня'
  return `${days} ${plural(days, ['день', 'дня', 'дней'])}`
}

export function plural(n: number, forms: [string, string, string]) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1]
  return forms[2]
}

/** Сегодняшняя дата по местному времени в виде YYYY-MM-DD: toISOString() даёт дату по UTC, и у границы суток min поля даты сдвигается на день */
export function todayLocal() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export const isOverdue = (date?: string | null) => !!date && new Date(date + 'T23:59:59') < new Date()

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

/** Текст ошибки для тоста: сообщение Error (его формирует api.ts) или запасной текст */
export const errorMessage = (e: unknown, fallback = 'Ошибка') => (e instanceof Error ? e.message : fallback)
