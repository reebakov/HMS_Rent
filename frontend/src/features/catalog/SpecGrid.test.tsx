import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { InsightAttributes, Location, SpecGrid } from './SpecGrid'
import { makeComputer } from '@/test/helpers'

/** Значение под подписью характеристики */
const valueOf = (label: string) => screen.getByText(label).nextElementSibling as HTMLElement

describe('SpecGrid', () => {
  it('показывает процессор с ядрами, память, диск и видеокарту', () => {
    render(<SpecGrid computer={makeComputer({ gpu: 'RTX 4070' })} />)
    expect(valueOf('Процессор')).toHaveTextContent('Intel Core i5 · 6 ядер')
    expect(valueOf('Память')).toHaveTextContent('16 ГБ')
    expect(valueOf('Диск')).toHaveTextContent('SSD 512 ГБ')
    expect(valueOf('Видеокарта')).toHaveTextContent('RTX 4070')
  })

  it('полное значение доступно в подсказке (title) для обрезанного текста', () => {
    render(<SpecGrid computer={makeComputer({ gpu: 'RTX 4070' })} />)
    expect(valueOf('Процессор')).toHaveAttribute('title', 'Intel Core i5 · 6 ядер')
    expect(valueOf('Видеокарта')).toHaveAttribute('title', 'RTX 4070')
  })

  it('процессор без числа ядер — только модель', () => {
    render(<SpecGrid computer={makeComputer({ cpu_cores: null })} />)
    expect(valueOf('Процессор')).toHaveTextContent(/^Intel Core i5$/)
  })

  it('неизвестные характеристики — прочерки без подсказки', () => {
    render(<SpecGrid computer={makeComputer({ cpu: null, ram_gb: null, storage: null, gpu: null })} />)
    for (const label of ['Процессор', 'Память', 'Диск', 'Видеокарта']) {
      expect(valueOf(label)).toHaveTextContent(/^—$/)
      expect(valueOf(label)).not.toHaveAttribute('title')
    }
  })

  it('ram_gb = 0 считается неизвестной памятью', () => {
    render(<SpecGrid computer={makeComputer({ ram_gb: 0 })} />)
    expect(valueOf('Память')).toHaveTextContent(/^—$/)
  })

  it('у виртуалки без видеокарты — «Виртуальный адаптер», у физического ПК — прочерк', () => {
    const { unmount } = render(<SpecGrid computer={makeComputer({ is_virtual: true, gpu: null })} />)
    expect(valueOf('Видеокарта')).toHaveTextContent('Виртуальный адаптер')
    unmount()
    render(<SpecGrid computer={makeComputer({ is_virtual: false, gpu: null })} />)
    expect(valueOf('Видеокарта')).toHaveTextContent(/^—$/)
  })

  it('реальная видеокарта виртуалки важнее заглушки', () => {
    render(<SpecGrid computer={makeComputer({ is_virtual: true, gpu: 'vGPU 8Q' })} />)
    expect(valueOf('Видеокарта')).toHaveTextContent('vGPU 8Q')
  })

  it('className добавляется к сетке', () => {
    const { container } = render(<SpecGrid computer={makeComputer()} className="mt-4" />)
    expect(container.firstElementChild).toHaveClass('grid', 'mt-4')
  })
})

describe('Location', () => {
  it('показывает расположение', () => {
    render(<Location value="Офис, 3 этаж" />)
    expect(screen.getByText('Офис, 3 этаж')).toBeInTheDocument()
  })

  it.each([[null], ['']])('пустое значение (%j) — ничего не рисует', (value) => {
    const { container } = render(<Location value={value} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('InsightAttributes', () => {
  it('показывает каждый атрибут: ключ и значение', () => {
    render(<InsightAttributes attributes={{ Hostname: 'PC-001', 'Инв. номер': '42' }} />)
    expect(screen.getByText('Hostname').nextElementSibling).toHaveTextContent('PC-001')
    expect(screen.getByText('Инв. номер').nextElementSibling).toHaveTextContent('42')
  })

  it('без атрибутов — пустой список', () => {
    const { container } = render(<InsightAttributes attributes={{}} />)
    expect(container.firstElementChild).toBeEmptyDOMElement()
  })
})
