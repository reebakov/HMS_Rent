import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VmSizesEditor } from './VmSizesEditor'
import type { VmSize } from '@/lib/types'

const S: VmSize = { label: 'S', cpu: 2, ram_gb: 4, disk_gb: 50 }
const M: VmSize = { label: 'M', cpu: 4, ram_gb: 8, disk_gb: 100 }

const setup = (value: VmSize[] = [S, M]) => {
  const onChange = vi.fn()
  render(<VmSizesEditor value={value} onChange={onChange} />)
  return { onChange, user: userEvent.setup() }
}

describe('VmSizesEditor', () => {
  it('показывает размеры построчно', () => {
    setup()
    expect(screen.getByLabelText('Название размера, строка 1')).toHaveValue('S')
    expect(screen.getByLabelText('Ядра, строка 2')).toHaveValue(4)
    expect(screen.getByLabelText('Память, ГБ, строка 2')).toHaveValue(8)
    expect(screen.getByLabelText('Диск, ГБ, строка 1')).toHaveValue(50)
  })

  it('правка числа меняет только своё поле своей строки', () => {
    const { onChange } = setup()
    fireEvent.change(screen.getByLabelText('Память, ГБ, строка 2'), { target: { value: '12' } })
    expect(onChange).toHaveBeenCalledWith([S, { ...M, ram_gb: 12 }])
  })

  it('правка названия', () => {
    const { onChange } = setup()
    fireEvent.change(screen.getByLabelText('Название размера, строка 1'), { target: { value: 'Мини' } })
    expect(onChange).toHaveBeenCalledWith([{ ...S, label: 'Мини' }, M])
  })

  it('«Добавить размер» добавляет строку с базовыми значениями', async () => {
    const { onChange, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Добавить размер' }))
    expect(onChange).toHaveBeenCalledWith([S, M, { label: 'Размер 3', cpu: 2, ram_gb: 4, disk_gb: 50 }])
  })

  it('«Удалить» убирает строку', async () => {
    const { onChange, user } = setup()
    await user.click(screen.getAllByTitle('Удалить')[0])
    expect(onChange).toHaveBeenCalledWith([M])
  })
})
