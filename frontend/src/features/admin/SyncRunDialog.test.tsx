import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SyncRunDialog } from './SyncRunDialog'
import { api } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { SyncRunDetails } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const STARTED = '2026-10-01T09:30:00Z'
let details: SyncRunDetails

beforeEach(() => {
  details = {
    id: 7,
    started_at: STARTED,
    updated: [
      { id: 1, name: 'PC-001', changes: [{ field: 'RAM', old: '8', new: '16' }, { field: 'Статус', old: 'Ожидает', new: 'Используется' }] },
      { id: 2, name: 'PC-002', changes: [] },
    ],
    created: [{ id: 3, name: 'PC-003' }, { id: 4, name: 'PC-004' }],
    archived: [{ id: 5, name: 'PC-005' }],
  }
  vi.mocked(api.get).mockReset().mockImplementation(async (path: string) => {
    if (path === '/admin/sync/runs/7') return details
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('SyncRunDialog', () => {
  it('закрыт (runId = null): ничего не рисует и не грузит данные', () => {
    renderWithProviders(<SyncRunDialog runId={null} tab="updated" onClose={() => undefined} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalled()
  })

  it('загрузка: спиннер вместо списка, запрос GET /admin/sync/runs/{id}', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    renderWithProviders(<SyncRunDialog runId={7} tab="updated" onClose={() => undefined} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/sync/runs/7')
    expect(screen.getByText('Изменено: 0')).toBeInTheDocument()
    expect(screen.queryByText(/Подробностей нет/)).not.toBeInTheDocument()
  })

  it('«Изменено»: у каждого ПК список «поле: было → стало»', async () => {
    renderWithProviders(<SyncRunDialog runId={7} tab="updated" onClose={() => undefined} />)
    expect(await screen.findByText('Изменено: 2')).toBeInTheDocument()
    expect(screen.getByText(`Синхронизация ${formatDateTime(STARTED)}`)).toBeInTheDocument()

    const pc1 = screen.getByText('PC-001').parentElement as HTMLElement
    const items = within(pc1).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('RAM:8→16')
    expect(within(items[0]).getByText('8')).toHaveClass('line-through')
    expect(within(items[0]).getByText('16')).toBeInTheDocument()
    expect(items[1]).toHaveTextContent('Статус:Ожидает→Используется')
  })

  it('«Изменено» без списка изменений: пояснение про архив и служебные поля', async () => {
    renderWithProviders(<SyncRunDialog runId={7} tab="updated" onClose={() => undefined} />)
    await screen.findByText('PC-002')
    const pc2 = screen.getByText('PC-002').parentElement as HTMLElement
    expect(within(pc2).queryByRole('listitem')).not.toBeInTheDocument()
    expect(within(pc2).getByText('Вернулся из архива или изменились служебные поля')).toBeInTheDocument()
  })

  it.each([
    ['created', 'Новые ПК: 2', ['PC-003', 'PC-004'], ['PC-001', 'PC-005']],
    ['archived', 'Ушли в архив: 1', ['PC-005'], ['PC-001', 'PC-003']],
  ] as const)('вкладка %s: заголовок со счётчиком и только свои названия, без «было → стало»', async (tab, title, shown, hidden) => {
    renderWithProviders(<SyncRunDialog runId={7} tab={tab} onClose={() => undefined} />)
    expect(await screen.findByText(title)).toBeInTheDocument()
    for (const name of shown) expect(screen.getByText(name)).toBeInTheDocument()
    for (const name of hidden) expect(screen.queryByText(name)).not.toBeInTheDocument()
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
    expect(screen.queryByText('→')).not.toBeInTheDocument()
  })

  it.each(['updated', 'created', 'archived'] as const)('пустой список (%s): «Подробностей нет»', async (tab) => {
    details = { ...details, updated: [], created: [], archived: [] }
    renderWithProviders(<SyncRunDialog runId={7} tab={tab} onClose={() => undefined} />)
    expect(await screen.findByText(/Подробностей нет/)).toBeInTheDocument()
    expect(screen.getByText(/: 0$/)).toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо «Подробностей нет»; повтор перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/sync/runs/7', 'Запуск не найден')
    renderWithProviders(<SyncRunDialog runId={7} tab="created" onClose={() => undefined} />)
    expect(await screen.findByText('Не удалось загрузить подробности запуска')).toBeInTheDocument()
    expect(screen.getByText('Запуск не найден')).toBeInTheDocument()
    expect(screen.queryByText(/Подробностей нет/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('PC-003')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('закрытие по Escape и по крестику вызывает onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<SyncRunDialog runId={7} tab="created" onClose={onClose} />)
    await screen.findByText('PC-003')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))

    const dialog = screen.getByRole('dialog')
    const x = within(dialog).getAllByRole('button').find((b) => !b.textContent)!
    await user.click(x)
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(2))
  })
})
