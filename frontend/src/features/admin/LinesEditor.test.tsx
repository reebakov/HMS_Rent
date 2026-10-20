import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { LinesEditor, cleanLines } from './LinesEditor'

describe('LinesEditor', () => {
  it('показывает список по строке и отдаёт строки как есть, с пустыми — их убирает cleanLines при сохранении', () => {
    const onChange = vi.fn()
    render(<LinesEditor label="ОС" value={['Ubuntu', 'Debian']} onChange={onChange} />)
    const area = screen.getByLabelText('ОС')
    expect(area).toHaveValue('Ubuntu\nDebian')
    fireEvent.change(area, { target: { value: 'Ubuntu\n\nDebian\n' } })
    expect(onChange).toHaveBeenCalledWith(['Ubuntu', '', 'Debian', ''])
  })

  it('cleanLines обрезает пробелы и убирает пустые строки', () => {
    expect(cleanLines(['  Ubuntu ', '', '   ', 'Debian'])).toEqual(['Ubuntu', 'Debian'])
  })
})
