import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { toast } from 'sonner'
import { VmBuilderDialog } from './VmBuilderDialog'
import { api, ApiError } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { VmOptions } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let session = makeSession()
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => session }))

const departments = [
  { id: 1, name: 'Разработка', code: 'DEV', head_name: null, is_active: true },
  { id: 2, name: 'Аналитика', code: 'AN', head_name: null, is_active: true },
]

const makeOptions = (over: Partial<VmOptions> = {}): VmOptions => ({
  enabled: true,
  reason: null,
  name_prefix: 'rent-',
  template: 'win10-tpl',
  min_cpu: 2,
  max_cpu: 8,
  min_ram_gb: 4,
  max_ram_gb: 16,
  min_disk_gb: 50,
  max_disk_gb: 200,
  max_per_user: 3,
  used_by_me: 1,
  ...over,
})

let options: VmOptions

const Where = () => <span data-testid="path">{useLocation().pathname}</span>

async function setup(onClose = vi.fn()) {
  renderWithProviders(<><VmBuilderDialog open onClose={onClose} /><Where /></>, { route: '/' })
  await screen.findByRole('option', { name: 'Аналитика' })
  return { onClose, user: userEvent.setup() }
}

const submit = () => screen.getByRole('button', { name: 'Создать' })
const sliders = () => screen.getAllByRole('slider') as HTMLInputElement[] // ядра, память, диск
const nameInput = () => screen.getByLabelText(/Имя виртуалки/)

/** Заполняет минимум, чтобы форма стала валидной */
async function fillValid(user: ReturnType<typeof userEvent.setup>, name = 'design-01') {
  await user.type(nameInput(), name)
  await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
}

beforeEach(() => {
  session = makeSession()
  options = makeOptions()
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/vms/options') return options
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({ id: 5, order_number: 77, name: 'rent-design-01' })
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

  it('отключённый конструктор показывает причину и не даёт создать', async () => {
    options = makeOptions({ enabled: false, reason: 'vSphere не настроен администратором' })
    renderWithProviders(<VmBuilderDialog open onClose={() => undefined} />)
    expect(await screen.findByText('vSphere не настроен администратором')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Имя виртуалки/)).not.toBeInTheDocument()
    expect(submit()).toBeDisabled()
  })

  it('подставляет значения по умолчанию: минимумы лимитов, имя и ник из сессии', async () => {
    session = makeSession({ username: 'i.ivanov@corp.example', department_id: 2 })
    await setup()
    expect(screen.getByRole('dialog', { name: 'Конструктор виртуалки' })).toBeInTheDocument()
    expect(sliders().map((s) => s.value)).toEqual(['2', '4', '50'])
    expect(screen.getByLabelText(/Имя и фамилия/)).toHaveValue('Иван Иванов')
    // ник — часть логина до «@»
    expect(screen.getByLabelText(/Ник/)).toHaveValue('i.ivanov')
    // отдел из профиля
    expect(screen.getByLabelText(/Отдел/)).toHaveValue('2')
  })

  it('отдел берётся из localStorage, если в профиле его нет', async () => {
    localStorage.setItem('hmsrent:last-department', '1')
    await setup()
    expect(screen.getByLabelText(/Отдел/)).toHaveValue('1')
  })

  it('ползунки ограничены лимитами из настроек', async () => {
    options = makeOptions({ min_cpu: 1, max_cpu: 4, min_ram_gb: 2, max_ram_gb: 8, min_disk_gb: 30, max_disk_gb: 100 })
    await setup()
    const [cpu, ram, disk] = sliders()
    expect([cpu.min, cpu.max, cpu.step]).toEqual(['1', '4', '1'])
    expect([ram.min, ram.max, ram.step]).toEqual(['2', '8', '2'])
    expect([disk.min, disk.max, disk.step]).toEqual(['30', '100', '10'])
    // стартовые значения — минимумы
    expect([cpu.value, ram.value, disk.value]).toEqual(['1', '2', '30'])
  })

  it('подсказка показывает префикс vCenter и счётчик занятых ВМ', async () => {
    const { user } = await setup()
    expect(screen.getByText('В vCenter будет «rent-имя»', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/Занято виртуалок: 1 из 3/)).toBeInTheDocument()
    await user.type(nameInput(), 'qa-01')
    expect(screen.getByText('В vCenter будет «rent-qa-01»', { exact: false })).toBeInTheDocument()
  })

  describe('валидация имени', () => {
    it('приводит к нижнему регистру', async () => {
      const { user } = await setup()
      await user.type(nameInput(), 'Design-01')
      expect(nameInput()).toHaveValue('design-01')
    })

    it.each([
      ['слишком короткое', 'ab'],
      ['начинается с дефиса', '-abc'],
      ['заканчивается дефисом', 'abc-'],
      ['с пробелом', 'ab cd'],
      ['с подчёркиванием', 'ab_cd'],
      ['кириллица', 'дизайн'],
      ['21 символ', 'a'.repeat(21)],
    ])('%s — ошибка и кнопка отключена', async (_title, value) => {
      const { user } = await setup()
      await fillValid(user, value)
      expect(screen.getByText(/Только a–z, 0–9 и дефис/)).toBeInTheDocument()
      expect(submit()).toBeDisabled()
    })

    it.each([['3 символа', 'abc'], ['20 символов', 'a'.repeat(20)], ['с дефисом внутри', 'a-b-c'], ['только цифры', '123']])(
      '%s — допустимо',
      async (_title, value) => {
        const { user } = await setup()
        await fillValid(user, value)
        expect(screen.queryByText(/Только a–z, 0–9 и дефис/)).not.toBeInTheDocument()
        expect(submit()).toBeEnabled()
      },
    )

    it('пустое имя — без ошибки, но кнопка отключена', async () => {
      const { user } = await setup()
      await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
      expect(screen.queryByText(/Только a–z, 0–9 и дефис/)).not.toBeInTheDocument()
      expect(submit()).toBeDisabled()
    })
  })

  describe('прочие обязательные поля', () => {
    it('без отдела отправить нельзя', async () => {
      const { user } = await setup()
      await user.type(nameInput(), 'design-01')
      expect(submit()).toBeDisabled()
      await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
      expect(submit()).toBeEnabled()
    })

    it('имя и фамилия короче 2 символов или пустой ник блокируют отправку', async () => {
      const { user } = await setup()
      await fillValid(user)
      const person = screen.getByLabelText(/Имя и фамилия/)
      await user.clear(person)
      await user.type(person, 'И')
      expect(submit()).toBeDisabled()
      await user.type(person, 'в')
      expect(submit()).toBeEnabled()

      const nick = screen.getByLabelText(/Ник/)
      await user.clear(nick)
      expect(submit()).toBeDisabled()
    })

    it('«Вернуть до» не позволяет выбрать прошедшую дату', async () => {
      await setup()
      const min = (screen.getByLabelText(/Вернуть до/) as HTMLInputElement).min
      expect(min).toBe(new Date().toISOString().slice(0, 10))
    })
  })

  describe('отправка', () => {
    it('шлёт выбранные параметры, показывает toast, закрывает окно и ведёт в «Мою аренду»', async () => {
      const { onClose, user } = await setup()
      await fillValid(user)
      fireEvent.change(sliders()[0], { target: { value: '6' } })
      fireEvent.change(sliders()[1], { target: { value: '12' } })
      fireEvent.change(sliders()[2], { target: { value: '120' } })
      await user.type(screen.getByLabelText(/Вернуть до/), '2099-12-31')
      await user.click(submit())

      await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
      expect(api.post).toHaveBeenCalledWith('/vms', {
        name: 'design-01',
        cpu: 6,
        ram_gb: 12,
        disk_gb: 120,
        department_id: 2,
        requester_name: 'Иван Иванов',
        requester_nick: 'i.ivanov',
        expected_return_at: '2099-12-31',
      })
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Заказ №77'))
      expect(screen.getByTestId('path')).toHaveTextContent('/my')
    })

    it('без даты возврата уходит null', async () => {
      const { user } = await setup()
      await fillValid(user)
      await user.click(submit())
      await waitFor(() => expect(api.post).toHaveBeenCalled())
      expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ expected_return_at: null, cpu: 2, ram_gb: 4, disk_gb: 50 })
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
