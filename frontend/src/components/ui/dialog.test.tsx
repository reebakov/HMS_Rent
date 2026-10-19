import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactNode } from 'react'
import { Button } from './button'
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

  it('Esc закрывает окно, фокус возвращается на кнопку, которая его открыла', async () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button onClick={() => setOpen(true)}>Открыть</button>
          <Component open={open} onOpenChange={setOpen} title="Заголовок">
            <p>содержимое</p>
          </Component>
        </>
      )
    }
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Открыть' })
    await userEvent.click(opener)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(opener).toHaveFocus())
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

describe('Dialog: начальный фокус', () => {
  const renderDialog = (children: ReactNode, footer?: ReactNode) =>
    render(
      <Dialog open onOpenChange={() => undefined} title="Заголовок" footer={footer}>
        {children}
      </Dialog>,
    )

  it('в форме — на первом поле, а не на «Закрыть»', () => {
    renderDialog(
      <>
        <input aria-label="Имя" />
        <input aria-label="Ник" />
      </>,
      <button>Сохранить</button>,
    )
    expect(screen.getByRole('textbox', { name: 'Имя' })).toHaveFocus()
  })

  it('отключённые поля пропускаются', () => {
    renderDialog(
      <>
        <input aria-label="Имя" disabled />
        <select aria-label="Отдел" />
      </>,
    )
    expect(screen.getByRole('combobox', { name: 'Отдел' })).toHaveFocus()
  })

  it('без полей — на первой доступной кнопке подвала («Отмена»)', () => {
    renderDialog(<p>Удалить?</p>, <><button>Отмена</button><button>Удалить</button></>)
    expect(screen.getByRole('button', { name: 'Отмена' })).toHaveFocus()
  })

  it('без полей и подвала фокус остаётся у Radix — на «Закрыть»', () => {
    renderDialog(<p>Текст</p>)
    expect(screen.getByRole('button', { name: 'Закрыть' })).toHaveFocus()
  })
})

describe('Dialog: onSubmit', () => {
  it('Enter в поле отправляет форму, «Отмена» без type форму не отправляет', async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    render(
      <Dialog
        open
        onOpenChange={() => undefined}
        title="Заголовок"
        onSubmit={onSubmit}
        footer={
          <>
            <Button>Отмена</Button>
            <Button type="submit">Сохранить</Button>
          </>
        }
      >
        <input aria-label="Имя" />
        <input aria-label="Ник" />
      </Dialog>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.type(screen.getByRole('textbox', { name: 'Ник' }), 'x{Enter}')
    expect(onSubmit).toHaveBeenCalledOnce()
  })
})
