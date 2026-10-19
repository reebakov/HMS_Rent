import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DateRange, DepartmentOptions, SearchInput, Select } from './input'

describe('SearchInput', () => {
  it('поле найдено по подписи, показывает значение и подсказку', () => {
    render(<SearchInput label="Поиск по журналу" placeholder="ПК, имя или ник…" value="pc" onChange={() => undefined} />)
    const input = screen.getByRole('textbox', { name: 'Поиск по журналу' })
    expect(input).toHaveValue('pc')
    expect(input).toHaveAttribute('placeholder', 'ПК, имя или ник…')
  })

  it('отдаёт введённый текст строкой', async () => {
    const onChange = vi.fn()
    function Controlled() {
      const [value, setValue] = useState('')
      return <SearchInput label="Поиск" placeholder="…" value={value} onChange={(v) => { setValue(v); onChange(v) }} />
    }
    render(<Controlled />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Поиск' }), 'ab')
    expect(onChange).toHaveBeenLastCalledWith('ab')
  })

  it('className задаёт ширину обёртки', () => {
    const { container } = render(<SearchInput className="sm:w-64" label="Поиск" placeholder="…" value="" onChange={() => undefined} />)
    expect(container.firstElementChild).toHaveClass('w-full', 'sm:w-64')
  })
})

describe('DateRange', () => {
  it('поля доступны по подписям «Дата с» и «Дата по» и показывают значения', () => {
    render(<DateRange from="2026-01-05" to="2026-02-01" onChange={() => undefined} />)
    expect(screen.getByLabelText('Дата с')).toHaveValue('2026-01-05')
    expect(screen.getByLabelText('Дата по')).toHaveValue('2026-02-01')
  })

  it('без значений поля пустые', () => {
    render(<DateRange onChange={() => undefined} />)
    expect(screen.getByLabelText('Дата с')).toHaveValue('')
    expect(screen.getByLabelText('Дата по')).toHaveValue('')
  })

  it.each([
    ['Дата с', 'date_from'],
    ['Дата по', 'date_to'],
  ])('«%s» меняет только %s', async (label, key) => {
    const onChange = vi.fn()
    render(<DateRange onChange={onChange} />)
    await userEvent.type(screen.getByLabelText(label), '2026-03-04')
    expect(onChange).toHaveBeenLastCalledWith({ [key]: '2026-03-04' })
  })

  it('очищенное поле даёт undefined', async () => {
    const onChange = vi.fn()
    render(<DateRange from="2026-01-05" onChange={onChange} />)
    await userEvent.clear(screen.getByLabelText('Дата с'))
    expect(onChange).toHaveBeenLastCalledWith({ date_from: undefined })
  })
})

describe('DepartmentOptions', () => {
  const departments = [
    { id: 1, name: 'Разработка', code: null, head_name: null, is_active: true },
    { id: 2, name: 'Дизайн', code: null, head_name: null, is_active: true },
  ]

  it('по опции на отдел после опции вызывающего', () => {
    render(
      <Select aria-label="Отдел">
        <option value="">Все отделы</option>
        <DepartmentOptions departments={departments} />
      </Select>,
    )
    expect(screen.getAllByRole('option').map((o) => [o.textContent, (o as HTMLOptionElement).value])).toEqual([
      ['Все отделы', ''],
      ['Разработка', '1'],
      ['Дизайн', '2'],
    ])
  })

  it('пока отделы не загружены — только опция вызывающего', () => {
    render(
      <Select aria-label="Отдел">
        <option value="">Все отделы</option>
        <DepartmentOptions departments={undefined} />
      </Select>,
    )
    expect(screen.getAllByRole('option')).toHaveLength(1)
  })
})
