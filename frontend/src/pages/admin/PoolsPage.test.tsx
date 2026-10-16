import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { PoolsPage } from './PoolsPage'
import { api } from '@/lib/api'
import { renderWithProviders } from '@/test/helpers'
import type { Pool } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))
const navigate = vi.fn()
vi.mock('react-router-dom', async (orig) => ({ ...(await orig<typeof import('react-router-dom')>()), useNavigate: () => navigate }))

const departments = [
  { id: 1, name: 'Разработка', code: 'DEV', head_name: null, is_active: true },
  { id: 2, name: 'Аналитика', code: 'AN', head_name: null, is_active: true },
]
const makePool = (over: Partial<Pool> = {}): Pool => ({
  id: 1, name: 'Аренда', description: 'Для отделов', is_published: true, departments: [],
  total: 10, available: 6, booked: 4, ...over,
})

let pools: Pool[]

/** Карточка пула по названию */
const card = (name: string) => screen.getByText(name).closest('div.flex-col') as HTMLElement

beforeEach(() => {
  pools = [
    makePool(),
    makePool({ id: 2, name: 'Резерв', description: null, is_published: false, departments: [{ id: 1, name: 'Разработка' }, { id: 2, name: 'Аналитика' }], total: 3, available: 3, booked: 0 }),
  ]
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  navigate.mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/pools') return pools
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({})
  vi.mocked(api.patch).mockResolvedValue({})
  vi.mocked(api.del).mockResolvedValue(undefined)
})

describe('PoolsPage', () => {
  it('рисует карточки пулов: статус публикации, видимость по отделам, счётчики', async () => {
    renderWithProviders(<PoolsPage />)
    await screen.findByText('Аренда')
    const a = within(card('Аренда'))
    expect(a.getByText('В каталоге')).toBeInTheDocument()
    expect(a.getByText('Для отделов')).toBeInTheDocument()
    expect(a.getByText('Видят все сотрудники')).toBeInTheDocument()
    expect(a.getByText('10')).toBeInTheDocument()
    expect(a.getByText('6')).toBeInTheDocument()
    expect(a.getByText('4')).toBeInTheDocument()

    const r = within(card('Резерв'))
    expect(r.getByText('Скрыт')).toBeInTheDocument()
    expect(r.getByText('Без описания')).toBeInTheDocument()
    expect(r.getByText('Видят: Разработка, Аналитика')).toBeInTheDocument()
  })

  it('пустой список — «Пулов пока нет»', async () => {
    pools = []
    renderWithProviders(<PoolsPage />)
    expect(await screen.findByText('Пулов пока нет')).toBeInTheDocument()
  })

  it('«Состав» ведёт в инвентаризацию с фильтром по пулу', async () => {
    const user = userEvent.setup()
    renderWithProviders(<PoolsPage />)
    await screen.findByText('Резерв')
    await user.click(within(card('Резерв')).getByRole('button', { name: 'Состав' }))
    expect(navigate).toHaveBeenCalledWith('/admin/inventory?pool=2')
  })

  describe('создание и редактирование', () => {
    it('кнопка «Сохранить» активна только при названии от 2 символов', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(screen.getByRole('button', { name: 'Новый пул' }))
      const save = screen.getByRole('button', { name: 'Сохранить' })
      expect(save).toBeDisabled()
      await user.type(screen.getByLabelText(/Название/), ' a ')
      expect(save).toBeDisabled()
      await user.type(screen.getByLabelText(/Название/), 'b')
      expect(save).toBeEnabled()
    })

    it('создаёт пул: POST с отделами и описанием, тост, диалог закрывается', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(screen.getByRole('button', { name: 'Новый пул' }))
      expect(screen.getByRole('dialog', { name: 'Новый пул' })).toBeInTheDocument()

      await user.type(screen.getByLabelText(/Название/), 'Тестовый')
      await user.click(await screen.findByLabelText('Аналитика'))
      await user.click(screen.getByLabelText('Разработка'))
      await user.click(screen.getByLabelText('Аналитика')) // снять отметку
      await user.type(screen.getByLabelText(/Описание/), 'Только для тестов')
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))

      await waitFor(() =>
        expect(api.post).toHaveBeenCalledWith('/admin/pools', {
          name: 'Тестовый', description: 'Только для тестов', department_ids: [1],
        }),
      )
      expect(toast.success).toHaveBeenCalledWith('Пул создан')
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('пустое описание уходит как null', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(screen.getByRole('button', { name: 'Новый пул' }))
      await user.type(screen.getByLabelText(/Название/), 'Без описания')
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))
      await waitFor(() =>
        expect(api.post).toHaveBeenCalledWith('/admin/pools', { name: 'Без описания', description: null, department_ids: [] }),
      )
    })

    it('редактирование подставляет значения и шлёт PATCH', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Резерв')
      await user.click(within(card('Резерв')).getByTitle('Изменить'))

      expect(screen.getByRole('dialog', { name: 'Редактирование пула' })).toBeInTheDocument()
      expect(screen.getByLabelText(/Название/)).toHaveValue('Резерв')
      expect(screen.getByLabelText(/Описание/)).toHaveValue('')
      expect(await screen.findByLabelText('Разработка')).toBeChecked()
      expect(screen.getByLabelText('Аналитика')).toBeChecked()

      await user.click(screen.getByLabelText('Аналитика'))
      await user.clear(screen.getByLabelText(/Название/))
      await user.type(screen.getByLabelText(/Название/), 'Резерв-2')
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))

      await waitFor(() =>
        expect(api.patch).toHaveBeenCalledWith('/admin/pools/2', { name: 'Резерв-2', description: null, department_ids: [1] }),
      )
      expect(toast.success).toHaveBeenCalledWith('Пул обновлён')
    })

    it('ошибка сохранения — тост, диалог остаётся открытым', async () => {
      vi.mocked(api.post).mockRejectedValue(new Error('Пул с таким именем уже есть'))
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(screen.getByRole('button', { name: 'Новый пул' }))
      await user.type(screen.getByLabelText(/Название/), 'Аренда')
      await user.click(screen.getByRole('button', { name: 'Сохранить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Пул с таким именем уже есть'))
      expect(screen.getByRole('dialog', { name: 'Новый пул' })).toBeInTheDocument()
    })

    it('«Отмена» закрывает диалог без запросов', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(screen.getByRole('button', { name: 'Новый пул' }))
      await user.click(screen.getByRole('button', { name: 'Отмена' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(api.post).not.toHaveBeenCalled()
    })
  })

  describe('публикация', () => {
    it('опубликованный пул скрывается', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(within(card('Аренда')).getByTitle('Скрыть из каталога'))
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/pools/1', { is_published: false }))
      expect(toast.success).toHaveBeenCalledWith('«Аренда» скрыт из каталога')
    })

    it('скрытый пул публикуется', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Резерв')
      await user.click(within(card('Резерв')).getByTitle('Опубликовать'))
      await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/admin/pools/2', { is_published: true }))
      expect(toast.success).toHaveBeenCalledWith('«Резерв» опубликован')
    })

    it('ошибка смены публикации — тост', async () => {
      vi.mocked(api.patch).mockRejectedValue(new Error('Нет доступа'))
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(within(card('Аренда')).getByTitle('Скрыть из каталога'))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Нет доступа'))
    })
  })

  describe('удаление', () => {
    it('после подтверждения шлёт DELETE', async () => {
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(within(card('Аренда')).getByTitle('Удалить'))
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Удалить пул «Аренда»?'))
      await waitFor(() => expect(api.del).toHaveBeenCalledWith('/admin/pools/1'))
      expect(toast.success).toHaveBeenCalledWith('Пул удалён')
    })

    it('без подтверждения ничего не удаляет', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(within(card('Аренда')).getByTitle('Удалить'))
      expect(api.del).not.toHaveBeenCalled()
    })

    it('ошибка удаления — тост; не-Error даёт «Ошибка»', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      vi.mocked(api.del).mockRejectedValue('boom')
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await screen.findByText('Аренда')
      await user.click(within(card('Аренда')).getByTitle('Удалить'))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Ошибка'))
    })
  })

  describe('массовое добавление ПК списком имён', () => {
    const openFill = async (user: ReturnType<typeof userEvent.setup>, name = 'Аренда') => {
      await screen.findByText(name)
      await user.click(within(card(name)).getByRole('button', { name: 'Добавить ПК' }))
    }

    it('«Добавить» недоступна, пока список пуст', async () => {
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await openFill(user)
      expect(screen.getByRole('dialog', { name: 'Добавить ПК в «Аренда»' })).toBeInTheDocument()
      const add = screen.getByRole('button', { name: 'Добавить' })
      expect(add).toBeDisabled()
      await user.type(screen.getByRole('textbox'), '   ')
      expect(add).toBeDisabled()
      await user.type(screen.getByRole('textbox'), 'A24')
      expect(add).toBeEnabled()
    })

    it('отправляет текст как есть, всё найдено — тост успеха', async () => {
      vi.mocked(api.post).mockResolvedValue({ updated: 3, not_found: [] })
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await openFill(user)
      await user.type(screen.getByRole('textbox'), 'A24, A25 A26')
      await user.click(screen.getByRole('button', { name: 'Добавить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/pools/assign', { pool_id: 1, names: 'A24, A25 A26' }))
      expect(toast.success).toHaveBeenCalledWith('Добавлено в «Аренда»: 3')
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('не найденные имена — предупреждение; больше 15 обрезается многоточием', async () => {
      const missing = Array.from({ length: 17 }, (_, i) => `X${i + 1}`)
      vi.mocked(api.post).mockResolvedValue({ updated: 1, not_found: missing })
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await openFill(user)
      await user.type(screen.getByRole('textbox'), 'A24')
      await user.click(screen.getByRole('button', { name: 'Добавить' }))
      await waitFor(() => expect(toast.warning).toHaveBeenCalled())
      const msg = vi.mocked(toast.warning).mock.calls[0][0] as string
      expect(msg).toBe(`Добавлено: 1. Не найдены: ${missing.slice(0, 15).join(', ')}…`)
      expect(toast.success).not.toHaveBeenCalled()
    })

    it('ошибка — тост, диалог и введённый текст сохраняются', async () => {
      vi.mocked(api.post).mockRejectedValue(new Error('Сервер недоступен'))
      const user = userEvent.setup()
      renderWithProviders(<PoolsPage />)
      await openFill(user)
      await user.type(screen.getByRole('textbox'), 'A24')
      await user.click(screen.getByRole('button', { name: 'Добавить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Сервер недоступен'))
      expect(screen.getByRole('textbox')).toHaveValue('A24')
    })
  })
})
