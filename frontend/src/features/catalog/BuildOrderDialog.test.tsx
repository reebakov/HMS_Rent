import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { BuildOrderDialog } from './BuildOrderDialog'
import { api, ApiError } from '@/lib/api'
import { makeSession, renderWithProviders } from '@/test/helpers'
import { addDays, todayLocal } from '@/lib/utils'
import type { OrderOptions } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
let session = makeSession()
vi.mock('@/auth/AuthProvider', () => ({ useSession: () => session }))

const departments = [{ id: 2, name: 'Аналитика', code: 'AN', head_name: null, is_active: true }]
const BUILD_A = 'A — Intel i5-12400F, 16 ГБ, RTX 3050'
let options: OrderOptions
const UNTIL = addDays(todayLocal(), 30)

beforeEach(() => {
  session = makeSession({ department_id: 2 })
  options = { os: ['Ubuntu 24.04', 'Windows 11 26H2'], builds: [BUILD_A, 'B — Ryzen 7'] }
  for (const m of [api.get, api.post]) vi.mocked(m).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/catalog/order-options') return options
    if (path === '/departments') return departments
    throw new Error(`неожиданный GET ${path}`)
  })
  vi.mocked(api.post).mockResolvedValue({ id: 1, issue_key: 'HMS-42', kind: 'build' })
})

async function setup() {
  const onClose = vi.fn()
  renderWithProviders(<BuildOrderDialog open onClose={onClose} />)
  await screen.findByRole('option', { name: 'Аналитика' })
  await screen.findByRole('option', { name: BUILD_A })
  return { onClose, user: userEvent.setup() }
}

const submit = () => screen.getByRole('button', { name: 'Отправить заявку' })

async function fillCommon(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText(/Операционная система/), 'Ubuntu 24.04')
  await user.type(screen.getByLabelText(/Вернуть до/), UNTIL)
}

describe('BuildOrderDialog', () => {
  it('типовая сборка: без сборки, ОС и срока отправить нельзя; затем POST с выбранным и тост', async () => {
    const { onClose, user } = await setup()
    expect(submit()).toBeDisabled()
    await user.selectOptions(screen.getByLabelText(/Типовая сборка/), BUILD_A)
    expect(submit()).toBeDisabled()
    await fillCommon(user)
    expect(submit()).toBeEnabled()
    await user.click(submit())

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledWith('/requests/build', {
      build: BUILD_A, custom: undefined, os_label: 'Ubuntu 24.04', department_id: 2, requester_name: 'Иван Иванов',
      requester_nick: 'i.ivanov', expected_return_at: UNTIL, wanted_by: undefined, purpose: undefined,
    })
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('HMS-42'), expect.objectContaining({ action: expect.anything() }))
  })

  it('своя конфигурация: описание не короче 5 символов, сборка не отправляется', async () => {
    const { user } = await setup()
    await user.click(screen.getByRole('button', { name: 'Своя конфигурация' }))
    await fillCommon(user)
    const config = screen.getByLabelText(/Конфигурация/)
    await user.type(config, 'i9')
    expect(submit()).toBeDisabled()
    await user.type(config, ', 64 ГБ')
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ build: undefined, custom: 'i9, 64 ГБ' })
  })

  it('желаемый срок: сегодня нельзя, завтра можно; уходит в заявку', async () => {
    const { user } = await setup()
    await user.selectOptions(screen.getByLabelText(/Типовая сборка/), BUILD_A)
    await fillCommon(user)
    const wanted = screen.getByLabelText(/Нужен к/)
    expect(wanted).toHaveAttribute('min', addDays(todayLocal(), 1))
    await user.type(wanted, todayLocal())
    expect(submit()).toBeDisabled()
    await user.clear(wanted)
    await user.type(wanted, addDays(todayLocal(), 1))
    await user.click(submit())
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ wanted_by: addDays(todayLocal(), 1) })
  })

  it('без типовых сборок в настройках — сразу своя конфигурация, переключателя нет', async () => {
    options = { os: ['Ubuntu 24.04'], builds: [] }
    renderWithProviders(<BuildOrderDialog open onClose={vi.fn()} />)
    expect(await screen.findByLabelText(/Конфигурация/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Типовая сборка' })).not.toBeInTheDocument()
  })

  it('ошибка API показывается в окне, окно не закрывается', async () => {
    vi.mocked(api.post).mockRejectedValue(new ApiError(400, 'Не удалось создать заявку: Service Desk недоступен'))
    const { onClose, user } = await setup()
    await user.selectOptions(screen.getByLabelText(/Типовая сборка/), BUILD_A)
    await fillCommon(user)
    await user.click(submit())
    expect(await screen.findByText('Не удалось создать заявку: Service Desk недоступен')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('ошибка загрузки вариантов — «Повторить» вместо пустой формы', async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === '/departments') return departments
      throw new ApiError(500, 'Сервер недоступен')
    })
    renderWithProviders(<BuildOrderDialog open onClose={vi.fn()} />)
    expect(await screen.findByText('Не удалось загрузить варианты сборки')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
  })
})
