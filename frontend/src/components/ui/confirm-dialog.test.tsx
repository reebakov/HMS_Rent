import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDialog } from './confirm-dialog'

const setup = (props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) => {
  const onClose = vi.fn()
  const onConfirm = vi.fn()
  render(
    <ConfirmDialog
      open
      onClose={onClose}
      onConfirm={onConfirm}
      title="Удалить пул «Аренда»?"
      description="Компьютеры останутся без пула."
      confirmLabel="Удалить"
      {...props}
    />,
  )
  return { onClose, onConfirm }
}

describe('ConfirmDialog', () => {
  it('окно названо заголовком и описано пояснением', () => {
    setup()
    expect(screen.getByRole('dialog', { name: 'Удалить пул «Аренда»?', description: 'Компьютеры останутся без пула.' })).toBeInTheDocument()
  })

  it('закрытое окно ничего не показывает', () => {
    setup({ open: false })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('кнопка подтверждения с заданной подписью вызывает onConfirm, окно само не закрывается', async () => {
    const { onConfirm, onClose } = setup({ confirmLabel: 'Вернуть' })
    await userEvent.click(screen.getByRole('button', { name: 'Вернуть' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onClose).not.toHaveBeenCalled()
  })

  it.each([
    ['«Отмена»', () => userEvent.click(screen.getByRole('button', { name: 'Отмена' }))],
    ['«Закрыть»', () => userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))],
    ['Escape', () => userEvent.keyboard('{Escape}')],
  ])('%s закрывает окно без подтверждения', async (_name, act) => {
    const { onConfirm, onClose } = setup()
    await act()
    expect(onClose).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('фокус сразу на «Отмена», Enter подтверждения не вызывает', async () => {
    const { onClose, onConfirm } = setup()
    expect(screen.getByRole('button', { name: 'Отмена' })).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(onConfirm).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('пока идёт запрос, подтверждение недоступно', () => {
    setup({ pending: true })
    expect(screen.getByRole('button', { name: 'Удалить' })).toBeDisabled()
  })

  it('показывает дополнительное содержимое', () => {
    setup({ children: <p>Отменить удаление будет нельзя.</p> })
    expect(screen.getByText('Отменить удаление будет нельзя.')).toBeInTheDocument()
  })
})
