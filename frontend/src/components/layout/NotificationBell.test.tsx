import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { NotificationBell } from './NotificationBell'
import { api } from '@/lib/api'
import { renderWithProviders } from '@/test/helpers'
import type { NotificationList, UserNotification } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const note = (over: Partial<UserNotification> = {}): UserNotification => ({
  id: 1,
  kind: 'vm_ready',
  title: 'ВМ A1001 готова',
  body: 'Заказ №7, аренда до 01.12.2026.',
  created_at: '2026-10-21T09:00:00Z',
  read_at: null,
  ...over,
})

let list: NotificationList

const Where = () => <span data-testid="path">{useLocation().pathname}</span>
const mount = () => renderWithProviders(<><NotificationBell /><Where /></>, { route: '/' })
const bell = () => screen.getByRole('button', { name: /Уведомления/ })

beforeEach(() => {
  list = { items: [note(), note({ id: 2, kind: 'term_overdue', title: 'Срок аренды ПК PC-5 закончился', body: '', read_at: '2026-10-20T09:00:00Z' })], unread: 1 }
  for (const m of [api.get, api.post]) vi.mocked(m).mockReset()
  vi.mocked(api.get).mockImplementation(async () => list)
  vi.mocked(api.post).mockResolvedValue(undefined)
})

describe('NotificationBell', () => {
  it('число непрочитанных на значке и в подписи кнопки; без них значка нет', async () => {
    mount()
    expect(await screen.findByRole('button', { name: 'Уведомления, непрочитанных: 1' })).toHaveTextContent('1')
    expect(api.get).toHaveBeenCalledWith('/notifications')
  })

  it('нет непрочитанных — нет и счётчика', async () => {
    list = { items: [note({ read_at: '2026-10-20T09:00:00Z' })], unread: 0 }
    mount()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    expect(bell()).toHaveAccessibleName('Уведомления')
    expect(bell()).not.toHaveTextContent(/\d/)
  })

  it('панель открывается по клику: тексты уведомлений, непрочитанное помечено', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByRole('button', { name: /непрочитанных: 1/ })
    expect(screen.queryByText('ВМ A1001 готова')).not.toBeInTheDocument()
    await user.click(bell())
    expect(bell()).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByRole('button', { name: /ВМ A1001 готова \(новое\)/ })).toHaveTextContent('Заказ №7, аренда до 01.12.2026.')
    expect(screen.getByRole('button', { name: /Срок аренды ПК PC-5 закончился/ })).toBeInTheDocument()
  })

  it('Esc закрывает панель и возвращает фокус на колокольчик', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(bell())
    await screen.findByText('ВМ A1001 готова', { exact: false })
    await user.keyboard('{Escape}')
    expect(screen.queryByText('Уведомления', { selector: 'p' })).not.toBeInTheDocument()
    expect(bell()).toHaveFocus()
  })

  it('клик вне панели закрывает её', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(bell())
    await screen.findByText('Уведомления', { selector: 'p' })
    await user.click(screen.getByTestId('path'))
    expect(screen.queryByText('Уведомления', { selector: 'p' })).not.toBeInTheDocument()
  })

  it('клик по непрочитанному отмечает его прочитанным и ведёт в «Мою аренду»', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(bell())
    await user.click(await screen.findByRole('button', { name: /ВМ A1001 готова/ }))
    expect(api.post).toHaveBeenCalledWith('/notifications/1/read')
    expect(screen.getByTestId('path')).toHaveTextContent('/my')
    expect(screen.queryByText('Уведомления', { selector: 'p' })).not.toBeInTheDocument()
  })

  it('прочитанное при клике не отправляется на сервер повторно', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(bell())
    await user.click(await screen.findByRole('button', { name: /Срок аренды ПК PC-5 закончился/ }))
    expect(api.post).not.toHaveBeenCalled()
    expect(screen.getByTestId('path')).toHaveTextContent('/my')
  })

  it('«Прочитать все» отправляет запрос; без непрочитанных кнопки нет', async () => {
    const user = userEvent.setup()
    const { unmount } = mount()
    await user.click(bell())
    await user.click(await screen.findByRole('button', { name: 'Прочитать все' }))
    expect(api.post).toHaveBeenCalledWith('/notifications/read-all')
    unmount()

    list = { items: [note({ read_at: '2026-10-20T09:00:00Z' })], unread: 0 }
    mount()
    await user.click(bell())
    await screen.findByRole('button', { name: /ВМ A1001 готова/ })
    expect(screen.queryByRole('button', { name: 'Прочитать все' })).not.toBeInTheDocument()
  })

  it('пустой список: подсказка вместо пустой панели', async () => {
    list = { items: [], unread: 0 }
    const user = userEvent.setup()
    mount()
    await user.click(bell())
    expect(await screen.findByText(/здесь появятся новости по вашим заказам/)).toBeInTheDocument()
  })

  it('ошибка загрузки: сообщение и «Повторить», а не пустая панель', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('500'))
    const user = userEvent.setup()
    mount()
    await user.click(bell())
    expect(await screen.findByText('Не удалось загрузить уведомления')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
    expect(screen.queryByText(/здесь появятся новости/)).not.toBeInTheDocument()
  })
})
