import { Cloud, Cpu, Monitor, Zap, type LucideIcon } from 'lucide-react'
import type { ComputerStatus, Tier } from './types'

// Всё, что связано с подписью категорий и статусов, — в одном месте

export const TIERS: Record<Tier, { label: string; short: string; hint: string; icon: LucideIcon; accent: string }> = {
  weak: {
    label: 'Слабые',
    short: 'Слабый',
    hint: 'Документы, браузер, офисные задачи',
    icon: Monitor,
    accent: 'text-slate-600 bg-slate-500/10 dark:text-slate-300',
  },
  medium: {
    label: 'Средние',
    short: 'Средний',
    hint: 'Разработка, тестирование, аналитика',
    icon: Cpu,
    accent: 'text-blue-700 bg-blue-500/10 dark:text-blue-300',
  },
  powerful: {
    label: 'Мощные',
    short: 'Мощный',
    hint: '3D, рендер, сборки, ML-задачи',
    icon: Zap,
    accent: 'text-violet-700 bg-violet-500/10 dark:text-violet-300',
  },
  vm: {
    label: 'Виртуальные',
    short: 'ВМ',
    hint: 'Удалённый рабочий стол на vSphere',
    icon: Cloud,
    accent: 'text-teal-700 bg-teal-500/10 dark:text-teal-300',
  },
}

export const TIER_ORDER: Tier[] = ['weak', 'medium', 'powerful', 'vm']

export const STATUSES: Record<ComputerStatus, { label: string; tone: 'success' | 'primary' | 'warning' | 'danger' | 'muted' }> = {
  available: { label: 'Свободен', tone: 'success' },
  booked: { label: 'Забронирован', tone: 'primary' },
  in_use: { label: 'Занят (Insight)', tone: 'warning' },
  maintenance: { label: 'Резерв', tone: 'warning' },
  retired: { label: 'Списан', tone: 'muted' },
  unknown: { label: 'Неизвестно', tone: 'muted' },
}

export const EVENT_LABELS: Record<string, string> = {
  booked: 'Бронирование',
  returned: 'Возврат',
  insight_created: 'Появился в Insight',
  insight_status_changed: 'Статус в Insight',
  insight_removed: 'Удалён из Insight',
  insight_pool_changed: 'Пул из Insight',
  admin_update: 'Правка админа',
  writeback_failed: 'Ошибка записи в Insight',
}
