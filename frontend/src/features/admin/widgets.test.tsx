import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BarList, EventTimeline, StatCard } from './widgets'
import type { AssetEvent } from '@/lib/types'

const makeEvent = (over: Partial<AssetEvent> = {}): AssetEvent => ({
  id: 1, computer: { id: 10, name: 'PC-010' }, booking_id: null, event_type: 'booked',
  from_status: null, to_status: null, message: 'Сообщение', actor: null,
  created_at: '2024-03-01T10:00:00Z', ...over,
})

describe('EventTimeline', () => {
  it('пустой список — «Событий пока нет»', () => {
    render(<EventTimeline events={[]} />)
    expect(screen.getByText('Событий пока нет')).toBeInTheDocument()
  })

  it('показывает имя ПК, русскую подпись типа, сообщение и «система» без автора', () => {
    render(<EventTimeline events={[makeEvent({ event_type: 'insight_status_changed', message: 'Статус изменился' })]} />)
    expect(screen.getByText(/PC-010 ·/)).toBeInTheDocument()
    expect(screen.getByText('Статус в Insight')).toBeInTheDocument()
    expect(screen.getByText('Статус изменился')).toBeInTheDocument()
    expect(screen.getByText(/· система/)).toBeInTheDocument()
  })

  it('showComputer=false скрывает имя ПК; автор выводится по display_name', () => {
    const actor = { id: 1, display_name: 'Админ', username: 'adm' } as never
    render(<EventTimeline showComputer={false} events={[makeEvent({ actor })]} />)
    expect(screen.queryByText(/PC-010/)).not.toBeInTheDocument()
    expect(screen.getByText(/· Админ/)).toBeInTheDocument()
  })

  it('неизвестный тип события выводится как есть, а иконка — как у admin_update', () => {
    render(<EventTimeline events={[makeEvent({ event_type: 'something_new' })]} />)
    expect(screen.getByText('something_new')).toBeInTheDocument()
  })

  it('рисует событие на каждый элемент, в порядке переданного списка', () => {
    render(<EventTimeline events={[makeEvent({ id: 1, message: 'первое' }), makeEvent({ id: 2, message: 'второе' })]} />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('первое')
    expect(items[1]).toHaveTextContent('второе')
  })
})

describe('BarList', () => {
  it('ширина полосок считается от максимума; hint заменяет число', () => {
    const { container } = render(
      <BarList items={[{ label: 'Слабые', value: 5 }, { label: 'Мощные', value: 20, hint: '20 шт.' }]} />,
    )
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('20 шт.')).toBeInTheDocument()
    const bars = container.querySelectorAll<HTMLElement>('[style]')
    expect(bars[0].style.width).toBe('25%')
    expect(bars[1].style.width).toBe('100%')
  })

  it('пустой список и нулевые значения не дают деления на ноль', () => {
    const { container } = render(<BarList items={[{ label: 'Пусто', value: 0 }]} />)
    expect(container.querySelector<HTMLElement>('[style]')!.style.width).toBe('0%')
  })
})

describe('StatCard', () => {
  it('подпись, значение и подсказка', () => {
    render(<StatCard label="Свободно" value={12} hint="из 40" tone="success" />)
    expect(screen.getByText('Свободно')).toBeInTheDocument()
    expect(screen.getByText('12').className).toContain('text-success')
    expect(screen.getByText('из 40')).toBeInTheDocument()
  })

  it('без подсказки и с тоном по умолчанию', () => {
    render(<StatCard label="Всего" value="—" />)
    expect(screen.getByText('—').className).toContain('text-foreground')
  })
})
