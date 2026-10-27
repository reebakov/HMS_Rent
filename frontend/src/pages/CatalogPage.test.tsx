import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CatalogPage } from './CatalogPage'
import { api } from '@/lib/api'
import { failGetOnce, makeComputer, makeSession, renderWithProviders } from '@/test/helpers'
import type { Computer, TierSummary } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => makeSession() }))

const summary: TierSummary[] = [
  { tier: 'weak', available: 1, total: 1, min_ram_gb: 8, max_ram_gb: 8 },
  { tier: 'medium', available: 2, total: 2, min_ram_gb: 16, max_ram_gb: 32 },
  { tier: 'powerful', available: 1, total: 1, min_ram_gb: 64, max_ram_gb: 64 },
]

let computers: Computer[]

/** Запросы списка ПК — с их query-параметрами, без лишних вызовов других эндпоинтов */
const computerCalls = () =>
  vi.mocked(api.get).mock.calls.filter(([path]) => path === '/computers').map(([, query]) => query)
const lastComputerQuery = () => computerCalls()[computerCalls().length - 1]

let sdEnabled = false // карточка «Сборка по запросу» — только с подключённым Service Desk

beforeEach(() => {
  sdEnabled = false
  computers = [makeComputer({ id: 1, name: 'PC-001' }), makeComputer({ id: 2, name: 'PC-002' }), makeComputer({ id: 3, name: 'PC-003' })]
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/catalog/summary') return summary
    if (path === '/computers') return computers
    if (path === '/departments') return []
    if (path === '/vms/options') return { enabled: false, reason: null }
    if (path === '/requests/config') return { enabled: sdEnabled }
    if (path === '/catalog/order-options') return { os: ['Ubuntu 24.04'], builds: ['A — i5'] }
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('CatalogPage', () => {
  it('по умолчанию запрашивает категорию «Средние» и рисует список с счётчиком', async () => {
    renderWithProviders(<CatalogPage />)
    expect(await screen.findByText('PC-001')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Средние' })).toBeInTheDocument()
    expect(screen.getByText('3 компьютера доступно')).toBeInTheDocument()
    expect(lastComputerQuery()).toMatchObject({ tier: 'medium', sort: 'name' })
  })

  it('элементы каталога, на которые указывает обучение, помечены data-tour', async () => {
    sdEnabled = true
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')
    await screen.findByText('Сборка по запросу')
    for (const tour of ['categories', 'filters', 'list', 'actions']) expect(document.querySelector(`[data-tour="${tour}"]`)).not.toBeNull()
  })

  it('в адресной строке gpu=integrated — встроенная видеокарта, неизвестное значение игнорируется', async () => {
    renderWithProviders(<CatalogPage />, { route: '/?gpu=integrated' })
    await screen.findByText('PC-001')
    expect(lastComputerQuery()).toMatchObject({ gpu: 'integrated' })
    expect(screen.getByRole('combobox', { name: 'Видеокарта' })).toHaveValue('integrated')
    renderWithProviders(<CatalogPage />, { route: '/?gpu=any' })
    await waitFor(() => expect(lastComputerQuery()?.gpu).toBeUndefined())
  })

  it('фильтры читаются из адресной строки (gpu=1 из старых ссылок — дискретная)', async () => {
    renderWithProviders(<CatalogPage />, { route: '/?tier=powerful&q=rtx&min_ram=32&gpu=1&sort=ram_desc' })
    await screen.findByText('PC-001')
    expect(lastComputerQuery()).toEqual({
      tier: 'powerful', q: 'rtx', min_ram: 32, gpu: 'discrete', sort: 'ram_desc',
    })
    expect(screen.getByPlaceholderText(/Имя, процессор/)).toHaveValue('rtx')
  })

  it('неизвестные tier и sort в адресной строке заменяются значениями по умолчанию, страница не падает', async () => {
    renderWithProviders(<CatalogPage />, { route: '/?tier=foo&sort=bar' })
    expect(await screen.findByText('PC-001')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Средние' })).toBeInTheDocument()
    expect(lastComputerQuery()).toMatchObject({ tier: 'medium', sort: 'name' })
    expect(screen.getByDisplayValue('По имени')).toBeInTheDocument()
  })

  it('поиск и фильтры доступны по подписи и роли', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')
    expect(screen.getByRole('textbox', { name: 'Поиск по каталогу' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Минимум ОЗУ' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Сортировка' })).toBeInTheDocument()
    const gpu = screen.getByRole('combobox', { name: 'Видеокарта' })
    expect(gpu).toHaveValue('')
    await user.selectOptions(gpu, 'Встроенная')
    expect(screen.getByRole('combobox', { name: 'Видеокарта' })).toHaveValue('integrated')
  })

  it('поиск уходит в API с задержкой (debounce), а не на каждую букву', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')

    await user.type(screen.getByPlaceholderText(/Имя, процессор/), 'ryzen')
    await waitFor(() => expect(lastComputerQuery()).toMatchObject({ q: 'ryzen' }))
    // промежуточные значения («r», «ry» …) в API не отправлялись
    const sentQueries = computerCalls().map((q) => q?.q).filter(Boolean)
    expect(new Set(sentQueries)).toEqual(new Set(['ryzen']))
  })

  it('выбор «ОЗУ от 32 ГБ» и сортировки меняет параметры запроса', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')

    await user.selectOptions(screen.getByDisplayValue('Любая ОЗУ'), 'ОЗУ от 32 ГБ')
    await waitFor(() => expect(lastComputerQuery()).toMatchObject({ min_ram: 32 }))

    await user.selectOptions(screen.getByDisplayValue('По имени'), 'Сначала мощнее')
    await waitFor(() => expect(lastComputerQuery()).toMatchObject({ min_ram: 32, sort: 'ram_desc' }))

    await user.selectOptions(screen.getByDisplayValue('ОЗУ от 32 ГБ'), 'Любая ОЗУ')
    await waitFor(() => expect(lastComputerQuery()?.min_ram).toBeUndefined())
  })

  it('выбор «Дискретная» и «Встроенная» уходит в API как gpu, «Любая» снимает фильтр', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')
    const select = screen.getByRole('combobox', { name: 'Видеокарта' })
    expect(select).toHaveTextContent('Любая видеокарта')

    await user.selectOptions(select, 'Дискретная')
    await waitFor(() => expect(lastComputerQuery()).toMatchObject({ gpu: 'discrete' }))
    await user.selectOptions(select, 'Встроенная')
    await waitFor(() => expect(lastComputerQuery()).toMatchObject({ gpu: 'integrated' }))
    await user.selectOptions(select, 'Любая видеокарта')
    await waitFor(() => expect(lastComputerQuery()?.gpu).toBeUndefined())
  })

  it('в категории ВМ фильтра по видеокарте нет', async () => {
    renderWithProviders(<CatalogPage />, { route: '/?tier=vm' })
    await screen.findByText('PC-001')
    expect(screen.queryByRole('combobox', { name: 'Видеокарта' })).not.toBeInTheDocument()
  })

  it('смена категории по клику на карточку', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await user.click(await screen.findByRole('button', { name: /Мощные/ }))
    await waitFor(() => expect(lastComputerQuery()).toMatchObject({ tier: 'powerful' }))
    expect(screen.getByRole('heading', { name: 'Мощные' })).toBeInTheDocument()
  })

  it('пустая выдача -> заглушка, «Сбросить фильтры» очищает поиск и фильтры', async () => {
    const user = userEvent.setup()
    computers = []
    renderWithProviders(<CatalogPage />, { route: '/?tier=weak&q=nothing&gpu=1' })
    expect(await screen.findByText('Свободных компьютеров не найдено')).toBeInTheDocument()
    expect(screen.getByText('0 компьютеров доступно')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }))
    await waitFor(() => expect(screen.getByPlaceholderText(/Имя, процессор/)).toHaveValue(''))
    await waitFor(() => {
      const q = lastComputerQuery()
      expect(q?.q).toBeUndefined()
      expect(q?.gpu).toBeUndefined()
      expect(q?.tier).toBe('weak')
    })
  })

  it('ошибка загрузки списка ПК: текст ошибки и «Повторить», счётчик «0 компьютеров» не показывается; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/computers')
    renderWithProviders(<CatalogPage />)
    expect(await screen.findByText('Не удалось загрузить компьютеры')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Свободных компьютеров не найдено')).not.toBeInTheDocument()
    expect(screen.queryByText(/компьютер\S* доступно/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-001')).toBeInTheDocument()
    expect(screen.getByText('3 компьютера доступно')).toBeInTheDocument()
  })

  it('ошибка загрузки категорий: текст ошибки и «Повторить» вместо вечных скелетонов; повтор показывает карточки', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/catalog/summary')
    renderWithProviders(<CatalogPage />)
    expect(await screen.findByText('Не удалось загрузить категории')).toBeInTheDocument()
    expect(screen.getByText('PC-001')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('button', { name: /Мощные/ })).toBeInTheDocument()
  })

  it('клик «Забронировать» открывает диалог бронирования выбранного ПК', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-002')
    await user.click(screen.getAllByRole('button', { name: /Забронировать/ })[1])
    expect(await screen.findByRole('dialog', { name: 'Бронирование PC-002' })).toBeInTheDocument()
  })

  it('переключатель вида запоминается и включает компактный список', async () => {
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')
    await user.click(screen.getByTitle('Списком — только номера'))
    expect(localStorage.getItem('hmsrent:view:catalog')).toBe('compact')
    expect(screen.queryByRole('button', { name: 'Подробнее' })).not.toBeInTheDocument()
  })
})

describe('CatalogPage: сборка по запросу', () => {
  it('без Service Desk карточки нет; с ним — открывает форму сборки', async () => {
    renderWithProviders(<CatalogPage />)
    await screen.findByText('PC-001')
    expect(screen.queryByRole('button', { name: /Сборка по запросу/ })).not.toBeInTheDocument()
  })

  it('с Service Desk карточка открывает форму', async () => {
    sdEnabled = true
    const user = userEvent.setup()
    renderWithProviders(<CatalogPage />)
    await user.click(await screen.findByRole('button', { name: /Сборка по запросу/ }))
    expect(await screen.findByRole('dialog', { name: 'Сборка по запросу' })).toBeInTheDocument()
  })
})
