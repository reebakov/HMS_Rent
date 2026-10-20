import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { MyVms } from './MyVms'
import { api, ApiError } from '@/lib/api'
import { useSdConfig } from '@/lib/queries'
import { formatDate } from '@/lib/utils'
import { makeSession, renderWithProviders } from '@/test/helpers'
import type { ServiceRequest, Vm } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => makeSession() }))

const makeVm = (over: Partial<Vm> = {}): Vm => ({
  id: 1,
  order_number: 200,
  name: 'A1001',
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
  requested_return_at: null,
  ip_address: '10.0.0.15',
  connection_login: 'user',
  connection_method: 'RDP',
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
let sdEnabled = false // включается в блоке «ОС и заявки Service Desk»

beforeEach(() => {
  vms = []
  sdEnabled = false
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/vms/my') return vms
    if (path === '/requests/config') return { enabled: sdEnabled }
    throw new Error(`неожиданный GET ${path}`)
  })
})

const renderVms = async (list: Vm[]) => {
  vms = list
  renderWithProviders(<MyVms />)
  if (list.some((v) => v.status !== 'deleted')) await screen.findByText(list[0].name, { exact: false })
  else await waitFor(() => expect(api.get).toHaveBeenCalledWith('/vms/my'))
}

describe('MyVms', () => {
  it('ошибка загрузки — сообщение и «Повторить», а не пустой блок', async () => {
    const user = userEvent.setup()
    let fail = true
    vi.mocked(api.get).mockImplementation(async () => {
      if (fail) throw new ApiError(500, 'Сервер недоступен')
      return [makeVm()]
    })
    renderWithProviders(<MyVms />)
    expect(await screen.findByText('Не удалось загрузить виртуальные машины')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('A1001')).toBeInTheDocument()
    expect(screen.queryByText(/Не удалось загрузить/)).not.toBeInTheDocument()
  })

  it('нет виртуалок — блок не рисуется', async () => {
    await renderVms([])
    expect(screen.queryByText('Виртуальные машины')).not.toBeInTheDocument()
  })

  it('удалённые виртуалки скрыты; если остались только они — блока нет', async () => {
    await renderVms([makeVm({ status: 'deleted' })])
    await new Promise((r) => setTimeout(r, 20)) // даём react-query применить ответ
    expect(screen.queryByText('Виртуальные машины')).not.toBeInTheDocument()
  })

  it('рисует параметры, заказ, отдел и срок возврата', async () => {
    await renderVms([makeVm({ expected_return_at: '2099-12-31' })])
    expect(screen.getByText('Виртуальные машины')).toBeInTheDocument()
    expect(screen.getByText('Заказ №200')).toBeInTheDocument()
    expect(screen.getByText('4 ядра · 8 ГБ · 80 ГБ · Разработка')).toBeInTheDocument()
    expect(screen.getByText(/· до /)).toBeInTheDocument()
  })

  it('без срока возврата «до …» не показывается', async () => {
    await renderVms([makeVm()])
    expect(screen.queryByText(/· до /)).not.toBeInTheDocument()
  })

  describe('статусы', () => {
    it.each([
      ['queued', 'В очереди'],
      ['creating', 'Создаётся'],
      ['ready', 'Готова'],
      ['failed', 'Ошибка'],
      ['deleting', 'Удаляется'],
    ] as const)('%s — «%s»', async (status, label) => {
      await renderVms([makeVm({ status, ip_address: null })])
      expect(screen.getByText(label)).toBeInTheDocument()
    })

    it('failed показывает текст ошибки vSphere', async () => {
      await renderVms([makeVm({ status: 'failed', ip_address: null, error: 'Нет места на datastore' })])
      expect(screen.getByText('Нет места на datastore')).toBeInTheDocument()
    })

    it('failed без текста ошибки — блока ошибки нет', async () => {
      await renderVms([makeVm({ status: 'failed', ip_address: null, error: null })])
      expect(screen.getByText('Ошибка')).toBeInTheDocument()
      expect(screen.queryByText('Нет места на datastore')).not.toBeInTheDocument()
    })

    it('ready без IP — «Windows загружается…»', async () => {
      await renderVms([makeVm({ status: 'ready', ip_address: null })])
      expect(screen.getByText('Windows загружается…')).toBeInTheDocument()
    })

    it('creating без IP — ни IP, ни «загружается»', async () => {
      await renderVms([makeVm({ status: 'creating', ip_address: null })])
      expect(screen.queryByText('Windows загружается…')).not.toBeInTheDocument()
      expect(screen.queryByTitle('Скопировать')).not.toBeInTheDocument()
    })
  })

  describe('кнопка отказа', () => {
    it.each([
      ['ready', 'Отказаться'],
      ['failed', 'Отказаться'],
      ['queued', 'Отменить'],
    ] as const)('для %s — «%s»', async (status, label) => {
      await renderVms([makeVm({ status })])
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    })

    it.each(['creating', 'deleting'] as const)('для %s кнопки нет', async (status) => {
      await renderVms([makeVm({ status })])
      expect(screen.queryByRole('button', { name: /Отказаться|Отменить/ })).not.toBeInTheDocument()
    })
  })

  describe('виртуалки команды', () => {
    const teammate = { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' }
    const team = () => [
      makeVm({ id: 1 }),
      makeVm({ id: 2, name: 'A1002', user: teammate, requester_name: 'Пётр Петров', requester_nick: 'p.petrov' }),
    ]

    it('у чужой ВМ — «Арендатор: Имя (ник)», у своей подписи нет', async () => {
      await renderVms(team())
      const row = (name: string) => within(screen.getByText(name).closest('.flex-wrap') as HTMLElement)
      expect(row('A1002').getByText('Арендатор: Пётр Петров (p.petrov)')).toBeInTheDocument()
      expect(row('A1001').queryByText(/Арендатор:/)).not.toBeInTheDocument()
    })

    it('чужую ВМ можно удалить: запрос уходит по её id', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms(team())
      await user.click(within(screen.getByText('A1002').closest('.flex-wrap') as HTMLElement).getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vms/2/release'))
    })

    it('отказ backend (403) показывается тостом', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(403, 'Отказаться от ВМ может тот, кто её заказывал, участник его команды или администратор'))
      const user = userEvent.setup()
      await renderVms(team())
      await user.click(within(screen.getByText('A1002').closest('.flex-wrap') as HTMLElement).getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Отказаться от ВМ может тот, кто её заказывал, участник его команды или администратор'),
      )
    })
  })

  describe('продление', () => {
    it.each(['queued', 'creating', 'ready', 'failed'] as const)('для %s кнопка «Продлить» есть', async (status) => {
      await renderVms([makeVm({ status, ip_address: null })])
      expect(screen.getByRole('button', { name: 'Продлить' })).toBeInTheDocument()
    })

    it.each(['deleting', 'deleted'] as const)('для %s кнопки нет', async (status) => {
      await renderVms([makeVm({ status: 'ready' }), makeVm({ id: 2, name: 'A1009', status })])
      // кнопка только у «готовой» ВМ: у удаляемой и удалённой её нет
      expect(screen.getAllByRole('button', { name: 'Продлить' })).toHaveLength(1)
    })

    it('окно показывает текущий срок; новый срок и причина уходят в POST /vms/{id}/extend, список обновляется', async () => {
      vi.mocked(api.post).mockImplementation(async () => {
        vms = [makeVm({ id: 9, expected_return_at: '3000-01-31' })]
        return vms[0]
      })
      const user = userEvent.setup()
      await renderVms([makeVm({ id: 9, expected_return_at: '2999-12-31' })])
      await user.click(screen.getByRole('button', { name: 'Продлить' }))
      const dialog = within(screen.getByRole('dialog', { name: 'Продлить аренду A1001' }))
      expect(dialog.getByText(/Текущий срок — /)).toBeInTheDocument()
      expect(dialog.getByLabelText(/Новый срок/)).toHaveAttribute('min', '3000-01-01')
      await user.type(dialog.getByLabelText(/Новый срок/), '3000-01-31')
      await user.type(dialog.getByLabelText(/Причина/), 'Тесты ещё идут')
      await user.click(dialog.getByRole('button', { name: 'Продлить' }))

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).toHaveBeenCalledWith('/vms/9/extend', { expected_return_at: '3000-01-31', comment: 'Тесты ещё идут' })
      expect(toast.success).toHaveBeenCalledWith(`Аренда A1001 продлена до ${formatDate('3000-01-31')}`)
      expect(await screen.findByText(new RegExp(`до ${formatDate('3000-01-31')}`))).toBeInTheDocument()
    })

    it('срок не позже текущего отправить нельзя', async () => {
      const user = userEvent.setup()
      await renderVms([makeVm({ expected_return_at: '2999-12-31' })])
      await user.click(screen.getByRole('button', { name: 'Продлить' }))
      const dialog = within(screen.getByRole('dialog'))
      await user.type(dialog.getByLabelText(/Новый срок/), '2999-12-31')
      expect(dialog.getByRole('button', { name: 'Продлить' })).toBeDisabled()
    })

    it('ответ 409 показывается в окне, окно остаётся открытым', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(409, 'Виртуалка удаляется или уже удалена — продлить срок нельзя'))
      const user = userEvent.setup()
      await renderVms([makeVm()])
      await user.click(screen.getByRole('button', { name: 'Продлить' }))
      const dialog = within(screen.getByRole('dialog'))
      await user.type(dialog.getByLabelText(/Новый срок/), '3000-01-31')
      await user.click(dialog.getByRole('button', { name: 'Продлить' }))
      expect(await dialog.findByText('Виртуалка удаляется или уже удалена — продлить срок нельзя')).toBeInTheDocument()
      expect(toast.success).not.toHaveBeenCalled()
    })

    it('ВМ коллеги по команде продлевается так же: запрос по её id', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm())
      const user = userEvent.setup()
      await renderVms([makeVm({ id: 2, user: { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' } })])
      await user.click(screen.getByRole('button', { name: 'Продлить' }))
      await user.type(within(screen.getByRole('dialog')).getByLabelText(/Новый срок/), '3000-01-31')
      await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Продлить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vms/2/extend', { expected_return_at: '3000-01-31' }))
    })
  })

  describe('данные подключения', () => {
    it.each([
      ['RDP', 'Логин user · RDP'],
      ['VNC', 'Логин user · VNC'],
      [null, 'Логин user'],
    ] as const)('готовая ВМ со способом %s показывает «%s»', async (connection_method, text) => {
      await renderVms([makeVm({ connection_method })])
      expect(screen.getByText(text)).toBeInTheDocument()
    })

    it.each(['queued', 'creating', 'failed'] as const)('ВМ в статусе %s логин не показывает', async (status) => {
      await renderVms([makeVm({ status, ip_address: null })])
      expect(screen.queryByText(/Логин user/)).not.toBeInTheDocument()
    })
  })

  it('клик по IP копирует его в буфер и показывает toast', async () => {
    const user = userEvent.setup()
    const write = vi.spyOn(navigator.clipboard, 'writeText')
    await renderVms([makeVm({ ip_address: '10.0.0.15' })])
    await user.click(screen.getByTitle('Скопировать'))
    expect(write).toHaveBeenCalledWith('10.0.0.15')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('IP скопирован'))
  })

  describe('удаление', () => {
    it('просит подтверждение, и только потом шлёт запрос; затем toast и закрытие окна', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms([makeVm({ id: 9 })])
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))

      const dialog = screen.getByRole('dialog', { name: 'Отказаться от A1001?' })
      expect(dialog).toHaveTextContent('Отменить удаление после подтверждения будет нельзя.')
      expect(api.post).not.toHaveBeenCalled()

      await user.click(within(dialog).getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).toHaveBeenCalledWith('/vms/9/release')
      expect(toast.success).toHaveBeenCalledWith('A1001 будет удалена')
    })

    it('после удаления список перезапрашивается', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms([makeVm()])
      const before = vi.mocked(api.get).mock.calls.filter(([p]) => p === '/vms/my').length
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() =>
        expect(vi.mocked(api.get).mock.calls.filter(([p]) => p === '/vms/my').length).toBeGreaterThan(before),
      )
    })

    it('«Отмена» закрывает окно без запроса', async () => {
      const user = userEvent.setup()
      await renderVms([makeVm()])
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Отмена' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(api.post).not.toHaveBeenCalled()
    })

    it('ошибка API — toast с текстом, окно подтверждения остаётся', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'vCenter недоступен'))
      const user = userEvent.setup()
      await renderVms([makeVm()])
      await user.click(screen.getByRole('button', { name: 'Отказаться' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('vCenter недоступен'))
      expect(toast.success).not.toHaveBeenCalled()
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('для queued заголовок/кнопка «Отменить», а подтверждение то же', async () => {
      vi.mocked(api.post).mockResolvedValue(makeVm({ status: 'deleting' }))
      const user = userEvent.setup()
      await renderVms([makeVm({ id: 3, status: 'queued', ip_address: null })])
      await user.click(screen.getByRole('button', { name: 'Отменить' }))
      await user.click(screen.getByRole('button', { name: 'Удалить' }))
      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/vms/3/release'))
    })
  })
})

/** Маркер «конфиг Service Desk уже загружен» — по нему проверяем отсутствие кнопки */
const CfgProbe = () => <span data-testid="cfg">{useSdConfig().isFetched ? 'loaded' : 'loading'}</span>
const cfgLoaded = () => waitFor(() => expect(screen.getByTestId('cfg')).toHaveTextContent('loaded'))

/** Строка виртуалки по имени */
const rowOf = (name: string) => screen.getByText(name).closest('.flex-wrap') as HTMLElement

async function renderVmsWithSd(list: Vm[], props: Parameters<typeof MyVms>[0] = {}) {
  vms = list
  renderWithProviders(<><MyVms {...props} /><CfgProbe /></>)
  await screen.findByText(list[0].name)
}

describe('MyVms: ОС и заявки Service Desk', () => {
  beforeEach(() => {
    sdEnabled = true
  })

  it('шаблон ОС выводится перед параметрами, без шаблона — как раньше', async () => {
    await renderVmsWithSd([makeVm({ os_label: 'Windows 10' }), makeVm({ id: 2, name: 'A1009', os_label: null })])
    expect(screen.getByText('Windows 10 · 4 ядра · 8 ГБ · 80 ГБ · Разработка')).toBeInTheDocument()
    expect(screen.getByText('4 ядра · 8 ГБ · 80 ГБ · Разработка')).toBeInTheDocument()
  })

  it('без пропсов заявок нет ни бейджей, ни кнопки «Сообщить о проблеме»', async () => {
    await renderVmsWithSd([makeVm()])
    await cfgLoaded()
    expect(screen.queryByRole('button', { name: /Заявка|Возврат|Сообщить о проблеме/ })).not.toBeInTheDocument()
  })

  it('requestsFor запрашивается для каждой ВМ; бейджи заявок видны, клик открывает заявку', async () => {
    const user = userEvent.setup()
    const onOpenRequest = vi.fn()
    const requestsFor = vi.fn((vmId: number) => (vmId === 1 ? [makeRequest({ id: 5 }), makeRequest({ id: 6, issue_key: 'HMS-102', status: 'Выполнено', status_category: 'done' })] : []))
    await renderVmsWithSd([makeVm({ id: 1 }), makeVm({ id: 2, name: 'A1002' })], { requestsFor, onOpenRequest })

    expect(requestsFor).toHaveBeenCalledWith(1)
    expect(requestsFor).toHaveBeenCalledWith(2)
    const first = within(rowOf('A1001'))
    expect(first.getByRole('button', { name: 'Заявка HMS-101 · В работе' })).toBeInTheDocument()
    expect(first.getByRole('button', { name: 'Заявка HMS-102 · Выполнено' })).toBeInTheDocument()
    expect(within(rowOf('A1002')).queryByRole('button', { name: /Заявка/ })).not.toBeInTheDocument()

    await user.click(first.getByRole('button', { name: 'Заявка HMS-102 · Выполнено' }))
    expect(onOpenRequest).toHaveBeenCalledWith(6)
  })

  it('«Сообщить о проблеме» есть и у ВМ коллеги по команде', async () => {
    const teammate = { id: 2, username: 'p.petrov', display_name: 'Пётр Петров' }
    await renderVmsWithSd([makeVm({ user: teammate, requester_name: 'Пётр Петров', requester_nick: 'p.petrov' })], { onReport: vi.fn() })
    expect(await screen.findByRole('button', { name: 'Сообщить о проблеме' })).toBeInTheDocument()
  })

  it('«Сообщить о проблеме» передаёт выбранную ВМ', async () => {
    const user = userEvent.setup()
    const onReport = vi.fn()
    const second = makeVm({ id: 2, name: 'A1002' })
    await renderVmsWithSd([makeVm({ id: 1 }), second], { onReport })
    await user.click(await within(rowOf('A1002')).findByRole('button', { name: 'Сообщить о проблеме' }))
    expect(onReport).toHaveBeenCalledOnce()
    expect(onReport).toHaveBeenCalledWith(second)
  })

  it('Service Desk выключен — кнопки нет, бейджи существующих заявок остаются', async () => {
    sdEnabled = false
    await renderVmsWithSd([makeVm()], { onReport: vi.fn(), requestsFor: () => [makeRequest()] })
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
    await renderVmsWithSd([makeVm({ status, ip_address: null })], { onReport: vi.fn() })
    if (shown) {
      expect(await screen.findByRole('button', { name: 'Сообщить о проблеме' })).toBeInTheDocument()
    } else {
      await cfgLoaded()
      expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
    }
  })
})

describe('MyVms: заявка на срок', () => {
  it('срок из заявки, которая ждёт админа, виден у ВМ', async () => {
    await renderVms([makeVm({ requested_return_at: '2999-12-31' })])
    expect(screen.getByText(`Заявка на срок до ${formatDate('2999-12-31')} ждёт администратора`)).toBeInTheDocument()
  })

  it('без заявки пояснения нет', async () => {
    await renderVms([makeVm()])
    expect(screen.queryByText(/ждёт администратора/)).not.toBeInTheDocument()
  })
})
