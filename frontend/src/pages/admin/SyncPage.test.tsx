import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { SyncPage } from './SyncPage'
import { api, ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'
import { renderWithProviders } from '@/test/helpers'
import type { SyncInfo, SyncRun, SyncRunDetails } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

const makeRun = (over: Partial<SyncRun> = {}): SyncRun => ({
  id: 1, started_at: '2026-10-02T10:00:00Z', finished_at: '2026-10-02T10:01:00Z', status: 'success', mode: 'live',
  total: 120, created: 3, updated: 5, archived: 0, error: null, ...over,
})
const OK_RUN = makeRun()
const FAILED_RUN = makeRun({ id: 2, started_at: '2026-10-01T10:00:00Z', status: 'failed', total: 0, created: 0, updated: 0, archived: 0, error: 'Jira недоступна' })
const ARCHIVE_RUN = makeRun({ id: 3, started_at: '2026-09-30T10:00:00Z', total: 77, created: 0, updated: 0, archived: 4 })

const details: SyncRunDetails = {
  id: 1,
  started_at: OK_RUN.started_at,
  updated: [{ id: 1, name: 'PC-001', changes: [{ field: 'RAM', old: '8', new: '16' }] }],
  created: [{ id: 2, name: 'PC-NEW-1' }, { id: 3, name: 'PC-NEW-2' }, { id: 4, name: 'PC-NEW-3' }],
  archived: [{ id: 5, name: 'PC-OLD' }],
}

let info: SyncInfo

const rowOf = (run: SyncRun) => screen.getByText(formatDateTime(run.started_at)).closest('tr') as HTMLElement

beforeEach(() => {
  info = { mode: 'live', jira_url: 'https://jira.example.com', interval_sec: 900, writeback: true, runs: [OK_RUN, FAILED_RUN, ARCHIVE_RUN] }
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/sync') return info
    if (path === '/admin/sync/runs/1') return details
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue(OK_RUN)
})

describe('SyncPage: состояние и таблица', () => {
  it('карточки: источник, Jira, интервал в минутах, запись в Insight', async () => {
    renderWithProviders(<SyncPage />)
    expect(await screen.findByText('Jira Insight')).toBeInTheDocument()
    expect(screen.getByText('https://jira.example.com')).toBeInTheDocument()
    expect(screen.getByText('каждые 15 мин')).toBeInTheDocument()
    expect(screen.getByText('Включена')).toBeInTheDocument()
  })

  it('mock-режим и выключенная запись', async () => {
    info = { ...info, mode: 'mock', writeback: false }
    renderWithProviders(<SyncPage />)
    expect(await screen.findByText('Демо-данные (mock)')).toBeInTheDocument()
    expect(screen.getByText('Выключена')).toBeInTheDocument()
  })

  it('пока данные не пришли — скелетоны вместо значений и пустая таблица', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    const { container } = renderWithProviders(<SyncPage />)
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(4)
    expect(screen.getByRole('button', { name: 'Синхронизировать сейчас' })).toBeEnabled()
    expect(screen.getAllByRole('row')).toHaveLength(1)
  })

  it('таблица запусков: результат, число объектов, ошибка', async () => {
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    expect(screen.getAllByRole('row')).toHaveLength(4)

    const ok = within(rowOf(OK_RUN))
    expect(ok.getByText('Успешно')).toBeInTheDocument()
    expect(ok.getByText('120')).toBeInTheDocument()

    const failed = within(rowOf(FAILED_RUN))
    expect(failed.getByText('Ошибка')).toBeInTheDocument()
    expect(failed.getByText('Jira недоступна')).toHaveAttribute('title', 'Jira недоступна')
  })

  it('счётчик больше нуля — кнопка, ноль — просто текст', async () => {
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    const ok = within(rowOf(OK_RUN))
    expect(ok.getByRole('button', { name: '3' })).toBeInTheDocument()
    expect(ok.getByRole('button', { name: '5' })).toBeInTheDocument()
    expect(ok.queryByRole('button', { name: '0' })).not.toBeInTheDocument() // «В архив» = 0
    expect(within(rowOf(FAILED_RUN)).queryAllByRole('button')).toHaveLength(0)
    expect(within(rowOf(ARCHIVE_RUN)).getAllByRole('button')).toHaveLength(1)
  })
})

describe('SyncPage: детали запуска', () => {
  it('клик по «Новых» запрашивает запуск и показывает новые ПК', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    expect(api.get).not.toHaveBeenCalledWith('/admin/sync/runs/1')
    await user.click(within(rowOf(OK_RUN)).getByRole('button', { name: '3' }))
    expect(await screen.findByText('Новые ПК: 3')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/sync/runs/1')
    const dialog = screen.getByRole('dialog')
    for (const n of ['PC-NEW-1', 'PC-NEW-2', 'PC-NEW-3']) expect(within(dialog).getByText(n)).toBeInTheDocument()
  })

  it('клик по «Изменено» показывает «было → стало»', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    await user.click(within(rowOf(OK_RUN)).getByRole('button', { name: '5' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('PC-001')).toBeInTheDocument()
    expect(within(dialog).getByText('Изменено: 1')).toBeInTheDocument()
    expect(within(dialog).getByRole('listitem')).toHaveTextContent('RAM:8→16')
  })

  it('клик по «В архив» открывает вкладку архива', async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === '/admin/sync') return info
      if (path === '/admin/sync/runs/3') return { ...details, id: 3 }
      throw new Error(`неожиданный GET ${path}`)
    })
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(ARCHIVE_RUN.started_at))
    await user.click(within(rowOf(ARCHIVE_RUN)).getByRole('button', { name: '4' }))
    expect(await screen.findByText('Ушли в архив: 1')).toBeInTheDocument()
    expect(screen.getByText('PC-OLD')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/sync/runs/3')
  })

  it('диалог закрывается по Escape', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    await user.click(within(rowOf(OK_RUN)).getByRole('button', { name: '3' }))
    await screen.findByText('PC-NEW-1')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('до клика диалога нет', async () => {
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('SyncPage: «Синхронизировать сейчас»', () => {
  const runNowButton = () => screen.getByRole('button', { name: 'Синхронизировать сейчас' })

  it('успех: POST /admin/sync, тост с итогами и перезапрос списка запусков', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await screen.findByText(formatDateTime(OK_RUN.started_at))
    const before = vi.mocked(api.get).mock.calls.filter(([p]) => p === '/admin/sync').length
    await user.click(runNowButton())
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/admin/sync'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Готово: 120 объектов, новых 3, изменено 5'))
    await waitFor(() => expect(vi.mocked(api.get).mock.calls.filter(([p]) => p === '/admin/sync').length).toBeGreaterThan(before))
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('запуск завершился с ошибкой: тост с текстом ошибки запуска', async () => {
    vi.mocked(api.post).mockResolvedValue(makeRun({ status: 'failed', error: 'Insight вернул 500' }))
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await user.click(runNowButton())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Insight вернул 500'))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('запуск failed без текста ошибки: общий тост', async () => {
    vi.mocked(api.post).mockResolvedValue(makeRun({ status: 'failed', error: null }))
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await user.click(runNowButton())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Синхронизация завершилась с ошибкой'))
  })

  it('конфликт 409 (синхронизация уже идёт): тост с сообщением сервера', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Синхронизация уже выполняется'))
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await user.click(runNowButton())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Синхронизация уже выполняется'))
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('не-Error в отказе: тост «Ошибка»', async () => {
    vi.mocked(api.post).mockRejectedValue('boom')
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await user.click(runNowButton())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Ошибка'))
  })

  it('пока запрос идёт, кнопка заблокирована и повторный клик не шлёт второй POST', async () => {
    let finish!: (r: SyncRun) => void
    vi.mocked(api.post).mockReturnValue(new Promise((r) => (finish = r as never)))
    const user = userEvent.setup()
    renderWithProviders(<SyncPage />)
    await user.click(runNowButton())
    await waitFor(() => expect(runNowButton()).toBeDisabled())
    await user.click(runNowButton())
    expect(api.post).toHaveBeenCalledTimes(1)
    finish(OK_RUN)
    await waitFor(() => expect(runNowButton()).toBeEnabled())
  })
})
