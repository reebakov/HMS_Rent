import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CategoryCards } from './CategoryCards'
import { stubQuery } from '@/test/helpers'
import type { TierSummary } from '@/lib/types'

const summary: TierSummary[] = [
  { tier: 'weak', available: 3, total: 5, min_ram_gb: 8, max_ram_gb: 8 },
  { tier: 'medium', available: 1, total: 4, min_ram_gb: 16, max_ram_gb: 32 },
  { tier: 'powerful', available: 0, total: 2, min_ram_gb: null, max_ram_gb: null },
  { tier: 'vm', available: 0, total: 0, min_ram_gb: null, max_ram_gb: null },
]

describe('CategoryCards', () => {
  it('показывает карточки категорий с числом свободных и диапазоном ОЗУ', () => {
    render(<CategoryCards query={stubQuery({ data: summary })} value="medium" onChange={() => undefined} />)
    expect(screen.getByRole('button', { name: /Слабые/ })).toHaveTextContent('3')
    expect(screen.getByRole('button', { name: /Слабые/ })).toHaveTextContent('из 5')
    expect(screen.getByRole('button', { name: /Слабые/ })).toHaveTextContent('8 ГБ ОЗУ')
    expect(screen.getByRole('button', { name: /Средние/ })).toHaveTextContent('16–32 ГБ ОЗУ')
  })

  it('скрывает категории без единого ПК (vm с total=0)', () => {
    render(<CategoryCards query={stubQuery({ data: summary })} value="weak" onChange={() => undefined} />)
    expect(screen.queryByRole('button', { name: /Виртуальные/ })).not.toBeInTheDocument()
  })

  it('клик по карточке вызывает onChange с категорией', async () => {
    const onChange = vi.fn()
    render(<CategoryCards query={stubQuery({ data: summary })} value="weak" onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: /Мощные/ }))
    expect(onChange).toHaveBeenCalledWith('powerful')
  })

  it('карточка конструктора ВМ показывается только с onBuildVm', async () => {
    const onBuildVm = vi.fn()
    const { rerender } = render(<CategoryCards query={stubQuery({ data: summary })} value="weak" onChange={() => undefined} />)
    expect(screen.queryByText('Виртуализация')).not.toBeInTheDocument()
    rerender(<CategoryCards query={stubQuery({ data: summary })} value="weak" onChange={() => undefined} onBuildVm={onBuildVm} />)
    await userEvent.click(screen.getByRole('button', { name: /Виртуализация/ }))
    expect(onBuildVm).toHaveBeenCalledOnce()
  })

  it('пока сводки нет — скелетоны, а не карточки', () => {
    const { container } = render(<CategoryCards query={stubQuery()} value="weak" onChange={() => undefined} />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(4)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо вечных скелетонов; клик перезапрашивает', async () => {
    const refetch = vi.fn()
    const { container } = render(
      <CategoryCards
        query={stubQuery({ isError: true, error: new Error('Сервер недоступен'), refetch })}
        value="weak"
        onChange={() => undefined}
      />,
    )
    expect(screen.getByText('Не удалось загрузить категории')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(refetch).toHaveBeenCalledOnce()
  })
})

describe('CategoryCards: сборка по запросу', () => {
  it('карточка сборки показывается только с onOrderBuild и вызывает его', async () => {
    const onOrderBuild = vi.fn()
    const { rerender } = render(<CategoryCards query={stubQuery({ data: summary })} value="weak" onChange={() => undefined} />)
    expect(screen.queryByText('Сборка по запросу')).not.toBeInTheDocument()
    rerender(<CategoryCards query={stubQuery({ data: summary })} value="weak" onChange={() => undefined} onOrderBuild={onOrderBuild} />)
    await userEvent.click(screen.getByRole('button', { name: /Сборка по запросу/ }))
    expect(onOrderBuild).toHaveBeenCalledOnce()
  })
})
