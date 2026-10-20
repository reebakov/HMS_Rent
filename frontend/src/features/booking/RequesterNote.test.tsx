import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RequesterNote } from './RequesterNote'
import { makeSession } from '@/test/helpers'

vi.mock('@/auth/AuthProvider', () => ({ useSession: () => makeSession({ id: 1 }) }))

const order = (userId: number) => ({
  user: { id: userId, username: 'p.petrov', display_name: 'Пётр Петров' },
  requester_name: 'Пётр Петров',
  requester_nick: 'p.petrov',
})

describe('RequesterNote', () => {
  it('у заказа коллеги по команде — «Арендатор: Имя (ник)»', () => {
    render(<RequesterNote order={order(2)} />)
    expect(screen.getByText('Арендатор: Пётр Петров (p.petrov)')).toBeInTheDocument()
  })

  it('у своего заказа подписи нет', () => {
    const { container } = render(<RequesterNote order={order(1)} />)
    expect(container).toBeEmptyDOMElement()
  })
})
