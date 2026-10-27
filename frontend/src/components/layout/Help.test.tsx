import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HelpButton, SHORTCUTS } from './Help'
import { CUSTOMER_TOUR } from '@/features/help/customerTour'
import { renderWithProviders } from '@/test/helpers'

let versions = { APP_RELEASE: '1.69.0', APP_VERSION: '4ca2db5f0c1e2d3a4b5c6d7e8f9a0b1c2d3e4f5a' }
vi.mock('@/lib/version', () => ({
  get APP_RELEASE() {
    return versions.APP_RELEASE
  },
  get APP_VERSION() {
    return versions.APP_VERSION
  },
}))

const opener = () => screen.getByRole('button', { name: 'Справка' })

beforeEach(() => {
  versions = { APP_RELEASE: '1.69.0', APP_VERSION: '4ca2db5f0c1e2d3a4b5c6d7e8f9a0b1c2d3e4f5a' }
})

describe('HelpButton', () => {
  it('кнопка «?» открывает справку', async () => {
    renderWithProviders(<HelpButton />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(opener())
    expect(screen.getByRole('dialog', { name: 'Справка' })).toBeInTheDocument()
  })

  it('показывает версию сервиса и короткий номер сборки', async () => {
    renderWithProviders(<HelpButton />)
    await userEvent.click(opener())
    expect(screen.getByText(/Версия сервиса:/)).toHaveTextContent('Версия сервиса: 1.69.0 (сборка 4ca2db5)')
  })

  it('в разработке (сборка dev) номер сборки не показывается', async () => {
    versions = { APP_RELEASE: 'dev', APP_VERSION: 'dev' }
    renderWithProviders(<HelpButton />)
    await userEvent.click(opener())
    expect(screen.getByText(/Версия сервиса:/).textContent?.replace(/\s+/g, ' ').trim()).toBe('Версия сервиса: dev')
  })

  it.each(SHORTCUTS.flatMap(({ keys, action }) => keys.map((key) => [key, action])))(
    'в справке есть клавиша «%s» с действием «%s»',
    async (key, action) => {
      renderWithProviders(<HelpButton />)
      await userEvent.click(opener())
      const row = screen.getByText(action).closest('tr')!
      expect(within(row).getByText(key)).toBeInTheDocument()
    },
  )

  it('«?» открывает справку из любого места, а в поле ввода — нет', async () => {
    renderWithProviders(
      <>
        <HelpButton />
        <input aria-label="Поле" />
      </>,
    )
    await userEvent.type(screen.getByRole('textbox', { name: 'Поле' }), '?')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Поле' })).toHaveValue('?')

    await userEvent.click(document.body)
    await userEvent.keyboard('?')
    expect(screen.getByRole('dialog', { name: 'Справка' })).toBeInTheDocument()
  })

  it('при открытой справке «?» ничего не делает; Esc закрывает её и возвращает фокус на кнопку', async () => {
    renderWithProviders(<HelpButton />)
    await userEvent.click(opener())
    expect(screen.getByRole('button', { name: 'Понятно' })).toHaveFocus()
    await userEvent.keyboard('?')
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(opener()).toHaveFocus())
  })

  it('«Пройти обучение» закрывает справку и запускает тур; «Закончить» возвращает фокус на «?»', async () => {
    renderWithProviders(<HelpButton />)
    await userEvent.click(opener())
    await userEvent.click(screen.getByRole('button', { name: 'Пройти обучение' }))
    const tour = await screen.findByRole('dialog', { name: 'Обучение' })
    expect(screen.queryByRole('dialog', { name: 'Справка' })).not.toBeInTheDocument()
    expect(within(tour).getByText(`Шаг 1 из ${CUSTOMER_TOUR.length}`)).toBeInTheDocument()

    await userEvent.keyboard('?') // во время обучения справка не открывается
    expect(screen.queryByRole('dialog', { name: 'Справка' })).not.toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Обучение' })).not.toBeInTheDocument())
    expect(opener()).toHaveFocus()
  })
})
