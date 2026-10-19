import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SHORTCUTS, ShortcutsButton } from './Shortcuts'

const opener = () => screen.getByRole('button', { name: 'Горячие клавиши' })

describe('ShortcutsButton', () => {
  it('кнопка открывает окно с таблицей клавиш', async () => {
    render(<ShortcutsButton />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(opener())
    expect(screen.getByRole('dialog', { name: 'Горячие клавиши' })).toBeInTheDocument()
  })

  it.each(SHORTCUTS.flatMap(({ keys, action }) => keys.map((key) => [key, action])))(
    'в окне есть клавиша «%s» с действием «%s»',
    async (key, action) => {
      render(<ShortcutsButton />)
      await userEvent.click(opener())
      const row = screen.getByText(action).closest('tr')!
      expect(within(row).getByText(key)).toBeInTheDocument()
    },
  )

  it('«?» открывает окно из любого места, а в поле ввода — нет', async () => {
    render(
      <>
        <ShortcutsButton />
        <input aria-label="Поле" />
      </>,
    )
    await userEvent.type(screen.getByRole('textbox', { name: 'Поле' }), '?')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Поле' })).toHaveValue('?')

    await userEvent.click(document.body)
    await userEvent.keyboard('?')
    expect(screen.getByRole('dialog', { name: 'Горячие клавиши' })).toBeInTheDocument()
  })

  it('при открытом окне «?» ничего не делает; Esc закрывает окно и возвращает фокус на кнопку', async () => {
    render(<ShortcutsButton />)
    await userEvent.click(opener())
    expect(screen.getByRole('button', { name: 'Понятно' })).toHaveFocus()
    await userEvent.keyboard('?')
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(opener()).toHaveFocus())
  })
})
