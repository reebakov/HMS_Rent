import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { InventoryPage } from './InventoryPage'
import { api } from '@/lib/api'
import { failGetOnce, makeComputer, renderWithProviders } from '@/test/helpers'
import type { InventoryRow, Pool } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => {
  const real = await orig<typeof import('@/lib/api')>()
  // api.url — настоящая (нужна для ссылки на CSV), остальное мокаем
  return { ...real, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: real.api.url } }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// карточка ПК тестируется отдельно — здесь только факт открытия
vi.mock('@/features/admin/ComputerHistorySheet', () => ({
  ComputerHistorySheet: ({ computerId }: { computerId: number | null }) =>
    computerId !== null ? <div data-testid="sheet">карточка {computerId}</div> : null,
}))

const makeRow = (over: Partial<InventoryRow> = {}): InventoryRow => ({
  ...makeComputer(),
  serial_number: null,
  is_archived: false,
  tier_override: null,
  note: null,
  writeback_error: null,
  usage_until: null,
  order_number: null,
  pool: null,
  booking: null,
  issues: [],
  ...over,
})

const pools: Pool[] = [
  { id: 1, name: 'Аренда', description: null, is_published: true, departments: [], total: 2, available: 1, booked: 1 },
  { id: 2, name: 'Резервный', description: null, is_published: false, departments: [], total: 0, available: 0, booked: 0 },
]
const departments = [{ id: 5, name: 'Разработка', code: 'DEV', head_name: null, is_active: true }]

let rows: InventoryRow[]
let total: number

/** Query-параметры последнего запроса /admin/inventory */
const inventoryCalls = () =>
  vi.mocked(api.get).mock.calls.filter(([p]) => p === '/admin/inventory').map(([, q]) => q as Record<string, unknown>)
const lastQuery = () => inventoryCalls()[inventoryCalls().length - 1]

/** Чекбоксы таблицы: [выбрать все, строка 1, строка 2, …] — без чекбоксов фильтров */
const tableBoxes = () => within(screen.getByRole('table')).getAllByRole('checkbox')

beforeEach(() => {
  rows = [
    makeRow({
      id: 1, name: 'PC-001', insight_key: 'INS-1', location: 'Склад', status: 'booked', insight_status: 'In use',
      pool: { id: 1, name: 'Аренда', is_published: true },
      department: { id: 5, name: 'Разработка' }, order_number: 77,
      booking: {
        id: 9, requester_name: 'Пётр Петров', requester_nick: 'p.petrov', booked_at: '2020-01-10T10:00:00Z',
        expected_return_at: '2020-02-01', user: { id: 2, display_name: 'Пётр Петров', username: 'p.petrov' } as never,
      },
    }),
    makeRow({ id: 2, name: 'PC-002', status: 'available', issues: ['Нет в Insight'], is_archived: true }),
    makeRow({ id: 3, name: 'PC-003', pool: { id: 2, name: 'Резервный', is_published: false }, usage_until: '2999-01-01', department: { id: 5, name: 'Разработка' } }),
  ]
  total = rows.length
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/inventory') return { items: rows, total }
    if (path === '/admin/pools') return pools
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({ updated: 2, not_found: [] })
})

describe('InventoryPage', () => {
  it('рисует таблицу: ПК, пул, отдел, ответственного, заказ и счётчик записей', async () => {
    renderWithProviders(<InventoryPage />)
    expect(await screen.findByText('PC-001')).toBeInTheDocument()
    const row = screen.getByText('PC-001').closest('tr')!
    expect(within(row).getByText('INS-1')).toBeInTheDocument()
    expect(within(row).getByText('Склад')).toBeInTheDocument()
    expect(within(row).getByText('Аренда')).toBeInTheDocument()
    expect(within(row).getByText('Забронирован')).toBeInTheDocument()
    expect(within(row).getByText('In use')).toBeInTheDocument()
    expect(within(row).getByText(/Пётр Петров \(p\.petrov\) · заказ №77/)).toBeInTheDocument()
    expect(screen.getByText('1–3 из 3')).toBeInTheDocument()
    expect(lastQuery()).toMatchObject({ limit: 100, offset: 0 })
  })

  it('ПК без брони, но с отделом помечается как «выдан мимо портала»; просрочка «до» подсвечена', async () => {
    renderWithProviders(<InventoryPage />)
    const row = (await screen.findByText('PC-003')).closest('tr')!
    expect(within(row).getByText('выдан мимо портала')).toBeInTheDocument()
    // usage_until в будущем — не просрочено; у PC-001 срок вернуть 2020-02-01 — просрочен
    expect(within(row).getByText(/^до /).className).toContain('text-muted-foreground')
    const overdue = within(screen.getByText('PC-001').closest('tr')!).getByText(/^до /)
    expect(overdue.className).toContain('text-danger')
  })

  it('проблемы ПК выводятся в title иконки, удалённые из Insight — приглушены', async () => {
    renderWithProviders(<InventoryPage />)
    const row = (await screen.findByText('PC-002')).closest('tr')!
    // подсказка — на обёртке-span: у svg атрибут title браузер как тултип не показывает
    expect(row.querySelector('span[title="Нет в Insight"] svg')).not.toBeNull()
    expect(row.className).toContain('opacity-60')
  })

  it('пустая выдача — «Ничего не найдено» и «0 записей»', async () => {
    rows = []
    total = 0
    renderWithProviders(<InventoryPage />)
    expect(await screen.findByText('Ничего не найдено')).toBeInTheDocument()
    expect(screen.getByText('0 записей')).toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Ничего не найдено» и «0 записей»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/inventory')
    renderWithProviders(<InventoryPage />)
    expect(await screen.findByText('Не удалось загрузить инвентаризацию')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Ничего не найдено')).not.toBeInTheDocument()
    expect(screen.queryByText('0 записей')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-001')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each([
    ['/departments', 'Не удалось загрузить отделы'],
    ['/admin/pools', 'Не удалось загрузить пулы'],
  ])('ошибка справочника %s: сообщение над таблицей, таблица остаётся; «Повторить» перезапрашивает', async (path, title) => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), path)
    renderWithProviders(<InventoryPage />)
    expect(await screen.findByText(title)).toBeInTheDocument()
    expect(screen.getByText('PC-001')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() => expect(screen.queryByText(title)).not.toBeInTheDocument())
  })

  it('фильтры из адресной строки: ?issues=1&pool=2', async () => {
    renderWithProviders(<InventoryPage />, { route: '/?issues=1&pool=2' })
    await screen.findByText('PC-001')
    expect(lastQuery()).toMatchObject({ issues_only: true, pool_id: '2' })
    expect(screen.getByLabelText('Только с проблемами')).toBeChecked()
  })

  it('фильтр статуса из адресной строки (ссылка «Недоступно» из обзора) попадает в запрос и в селект', async () => {
    renderWithProviders(<InventoryPage />, { route: '/?status=unavailable' })
    await screen.findByText('PC-001')
    expect(lastQuery()).toMatchObject({ status: 'unavailable' })
    expect(screen.getByDisplayValue('⚠️ Недоступные')).toBeInTheDocument()
  })

  it('известный статус в адресной строке применяется, неизвестный — игнорируется', async () => {
    const { unmount } = renderWithProviders(<InventoryPage />, { route: '/?status=maintenance' })
    await screen.findByText('PC-001')
    expect(lastQuery()).toMatchObject({ status: 'maintenance' })
    unmount()
    vi.mocked(api.get).mockClear()
    renderWithProviders(<InventoryPage />, { route: '/?status=foo' })
    await screen.findByText('PC-001')
    expect(lastQuery().status).toBeUndefined()
    expect(screen.getByDisplayValue('Все статусы')).toBeInTheDocument()
  })

  it('селекты и чекбоксы фильтров попадают в запрос, «Все …» сбрасывает', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await screen.findByRole('option', { name: 'Аренда' })

    await user.selectOptions(screen.getByDisplayValue('Все пулы'), 'Без пула (не выдаются)')
    await waitFor(() => expect(lastQuery()).toMatchObject({ pool_id: 'none' }))
    await user.selectOptions(screen.getByDisplayValue('Все статусы'), 'Свободен')
    await waitFor(() => expect(lastQuery()).toMatchObject({ status: 'available' }))
    await user.selectOptions(screen.getByDisplayValue('Все категории'), 'Мощные')
    await waitFor(() => expect(lastQuery()).toMatchObject({ tier: 'powerful' }))
    await user.selectOptions(screen.getByDisplayValue('Все отделы'), 'Разработка')
    await waitFor(() => expect(lastQuery()).toMatchObject({ department_id: 5 }))
    await user.click(screen.getByLabelText('Удалённые из Insight'))
    await waitFor(() => expect(lastQuery()).toMatchObject({ include_archived: true }))

    await user.selectOptions(screen.getByDisplayValue('Свободен'), 'Все статусы')
    await waitFor(() => expect(lastQuery().status).toBeUndefined())
  })

  it('поиск уходит в API с debounce и обрезает пробелы', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await user.type(screen.getByPlaceholderText(/Имя, ключ Insight/), '  pc-7 ')
    await waitFor(() => expect(lastQuery()).toMatchObject({ q: 'pc-7' }))
    expect(new Set(inventoryCalls().map((q) => q.q).filter(Boolean))).toEqual(new Set(['pc-7']))
  })

  it('поля фильтров, поиск и чекбоксы выбора доступны по подписи', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    for (const name of ['Поиск по инвентаризации', 'Фильтр по пулу', 'Фильтр по статусу', 'Фильтр по категории', 'Фильтр по отделу']) {
      expect(screen.getByLabelText(name)).toBeInTheDocument()
    }
    await user.click(screen.getByRole('checkbox', { name: 'Выбрать PC-002' }))
    expect(screen.getByText('Выбрано: 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Пул для перемещения')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Выбрать все на странице' }))
    expect(screen.getByText('Выбрано: 3')).toBeInTheDocument()
  })

  it('режим «список» — компактная таблица, выбор запоминается в localStorage', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    expect(screen.getByText('Характеристики')).toBeInTheDocument()

    await user.click(screen.getByTitle('Списком — только номера'))
    expect(screen.queryByText('Характеристики')).not.toBeInTheDocument()
    expect(screen.getByText('Статус (Портал)')).toBeInTheDocument()
    expect(screen.getByText('PC-002')).toBeInTheDocument()
    expect(localStorage.getItem('hmsrent:view:inventory')).toBe('compact')
    // в компактном режиме тоже видно отдел и ответственного
    expect(screen.getAllByText('Разработка').length).toBeGreaterThan(0)
    expect(screen.getByText('(p.petrov)')).toBeInTheDocument()
  })

  it('клик по строке открывает карточку ПК, клик по чекбоксу — нет', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    const row = (await screen.findByText('PC-002')).closest('tr')!
    await user.click(within(row).getByRole('checkbox'))
    expect(screen.queryByTestId('sheet')).not.toBeInTheDocument()
    await user.click(screen.getByText('PC-002'))
    expect(screen.getByTestId('sheet')).toHaveTextContent('карточка 2')
  })

  it.each([['подробная таблица', false], ['компактная таблица', true]])(
    'с клавиатуры (%s): Tab доходит до имени ПК, Enter открывает карточку, пробел на чекбоксе не открывает',
    async (_name, compact) => {
      const user = userEvent.setup()
      renderWithProviders(<InventoryPage />)
      await screen.findByText('PC-002')
      if (compact) await user.click(screen.getByTitle('Списком — только номера'))
      const row = screen.getByText('PC-002').closest('tr')!
      const box = within(row).getByRole('checkbox')
      box.focus()
      await user.keyboard(' ')
      expect(box).toBeChecked()
      expect(screen.queryByTestId('sheet')).not.toBeInTheDocument()
      await user.tab()
      expect(within(row).getByRole('button', { name: 'PC-002' })).toHaveFocus()
      await user.keyboard('{Enter}')
      expect(screen.getByTestId('sheet')).toHaveTextContent('карточка 2')
    },
  )

  it('выбор строк показывает панель, «выбрать все» и «снять выделение»', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    expect(screen.queryByText(/Выбрано:/)).not.toBeInTheDocument()

    const [all, ...boxes] = tableBoxes()
    await user.click(boxes[0])
    expect(screen.getByText('Выбрано: 1')).toBeInTheDocument()
    await user.click(all)
    expect(screen.getByText('Выбрано: 3')).toBeInTheDocument()
    await user.click(all) // все были выбраны — снимает
    expect(screen.queryByText(/Выбрано:/)).not.toBeInTheDocument()

    await user.click(boxes[1])
    await user.click(screen.getByText('Снять выделение'))
    expect(screen.queryByText(/Выбрано:/)).not.toBeInTheDocument()
  })

  it('отмеченные ПК не сбрасываются таймером поиска, сработавшим без ввода в поиск', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await user.click(tableBoxes()[1])
    expect(screen.getByText('Выбрано: 1')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 400)) // дольше дебаунса поиска в 250 мс
    expect(screen.getByText('Выбрано: 1')).toBeInTheDocument()
  })

  it('перемещение выбранных в пул: POST /admin/pools/assign, тост, сброс выделения', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await screen.findByRole('option', { name: 'Резервный' })
    const boxes = tableBoxes()
    await user.click(boxes[2]) // PC-002
    await user.click(boxes[3]) // PC-003

    const apply = screen.getByRole('button', { name: 'Применить' })
    expect(apply).toBeDisabled() // пул не выбран
    await user.selectOptions(screen.getByDisplayValue('Переместить в пул…'), 'Резервный')
    await user.click(apply)

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/pools/assign', { pool_id: 2, computer_ids: [2, 3] }))
    expect(toast.success).toHaveBeenCalledWith('Перемещено в пул: 2')
    await waitFor(() => expect(screen.queryByText(/Выбрано:/)).not.toBeInTheDocument())
  })

  it('«Убрать из пулов» отправляет pool_id = null', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await user.click(tableBoxes()[1])
    await user.selectOptions(screen.getByDisplayValue('Переместить в пул…'), '— Убрать из пулов')
    await user.click(screen.getByRole('button', { name: 'Применить' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/pools/assign', { pool_id: null, computer_ids: [1] }))
    expect(toast.success).toHaveBeenCalledWith('Убрано из пулов: 2')
  })

  it('ошибка массового перемещения — тост с текстом, выделение остаётся', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('Пул не найден'))
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await screen.findByRole('option', { name: 'Аренда' })
    await user.click(tableBoxes()[1])
    await user.selectOptions(screen.getByDisplayValue('Переместить в пул…'), 'Аренда')
    await user.click(screen.getByRole('button', { name: 'Применить' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Пул не найден'))
    expect(screen.getByText('Выбрано: 1')).toBeInTheDocument()
  })

  it('смена фильтра сбрасывает выделение', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InventoryPage />)
    await screen.findByText('PC-001')
    await user.click(tableBoxes()[1])
    expect(screen.getByText('Выбрано: 1')).toBeInTheDocument()
    await user.selectOptions(screen.getByDisplayValue('Все статусы'), 'Свободен')
    await waitFor(() => expect(screen.queryByText(/Выбрано:/)).not.toBeInTheDocument())
  })

  describe('пагинация', () => {
    beforeEach(() => {
      total = 750 // 8 страниц по 100
    })

    it('показывает диапазон и скользящее окно из 5 страниц', async () => {
      renderWithProviders(<InventoryPage />)
      expect(await screen.findByText('1–100 из 750')).toBeInTheDocument()
      const nums = screen.getAllByRole('button').map((b) => b.textContent).filter((t) => /^\d+$/.test(t ?? ''))
      expect(nums).toEqual(['1', '2', '3', '4', '5'])
      expect(screen.getByRole('button', { name: 'На первую страницу' })).toBeDisabled()
      expect(screen.getByRole('button', { name: '1' })).toHaveAttribute('aria-current', 'page')
    })

    it('переход вперёд/назад, на последнюю и первую страницу меняет offset', async () => {
      const user = userEvent.setup()
      renderWithProviders(<InventoryPage />)
      await screen.findByText('1–100 из 750')

      await user.click(screen.getByRole('button', { name: '3' }))
      await waitFor(() => expect(lastQuery()).toMatchObject({ offset: 200 }))
      expect(await screen.findByText('201–300 из 750')).toBeInTheDocument()

      await user.click(screen.getByTitle('На последнюю страницу'))
      await waitFor(() => expect(lastQuery()).toMatchObject({ offset: 700 }))
      // последняя страница: 701–750, вперёд недоступно, окно сместилось к концу
      expect(await screen.findByText('701–750 из 750')).toBeInTheDocument()
      expect(screen.getByTitle('На последнюю страницу')).toBeDisabled()
      const nums = screen.getAllByRole('button').map((b) => b.textContent).filter((t) => /^\d+$/.test(t ?? ''))
      expect(nums).toEqual(['4', '5', '6', '7', '8'])

      await user.click(screen.getByTitle('На первую страницу'))
      await waitFor(() => expect(lastQuery()).toMatchObject({ offset: 0 }))
    })

    it('смена фильтра возвращает на первую страницу', async () => {
      const user = userEvent.setup()
      renderWithProviders(<InventoryPage />)
      await screen.findByText('1–100 из 750')
      await user.click(screen.getByRole('button', { name: '2' }))
      await screen.findByText('101–200 из 750')
      await user.click(screen.getByLabelText('Только с проблемами'))
      await waitFor(() => expect(lastQuery()).toMatchObject({ offset: 0, issues_only: true }))
    })
  })

  it('«Выгрузить в Excel (CSV)» переходит на экспорт с текущими фильтрами пула и отдела', async () => {
    const assign = vi.fn()
    const original = window.location
    // jsdom: location.assign не реализован — подменяем объект целиком
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, assign } })
    try {
      const user = userEvent.setup()
      renderWithProviders(<InventoryPage />, { route: '/?pool=1' })
      await screen.findByText('PC-001')
      await user.click(screen.getByRole('button', { name: /Выгрузить в Excel/ }))
      expect(assign).toHaveBeenCalledWith('/api/v1/admin/inventory/export?pool_id=1')
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original })
    }
  })
})
