import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { Tour, type TourStep } from './Tour'
import { renderWithProviders } from '@/test/helpers'

const steps: TourStep[] = [
  { title: 'Первый', text: 'Текст первого' },
  { title: 'Второй', text: 'Текст второго', target: 'box', to: '/two' },
  { title: 'Третий', text: 'Текст третьего' },
]

const Path = () => <p data-testid="path">{useLocation().pathname}</p>

function mount(onClose = vi.fn()) {
  renderWithProviders(
    <>
      <Path />
      <div data-tour="box">цель</div>
      <Tour steps={steps} onClose={onClose} />
    </>,
  )
  return onClose
}

const card = () => screen.getByRole('dialog', { name: 'Обучение' })
const next = () => userEvent.click(screen.getByRole('button', { name: 'Далее' }))

afterEach(() => vi.restoreAllMocks())

describe('Tour', () => {
  it('начинает с первого шага, фокус на «Далее», «Назад» на первом шаге нет', () => {
    mount()
    expect(screen.getByRole('heading', { name: 'Первый' })).toBeInTheDocument()
    expect(screen.getByText('Шаг 1 из 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Далее' })).toHaveFocus()
    expect(screen.queryByRole('button', { name: 'Назад' })).not.toBeInTheDocument()
  })

  it('«Далее» и «Назад» листают шаги, на последнем вместо «Далее» — «Закончить», которая закрывает тур', async () => {
    const onClose = mount()
    await next()
    expect(screen.getByRole('heading', { name: 'Второй' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Назад' }))
    expect(screen.getByRole('heading', { name: 'Первый' })).toBeInTheDocument()
    await next()
    await next()
    expect(screen.queryByRole('button', { name: 'Далее' })).not.toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Закончить' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('стрелки листают шаги, но не выходят за границы', async () => {
    mount()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByText('Шаг 1 из 3')).toBeInTheDocument()
    await userEvent.keyboard('{ArrowRight}{ArrowRight}{ArrowRight}')
    expect(screen.getByText('Шаг 3 из 3')).toBeInTheDocument()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByText('Шаг 2 из 3')).toBeInTheDocument()
  })

  it.each([
    ['Esc', () => userEvent.keyboard('{Escape}')],
    ['«Пропустить»', () => userEvent.click(screen.getByRole('button', { name: 'Пропустить' }))],
  ])('%s закрывает тур', async (_, close) => {
    const onClose = mount()
    await close()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('шаг со страницей переводит на неё', async () => {
    mount()
    expect(screen.getByTestId('path')).toHaveTextContent('/')
    await next()
    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/two'))
  })

  it('Tab не выходит из карточки: с последней кнопки — на первую, Shift+Tab с первой — на последнюю', async () => {
    mount()
    await next() // на втором шаге в карточке три кнопки
    const [skip, back, forward] = ['Пропустить', 'Назад', 'Далее'].map((name) => screen.getByRole('button', { name }))
    forward.focus()
    await userEvent.tab()
    expect(skip).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(forward).toHaveFocus()
    expect(back).toBeInTheDocument()
  })

  it('карточка встаёт под подсвеченным элементом, а без видимой цели — по центру', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      top: 100, left: 50, width: 200, height: 40, right: 250, bottom: 140, x: 50, y: 100, toJSON: () => ({}),
    })
    mount()
    const centered = card().style.top
    await next()
    // подсветка шире элемента на 6 px с каждой стороны, под ней зазор 12 px: 100 − 6 + 40 + 12 + 12
    await waitFor(() => expect(card().style.top).toBe('158px'))
    expect(card().style.left).toBe('44px')
    await next()
    await waitFor(() => expect(card().style.top).toBe(centered))
  })
})
