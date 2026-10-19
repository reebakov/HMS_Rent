import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { ReportProblemButton, ReportProblemDialog, RequestBadges, RequestSheet, type ProblemTarget } from './ServiceDesk'
import { api, ApiError } from '@/lib/api'
import { useSdConfig } from '@/lib/queries'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { ServiceComment, ServiceRequest } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const makeRequest = (over: Partial<ServiceRequest> = {}): ServiceRequest => ({
  id: 5,
  kind: 'problem',
  booking_id: 1,
  vm_id: null,
  issue_key: 'HMS-101',
  summary: 'Не включается',
  status: 'В работе',
  status_category: 'indeterminate',
  error: null,
  created_at: '2024-01-10T09:00:00Z',
  url: 'https://jira.example.com/browse/HMS-101',
  ...over,
})

let sdEnabled: boolean
let request: ServiceRequest
let comments: ServiceComment[]

beforeEach(() => {
  sdEnabled = true
  request = makeRequest()
  comments = []
  vi.mocked(api.get).mockReset()
  vi.mocked(api.post).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/requests/config') return { enabled: sdEnabled }
    if (path === `/requests/${request.id}`) return { request, comments }
    throw new Error(`неожиданный GET ${path}`)
  })
})

describe('ReportProblemButton', () => {
  /** Рядом с кнопкой — маркер «конфиг загружен», чтобы проверять отсутствие кнопки после ответа API */
  const Probe = () => <span data-testid="cfg">{useSdConfig().isFetched ? 'loaded' : 'loading'}</span>
  const renderButton = (onClick = vi.fn()) => {
    renderWithProviders(<><ReportProblemButton onClick={onClick} /><Probe /></>)
    return onClick
  }

  it('Service Desk подключён — кнопка видна и вызывает обработчик', async () => {
    const user = userEvent.setup()
    const onClick = renderButton()
    await user.click(await screen.findByRole('button', { name: 'Сообщить о проблеме' }))
    expect(onClick).toHaveBeenCalledOnce()
    expect(api.get).toHaveBeenCalledWith('/requests/config')
  })

  it('Service Desk выключен — кнопки нет', async () => {
    sdEnabled = false
    renderButton()
    await waitFor(() => expect(screen.getByTestId('cfg')).toHaveTextContent('loaded'))
    expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
  })

  it('пока конфиг грузится, кнопки нет', () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => undefined))
    renderButton()
    expect(screen.queryByRole('button', { name: 'Сообщить о проблеме' })).not.toBeInTheDocument()
  })

  it('ошибка загрузки конфига — кнопка не пропадает: видна, недоступна и объясняет почему', async () => {
    const user = userEvent.setup()
    vi.mocked(api.get).mockRejectedValue(new ApiError(500, 'Сервер недоступен'))
    const onClick = renderButton()
    await waitFor(() => expect(screen.getByTestId('cfg')).toHaveTextContent('loaded'))
    const button = screen.getByRole('button', { name: 'Сообщить о проблеме' })
    expect(button).toBeDisabled()
    expect(screen.getByTitle('Не удалось проверить, подключён ли Service Desk')).toContainElement(button)
    await user.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('RequestBadges', () => {
  it('без заявок ничего не рисует', () => {
    const { container } = renderWithProviders(<RequestBadges requests={[]} onOpen={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('показывает тип, ключ и статус; клик открывает заявку по id', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    renderWithProviders(
      <RequestBadges
        requests={[makeRequest({ id: 5 }), makeRequest({ id: 6, kind: 'return', issue_key: 'HMS-102', status: 'Выполнено', status_category: 'done' })]}
        onOpen={onOpen}
      />,
    )
    expect(screen.getByRole('button', { name: 'Заявка HMS-101 · В работе' })).toHaveAttribute('title', 'Не включается')
    await user.click(screen.getByRole('button', { name: 'Возврат HMS-102 · Выполнено' }))
    expect(onOpen).toHaveBeenCalledWith(6)
  })

  it.each([
    ['new', 'text-warning'],
    ['indeterminate', 'text-primary'],
    ['done', 'text-success'],
    [null, 'text-warning'],
  ])('категория статуса %s — цвет %s', (status_category, cls) => {
    renderWithProviders(<RequestBadges requests={[makeRequest({ status_category })]} onOpen={vi.fn()} />)
    expect(screen.getByText(/HMS-101/)).toHaveClass(cls)
  })

  it('заявка с ошибкой — «не создана», красный бейдж, а не статус', () => {
    renderWithProviders(
      <RequestBadges requests={[makeRequest({ issue_key: null, status: null, error: 'Jira недоступна' })]} onOpen={vi.fn()} />,
    )
    const badge = screen.getByText('Заявка — · не создана')
    expect(badge).toHaveClass('text-danger')
  })

  it('без статуса показывает многоточие', () => {
    renderWithProviders(<RequestBadges requests={[makeRequest({ status: null })]} onOpen={vi.fn()} />)
    expect(screen.getByText('Заявка HMS-101 · …')).toBeInTheDocument()
  })
})

describe('ReportProblemDialog', () => {
  const renderDialog = (target: ProblemTarget = { bookingId: 7, name: 'PC-010' }) => {
    const onClose = vi.fn()
    renderWithProviders(<ReportProblemDialog target={target} onClose={onClose} />)
    return { onClose, user: userEvent.setup() }
  }
  const send = () => screen.getByRole('button', { name: 'Отправить' })
  const field = () => screen.getByLabelText(/Что случилось/)

  it('без цели окно не рисуется', () => {
    renderDialog(null)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('заголовок содержит имя ПК или ВМ', () => {
    renderDialog({ vmId: 3, name: 'rent-design-01' })
    expect(screen.getByRole('dialog', { name: 'Проблема с rent-design-01' })).toBeInTheDocument()
  })

  it.each([
    ['пусто', ''],
    ['пробелы', '        '],
    ['4 символа', 'abcd'],
    ['4 символа и пробелы вокруг', '  abcd  '],
  ])('%s — отправка заблокирована', async (_t, text) => {
    const { user } = renderDialog()
    expect(send()).toBeDisabled()
    if (text) await user.type(field(), text)
    expect(send()).toBeDisabled()
  })

  it('5 символов достаточно — кнопка активна', async () => {
    const { user } = renderDialog()
    await user.type(field(), 'abcde')
    expect(send()).toBeEnabled()
  })

  it('для ПК шлёт booking_id, показывает toast с номером и закрывает окно', async () => {
    vi.mocked(api.post).mockResolvedValue(makeRequest({ issue_key: 'HMS-555' }))
    const { onClose, user } = renderDialog({ bookingId: 7, name: 'PC-010' })
    await user.type(field(), 'Не включается')
    await user.click(send())

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/requests', { booking_id: 7, vm_id: undefined, message: 'Не включается' })
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Заявка HMS-555 создана'))
  })

  it('для ВМ шлёт vm_id', async () => {
    vi.mocked(api.post).mockResolvedValue(makeRequest({ vm_id: 3, booking_id: null }))
    const { onClose, user } = renderDialog({ vmId: 3, name: 'rent-design-01' })
    await user.type(field(), 'Нет интернета')
    await user.click(send())
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/requests', { booking_id: undefined, vm_id: 3, message: 'Нет интернета' })
  })

  it('ошибка API — toast с текстом, окно открыто, текст сохранён, можно повторить', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(502, 'Jira недоступна'))
    const { onClose, user } = renderDialog()
    await user.type(field(), 'Не включается')
    await user.click(send())

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Jira недоступна'))
    expect(onClose).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
    expect(field()).toHaveValue('Не включается')
    expect(send()).toBeEnabled()

    vi.mocked(api.post).mockResolvedValueOnce(makeRequest())
    await user.click(send())
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
  })

  it('пока запрос идёт, кнопка отключена (двойной отправки нет)', async () => {
    vi.mocked(api.post).mockImplementation(() => new Promise(() => undefined))
    const { user } = renderDialog()
    await user.type(field(), 'Не включается')
    await user.click(send())
    await waitFor(() => expect(send()).toBeDisabled())
    expect(api.post).toHaveBeenCalledOnce()
  })

  it('«Отмена» закрывает окно без запроса', async () => {
    const { onClose, user } = renderDialog()
    await user.type(field(), 'Не включается')
    await user.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('при смене цели текст сбрасывается', async () => {
    const user = userEvent.setup()
    function Switch() {
      const [t, setT] = useState<ProblemTarget>({ bookingId: 1, name: 'PC-001' })
      return (
        <>
          <button onClick={() => setT({ bookingId: 2, name: 'PC-002' })}>другой ПК</button>
          <ReportProblemDialog target={t} onClose={() => undefined} />
        </>
      )
    }
    renderWithProviders(<Switch />)
    await user.type(field(), 'Не включается')
    // модальное окно блокирует pointer-events снаружи, поэтому клик без userEvent
    fireEvent.click(screen.getByText('другой ПК'))
    expect(await screen.findByRole('dialog', { name: 'Проблема с PC-002' })).toBeInTheDocument()
    expect(field()).toHaveValue('')
  })
})

describe('RequestSheet', () => {
  const renderSheet = (id: number | null = 5) => {
    const onClose = vi.fn()
    renderWithProviders(<RequestSheet id={id} onClose={onClose} />)
    return { onClose, user: userEvent.setup() }
  }
  const replyBox = () => screen.getByRole('textbox', { name: 'Ответ администраторам' })
  /** Кнопка отправки без текста (иконка), подписана aria-label */
  const sendReply = () => screen.getByRole('button', { name: 'Отправить ответ' })

  it('id=null — панель закрыта и ничего не запрашивает', () => {
    renderSheet(null)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith('/requests/null')
  })

  it('пока грузится — индикатор без текста заявки', () => {
    vi.mocked(api.get).mockImplementation(() => new Promise(() => undefined))
    renderSheet()
    const dialog = screen.getByRole('dialog', { name: 'Заявка' })
    expect(dialog.querySelector('svg.animate-spin')).not.toBeNull()
    expect(screen.queryByText('Администраторы ещё не ответили')).not.toBeInTheDocument()
  })

  it('ошибка загрузки — заголовок, текст ошибки и «Повторить», который перезапрашивает', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/requests/5', 'Заявка не найдена')
    renderSheet()
    expect(await screen.findByText('Не удалось загрузить заявку')).toBeInTheDocument()
    expect(screen.getByText('Заявка не найдена')).toBeInTheDocument()
    expect(screen.queryByText('Администраторы ещё не ответили')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('Не включается')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('показывает ключ, статус, тему и ссылку на Service Desk', async () => {
    renderSheet()
    expect(await screen.findByRole('dialog', { name: 'Заявка HMS-101' })).toBeInTheDocument()
    expect(screen.getByText('В работе')).toBeInTheDocument()
    expect(screen.getByText('Не включается')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Открыть в Service Desk/ })
    expect(link).toHaveAttribute('href', 'https://jira.example.com/browse/HMS-101')
    expect(link).toHaveAttribute('target', '_blank')
    expect(api.get).toHaveBeenCalledWith('/requests/5')
  })

  it('без url ссылки нет', async () => {
    request = makeRequest({ url: null })
    renderSheet()
    await screen.findByText('Не включается')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('нет комментариев — «Администраторы ещё не ответили»', async () => {
    renderSheet()
    expect(await screen.findByText('Администраторы ещё не ответили')).toBeInTheDocument()
  })

  it('комментарии: автор админа, свои с сайта помечены и без служебного префикса', async () => {
    comments = [
      { author: 'Админ Петров', body: 'Принёс новый кабель', created: '2024-01-10T10:00:00Z', from_portal: false },
      { author: 'svc', body: '[HMS Rent] Иван Иванов: Спасибо, жду', created: '2024-01-10T10:05:00Z', from_portal: true },
      { author: 'svc', body: 'Текст без префикса', created: null, from_portal: true },
    ]
    renderSheet()
    expect(await screen.findByText('Принёс новый кабель')).toBeInTheDocument()
    expect(screen.getByText(/Админ Петров ·/)).toBeInTheDocument()
    expect(screen.getByText('Спасибо, жду')).toBeInTheDocument()
    expect(screen.queryByText(/\[HMS Rent\]/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/Вы \(с сайта\) ·/)).toHaveLength(2)
    expect(screen.getByText('Текст без префикса')).toBeInTheDocument()
    // комментарий админа — без пометки «с сайта»
    expect(screen.getByText(/Админ Петров ·/)).not.toHaveTextContent('Вы (с сайта)')
    expect(screen.queryByText('Администраторы ещё не ответили')).not.toBeInTheDocument()
  })

  it('ошибка заявки (не создана в Jira) показана текстом, ответить нельзя', async () => {
    request = makeRequest({ issue_key: null, status: null, error: 'Jira отклонила заявку' })
    renderSheet()
    expect(await screen.findByText('Jira отклонила заявку')).toBeInTheDocument()
    expect(screen.getByText('не создана')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Заявка' })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Ответить администраторам…')).not.toBeInTheDocument()
  })

  it('закрытая заявка (done) — поле ответа скрыто', async () => {
    request = makeRequest({ status: 'Выполнено', status_category: 'done' })
    renderSheet()
    await screen.findByText('Выполнено')
    expect(screen.queryByPlaceholderText('Ответить администраторам…')).not.toBeInTheDocument()
  })

  describe('ответ', () => {
    it('пустой и пробельный ответ отправить нельзя', async () => {
      const { user } = renderSheet()
      await screen.findByText('Не включается')
      expect(sendReply()).toBeDisabled()
      await user.type(replyBox(), '   ')
      expect(sendReply()).toBeDisabled()
      await user.type(replyBox(), 'ок')
      expect(sendReply()).toBeEnabled()
    })

    it('шлёт POST /requests/{id}/comments, очищает поле и подтягивает новый комментарий', async () => {
      vi.mocked(api.post).mockImplementation(async () => {
        comments = [{ author: 'svc', body: '[HMS Rent] Иван Иванов: Всё ещё не работает', created: '2024-01-10T11:00:00Z', from_portal: true }]
      })
      const { user } = renderSheet()
      await screen.findByText('Администраторы ещё не ответили')
      await user.type(replyBox(), 'Всё ещё не работает')
      await user.click(sendReply())

      await waitFor(() => expect(api.post).toHaveBeenCalledWith('/requests/5/comments', { message: 'Всё ещё не работает' }))
      // детали заявки перезапрошены после мутации
      expect(await screen.findByText('Всё ещё не работает', { selector: 'p' })).toBeInTheDocument()
      expect(screen.getByText(/Вы \(с сайта\)/)).toBeInTheDocument()
      expect(replyBox()).toHaveValue('')
    })

    it('ошибка API — toast, текст ответа остаётся', async () => {
      vi.mocked(api.post).mockRejectedValue(new ApiError(502, 'Jira недоступна'))
      const { user } = renderSheet()
      await screen.findByText('Не включается')
      await user.type(replyBox(), 'Помогите')
      await user.click(sendReply())
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Jira недоступна'))
      expect(replyBox()).toHaveValue('Помогите')
    })

    it('пока ответ уходит, кнопка отключена', async () => {
      vi.mocked(api.post).mockImplementation(() => new Promise(() => undefined))
      const { user } = renderSheet()
      await screen.findByText('Не включается')
      await user.type(replyBox(), 'Помогите')
      await user.click(sendReply())
      await waitFor(() => expect(sendReply()).toBeDisabled())
      expect(api.post).toHaveBeenCalledOnce()
    })
  })

  it('Escape закрывает панель через onClose', async () => {
    const { onClose, user } = renderSheet()
    await screen.findByText('Не включается')
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })
})
