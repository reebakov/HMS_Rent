import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { VmStatusBadge } from './badge'

describe('VmStatusBadge', () => {
  it.each([
    ['queued', 'В очереди', true],
    ['creating', 'Создаётся', true],
    ['ready', 'Готова', false],
    ['failed', 'Ошибка', false],
    ['deleting', 'Удаляется', true],
    ['deleted', 'Удалена', false],
  ] as const)('%s — «%s»: занятые статусы со спиннером, остальные с точкой', (status, label, busy) => {
    render(<VmStatusBadge status={status} />)
    const badge = screen.getByText(label)
    expect(!!badge.querySelector('svg.animate-spin')).toBe(busy)
    expect(!!badge.querySelector('span.rounded-full')).toBe(!busy)
  })
})
