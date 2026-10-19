import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ComputerList } from './ComputerList'
import { makeComputer, stubQuery } from '@/test/helpers'

const computers = [
  makeComputer({ id: 1, name: 'PC-001', cpu: 'Ryzen 5', ram_gb: 16, gpu: null }),
  makeComputer({ id: 2, name: 'PC-002', cpu: 'Core i9', ram_gb: 64, gpu: 'RTX 4080' }),
]

const noop = () => undefined

describe('ComputerList', () => {
  it('пустой список -> заглушка и кнопка сброса фильтров', async () => {
    const onReset = vi.fn()
    render(<ComputerList query={stubQuery({ data: [] })} onOpen={noop} onBook={noop} onReset={onReset} />)
    expect(screen.getByText('Свободных компьютеров не найдено')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Сбросить фильтры' }))
    expect(onReset).toHaveBeenCalledOnce()
  })

  it('во время первой загрузки нет ни заглушки, ни карточек', () => {
    render(<ComputerList query={stubQuery()} onOpen={noop} onBook={noop} onReset={noop} />)
    expect(screen.queryByText('Свободных компьютеров не найдено')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Забронировать/ })).not.toBeInTheDocument()
  })

  it('ошибка загрузки: текст ошибки и «Повторить», а не заглушка «не найдено»; клик перезапрашивает', async () => {
    const refetch = vi.fn()
    render(
      <ComputerList
        query={stubQuery({ isError: true, error: new Error('Сервер недоступен'), refetch })}
        onOpen={noop}
        onBook={noop}
        onReset={noop}
      />,
    )
    expect(screen.getByText('Не удалось загрузить компьютеры')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Свободных компьютеров не найдено')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Забронировать/ })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(refetch).toHaveBeenCalledOnce()
  })

  it('карточки: показывает характеристики, бронь и «Подробнее» передают нужный ПК', async () => {
    const onBook = vi.fn()
    const onOpen = vi.fn()
    render(<ComputerList query={stubQuery({ data: computers })} onOpen={onOpen} onBook={onBook} onReset={noop} />)
    expect(screen.getByText('Ryzen 5 · 6 ядер')).toBeInTheDocument()
    expect(screen.getByText('RTX 4080')).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: /Забронировать/ })[1])
    expect(onBook).toHaveBeenCalledWith(computers[1])

    await userEvent.click(screen.getAllByRole('button', { name: 'Подробнее' })[0])
    expect(onOpen).toHaveBeenCalledWith(1)
  })

  it('компактный режим: краткая строка «процессор · ОЗУ · видеокарта»', async () => {
    const onBook = vi.fn()
    render(<ComputerList query={stubQuery({ data: computers })} compact onOpen={noop} onBook={onBook} onReset={noop} />)
    expect(screen.getByText('Ryzen 5 · 16 ГБ')).toBeInTheDocument()
    expect(screen.getByText('Core i9 · 64 ГБ · RTX 4080')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Забронировать' })[0])
    expect(onBook).toHaveBeenCalledWith(computers[0])
  })
})
