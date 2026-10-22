import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { toast } from 'sonner'
import { ExecutorOrderPage } from './ExecutorOrderPage'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, makeExecutorOrder, renderWithProviders } from '@/test/helpers'
import type { ExecutorOrder } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let order: ExecutorOrder

const mount = () =>
  renderWithProviders(
    <Routes>
      <Route path="/executor" element={<p>очередь</p>} />
      <Route path="/executor/orders/:id" element={<ExecutorOrderPage />} />
    </Routes>,
    { route: '/executor/orders/7' },
  )

beforeEach(() => {
  order = makeExecutorOrder({ purpose: 'Сборка билдов' })
  for (const m of [api.get, api.post]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/executor/orders/7') return order
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('ExecutorOrderPage: заказ', () => {
  it('показывает ПК, ОС, команду, заказчика и цель', async () => {
    mount()
    expect(await screen.findByRole('heading', { name: 'A032 · заказ №1042' })).toBeInTheDocument()
    expect(screen.getByText('Windows 11 26H2')).toBeInTheDocument()
    expect(screen.getByText('Builder Studio')).toBeInTheDocument()
    expect(screen.getByText('Пётр Петров (petrov)')).toBeInTheDocument()
    expect(screen.getByText('Сборка билдов')).toBeInTheDocument()
    expect(screen.getByText('Ждёт подготовки')).toBeInTheDocument()
  })

  it('«Все заказы» ведёт в очередь', async () => {
    mount()
    await userEvent.click(await screen.findByRole('link', { name: 'Все заказы' }))
    expect(screen.getByText('очередь')).toBeInTheDocument()
  })

  it('закрытый заказ — без формы', async () => {
    order = makeExecutorOrder({ status: 'returned', returned_at: '2026-10-21T12:00:00Z' })
    mount()
    expect(await screen.findByText(/Заказ закрыт: ПК вернули/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Отправить заказчику' })).not.toBeInTheDocument()
  })

  it('ошибка загрузки — сообщение и «Повторить»', async () => {
    failGetOnce(vi.mocked(api.get), '/executor/orders/7')
    mount()
    expect(await screen.findByText('Не удалось загрузить заказ')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('heading', { name: 'A032 · заказ №1042' })).toBeInTheDocument()
  })
})

describe('ExecutorOrderPage: данные для подключения', () => {
  it('имя хоста подставлено по номеру комплекта, для Windows — RDP; отправка уходит на сервер', async () => {
    vi.mocked(api.post).mockResolvedValue({ ...order, prepared_at: '2026-10-21T10:00:00Z' })
    mount()
    expect(await screen.findByLabelText(/Доменное имя/)).toHaveValue('A032.ff.local')
    expect(screen.getByLabelText(/Способ подключения/)).toHaveValue('RDP')
    await userEvent.type(screen.getByLabelText(/IP-адрес/), ' 10.1.2.3 ')
    await userEvent.click(screen.getByRole('button', { name: 'Отправить заказчику' }))
    expect(api.post).toHaveBeenCalledWith('/executor/orders/7/result', { host: 'A032.ff.local', ip: '10.1.2.3', method: 'RDP' })
    expect(toast.success).toHaveBeenCalledWith('Данные для подключения отправлены заказчику')
  })

  it('для Linux по умолчанию VNC, способ можно сменить с клавиатуры', async () => {
    order = makeExecutorOrder({ os_label: 'Ubuntu 24.04' })
    mount()
    const method = await screen.findByLabelText(/Способ подключения/)
    expect(method).toHaveValue('VNC')
    await userEvent.selectOptions(method, 'RDP')
    expect(method).toHaveValue('RDP')
  })

  it('подготовленный заказ: поля заполнены внесёнными данными, видно, кто подготовил', async () => {
    order = makeExecutorOrder({
      connection_host: 'A032.ff.local', connection_ip: '10.1.2.3', connection_method: 'VNC', connection_login: 'user',
      prepared_at: '2026-10-21T10:00:00Z', prepared_by: { id: 5, username: 'worker', display_name: 'Олег Смирнов' },
    })
    mount()
    expect(await screen.findByLabelText(/IP-адрес/)).toHaveValue('10.1.2.3')
    expect(screen.getByLabelText(/Способ подключения/)).toHaveValue('VNC')
    expect(screen.getByText(/Подготовил Олег Смирнов/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeInTheDocument()
  })

  it('ошибка сервера показана в форме, успех не объявлен', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Заказ уже закрыт: ПК вернули'))
    mount()
    await userEvent.type(await screen.findByLabelText(/IP-адрес/), '10.1.2.3')
    await userEvent.click(screen.getByRole('button', { name: 'Отправить заказчику' }))
    expect(await screen.findByText('Заказ уже закрыт: ПК вернули')).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalled()
  })
})

describe('ExecutorOrderPage: отклонение', () => {
  const fill = async (reason: string, comment = 'Нет ответа 5 рабочих дней') => {
    const user = userEvent.setup()
    await user.selectOptions(await screen.findByLabelText(/Основание/), reason)
    await user.type(screen.getByLabelText(/Комментарий для заказчика/), comment)
    return user
  }

  it('кнопка недоступна, пока нет основания и комментария', async () => {
    mount()
    const button = await screen.findByRole('button', { name: 'Отклонить заказ…' })
    expect(button).toBeDisabled()
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText(/Основание/), 'Некорректный заказ')
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText(/Комментарий для заказчика/), '   ')
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText(/Комментарий для заказчика/), 'Дубль заказа')
    expect(button).toBeEnabled()
  })

  it('основания — по регламенту', async () => {
    mount()
    await screen.findByRole('heading', { name: /заказ №1042/ })
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(expect.arrayContaining(['Сервер неисправен', 'Заказчик не ответил', 'Некорректный заказ']))
  })

  it('отправка идёт через подтверждение: POST, тост и возврат в очередь', async () => {
    vi.mocked(api.post).mockResolvedValue({ ...order, status: 'cancelled' })
    mount()
    const user = await fill('Заказчик не ответил')
    await user.click(screen.getByRole('button', { name: 'Отклонить заказ…' }))
    expect(api.post).not.toHaveBeenCalled() // пока не подтвердили
    await user.click(await screen.findByRole('button', { name: 'Отклонить' }))
    expect(api.post).toHaveBeenCalledWith('/executor/orders/7/reject', {
      reason: 'Заказчик не ответил', comment: 'Нет ответа 5 рабочих дней',
    })
    expect(toast.success).toHaveBeenCalledWith('Заказ отклонён, заказчик получил уведомление')
    expect(await screen.findByText('очередь')).toBeInTheDocument()
  })

  it('«Сервер неисправен» предупреждает про вывод ПК из пула', async () => {
    mount()
    expect(await screen.findByLabelText(/Основание/)).toBeInTheDocument()
    expect(screen.queryByText(/выведен из пула/)).not.toBeInTheDocument()
    const user = await fill('Сервер неисправен', 'Не включается')
    expect(screen.getByText(/ПК будет выведен из пула, а исполнителям создастся заявка/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Отклонить заказ…' }))
    expect(await screen.findByText(/ПК будет выведен из пула, заказчик получит уведомление/)).toBeInTheDocument()
  })

  it('ошибка сервера показана в окне, заказ остаётся открытым', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Заказ уже закрыт'))
    mount()
    const user = await fill('Некорректный заказ', 'Дубль')
    await user.click(screen.getByRole('button', { name: 'Отклонить заказ…' }))
    await user.click(await screen.findByRole('button', { name: 'Отклонить' }))
    expect(await screen.findByText('Заказ уже закрыт')).toBeInTheDocument()
    expect(toast.success).not.toHaveBeenCalled()
    expect(screen.queryByText('очередь')).not.toBeInTheDocument()
  })

  it('у закрытого заказа формы отклонения нет', async () => {
    order = makeExecutorOrder({ status: 'cancelled', returned_at: '2026-10-21T12:00:00Z' })
    mount()
    await screen.findByText(/Заказ закрыт/)
    expect(screen.queryByRole('button', { name: 'Отклонить заказ…' })).not.toBeInTheDocument()
  })
})
