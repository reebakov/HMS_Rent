import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cn, formatDate, formatDateTime, formatDuration, formatRelative, initials, isOverdue, plural } from './utils'

const DAYS: [string, string, string] = ['день', 'дня', 'дней']

describe('plural', () => {
  it.each([
    [1, 'день'], [2, 'дня'], [4, 'дня'], [5, 'дней'], [11, 'дней'], [12, 'дней'], [14, 'дней'],
    [21, 'день'], [22, 'дня'], [25, 'дней'], [100, 'дней'], [101, 'день'], [111, 'дней'], [0, 'дней'],
  ])('%i -> %s', (n, expected) => {
    expect(plural(n, DAYS)).toBe(expected)
  })
})

describe('initials', () => {
  it('берёт первые буквы двух слов в верхнем регистре', () => {
    expect(initials('иван иванов')).toBe('ИИ')
  })
  it('игнорирует лишние пробелы и третье слово', () => {
    expect(initials('  Анна   Мария  Петрова ')).toBe('АМ')
  })
  it('пустая строка даёт пустой результат', () => {
    expect(initials('')).toBe('')
  })
})

describe('cn', () => {
  it('склеивает классы и разрешает конфликты tailwind', () => {
    expect(cn('px-2', false && 'hidden', 'px-4')).toBe('px-4')
  })
})

describe('форматирование дат', () => {
  it('пустые значения -> тире', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDateTime('')).toBe('—')
    expect(formatRelative(null)).toBe('—')
  })
  it('formatDate содержит год и день', () => {
    const out = formatDate('2025-03-07T12:00:00Z')
    expect(out).toMatch(/2025/)
    expect(out).toMatch(/07/)
  })
})

describe('относительное время и длительность', () => {
  const NOW = new Date('2025-06-15T12:00:00Z')
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  const ago = (sec: number) => new Date(NOW.getTime() - sec * 1000).toISOString()

  it('formatRelative: только что / минуты / часы', () => {
    expect(formatRelative(ago(30))).toBe('только что')
    expect(formatRelative(ago(5 * 60))).toBe('5 мин назад')
    expect(formatRelative(ago(3 * 3600))).toBe('3 ч назад')
  })
  it('formatRelative: старше суток — обычная дата', () => {
    expect(formatRelative(ago(3 * 86400))).toBe(formatDate(ago(3 * 86400)))
  })
  it('formatDuration: от даты до сейчас', () => {
    expect(formatDuration(ago(3600))).toBe('меньше дня')
    expect(formatDuration(ago(3 * 86400))).toBe('3 дня')
    expect(formatDuration(ago(21 * 86400))).toBe('21 день')
  })
  it('formatDuration: явная дата окончания, отрицательный интервал -> меньше дня', () => {
    expect(formatDuration('2025-01-01T00:00:00Z', '2025-01-06T00:00:00Z')).toBe('5 дней')
    expect(formatDuration('2025-01-06T00:00:00Z', '2025-01-01T00:00:00Z')).toBe('меньше дня')
  })
  it('isOverdue: сравнивает с концом указанного дня', () => {
    expect(isOverdue('2025-06-14')).toBe(true)
    expect(isOverdue('2025-06-15')).toBe(false)
    expect(isOverdue('2025-06-16')).toBe(false)
    expect(isOverdue(null)).toBe(false)
  })
})
