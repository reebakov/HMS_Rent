import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Dialog, Sheet } from './dialog'

describe.each([
  ['Dialog', Dialog],
  ['Sheet', Sheet],
])('%s', (_name, Component) => {
  it('кнопка закрытия доступна по имени «Закрыть» и закрывает окно', async () => {
    const onOpenChange = vi.fn()
    render(
      <Component open onOpenChange={onOpenChange} title="Заголовок">
        <p>содержимое</p>
      </Component>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('заголовок даёт окну имя', () => {
    render(
      <Component open onOpenChange={() => undefined} title="Заголовок">
        <p>содержимое</p>
      </Component>,
    )
    expect(screen.getByRole('dialog', { name: 'Заголовок' })).toBeInTheDocument()
  })
})
