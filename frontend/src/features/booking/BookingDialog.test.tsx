import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { BookingDialog, ExtendDialog, type ExtendTarget } from './BookingDialog'
import { termLimit } from './TermLimit'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, makeComputer, makeSession, renderWithProviders } from '@/test/helpers'
import { addDays, formatDate, todayLocal } from '@/lib/utils'

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
const computer = makeComputer({ id: 42, name: 'PC-042' })

const bookingResponse = {
  id: 7,
  order_number: 123,
  computer: { id: 42, name: 'PC-042' },
  department: { id: 2, name: 'Аналитика' },
}

function setup(onClose = vi.fn()) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  renderWithProviders(<BookingDialog computer={computer} onClose={onClose} />)
  return { onClose, user: userEvent.setup() }
}

const submitButton = () => screen.getByRole('button', { name: 'Забронировать' })
const waitForDepartments = () => screen.findByRole('option', { name: 'Аналитика' })
const returnDate = () => screen.getByLabelText(/Планирую вернуть/)
const fillReturnDate = (user: ReturnType<typeof userEvent.setup>) => user.type(returnDate(), '2099-12-31')

describe('BookingDialog', () => {
  beforeEach(() => {
    session = makeSession()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.post).mockResolvedValue(bookingResponse)
  })

  it('ошибка загрузки отделов: сообщение и «Повторить» вместо пустого списка, бронь недоступна; повтор подгружает отделы', async () => {
    const user = userEvent.setup()
    vi.mocked(api.get).mockImplementation(async () => departments)
    failGetOnce(vi.mocked(api.get), '/departments')
    renderWithProviders(<BookingDialog computer={computer} onClose={vi.fn()} />)
    expect(await screen.findByText('Не удалось загрузить отделы')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Аналитика' })).not.toBeInTheDocument()
    expect(submitButton()).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await waitForDepartments()).toBeInTheDocument()
    expect(screen.queryByText('Не удалось загрузить отделы')).not.toBeInTheDocument()
  })

  it('ник по умолчанию — часть логина до «@», как в конструкторе ВМ', async () => {
    session = makeSession({ username: 'i.ivanov@corp.example' })
    setup()
    await waitForDepartments()
    expect(screen.getByLabelText(/Ник \/ логин/)).toHaveValue('i.ivanov')
  })

  it('ничего не рисует без выбранного компьютера', () => {
    renderWithProviders(<BookingDialog computer={null} onClose={() => undefined} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('подставляет имя и ник из сессии и показывает карточку ПК', async () => {
    setup()
    await waitForDepartments()
    expect(screen.getByRole('dialog', { name: 'Бронирование PC-042' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Имя и фамилия/)).toHaveValue('Иван Иванов')
    expect(screen.getByLabelText(/Ник \/ логин/)).toHaveValue('i.ivanov')
    expect(screen.getByText('Intel Core i5 · 6 ядер')).toBeInTheDocument()
  })

  it('«Планирую вернуть»: min — сегодняшняя дата по местному времени, а не по UTC', async () => {
    vi.stubEnv('TZ', 'Asia/Yekaterinburg')
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-19T22:30:00Z')) // в Екатеринбурге уже 20 октября
    try {
      setup()
      await waitForDepartments()
      expect(screen.getByLabelText(/Планирую вернуть/)).toHaveAttribute('min', '2026-10-20')
    } finally {
      vi.useRealTimers()
      vi.unstubAllEnvs()
    }
  })

  it('кнопка отключена, пока не выбран отдел', async () => {
    setup()
    await waitForDepartments()
    expect(submitButton()).toBeDisabled()
  })

  it('кнопка отключена без срока возврата, при слишком коротком имени или пустом нике', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
    expect(submitButton()).toBeDisabled()
    await fillReturnDate(user)
    expect(submitButton()).toBeEnabled()

    const name = screen.getByLabelText(/Имя и фамилия/)
    await user.clear(name)
    await user.type(name, 'И')
    expect(submitButton()).toBeDisabled()
    await user.type(name, 'в')
    expect(submitButton()).toBeEnabled()

    const nick = screen.getByLabelText(/Ник \/ логин/)
    await user.clear(nick)
    await user.type(nick, '   ')
    expect(submitButton()).toBeDisabled()
  })

  it('отправляет форму: корректный payload, toast, запоминает отдел и закрывает окно', async () => {
    const { onClose, user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
    await fillReturnDate(user)
    await user.type(screen.getByLabelText(/Для чего нужен/), 'Тесты')
    await user.click(submitButton())

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/bookings', {
      computer_id: 42,
      department_id: 2,
      requester_name: 'Иван Иванов',
      requester_nick: 'i.ivanov',
      purpose: 'Тесты',
      expected_return_at: '2099-12-31',
    })
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining('заказ №123'),
      expect.objectContaining({ action: expect.objectContaining({ label: 'Моя аренда' }) }),
    )
    expect(localStorage.getItem('hmsrent:last-department')).toBe('2')
  })

  it('Enter в поле формы отправляет бронь, пока форма невалидна — нет', async () => {
    const { onClose, user } = setup()
    await waitForDepartments()
    const purpose = screen.getByLabelText(/Для чего нужен/)
    await user.type(purpose, 'Тесты{Enter}')
    expect(api.post).not.toHaveBeenCalled() // отдел не выбран
    await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
    await user.type(purpose, '{Enter}')
    expect(api.post).not.toHaveBeenCalled() // срок возврата не указан
    await fillReturnDate(user)
    await user.type(purpose, '{Enter}')
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/bookings', expect.objectContaining({ department_id: 2, purpose: 'Тесты' }))
  })

  it('пустое «для чего» уходит как undefined', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
    await fillReturnDate(user)
    await user.click(submitButton())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const payload = vi.mocked(api.post).mock.calls[0][1] as Record<string, unknown>
    expect(payload.purpose).toBeUndefined()
  })

  it('прошедшую дату возврата, впечатанную вручную, отправить нельзя', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
    await user.type(returnDate(), '2000-01-01')
    expect(submitButton()).toBeDisabled()
  })

  it('подставляет последний выбранный отдел из localStorage', async () => {
    localStorage.setItem('hmsrent:last-department', '2')
    const { user } = setup()
    await waitForDepartments()
    expect(screen.getByLabelText(/Отдел/)).toHaveValue('2')
    await fillReturnDate(user)
    expect(submitButton()).toBeEnabled()
  })

  it('неизвестный отдел из localStorage не даёт отправить форму', async () => {
    localStorage.setItem('hmsrent:last-department', '999')
    const { user } = setup()
    await waitForDepartments()
    await fillReturnDate(user)
    expect(submitButton()).toBeDisabled()
  })

  it('ошибка API показывается в форме, окно остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Компьютер уже забронирован'))
    const { onClose, user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
    await fillReturnDate(user)
    await user.click(submitButton())

    expect(await screen.findByText('Компьютер уже забронирован')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
    expect(localStorage.getItem('hmsrent:last-department')).toBeNull()
  })

  it('«Отмена» закрывает окно без запроса', async () => {
    const { onClose, user } = setup()
    await waitForDepartments()
    await user.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(api.post).not.toHaveBeenCalled()
  })
})

describe('ExtendDialog', () => {
  const today = todayLocal()
  const setupExtend = (target: ExtendTarget = { kind: 'pc', id: 7, name: 'PC-042', due: addDays(today, 3) }, onClose = vi.fn()) => {
    renderWithProviders(<ExtendDialog target={target} onClose={onClose} />)
    return { onClose, user: userEvent.setup() }
  }
  const dateInput = () => screen.getByLabelText(/Новый срок/)
  const extendButton = () => screen.getByRole('button', { name: 'Продлить' })

  beforeEach(() => {
    vi.mocked(api.post).mockReset()
    vi.mocked(api.post).mockResolvedValue({})
    vi.mocked(toast.success).mockReset()
  })

  it('показывает текущий срок; новый должен быть позже него', async () => {
    const due = addDays(today, 3)
    const { user } = setupExtend()
    expect(screen.getByText(`Текущий срок — ${formatDate(due)}. Администраторы увидят продление.`)).toBeInTheDocument()
    expect(dateInput()).toHaveAttribute('min', addDays(due, 1))
    expect(extendButton()).toBeDisabled()
    await user.type(dateInput(), due)
    expect(extendButton()).toBeDisabled()
    await user.clear(dateInput())
    await user.type(dateInput(), addDays(due, 1))
    expect(extendButton()).toBeEnabled()
  })

  it.each([
    ['просрочена', addDays(today, -5)],
    ['без срока', null],
  ])('бронь %s — продлить можно с сегодняшнего дня', async (_, due) => {
    const { user } = setupExtend({ kind: 'pc', id: 7, name: 'PC-042', due })
    expect(dateInput()).toHaveAttribute('min', today)
    await user.type(dateInput(), today)
    expect(extendButton()).toBeEnabled()
  })

  it('отправляет новый срок и причину, показывает тост и закрывается', async () => {
    const { onClose, user } = setupExtend()
    await user.type(dateInput(), '2099-12-31')
    await user.type(screen.getByLabelText(/Причина/), 'Тесты ещё идут')
    await user.click(extendButton())
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/bookings/7/extend', { expected_return_at: '2099-12-31', comment: 'Тесты ещё идут' })
    expect(toast.success).toHaveBeenCalledWith(`Аренда PC-042 продлена до ${formatDate('2099-12-31')}`)
  })

  it('продление ВМ уходит в POST /vms/{id}/extend с тем же диалогом', async () => {
    const { onClose, user } = setupExtend({ kind: 'vm', id: 4, name: 'rent-qa-02', due: addDays(today, 3) })
    expect(screen.getByRole('dialog', { name: 'Продлить аренду rent-qa-02' })).toBeInTheDocument()
    expect(dateInput()).toHaveAttribute('min', addDays(today, 4))
    await user.type(dateInput(), '2099-12-31')
    await user.type(screen.getByLabelText(/Причина/), 'Нужна до релиза')
    await user.click(extendButton())
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledOnce()
    expect(api.post).toHaveBeenCalledWith('/vms/4/extend', { expected_return_at: '2099-12-31', comment: 'Нужна до релиза' })
    expect(toast.success).toHaveBeenCalledWith(`Аренда rent-qa-02 продлена до ${formatDate('2099-12-31')}`)
  })

  it('ошибка продления ВМ (409) показывается в форме, окно остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Виртуалка удаляется или уже удалена — продлить срок нельзя'))
    const { onClose, user } = setupExtend({ kind: 'vm', id: 4, name: 'rent-qa-02', due: null })
    await user.type(dateInput(), '2099-12-31')
    await user.click(extendButton())
    expect(await screen.findByText('Виртуалка удаляется или уже удалена — продлить срок нельзя')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('Enter в поле срока отправляет форму', async () => {
    const { user } = setupExtend()
    await user.type(dateInput(), '2099-12-31{Enter}')
    await waitFor(() => expect(api.post).toHaveBeenCalledOnce())
  })

  it('Esc закрывает окно без запроса', async () => {
    const { onClose, user } = setupExtend()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('пустая причина не отправляется', async () => {
    const { user } = setupExtend()
    await user.type(dateInput(), '2099-12-31')
    await user.click(extendButton())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({ expected_return_at: '2099-12-31' })
  })

  it('ошибка API показывается в форме, окно остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Бронирование уже закрыто'))
    const { onClose, user } = setupExtend()
    await user.type(dateInput(), '2099-12-31')
    await user.click(extendButton())
    expect(await screen.findByText('Бронирование уже закрыто')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('«Отмена» закрывает окно без запроса', async () => {
    const { onClose, user } = setupExtend()
    await user.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(api.post).not.toHaveBeenCalled()
  })
})

describe('BookingDialog: лимит срока', () => {
  const limit = termLimit(todayLocal())
  const beyond = addDays(limit, 1)

  beforeEach(() => {
    session = makeSession()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.post).mockResolvedValue(bookingResponse)
    vi.mocked(toast.success).mockReset()
  })

  it('под полем срока подсказка, до какой даты можно без согласования', async () => {
    setup()
    await waitForDepartments()
    expect(screen.getByText(`Без согласования — до ${formatDate(limit)}`)).toBeInTheDocument()
  })

  it('срок в пределах лимита — пояснения про заявку нет', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.type(returnDate(), limit)
    expect(screen.queryByText(/администратору уйдёт заявка/)).not.toBeInTheDocument()
  })

  it('срок дальше лимита — пояснение: аренда по лимиту, заявка на выбранный срок; отправить можно', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
    await user.type(returnDate(), beyond)
    expect(screen.getByText(/администратору уйдёт заявка/)).toHaveTextContent(
      `аренда оформится до ${formatDate(limit)}, а администратору уйдёт заявка на ${formatDate(beyond)}`,
    )
    expect(submitButton()).toBeEnabled()
  })

  it('бронь ушла в заявку админу — тост с пояснением и кнопкой «Моя аренда»', async () => {
    vi.mocked(api.post).mockResolvedValue({ ...bookingResponse, expected_return_at: limit, requested_return_at: beyond })
    const { onClose, user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '2')
    await user.type(returnDate(), beyond)
    await user.click(submitButton())
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/bookings', expect.objectContaining({ expected_return_at: beyond }))
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining('заказ №123'),
      expect.objectContaining({
        description: `Срок ограничен ${formatDate(limit)} — заявка на ${formatDate(beyond)} отправлена администратору`,
        action: expect.objectContaining({ label: 'Моя аренда' }),
      }),
    )
  })
})

describe('ExtendDialog: лимит срока', () => {
  const today = todayLocal()
  const due = addDays(today, 30)
  const limit = termLimit(due)
  const beyond = addDays(limit, 1)
  const target: ExtendTarget = { kind: 'pc', id: 7, name: 'PC-042', due }

  const dateInput = () => screen.getByLabelText(/Новый срок/)
  const setupExtend = (t: ExtendTarget = target) => {
    const onClose = vi.fn()
    renderWithProviders(<ExtendDialog target={t} onClose={onClose} />)
    return { onClose, user: userEvent.setup() }
  }

  beforeEach(() => {
    vi.mocked(api.post).mockReset()
    vi.mocked(api.post).mockResolvedValue({})
    vi.mocked(toast.success).mockReset()
  })

  it('лимит считается от текущего срока, а не от сегодня', () => {
    setupExtend()
    expect(screen.getByText(`Без согласования — до ${formatDate(limit)}`)).toBeInTheDocument()
  })

  it('у просроченной аренды лимит считается от сегодня', () => {
    setupExtend({ ...target, due: addDays(today, -10) })
    expect(screen.getByText(`Без согласования — до ${formatDate(termLimit(today))}`)).toBeInTheDocument()
  })

  it('в пределах лимита пояснения нет, дальше — есть и отправить можно', async () => {
    const { user } = setupExtend()
    await user.type(dateInput(), limit)
    expect(screen.queryByText(/администратору уйдёт заявка/)).not.toBeInTheDocument()
    await user.clear(dateInput())
    await user.type(dateInput(), beyond)
    expect(screen.getByText(/администратору уйдёт заявка/)).toHaveTextContent(
      `аренда продлится до ${formatDate(limit)}, а администратору уйдёт заявка на ${formatDate(beyond)}`,
    )
    expect(screen.getByRole('button', { name: 'Продлить' })).toBeEnabled()
  })

  it('продление ушло в заявку админу — в тосте срок из ответа и пояснение', async () => {
    vi.mocked(api.post).mockResolvedValue({ expected_return_at: limit, requested_return_at: beyond })
    const { onClose, user } = setupExtend()
    await user.type(dateInput(), beyond)
    await user.click(screen.getByRole('button', { name: 'Продлить' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/bookings/7/extend', { expected_return_at: beyond })
    expect(toast.success).toHaveBeenCalledWith(`Аренда PC-042 продлена до ${formatDate(limit)}`, {
      description: `Срок ограничен ${formatDate(limit)} — заявка на ${formatDate(beyond)} отправлена администратору`,
    })
  })
})
