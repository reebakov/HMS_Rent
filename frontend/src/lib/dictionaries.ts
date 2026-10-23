import { Cloud, Cpu, Monitor, Zap, type LucideIcon } from 'lucide-react'
import type { Tone } from '@/components/ui/badge'
import type { ComputerStatus, ExecutorProblem, Tier, UserRole, VmStatus } from './types'

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
  cleaning: { label: 'Очистка', tone: 'warning' },
  in_use: { label: 'Занят (Insight)', tone: 'warning' },
  maintenance: { label: 'Резерв', tone: 'warning' },
  retired: { label: 'Списан', tone: 'muted' },
  unknown: { label: 'Неизвестно', tone: 'muted' },
}

export const VM_STATUS: Record<VmStatus, { label: string; tone: Tone; busy?: boolean }> = {
  queued: { label: 'В очереди', tone: 'muted', busy: true },
  creating: { label: 'Создаётся', tone: 'primary', busy: true },
  checking: { label: 'Проверяется', tone: 'primary', busy: true },
  ready: { label: 'Готова', tone: 'success' },
  failed: { label: 'Ошибка', tone: 'danger' },
  deleting: { label: 'Удаляется', tone: 'warning', busy: true },
  deleted: { label: 'Удалена', tone: 'muted' },
}

/** Отказаться от ВМ (или отменить заявку) можно, пока она не создаётся и не удаляется; на проверке — пока её не взял исполнитель */
export const canReleaseVm = (status: VmStatus) => status === 'ready' || status === 'failed' || status === 'queued' || status === 'checking'

/** Продлить срок ВМ можно, пока она не удаляется и не удалена */
export const canExtendVm = (status: VmStatus) => status !== 'deleting' && status !== 'deleted'

/** Основания отклонения заказа ПК исполнителем (регламент); первое ещё и выводит ПК из пула */
export const REJECT_REASONS = ['Сервер неисправен', 'Заказчик не ответил', 'Некорректный заказ'] as const
export const FAULTY_REASON = REJECT_REASONS[0]

/** Основания отклонения ВМ исполнителем при проверке (регламент) */
export const BUILD_REJECT_REASONS = ['Нет комплектующих', 'Несовместимая конфигурация', 'Заказчик не ответил', 'Некорректный заказ'] as const
export const VM_REJECT_REASONS = ['Не удалось подготовить ВМ', 'Недостаточно мощностей кластера', 'Заказчик не ответил', 'Некорректный заказ'] as const

export const EVENT_LABELS: Record<string, string> = {
  booked: 'Бронирование',
  returned: 'Возврат',
  extended: 'Продление',
  prepared: 'Подготовка ПК',
  rejected: 'Отклонение заказа',
  cleaned: 'Очистка диска',
  repaired: 'Возврат в пул после диагностики',
  replaced: 'Замена ПК в заказе',
  insight_created: 'Появился в Insight',
  insight_status_changed: 'Статус в Insight',
  insight_removed: 'Удалён из Insight',
  insight_pool_changed: 'Пул из Insight',
  admin_update: 'Правка админа',
  writeback_failed: 'Ошибка записи в Insight',
}

export const ROLE_LABELS: Record<UserRole, string> = {
  user: 'сотрудник',
  executor: 'исполнитель',
  admin: 'администратор',
}

/** Проблема открыта, пока её задача в Jira не закрыта (нет категории — тоже открыта: заявка не создалась) */
export const isOpenProblem = (p: Pick<ExecutorProblem, 'status_category'>) => p.status_category !== 'done'

/** Раздел «Исполнитель» видят исполнители и администраторы (как User.is_executor на backend) */
export const canExecute = (role: UserRole) => role === 'executor' || role === 'admin'
