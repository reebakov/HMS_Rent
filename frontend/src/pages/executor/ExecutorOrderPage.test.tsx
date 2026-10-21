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
