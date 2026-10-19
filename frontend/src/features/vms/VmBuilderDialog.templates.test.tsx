import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VmBuilderDialog } from './VmBuilderDialog'
import { api } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { VmOptions, VmTemplateOption } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => makeSession() }))

const win10: VmTemplateOption = { key: 'win10', label: 'Windows 10', os: 'windows', min_disk_gb: 50, available: true }
const win11: VmTemplateOption = { key: 'win11', label: 'Windows 11', os: 'windows', min_disk_gb: 100, available: true }
const ubuntu: VmTemplateOption = { key: 'ubuntu', label: 'Ubuntu 22.04', os: 'linux', min_disk_gb: 30, available: false }

const makeOptions = (templates: VmTemplateOption[], over: Partial<VmOptions> = {}): VmOptions => ({
  enabled: true,
  reason: null,
  name_prefix: 'rent-',
  template: 'win10',
  min_cpu: 2,
  max_cpu: 8,
  min_ram_gb: 4,
  max_ram_gb: 16,
  min_disk_gb: 40,
  max_disk_gb: 200,
  max_per_user: 3,
  used_by_me: 0,
  templates,
  ...over,
})

let options: VmOptions

async function setup() {
  renderWithProviders(<VmBuilderDialog open onClose={vi.fn()} />)
  await screen.findByRole('option', { name: 'Аналитика' })
  // начальное состояние (шаблон, диск, имя) выставляет эффект после загрузки /vms/options, а порядок ответов
  // опций и отделов не гарантирован: ждём результат эффекта, иначе слайдер можно прочитать до него
  await screen.findByDisplayValue('Иван Иванов')
  return userEvent.setup()
}

const osButton = (label: string) => screen.getByRole('button', { name: new RegExp(label) })
const diskSlider = () => screen.getAllByRole('slider')[2] as HTMLInputElement
const submit = () => screen.getByRole('button', { name: 'Создать' })
const description = (text: string) => screen.getByText(text, { exact: false })

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Имя виртуалки/), 'design-01')
  await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
}

beforeEach(() => {
  options = makeOptions([win10, win11, ubuntu])
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/vms/options') return options
    if (path === '/departments')
      return [
        { id: 1, name: 'Разработка', code: 'DEV', head_name: null, is_active: true },
        { id: 2, name: 'Аналитика', code: 'AN', head_name: null, is_active: true },
      ]
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({ id: 5, order_number: 77, name: 'rent-design-01' })
})

describe('VmBuilderDialog: выбор ОС', () => {
  it('рисует все шаблоны: доступные с минимальным диском, недоступные — «скоро» и отключены', async () => {
    await setup()
    expect(screen.getByText('Операционная система')).toBeInTheDocument()
    expect(osButton('Windows 10')).toHaveTextContent('диск от 50 ГБ')
    expect(osButton('Windows 10')).toBeEnabled()
    expect(osButton('Windows 11')).toHaveTextContent('диск от 100 ГБ')
    expect(osButton('Ubuntu 22.04')).toHaveTextContent('скоро')
    expect(osButton('Ubuntu 22.04')).not.toHaveTextContent('диск от')
    expect(osButton('Ubuntu 22.04')).toBeDisabled()
  })

  it('по умолчанию выбран первый доступный шаблон, недоступный в начале списка пропускается', async () => {
    options = makeOptions([ubuntu, win11, win10])
    await setup()
    expect(osButton('Windows 11')).toHaveClass('border-primary')
    expect(osButton('Windows 10')).not.toHaveClass('border-primary')
    expect(osButton('Ubuntu 22.04')).not.toHaveClass('border-primary')
    expect(description('будет создана на Windows 11')).toBeInTheDocument()
  })

  it('клик по другому доступному шаблону переключает выбор и описание', async () => {
    const user = await setup()
    expect(description('будет создана на Windows 10')).toBeInTheDocument()
    await user.click(osButton('Windows 11'))
    expect(osButton('Windows 11')).toHaveClass('border-primary')
    expect(osButton('Windows 10')).not.toHaveClass('border-primary')
    expect(description('будет создана на Windows 11')).toBeInTheDocument()
  })

  it('шаблон «скоро» не выбирается кликом', async () => {
    const user = await setup()
    await user.click(osButton('Ubuntu 22.04'))
    expect(osButton('Ubuntu 22.04')).not.toHaveClass('border-primary')
    expect(osButton('Windows 10')).toHaveClass('border-primary')
    expect(description('будет создана на Windows 10')).toBeInTheDocument()
  })

  it('нет доступных шаблонов — выбора нет, описание нейтральное, создать нельзя', async () => {
    options = makeOptions([{ ...ubuntu }, { ...win10, available: false }])
    const user = await setup()
    expect(screen.getByText('Выберите операционную систему и ресурсы')).toBeInTheDocument()
    expect(osButton('Ubuntu 22.04')).toBeDisabled()
    expect(osButton('Windows 10')).toBeDisabled()
    await fillValid(user)
    expect(submit()).toBeDisabled()
  })

  it('пустой список шаблонов — создать нельзя', async () => {
    options = makeOptions([])
    const user = await setup()
    expect(screen.queryByText('Операционная система')).toBeInTheDocument()
    await fillValid(user)
    expect(submit()).toBeDisabled()
  })
})

describe('VmBuilderDialog: минимальный диск от шаблона', () => {
  it('шаблон строже общего лимита — слайдер стартует с минимума шаблона', async () => {
    options = makeOptions([win11], { min_disk_gb: 40 })
    await setup()
    expect([diskSlider().min, diskSlider().max, diskSlider().value]).toEqual(['100', '200', '100'])
  })

  it('шаблон мягче общего лимита — действует общий минимум', async () => {
    options = makeOptions([{ ...win10, min_disk_gb: 20 }], { min_disk_gb: 40 })
    await setup()
    expect([diskSlider().min, diskSlider().value]).toEqual(['40', '40'])
  })

  it('смена шаблона пересчитывает минимум и поднимает значение диска', async () => {
    const user = await setup()
    expect([diskSlider().min, diskSlider().value]).toEqual(['50', '50'])
    await user.click(osButton('Windows 11'))
    expect([diskSlider().min, diskSlider().value]).toEqual(['100', '100'])
    expect(screen.getByText('100', { selector: 'span.tabular' })).toBeInTheDocument()
  })

  it('выбранный пользователем диск выше минимума нового шаблона сохраняется', async () => {
    const user = await setup()
    fireEvent.change(diskSlider(), { target: { value: '150' } })
    await user.click(osButton('Windows 11'))
    expect(diskSlider().value).toBe('150')
  })

  it('на отправку уходит диск не меньше минимума шаблона', async () => {
    const user = await setup()
    fireEvent.change(diskSlider(), { target: { value: '60' } })
    await user.click(osButton('Windows 11'))
    await fillValid(user)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ template_key: 'win11', disk_gb: 100 })
  })
})

describe('VmBuilderDialog: отправка с шаблоном', () => {
  it('по умолчанию уходит template_key первого доступного шаблона', async () => {
    options = makeOptions([ubuntu, win10, win11])
    const user = await setup()
    await fillValid(user)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/vms', expect.objectContaining({ template_key: 'win10', disk_gb: 50 }))
  })

  it('уходит template_key выбранного шаблона', async () => {
    const user = await setup()
    await user.click(osButton('Windows 11'))
    await fillValid(user)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/vms', expect.objectContaining({ template_key: 'win11' }))
  })
})
