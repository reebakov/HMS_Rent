import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CategoryCards } from './CategoryCards'
import type { TierSummary } from '@/lib/types'

const summary: TierSummary[] = [
  { tier: 'weak', available: 3, total: 5, min_ram_gb: 8, max_ram_gb: 8 },
  { tier: 'medium', available: 1, total: 4, min_ram_gb: 16, max_ram_gb: 32 },
  { tier: 'powerful', available: 0, total: 2, min_ram_gb: null, max_ram_gb: null },
  { tier: 'vm', available: 0, total: 0, min_ram_gb: null, max_ram_gb: null },
]

describe('CategoryCards', () => {
  it('показывает карточки категорий с числом свободных и диапазоном ОЗУ', () => {
    render(<CategoryCards summary={summary} value="medium" onChange={() => undefined} />)
    expect(screen.getByRole('button', { name: /Слабые/ })).toHaveTextContent('3')
    expect(screen.getByRole('button', { name: /Слабые/ })).toHaveTextContent('из 5')
    expect(screen.getByRole('button', { name: /Слабые/ })).toHaveTextContent('8 ГБ ОЗУ')
    expect(screen.getByRole('button', { name: /Средние/ })).toHaveTextContent('16–32 ГБ ОЗУ')
  })

  it('скрывает категории без единого ПК (vm с total=0)', () => {
    render(<CategoryCards summary={summary} value="weak" onChange={() => undefined} />)
    expect(screen.queryByRole('button', { name: /Виртуальные/ })).not.toBeInTheDocument()
  })

  it('клик по карточке вызывает onChange с категорией', async () => {
    const onChange = vi.fn()
    render(<CategoryCards summary={summary} value="weak" onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: /Мощные/ }))
    expect(onChange).toHaveBeenCalledWith('powerful')
  })

  it('карточка конструктора ВМ показывается только с onBuildVm', async () => {
    const onBuildVm = vi.fn()
    const { rerender } = render(<CategoryCards summary={summary} value="weak" onChange={() => undefined} />)
    expect(screen.queryByText('Виртуализация')).not.toBeInTheDocument()
    rerender(<CategoryCards summary={summary} value="weak" onChange={() => undefined} onBuildVm={onBuildVm} />)
    await userEvent.click(screen.getByRole('button', { name: /Виртуализация/ }))
    expect(onBuildVm).toHaveBeenCalledOnce()
  })
})
