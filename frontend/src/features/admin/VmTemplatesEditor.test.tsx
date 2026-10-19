import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { VmTemplatesEditor } from './VmTemplatesEditor'
import type { VmTemplate } from '@/lib/types'

const win: VmTemplate = { key: 'win11', label: 'Windows 11', os: 'windows', template: 'Template_Win11', customization_spec: 'spec-win', min_disk_gb: 80, enabled: true }
const lin: VmTemplate = { key: 'ubuntu', label: 'Ubuntu 24.04', os: 'linux', template: '', customization_spec: '', min_disk_gb: 40, enabled: false }

const row = (i: number) => screen.getAllByRole('row')[i + 1] // 0 — заголовок

/** Последний вызов onChange */
const last = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls[fn.mock.calls.length - 1][0] as VmTemplate[]

function setup(value: VmTemplate[] = [win, lin]) {
  const onChange = vi.fn()
  render(<VmTemplatesEditor value={value} onChange={onChange} />)
  return onChange
}

/** Редактор с состоянием — для проверки набора текста по символам */
function Stateful({ initial, spy }: { initial: VmTemplate[]; spy: (v: VmTemplate[]) => void }) {
  const [v, setV] = useState(initial)
  return <VmTemplatesEditor value={v} onChange={(n) => { spy(n); setV(n) }} />
}

describe('VmTemplatesEditor: отображение', () => {
  it('поля каждой строки подписаны номером строки', () => {
    setup()
    expect(screen.getByRole('textbox', { name: 'Название, строка 1' })).toHaveValue('Windows 11')
    expect(screen.getByRole('textbox', { name: 'Ключ, строка 2' })).toHaveValue('ubuntu')
    expect(screen.getByRole('combobox', { name: 'Тип, строка 1' })).toHaveValue('windows')
    expect(screen.getByRole('textbox', { name: 'Шаблон в vCenter, строка 1' })).toHaveValue('Template_Win11')
    expect(screen.getByRole('textbox', { name: 'Спецификация, строка 1' })).toHaveValue('spec-win')
    expect(screen.getByRole('spinbutton', { name: 'Диск от, ГБ, строка 1' })).toHaveValue(80)
    expect(screen.getByRole('checkbox', { name: 'Включена, строка 1' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Включена, строка 2' })).not.toBeChecked()
  })

  it('рисует строку на каждый шаблон со всеми полями', () => {
    setup()
    expect(screen.getAllByRole('row')).toHaveLength(3)
    const r0 = within(row(0))
    expect(r0.getByDisplayValue('Windows 11')).toBeInTheDocument()
    expect(r0.getByDisplayValue('win11')).toBeInTheDocument()
    expect(r0.getByRole('combobox')).toHaveValue('windows')
    expect(r0.getByDisplayValue('Template_Win11')).toBeInTheDocument()
    expect(r0.getByDisplayValue('spec-win')).toBeInTheDocument()
    expect(r0.getByRole('spinbutton')).toHaveValue(80)
    expect(r0.getByRole('checkbox')).toBeChecked()

    const r1 = within(row(1))
    expect(r1.getByRole('combobox')).toHaveValue('linux')
    expect(r1.getByPlaceholderText('например Template_Win11')).toHaveValue('')
    expect(r1.getByRole('checkbox')).not.toBeChecked()
  })

  it('пустой список — только заголовок и кнопка «Добавить ОС»', () => {
    setup([])
    expect(screen.getAllByRole('row')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Добавить ОС' })).toBeInTheDocument()
  })

  it('тип ОС: два варианта Windows и Linux', () => {
    setup([win])
    expect(within(row(0)).getAllByRole('option').map((o) => o.textContent)).toEqual(['Windows', 'Linux'])
  })
})

describe('VmTemplatesEditor: правка полей', () => {
  it('название: onChange получает тот же список с изменённой подписью, остальные поля и строки целы', () => {
    const onChange = setup()
    fireEvent.change(within(row(0)).getByDisplayValue('Windows 11'), { target: { value: 'Windows 11 Pro' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(last(onChange)).toEqual([{ ...win, label: 'Windows 11 Pro' }, lin])
  })

  it('ключ приводится к нижнему регистру', () => {
    const onChange = setup()
    fireEvent.change(within(row(1)).getByDisplayValue('ubuntu'), { target: { value: 'UbuntuLTS' } })
    expect(last(onChange)[1]).toEqual({ ...lin, key: 'ubuntults' })
  })

  it('тип ОС переключается на linux и обратно на windows', () => {
    const onChange = setup()
    fireEvent.change(within(row(0)).getByRole('combobox'), { target: { value: 'linux' } })
    expect(last(onChange)[0]).toEqual({ ...win, os: 'linux' })
    fireEvent.change(within(row(1)).getByRole('combobox'), { target: { value: 'windows' } })
    expect(last(onChange)[1]).toEqual({ ...lin, os: 'windows' })
  })

  it('имя шаблона в vCenter и спецификация правятся независимо', () => {
    const onChange = setup()
    fireEvent.change(within(row(1)).getByPlaceholderText('например Template_Win11'), { target: { value: 'Template_Ubuntu' } })
    expect(last(onChange)[1]).toEqual({ ...lin, template: 'Template_Ubuntu' })
    fireEvent.change(within(row(0)).getByDisplayValue('spec-win'), { target: { value: '' } })
    expect(last(onChange)[0]).toEqual({ ...win, customization_spec: '' })
  })

  it('минимальный диск уходит числом, а не строкой', () => {
    const onChange = setup()
    fireEvent.change(within(row(0)).getByRole('spinbutton'), { target: { value: '120' } })
    expect(last(onChange)[0].min_disk_gb).toBe(120)
  })

  it('чекбокс «Вкл.» включает и выключает шаблон', async () => {
    const user = userEvent.setup()
    const onChange = setup()
    await user.click(within(row(1)).getByRole('checkbox'))
    expect(last(onChange)[1]).toEqual({ ...lin, enabled: true })
    await user.click(within(row(0)).getByRole('checkbox'))
    expect(last(onChange)[0]).toEqual({ ...win, enabled: false })
  })

  it('набор текста по символам накапливается в значении', async () => {
    const user = userEvent.setup()
    const spy = vi.fn()
    render(<Stateful initial={[lin]} spy={spy} />)
    await user.type(within(row(0)).getByPlaceholderText('например Template_Win11'), 'Tpl')
    expect(spy.mock.calls[spy.mock.calls.length - 1][0][0].template).toBe('Tpl')
    expect(within(row(0)).getByDisplayValue('Tpl')).toBeInTheDocument()
  })

  it('пустое значение диска превращается в 0 (границы проверяет бэкенд)', () => {
    const onChange = setup()
    fireEvent.change(within(row(0)).getByRole('spinbutton'), { target: { value: '' } })
    expect(last(onChange)[0].min_disk_gb).toBe(0)
  })
})

describe('VmTemplatesEditor: добавление и удаление', () => {
  it('«Добавить ОС» дописывает шаблон-заготовку: ключ osN по числу строк, включён, без имени шаблона', async () => {
    const onChange = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить ОС' }))
    expect(last(onChange)).toEqual([
      win, lin,
      { key: 'os3', label: 'Новая ОС', os: 'windows', template: '', customization_spec: '', min_disk_gb: 50, enabled: true },
    ])
  })

  it('добавление в пустой список даёт ключ os1', async () => {
    const onChange = setup([])
    await userEvent.click(screen.getByRole('button', { name: 'Добавить ОС' }))
    expect(last(onChange)).toHaveLength(1)
    expect(last(onChange)[0].key).toBe('os1')
  })

  it('«Удалить» убирает именно свою строку', async () => {
    const onChange = setup()
    await userEvent.click(within(row(0)).getByTitle('Удалить'))
    expect(last(onChange)).toEqual([lin])
  })

  it('удаление последней строки даёт пустой список', async () => {
    const onChange = setup([win])
    await userEvent.click(within(row(0)).getByTitle('Удалить'))
    expect(last(onChange)).toEqual([])
  })

  it('исходный массив value не мутируется', async () => {
    const value = [{ ...win }, { ...lin }]
    const snapshot = JSON.parse(JSON.stringify(value))
    setup(value)
    fireEvent.change(within(row(0)).getByDisplayValue('Windows 11'), { target: { value: 'X' } })
    await userEvent.click(within(row(1)).getByTitle('Удалить'))
    expect(value).toEqual(snapshot)
  })
})
