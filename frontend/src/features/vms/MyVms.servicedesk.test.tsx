import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MyVms } from './MyVms'
import { api } from '@/lib/api'
import { useSdConfig } from '@/lib/queries'
import { renderWithProviders } from '@/test/helpers'
import type { ServiceRequest, Vm } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeVm = (over: Partial<Vm> = {}): Vm => ({
  id: 1,
  order_number: 200,
  name: 'rent-design-01',
  cpu: 4,
  ram_gb: 8,
  disk_gb: 80,
  template_key: null,
  os_label: null,
  status: 'ready',
  error: null,
  department: { id: 1, name: 'Разработка' },
  user: { id: 1, username: 'i.ivanov', display_name: 'Иван Иванов' },
  requester_name: 'Иван Иванов',
  requester_nick: 'iivanov',
  purpose: null,
  expected_return_at: null,
  ip_address: '10.0.0.15',
  power_state: 'on',
  created_at: '2024-01-10T09:00:00Z',
  ready_at: '2024-01-10T09:10:00Z',
  released_at: null,
  deleted_at: null,
  ...over,
})

const makeRequest = (over: Partial<ServiceRequest> = {}): ServiceRequest => ({
  id: 5,
  kind: 'problem',
  booking_id: null,
  vm_id: 1,
  issue_key: 'HMS-101',
  summary: 'Нет интернета',
  status: 'В работе',
  status_category: 'indeterminate',
  error: null,
  created_at: '2024-01-10T09:00:00Z',
  url: null,
  ...over,
})

let vms: Vm[]
let sdEnabled: boolean

beforeEach(() => {
  vms = []
  sdEnabled = true
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/vms/my') return vms
    if (path === '/requests/config') return { enabled: sdEnabled }
    throw new Error(`неожиданный GET ${path}`)
  })
})

/** Маркер «конфиг Service Desk уже загружен» — по нему проверяем отсутствие кнопки */
const CfgProbe = () => <span data-testid="cfg">{useSdConfig().isFetched ? 'loaded' : 'loading'}</span>
const cfgLoaded = () => waitFor(() => expect(screen.getByTestId('cfg')).toHaveTextContent('loaded'))

/** Строка виртуалки по имени */
const rowOf = (name: string) => screen.getByText(name).closest('.flex-wrap') as HTMLElement

async function renderVms(list: Vm[], props: Parameters<typeof MyVms>[0] = {}) {
  vms = list
  renderWithProviders(<><MyVms {...props} /><CfgProbe /></>)
  await screen.findByText(list[0].name)
}

describe('MyVms: ОС и заявки Service Desk', () => {
  it('шаблон ОС выводится перед параметрами, без шаблона — как раньше', async () => {
    await renderVms([makeVm({ os_label: 'Windows 10' }), makeVm({ id: 2, name: 'rent-old', os_label: null })])
    expect(screen.getByText('Windows 10 · 4 ядра · 8 ГБ · 80 ГБ · Разработка')).toBeInTheDocument()
    expect(screen.getByText('4 ядра · 8 ГБ · 80 ГБ · Разработка')).toBeInTheDocument()
  })

  it('без пропсов заявок нет ни бейджей, ни кнопки «Сообщить о проблеме»', async () => {
    await renderVms([makeVm()])
    await cfgLoaded()
    expect(screen.queryByRole('button', { name: /Заявка|Возврат|Сообщить о проблеме/ })).not.toBeInTheDocument()
  })

  it('requestsFor запрашивается для каждой ВМ; бейджи заявок видны, клик открывает заявку', async () => {
    const user = userEvent.setup()
    const onOpenRequest = vi.fn()
    const requestsFor = vi.fn((vmId: number) => (vmId === 1 ? [makeRequest({ id: 5 }), makeRequest({ id: 6, issue_key: 'HMS-102', status: 'Выполнено', status_category: 'done' })] : []))
    await renderVms([makeVm({ id: 1 }), makeVm({ id: 2, name: 'rent-qa-02' })], { requestsFor, onOpenRequest })

    expect(requestsFor).toHaveBeenCalledWith(1)
    expect(requestsFor).toHaveBeenCalledWith(2)
    const first = within(rowOf('rent-design-01'))
    expect(first.getByRole('button', { name: 'Заявка HMS-101 · В работе' })).toBeInTheDocument()
    expect(first.getByRole('button', { name: 'Заявка HMS-102 · Выполнено' })).toBeInTheDocument()
    expect(within(rowOf('rent-qa-02')).queryByRole('button', { name: /Заявка/ })).not.toBeInTheDocument()

    await user.click(first.getByRole('button', { name: 'Заявка HMS-102 · Выполнено' }))
    expect(onOpenRequest).toHaveBeenCalledWith(6)
  })

  it('«Сообщить о проблеме» передаёт выбранную ВМ', async () => {
    const user = userEvent.setup()
    const onReport = vi.fn()
    const second = makeVm({ id: 2, name: 'rent-qa-02' })
    await renderVms([makeVm({ id: 1 }), second], { onReport })
    await user.click(await within(rowOf('rent-qa-02')).findByRole('button', { name: 'Сообщить о проблеме' }))
    expect(onReport).toHaveBeenCalledOnce()
    expect(onReport).toHaveBeenCalledWith(second)
  })

  it('Service Desk выключен — кнопки нет, бейджи существующих заявок остаются', async () => {
    sdEnabled = false
    await renderVms([makeVm()], { onReport: vi.fn(), requestsFor: () => [makeRequest()] })
    await cfgLoaded()
    expect(screen.getByRole('button', { name: 'Заявка HMS-101 · В работе' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
  })

  it.each([
    ['ready', true],
    ['failed', true],
    ['queued', true],
    ['creating', true],
    ['deleting', false],
  ] as const)('статус %s — кнопка «Сообщить о проблеме»: %s', async (status, shown) => {
    await renderVms([makeVm({ status, ip_address: null })], { onReport: vi.fn() })
    if (shown) {
      expect(await screen.findByRole('button', { name: 'Сообщить о проблеме' })).toBeInTheDocument()
    } else {
      await cfgLoaded()
      expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
    }
  })
})
