import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { addDays, addMonths, cn, computerSpecs, errorMessage, formatDate, formatDateTime, formatDuration, formatRelative, initials, isOverdue, plural, todayLocal, workHours } from './utils'

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

describe('todayLocal', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  // 22:30 UTC — в Екатеринбурге (UTC+5) уже 03:30 следующего дня; toISOString() вернул бы вчерашнюю дату
  it('даёт дату по местному времени, а не по UTC', () => {
    vi.stubEnv('TZ', 'Asia/Yekaterinburg')
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-19T22:30:00Z'))
    expect(todayLocal()).toBe('2026-10-20')
    expect(new Date().toISOString().slice(0, 10)).toBe('2026-10-19')
  })

  it('добавляет нули к месяцу и дню', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 0, 5, 12))
    expect(todayLocal()).toBe('2026-01-05')
  })
})

describe('addDays', () => {
  it.each([
    ['2026-10-19', 1, '2026-10-20'],
    ['2026-10-31', 1, '2026-11-01'],
    ['2026-12-31', 1, '2027-01-01'],
    ['2028-02-28', 1, '2028-02-29'], // високосный год
    ['2026-03-01', -1, '2026-02-28'],
  ])('%s + %i -> %s', (date, days, expected) => {
    expect(addDays(date, days)).toBe(expected)
  })

  it('не сдвигается на переходе на летнее время', () => {
    vi.stubEnv('TZ', 'Europe/Berlin')
    expect(addDays('2026-03-28', 1)).toBe('2026-03-29')
    expect(addDays('2026-03-29', 1)).toBe('2026-03-30')
    vi.unstubAllEnvs()
  })
})

describe('errorMessage', () => {
  it('берёт сообщение Error', () => {
    expect(errorMessage(new Error('Нет прав'))).toBe('Нет прав')
  })
  it.each([undefined, 'строка', { message: 'не Error' }])('%j без Error даёт «Ошибка»', (e) => {
    expect(errorMessage(e)).toBe('Ошибка')
  })
  it('запасной текст можно задать', () => {
    expect(errorMessage(null, 'Не удалось войти')).toBe('Не удалось войти')
  })
})

describe('computerSpecs', () => {
  it.each([
    [{ cpu: 'Intel Core i5', ram_gb: 16, gpu: 'RTX 4070' }, 'Intel Core i5 · 16 ГБ · RTX 4070'],
    [{ cpu: 'Intel Core i5', ram_gb: 16, gpu: null }, 'Intel Core i5 · 16 ГБ'],
    [{ cpu: null, ram_gb: 0, gpu: 'RTX 4070' }, 'RTX 4070'],
    [{ cpu: null, ram_gb: null, gpu: null }, ''],
  ])('%j -> «%s»', (computer, expected) => {
    expect(computerSpecs(computer)).toBe(expected)
  })
})

describe('addMonths', () => {
  it.each([
    ['2026-01-15', 3, '2026-04-15'],
    ['2026-11-20', 3, '2027-02-20'], // через год
    ['2026-05-31', 3, '2026-08-31'],
    ['2026-11-30', 3, '2027-02-28'], // в феврале нет 30-го — конец месяца
    ['2023-11-30', 3, '2024-02-29'], // високосный год
    ['2026-12-31', 3, '2027-03-31'],
    ['2026-03-15', 0, '2026-03-15'],
  ])('%s + %i мес. = %s', (date, months, expected) => {
    expect(addMonths(date, months)).toBe(expected)
  })
})


describe('workHours', () => {
  it.each([[0, '0'], [3600, '1'], [12600, '3,5'], [28800, '8'], [4500, '1,3']])('%i с → %s ч', (seconds, expected) => {
    expect(workHours(seconds)).toBe(expected)
  })
})
