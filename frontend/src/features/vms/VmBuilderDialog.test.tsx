import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { VmBuilderDialog } from './VmBuilderDialog'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, makeSession, renderWithProviders } from '@/test/helpers'
import { termLimit } from '@/features/booking/TermLimit'
import { addDays, formatDate, todayLocal } from '@/lib/utils'
import type { VmOptions, VmTemplateOption } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let session = makeSession({ role: 'admin' })
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => session }))

const departments = [
  { id: 1, name: 'Разработка', code: 'DEV', head_name: null, is_active: true },
  { id: 2, name: 'Аналитика', code: 'AN', head_name: null, is_active: true },
]

const makeOptions = (over: Partial<VmOptions> = {}): VmOptions => ({
  enabled: true,
  reason: null,
  template: 'win10-tpl',
  min_cpu: 2,
  max_cpu: 8,
  min_ram_gb: 4,
  max_ram_gb: 16,
  min_disk_gb: 50,
  max_disk_gb: 200,
  max_per_user: 3,
  used_by_me: 1,
  templates: [{ key: 'win10-tpl', label: 'Windows 10', os: 'windows', min_disk_gb: 50, available: true }],
  sizes: [],
  ...over,
})

const win10: VmTemplateOption = { key: 'win10', label: 'Windows 10', os: 'windows', min_disk_gb: 50, available: true }
const win11: VmTemplateOption = { key: 'win11', label: 'Windows 11', os: 'windows', min_disk_gb: 100, available: true }
const ubuntu: VmTemplateOption = { key: 'ubuntu', label: 'Ubuntu 22.04', os: 'linux', min_disk_gb: 30, available: false }

/** Настройки для блоков про шаблоны ОС: свой набор шаблонов, диск по умолчанию 40, ВМ у пользователя нет */
const makeTemplateOptions = (templates: VmTemplateOption[], over: Partial<VmOptions> = {}): VmOptions =>
  makeOptions({ template: 'win10', min_disk_gb: 40, used_by_me: 0, templates, ...over })

let options: VmOptions

const Where = () => <span data-testid="path">{useLocation().pathname}</span>

/** Начальное состояние формы (шаблон, ползунки, имя) выставляет эффект после загрузки /vms/options, а порядок ответов
 * опций и отделов не гарантирован: ждём результат эффекта (имя из сессии), иначе ползунки можно прочитать до него */
async function setup(onClose = vi.fn()) {
  renderWithProviders(<><VmBuilderDialog open onClose={onClose} /><Where /></>, { route: '/' })
  await screen.findAllByText('Аналитика')
  await waitFor(() => expect(screen.getByLabelText(/Имя и фамилия/)).toHaveValue(session.user.display_name))
  return { onClose, user: userEvent.setup() }
}

const submit = () => screen.getByRole('button', { name: 'Создать' })
const sliders = () => screen.getAllByRole('slider') as HTMLInputElement[] // ядра, память, диск
const autoNameHint = () => screen.getByText(/назначается автоматически/)

const UNTIL = '2099-12-31'
const untilInput = () => screen.getByLabelText(/Вернуть до/)

/** Заполняет минимум, чтобы форма стала валидной (срок обязателен) */
async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
  await user.type(untilInput(), UNTIL)
}

beforeEach(() => {
  session = makeSession({ role: 'admin' })
  options = makeOptions()
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/vms/options') return options
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({ id: 5, order_number: 77, name: 'A1001' })
})

describe('VmBuilderDialog', () => {
  it('закрытый диалог ничего не рисует и не запрашивает настройки', () => {
    renderWithProviders(<VmBuilderDialog open={false} onClose={() => undefined} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith('/vms/options')
  })

  it('пока настройки грузятся — «Загрузка…» и кнопка «Создать» отключена', () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => undefined))
    renderWithProviders(<VmBuilderDialog open onClose={() => undefined} />)
    expect(screen.getByText('Загрузка…')).toBeInTheDocument()
    expect(submit()).toBeDisabled()
  })

  it('ошибка загрузки настроек: текст ошибки и «Повторить» вместо вечной «Загрузки…»; повтор показывает форму', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/vms/options')
    renderWithProviders(<VmBuilderDialog open onClose={() => undefined} />)
    expect(await screen.findByText('Не удалось загрузить параметры конструктора')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Загрузка…')).not.toBeInTheDocument()
    expect(submit()).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText(/назначается автоматически/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ошибка загрузки отделов: сообщение и «Повторить» вместо пустого списка; повтор подгружает отделы', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/departments')
    renderWithProviders(<VmBuilderDialog open onClose={() => undefined} />)
    expect(await screen.findByText('Не удалось загрузить отделы')).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Аналитика' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('option', { name: 'Аналитика' })).toBeInTheDocument()
    expect(screen.queryByText('Не удалось загрузить отделы')).not.toBeInTheDocument()
  })

  it('отключённый конструктор показывает причину и не даёт создать', async () => {
    options = makeOptions({ enabled: false, reason: 'vSphere не настроен администратором' })
    renderWithProviders(<VmBuilderDialog open onClose={() => undefined} />)
    expect(await screen.findByText('vSphere не настроен администратором')).toBeInTheDocument()
    expect(screen.queryByText(/назначается автоматически/)).not.toBeInTheDocument()
    expect(submit()).toBeDisabled()
  })

  it('подставляет значения по умолчанию: минимумы лимитов, имя и ник из сессии', async () => {
    session = makeSession({ role: 'admin', username: 'i.ivanov@corp.example', department_id: 2 })
    await setup()
    expect(screen.getByRole('dialog', { name: 'Конструктор виртуалки' })).toBeInTheDocument()
    expect(sliders().map((s) => s.value)).toEqual(['2', '4', '50'])
    // ползунки доступны по имени
    expect(screen.getByRole('slider', { name: 'Ядра' })).toHaveValue('2')
    expect(screen.getByRole('slider', { name: 'Память' })).toHaveValue('4')
    expect(screen.getByRole('slider', { name: 'Диск' })).toHaveValue('50')
    expect(screen.getByLabelText(/Имя и фамилия/)).toHaveValue('Иван Иванов')
    // ник — часть логина до «@»
    expect(screen.getByLabelText(/Ник/)).toHaveValue('i.ivanov')
    // отдел из профиля
    expect(screen.getByLabelText(/Отдел/)).toHaveValue('2')
  })

  it('сотрудник оформляет на свой отдел и не выбирает его', async () => {
    session = makeSession({ department_id: 2 })
    await setup()
    expect(screen.queryByLabelText(/Отдел/)).not.toBeInTheDocument()
    expect(screen.getByText('Аналитика')).toBeInTheDocument()
    await userEvent.setup().type(untilInput(), UNTIL)
    expect(submit()).toBeEnabled()
  })

  it('сотрудник без отдела не может оформить заказ', async () => {
    session = makeSession()
    renderWithProviders(<VmBuilderDialog open onClose={vi.fn()} />, { route: '/' })
    expect(await screen.findByText(/Вам не назначен отдел/)).toBeInTheDocument()
    await userEvent.setup().type(await waitFor(() => untilInput()), UNTIL)
    expect(submit()).toBeDisabled()
  })

  it('отдел берётся из localStorage, если в профиле его нет', async () => {
    localStorage.setItem('hmsrent:last-department', '1')
    await setup()
    expect(screen.getByLabelText(/Отдел/)).toHaveValue('1')
  })

  it('ползунки ограничены лимитами из настроек', async () => {
    options = makeOptions({ 
      min_cpu: 1, max_cpu: 4, min_ram_gb: 2, max_ram_gb: 8, min_disk_gb: 30, max_disk_gb: 100,
      templates: [{ key: 'win10-tpl', label: 'Windows 10', os: 'windows', min_disk_gb: 30, available: true }]
    })
    await setup()
    const [cpu, ram, disk] = sliders()
    expect([cpu.min, cpu.max, cpu.step]).toEqual(['1', '4', '1'])
    expect([ram.min, ram.max, ram.step]).toEqual(['2', '8', '2'])
    expect([disk.min, disk.max, disk.step]).toEqual(['30', '100', '10'])
    // стартовые значения — минимумы
    expect([cpu.value, ram.value, disk.value]).toEqual(['1', '2', '30'])
  })

  it('имя ВМ не вводится: подсказка про номер из Insight и счётчик занятых ВМ', async () => {
    await setup()
    expect(autoNameHint()).toHaveTextContent('Имя виртуалки (A1…) назначается автоматически')
    expect(screen.queryByLabelText(/Имя виртуалки/)).not.toBeInTheDocument()
    expect(screen.getByText(/Занято виртуалок: 1 из 3/)).toBeInTheDocument()
  })

  describe('отправка', () => {
    it('шлёт выбранные параметры, показывает toast, закрывает окно и ведёт в «Мою аренду»', async () => {
      const { onClose, user } = await setup()
      await fillValid(user)
      fireEvent.change(sliders()[0], { target: { value: '6' } })
      fireEvent.change(sliders()[1], { target: { value: '12' } })
      fireEvent.change(sliders()[2], { target: { value: '120' } })
      await user.click(submit())

      await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
      expect(api.post).toHaveBeenCalledWith('/vms', {
        cpu: 6,
        ram_gb: 12,
        disk_gb: 120,
        department_id: 2,
        template_key: 'win10-tpl', // <-- Добавлена эта строка
        requester_name: 'Иван Иванов',
        requester_nick: 'i.ivanov',
        expected_return_at: '2099-12-31',
      })
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Заказ №77'))
      expect(screen.getByTestId('path')).toHaveTextContent('/my')
    })

    it('Enter в поле формы отправляет валидную форму', async () => {
      const { onClose, user } = await setup()
      await fillValid(user)
      await user.type(screen.getByLabelText(/Имя и фамилия/), '{Enter}')
      await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
      expect(api.post).toHaveBeenCalledWith('/vms', expect.objectContaining({ department_id: 2 }))
      expect(vi.mocked(api.post).mock.calls[0][1]).not.toHaveProperty('name')
    })

    it('Enter в невалидной форме (нет отдела и срока) ничего не отправляет', async () => {
      const { user } = await setup()
      await user.type(screen.getByLabelText(/Имя и фамилия/), '{Enter}')
      expect(api.post).not.toHaveBeenCalled()
    })

    it('срок уходит в expected_return_at, ресурсы — минимальные', async () => {
      const { user } = await setup()
      await fillValid(user)
      await user.click(submit())
      await waitFor(() => expect(api.post).toHaveBeenCalled())
      expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ expected_return_at: UNTIL, cpu: 2, ram_gb: 4, disk_gb: 50 })
    })

    it('ошибка API показывается в окне; окно открыто, перехода нет', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Превышен лимит виртуалок'))
      const { onClose, user } = await setup()
      await fillValid(user)
      await user.click(submit())

      expect(await screen.findByText('Превышен лимит виртуалок')).toBeInTheDocument()
      expect(onClose).not.toHaveBeenCalled()
      expect(toast.success).not.toHaveBeenCalled()
      expect(screen.getByTestId('path')).toHaveTextContent(/^\/$/)
      // после ошибки форму можно исправить и отправить снова
      expect(submit()).toBeEnabled()
    })

    it('«Отмена» закрывает окно без запроса', async () => {
      const { onClose, user } = await setup()
      await user.click(screen.getByRole('button', { name: 'Отмена' }))
      expect(onClose).toHaveBeenCalledOnce()
      expect(api.post).not.toHaveBeenCalled()
    })
  })
})

const osButton = (label: string) => screen.getByRole('button', { name: new RegExp(label) })
const diskSlider = () => sliders()[2]
const description = (text: string) => screen.getByText(text, { exact: false })


describe('VmBuilderDialog: выбор ОС', () => {
  beforeEach(() => {
    options = makeTemplateOptions([win10, win11, ubuntu])
  })

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
    options = makeTemplateOptions([ubuntu, win11, win10])
    await setup()
    expect(osButton('Windows 11')).toHaveClass('border-primary')
    expect(osButton('Windows 10')).not.toHaveClass('border-primary')
    expect(osButton('Ubuntu 22.04')).not.toHaveClass('border-primary')
    expect(description('будет создана на Windows 11')).toBeInTheDocument()
  })

  it('клик по другому доступному шаблону переключает выбор и описание', async () => {
    const { user } = await setup()
    expect(description('будет создана на Windows 10')).toBeInTheDocument()
    await user.click(osButton('Windows 11'))
    expect(osButton('Windows 11')).toHaveClass('border-primary')
    expect(osButton('Windows 10')).not.toHaveClass('border-primary')
    expect(description('будет создана на Windows 11')).toBeInTheDocument()
  })

  it('шаблон «скоро» не выбирается кликом', async () => {
    const { user } = await setup()
    await user.click(osButton('Ubuntu 22.04'))
    expect(osButton('Ubuntu 22.04')).not.toHaveClass('border-primary')
    expect(osButton('Windows 10')).toHaveClass('border-primary')
    expect(description('будет создана на Windows 10')).toBeInTheDocument()
  })

  it('нет доступных шаблонов — выбора нет, описание нейтральное, создать нельзя', async () => {
    options = makeTemplateOptions([{ ...ubuntu }, { ...win10, available: false }])
    const { user } = await setup()
    expect(screen.getByText('Выберите операционную систему и ресурсы')).toBeInTheDocument()
    expect(osButton('Ubuntu 22.04')).toBeDisabled()
    expect(osButton('Windows 10')).toBeDisabled()
    await fillValid(user)
    expect(submit()).toBeDisabled()
  })

  it('пустой список шаблонов — создать нельзя', async () => {
    options = makeTemplateOptions([])
    const { user } = await setup()
    expect(screen.queryByText('Операционная система')).toBeInTheDocument()
    await fillValid(user)
    expect(submit()).toBeDisabled()
  })
})

describe('VmBuilderDialog: минимальный диск от шаблона', () => {
  beforeEach(() => {
    options = makeTemplateOptions([win10, win11, ubuntu])
  })

  it('шаблон строже общего лимита — слайдер стартует с минимума шаблона', async () => {
    options = makeTemplateOptions([win11], { min_disk_gb: 40 })
    await setup()
    expect([diskSlider().min, diskSlider().max, diskSlider().value]).toEqual(['100', '200', '100'])
  })

  it('шаблон мягче общего лимита — действует общий минимум', async () => {
    options = makeTemplateOptions([{ ...win10, min_disk_gb: 20 }], { min_disk_gb: 40 })
    await setup()
    expect([diskSlider().min, diskSlider().value]).toEqual(['40', '40'])
  })

  it('смена шаблона пересчитывает минимум и поднимает значение диска', async () => {
    const { user } = await setup()
    expect([diskSlider().min, diskSlider().value]).toEqual(['50', '50'])
    await user.click(osButton('Windows 11'))
    expect([diskSlider().min, diskSlider().value]).toEqual(['100', '100'])
    expect(screen.getByText('100', { selector: 'span.tabular' })).toBeInTheDocument()
  })

  it('выбранный пользователем диск выше минимума нового шаблона сохраняется', async () => {
    const { user } = await setup()
    fireEvent.change(diskSlider(), { target: { value: '150' } })
    await user.click(osButton('Windows 11'))
    expect(diskSlider().value).toBe('150')
  })

  it('на отправку уходит диск не меньше минимума шаблона', async () => {
    const { user } = await setup()
    fireEvent.change(diskSlider(), { target: { value: '60' } })
    await user.click(osButton('Windows 11'))
    await fillValid(user)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ template_key: 'win11', disk_gb: 100 })
  })
})

describe('VmBuilderDialog: отправка с шаблоном', () => {
  beforeEach(() => {
    options = makeTemplateOptions([win10, win11, ubuntu])
  })

  it('по умолчанию уходит template_key первого доступного шаблона', async () => {
    options = makeTemplateOptions([ubuntu, win10, win11])
    const { user } = await setup()
    await fillValid(user)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/vms', expect.objectContaining({ template_key: 'win10', disk_gb: 50 }))
  })

  it('уходит template_key выбранного шаблона', async () => {
    const { user } = await setup()
    await user.click(osButton('Windows 11'))
    await fillValid(user)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/vms', expect.objectContaining({ template_key: 'win11' }))
  })
})

describe('VmBuilderDialog: лимит срока', () => {
  const limit = termLimit(todayLocal())
  const beyond = addDays(limit, 1)

  it('подсказка про срок без согласования; дальше лимита — пояснение про заявку, отправить можно', async () => {
    const { user } = await setup()
    expect(screen.getByText(`Без согласования — до ${formatDate(limit)}`)).toBeInTheDocument()
    expect(screen.queryByText(/администратору уйдёт заявка/)).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
    await user.type(untilInput(), beyond)
    expect(screen.getByText(/администратору уйдёт заявка/)).toHaveTextContent(
      `аренда оформится до ${formatDate(limit)}, а администратору уйдёт заявка на ${formatDate(beyond)}`,
    )
    expect(submit()).toBeEnabled()
  })

  it('заказ ушёл в заявку админу — тост с пояснением', async () => {
    vi.mocked(api.post).mockResolvedValue({
      id: 5, order_number: 77, name: 'A1001', expected_return_at: limit, requested_return_at: beyond,
    })
    const { onClose, user } = await setup()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
    await user.type(untilInput(), beyond)
    await user.click(submit())
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Заказ №77'), {
      description: `Срок ограничен ${formatDate(limit)} — заявка на ${formatDate(beyond)} отправлена администратору`,
    })
  })
})

describe('VmBuilderDialog: готовые размеры', () => {
  const SIZES = [
    { label: 'S', cpu: 2, ram_gb: 4, disk_gb: 50 },
    { label: 'M', cpu: 4, ram_gb: 8, disk_gb: 100 },
  ]

  it('без размеров блока нет', async () => {
    await setup()
    expect(screen.queryByText('Размер')).not.toBeInTheDocument()
  })

  it('кнопка размера ставит ядра, память и диск; они уходят в заказ', async () => {
    options = makeOptions({ sizes: SIZES })
    const { user } = await setup()
    await user.click(screen.getByRole('button', { name: /^M/ }))
    expect(sliders().map((s) => Number(s.value))).toEqual([4, 8, 100])

    await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
    await user.type(untilInput(), UNTIL)
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ cpu: 4, ram_gb: 8, disk_gb: 100 })
  })

  it('диск размера меньше минимума шаблона показывается и заказывается по минимуму', async () => {
    options = makeOptions({ sizes: SIZES, templates: [{ key: 'win11', label: 'Windows 11', os: 'windows', min_disk_gb: 80, available: true }] })
    const { user } = await setup()
    expect(screen.getByRole('button', { name: /^S/ })).toHaveTextContent('2 ядра · 4 ГБ · 80 ГБ')
    await user.click(screen.getByRole('button', { name: /^S/ }))
    expect(Number(sliders()[2].value)).toBe(80)
  })

  it('ползунки после размера остаются: своя конфигурация', async () => {
    options = makeOptions({ sizes: SIZES })
    const { user } = await setup()
    await user.click(screen.getByRole('button', { name: /^M/ }))
    fireEvent.change(sliders()[0], { target: { value: '6' } })
    expect(Number(sliders()[0].value)).toBe(6)
  })
})
