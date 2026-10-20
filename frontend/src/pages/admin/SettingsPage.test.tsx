import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { SettingsPage } from './SettingsPage'
import { api, ApiError } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { AppSettings, VmTemplate } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

const WIN: VmTemplate = { key: 'win11', label: 'Windows 11', os: 'windows', template: 'Template_Win11', customization_spec: '', min_disk_gb: 80, enabled: true }
const LIN: VmTemplate = { key: 'ubuntu', label: 'Ubuntu', os: 'linux', template: '', customization_spec: '', min_disk_gb: 40, enabled: false }

const makeSettings = (over: Partial<AppSettings> = {}): AppSettings => ({
  insight_sync_interval_min: 15, insight_writeback: true, vm_enabled: true,
  vm_min_cpu: 1, vm_max_cpu: 16, vm_min_ram_gb: 2, vm_max_ram_gb: 64, vm_max_per_user: 3,
  vm_min_disk_gb: 50, vm_max_disk_gb: 500, catalog_refresh_sec: 60,
  vm_templates: [WIN, LIN], vm_sizes: [{ label: 'S', cpu: 2, ram_gb: 4, disk_gb: 50 }],
  pc_os_list: ['Ubuntu 24.04'], pc_builds: ['A — i5, 16 ГБ'], vsphere_configured: true, vcenter_host: 'vc.example.com', ...over,
})

let settings: AppSettings
const save = () => screen.getByRole('button', { name: 'Сохранить' })
// первая таблица на странице — шаблоны ОС (ниже — готовые размеры ВМ)
const tplRows = () => within(screen.getAllByRole('table')[0]).getAllByRole('row')
const tplRow = (i: number) => tplRows()[i + 1]
const patchBody = () => vi.mocked(api.patch).mock.calls[vi.mocked(api.patch).mock.calls.length - 1][1] as Record<string, unknown>

beforeEach(() => {
  settings = makeSettings()
  for (const m of [api.get, api.post, api.patch, api.del]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/admin/settings') return settings
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.patch).mockImplementation(async (_p: string, body: unknown) => {
    settings = { ...settings, ...(body as Partial<AppSettings>) }
    return settings
  })
})

describe('SettingsPage: загрузка и отображение', () => {
  it('пока настройки не пришли — скелетон, формы нет', () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => undefined))
    const { container } = renderWithProviders(<SettingsPage />)
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить» вместо вечного скелетона; повтор показывает форму', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/settings')
    const { container } = renderWithProviders(<SettingsPage />)
    expect(await screen.findByText('Не удалось загрузить настройки')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByLabelText(/^Интервал синхронизации, минут/)).toHaveValue(15)
  })

  it('показывает значения настроек и шаблоны ОС; «Сохранить» неактивна без правок', async () => {
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByLabelText(/^Интервал синхронизации, минут/)).toHaveValue(15)
    expect(screen.getByLabelText(/^Ядер до/)).toHaveValue(16)
    expect(screen.getByText('vCenter: vc.example.com')).toBeInTheDocument()
    expect(screen.getByText('Шаблоны ОС для виртуалок')).toBeInTheDocument()
    expect(tplRows()).toHaveLength(3)
    expect(within(tplRow(0)).getByDisplayValue('Windows 11')).toBeInTheDocument()
    expect(within(tplRow(1)).getByDisplayValue('Ubuntu')).toBeInTheDocument()
    expect(save()).toBeDisabled()
  })

  it('старый ответ без vm_templates: редактор пуст, страница не падает', async () => {
    settings = makeSettings({ vm_templates: undefined as never })
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    expect(tplRows()).toHaveLength(1)
  })
})

describe('SettingsPage: сохранение шаблонов ОС', () => {
  it('правка шаблона активирует «Сохранить»; PATCH /admin/settings содержит vm_templates, остальные настройки на месте', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    fireEvent.change(within(tplRow(1)).getByPlaceholderText('например Template_Win11'), { target: { value: 'Template_Ubuntu' } })
    await user.click(within(tplRow(1)).getByRole('checkbox'))
    expect(save()).toBeEnabled()
    await user.click(save())

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.patch).mock.calls[0][0]).toBe('/admin/settings')
    const { vm_templates, ...rest } = patchBody()
    expect(vm_templates).toEqual([WIN, { ...LIN, template: 'Template_Ubuntu', enabled: true }])
    const { vm_templates: _t, vsphere_configured: _v, vcenter_host: _h, ...original } = makeSettings()
    expect(rest).toEqual({ ...original, vm_templates: undefined }) // всё остальное не затёрто
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Настройки сохранены и уже действуют'))
  })

  it('в PATCH не уходят служебные поля vsphere_configured и vcenter_host', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText(/^Ядер до/), { target: { value: '32' } })
    await user.click(save())
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(patchBody()).not.toHaveProperty('vsphere_configured')
    expect(patchBody()).not.toHaveProperty('vcenter_host')
    expect(patchBody()).toMatchObject({ vm_max_cpu: 32, vm_templates: [WIN, LIN] })
  })

  it('добавление и удаление ОС попадают в PATCH', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    await user.click(screen.getByRole('button', { name: 'Добавить ОС' }))
    await user.click(within(tplRow(0)).getByTitle('Удалить'))
    await user.click(save())
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect((patchBody().vm_templates as VmTemplate[]).map((t) => t.key)).toEqual(['ubuntu', 'os3'])
  })

  it('возврат шаблона к исходному значению снова блокирует «Сохранить»', async () => {
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    const label = within(tplRow(0)).getByDisplayValue('Windows 11')
    fireEvent.change(label, { target: { value: 'Win' } })
    expect(save()).toBeEnabled()
    fireEvent.change(label, { target: { value: 'Windows 11' } })
    expect(save()).toBeDisabled()
  })

  it('после сохранения настройки перезапрашиваются, кнопка снова неактивна', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    const getsBefore = vi.mocked(api.get).mock.calls.length
    fireEvent.change(within(tplRow(0)).getByDisplayValue('Windows 11'), { target: { value: 'Win 11 Pro' } })
    await user.click(save())
    await waitFor(() => expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(getsBefore))
    await waitFor(() => expect(save()).toBeDisabled())
    expect(within(tplRow(0)).getByDisplayValue('Win 11 Pro')).toBeInTheDocument()
  })

  it('ошибка сохранения: тост с сообщением сервера, правки остаются, кнопка доступна для повтора', async () => {
    vi.mocked(api.patch).mockRejectedValue(new ApiError(422, 'Ключ шаблона должен быть уникальным'))
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    fireEvent.change(within(tplRow(0)).getByDisplayValue('Windows 11'), { target: { value: 'Broken' } })
    await user.click(save())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Ключ шаблона должен быть уникальным'))
    expect(toast.success).not.toHaveBeenCalled()
    expect(within(tplRow(0)).getByDisplayValue('Broken')).toBeInTheDocument()
    await waitFor(() => expect(save()).toBeEnabled())
  })

  it('не-Error в отказе: тост «Ошибка»', async () => {
    vi.mocked(api.patch).mockRejectedValue('boom')
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('Шаблоны ОС для виртуалок')
    await user.click(within(tplRow(0)).getByRole('checkbox'))
    await user.click(save())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Ошибка'))
  })
})

describe('SettingsPage: остальные настройки', () => {
  it('число правится и уходит числом; переключатели меняют булевы поля', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    fireEvent.change(await screen.findByLabelText(/^Интервал синхронизации, минут/), { target: { value: '30' } })
    await user.click(screen.getByRole('checkbox', { name: /Запись статусов в Insight/ }))
    await user.click(screen.getByRole('checkbox', { name: /Конструктор включён/ }))
    await user.click(save())
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ insight_sync_interval_min: 30, insight_writeback: false, vm_enabled: false, vm_templates: [WIN, LIN] })
  })
})

describe('SettingsPage: проверка vCenter', () => {
  const check = () => screen.getByRole('button', { name: 'Проверить' })

  it('vCenter не настроен: подсказка про .env и неактивная кнопка', async () => {
    settings = makeSettings({ vsphere_configured: false, vcenter_host: '' })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText('vCenter не настроен — впишите VCENTER_* в .env')).toBeInTheDocument()
    expect(check()).toBeDisabled()
  })

  it('успех: POST /admin/vsphere/check и сводка по найденному', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true, datacenter: 'DC1', pool: 'Pool1', template: 'Template_Win11', template_cpu: 4, template_ram_gb: 8, template_disk_gb: 60 })
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('vCenter: vc.example.com')
    await user.click(check())
    expect(await screen.findByText('Всё найдено: DC1 → Pool1, шаблон Template_Win11 (4 CPU, 8 ГБ, диск 60 ГБ)')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/admin/vsphere/check')
  })

  it('неуспех: текст ошибки от vCenter', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: false, error: 'Шаблон Template_Win11 не найден' })
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('vCenter: vc.example.com')
    await user.click(check())
    expect(await screen.findByText('Шаблон Template_Win11 не найден')).toBeInTheDocument()
    expect(screen.queryByText(/Всё найдено/)).not.toBeInTheDocument()
  })

  it('проверка не делает PATCH и не затрагивает форму', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: false, error: 'x' })
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    await screen.findByText('vCenter: vc.example.com')
    await user.click(check())
    await screen.findByText('x')
    expect(api.patch).not.toHaveBeenCalled()
    expect(save()).toBeDisabled()
  })
})

describe('SettingsPage: готовые размеры ВМ', () => {
  it('размер правится и уходит в PATCH вместе с остальными изменениями', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    const cpu = await screen.findByLabelText('Ядра, строка 1')
    expect(cpu).toHaveValue(2)
    fireEvent.change(cpu, { target: { value: '3' } })
    await user.click(save())
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(patchBody().vm_sizes).toEqual([{ label: 'S', cpu: 3, ram_gb: 4, disk_gb: 50 }])
  })
})

describe('SettingsPage: заказ физического ПК', () => {
  it('списки ОС и сборок правятся построчно; пустые строки и пробелы не сохраняются', async () => {
    const user = userEvent.setup()
    renderWithProviders(<SettingsPage />)
    const os = await screen.findByLabelText(/^Операционные системы/)
    expect(os).toHaveValue('Ubuntu 24.04')
    fireEvent.change(os, { target: { value: 'Ubuntu 24.04\n\n  Debian 12  \n' } })
    await user.click(save())
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    expect(patchBody().pc_os_list).toEqual(['Ubuntu 24.04', 'Debian 12'])
    expect(patchBody().pc_builds).toEqual(['A — i5, 16 ГБ'])
  })
})
