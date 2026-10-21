import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VmNumbersCard } from './VmNumbersCard'
import { api } from '@/lib/api'
import { failGetOnce, renderWithProviders } from '@/test/helpers'
import type { VmNumbers } from '@/lib/types'

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), url: vi.fn() },
}))

const numbers = (over: Partial<VmNumbers> = {}): VmNumbers => ({ ok: true, error: null, free: 20, low: false, ...over })

beforeEach(() => vi.mocked(api.get).mockReset())

describe('VmNumbersCard', () => {
  it('показывает число свободных номеров со склонением, без предупреждения при достаточном запасе', async () => {
    vi.mocked(api.get).mockResolvedValue(numbers({ free: 21 }))
    renderWithProviders(<VmNumbersCard />)
    expect(await screen.findByText('21 свободный номер')).toBeInTheDocument()
    expect(screen.queryByText(/заканчиваются/)).not.toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/admin/vm-numbers')
  })

  it.each([
    [2, '2 свободных номера'],
    [5, '5 свободных номеров'],
  ])('мало номеров (%i): предупреждение, что заказы скоро начнут отклоняться', async (free, text) => {
    vi.mocked(api.get).mockResolvedValue(numbers({ free, low: true }))
    renderWithProviders(<VmNumbersCard />)
    expect(await screen.findByText(text)).toBeInTheDocument()
    expect(screen.getByText(/Номера заканчиваются/)).toBeInTheDocument()
  })

  it('номеров нет: заказы отклоняются и сказано, что завести', async () => {
    vi.mocked(api.get).mockResolvedValue(numbers({ free: 0, low: true }))
    renderWithProviders(<VmNumbersCard />)
    expect(await screen.findByText(/заказы ВМ отклоняются/)).toBeInTheDocument()
    expect(screen.getByText(/Заведите в Insight объекты Virtual/)).toBeInTheDocument()
  })

  it('Insight недоступен: причина вместо числа', async () => {
    vi.mocked(api.get).mockResolvedValue(numbers({ ok: false, free: 0, error: 'Insight недоступен, свободные номера не проверить' }))
    renderWithProviders(<VmNumbersCard />)
    expect(await screen.findByText('Insight недоступен, свободные номера не проверить')).toBeInTheDocument()
    expect(screen.queryByText(/свободных номер/)).not.toBeInTheDocument()
  })

  it('ошибка запроса: сообщение и «Повторить», перезапрос показывает данные', async () => {
    const user = userEvent.setup()
    failGetOnce(vi.mocked(api.get), '/admin/vm-numbers')
    renderWithProviders(<VmNumbersCard />)
    expect(await screen.findByText('Не удалось загрузить номера ВМ')).toBeInTheDocument()
    vi.mocked(api.get).mockResolvedValue(numbers())
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText('20 свободных номеров')).toBeInTheDocument()
  })
})
