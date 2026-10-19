import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { BookingDialog } from './BookingDialog'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, makeComputer, makeSession, renderWithProviders } from '@/test/helpers'

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

  it('кнопка отключена при слишком коротком имени или пустом нике', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
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
    await user.type(screen.getByLabelText(/Для чего нужен/), 'Тесты')
    await user.click(submitButton())

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/bookings', {
      computer_id: 42,
      department_id: 2,
      requester_name: 'Иван Иванов',
      requester_nick: 'i.ivanov',
      purpose: 'Тесты',
      expected_return_at: null,
    })
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining('заказ №123'),
      expect.objectContaining({ action: expect.objectContaining({ label: 'Моя аренда' }) }),
    )
    expect(localStorage.getItem('hmsrent:last-department')).toBe('2')
  })

  it('пустое «для чего» уходит как undefined, дата возврата — как заполнено', async () => {
    const { user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
    const date = screen.getByLabelText(/Планирую вернуть/)
    await user.type(date, '2099-12-31')
    await user.click(submitButton())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const payload = vi.mocked(api.post).mock.calls[0][1] as Record<string, unknown>
    expect(payload.purpose).toBeUndefined()
    expect(payload.expected_return_at).toBe('2099-12-31')
  })

  it('подставляет последний выбранный отдел из localStorage', async () => {
    localStorage.setItem('hmsrent:last-department', '2')
    setup()
    await waitForDepartments()
    expect(screen.getByLabelText(/Отдел/)).toHaveValue('2')
    expect(submitButton()).toBeEnabled()
  })

  it('неизвестный отдел из localStorage не даёт отправить форму', async () => {
    localStorage.setItem('hmsrent:last-department', '999')
    setup()
    await waitForDepartments()
    expect(submitButton()).toBeDisabled()
  })

  it('ошибка API показывается в форме, окно остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Компьютер уже забронирован'))
    const { onClose, user } = setup()
    await waitForDepartments()
    await user.selectOptions(screen.getByLabelText(/Отдел/), '1')
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
