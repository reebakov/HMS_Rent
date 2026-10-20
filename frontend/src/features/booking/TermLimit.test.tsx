import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { toast } from 'sonner'
import { PendingTermNote, TermLimitNote, termLimit, toastTerm } from './TermLimit'
import { formatDate } from '@/lib/utils'

vi.mock('sonner', () => ({ toast: { success: vi.fn() } }))

beforeEach(() => vi.mocked(toast.success).mockReset())

describe('termLimit', () => {
  it('крайний срок без согласования — три месяца от даты', () => {
    expect(termLimit('2026-01-15')).toBe('2026-04-15')
    expect(termLimit('2026-11-30')).toBe('2027-02-28')
  })
})

describe('TermLimitNote', () => {
  const base = '2026-01-15'
  const note = (until: string) => render(<TermLimitNote until={until} base={base} verb="оформится" />)

  it.each([['срок не выбран', ''], ['срок в пределах лимита', '2026-03-01'], ['ровно лимит', '2026-04-15']])(
    '%s — подсказки нет',
    (_, until) => {
      const { container } = note(until)
      expect(container).toBeEmptyDOMElement()
    },
  )

  it('дальше лимита объясняет: срок по лимиту, администратору уйдёт заявка на выбранный', () => {
    note('2026-08-15')
    expect(screen.getByText(/аренда оформится до/)).toHaveTextContent(
      `аренда оформится до ${formatDate('2026-04-15')}, а администратору уйдёт заявка на ${formatDate('2026-08-15')}`,
    )
  })

  it('глагол подставляется из вызова (продление: «продлится»)', () => {
    render(<TermLimitNote until="2026-08-15" base={base} verb="продлится" />)
    expect(screen.getByText(/аренда продлится до/)).toBeInTheDocument()
  })
})

describe('PendingTermNote', () => {
  it('срок из заявки, которая ждёт админа, виден арендатору', () => {
    render(<PendingTermNote order={{ requested_return_at: '2026-08-15' }} />)
    expect(screen.getByText(`Заявка на срок до ${formatDate('2026-08-15')} ждёт администратора`)).toBeInTheDocument()
  })

  it('без заявки ничего не рисует', () => {
    const { container } = render(<PendingTermNote order={{ requested_return_at: null }} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('toastTerm', () => {
  it('без заявки — обычный тост без второго аргумента', () => {
    toastTerm('Готово', { expected_return_at: '2026-04-15', requested_return_at: null })
    expect(toast.success).toHaveBeenCalledWith('Готово')
  })

  it('без заявки опции вызывающего (кнопка действия) передаются как есть', () => {
    const action = { label: 'Моя аренда', onClick: vi.fn() }
    toastTerm('Готово', { expected_return_at: '2026-04-15', requested_return_at: null }, { action })
    expect(toast.success).toHaveBeenCalledWith('Готово', { action })
  })

  it('с заявкой добавляется пояснение, опции вызывающего сохраняются', () => {
    const action = { label: 'Моя аренда', onClick: vi.fn() }
    toastTerm('Готово', { expected_return_at: '2026-04-15', requested_return_at: '2026-08-15' }, { action })
    expect(toast.success).toHaveBeenCalledWith('Готово', {
      action,
      description: `Срок ограничен ${formatDate('2026-04-15')} — заявка на ${formatDate('2026-08-15')} отправлена администратору`,
    })
  })
})
