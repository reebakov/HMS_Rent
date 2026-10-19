import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataState, ErrorNotice, FormError, QueryError, RowsSkeleton, type QueryLike } from './data-state'

const query = (over: Partial<QueryLike<string[]>> = {}): QueryLike<string[]> => ({
  data: undefined,
  isError: false,
  error: null,
  refetch: vi.fn(),
  ...over,
})

const renderState = (q: QueryLike<string[]>, props: Partial<Parameters<typeof DataState<string[]>>[0]> = {}) =>
  render(
    <DataState query={q} errorTitle="Не удалось загрузить список" loading={<p>грузим</p>} {...props}>
      {(items) => <ul>{items.map((i) => <li key={i}>{i}</li>)}</ul>}
    </DataState>,
  )

describe('DataState', () => {
  it('пока данных нет и ошибки нет — показывает заглушку загрузки', () => {
    renderState(query())
    expect(screen.getByText('грузим')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('по умолчанию загрузка — строки-скелетоны', () => {
    const { container } = render(
      <DataState query={query()} errorTitle="Ошибка">
        {() => null}
      </DataState>,
    )
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(6)
  })

  it('ошибка без данных: заголовок, текст ошибки, «Повторить» вызывает refetch; ни данных, ни пустого состояния', async () => {
    const refetch = vi.fn()
    renderState(query({ isError: true, error: new Error('Сервер недоступен'), refetch }), { empty: <p>Пусто</p> })
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Не удалось загрузить список')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.queryByText('Пусто')).not.toBeInTheDocument()
    expect(screen.queryByText('грузим')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(refetch).toHaveBeenCalledOnce()
  })

  it('ошибка фонового обновления при уже загруженных данных не прячет данные', () => {
    renderState(query({ data: ['PC-1'], isError: true, error: new Error('сбой') }))
    expect(screen.getByText('PC-1')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('пустой список — empty; без empty пустой список отдаётся children', () => {
    const { unmount } = renderState(query({ data: [] }), { empty: <p>Пусто</p> })
    expect(screen.getByText('Пусто')).toBeInTheDocument()
    unmount()
    renderState(query({ data: [] }))
    expect(screen.getByRole('list')).toBeInTheDocument()
  })

  it('isEmpty переопределяет понятие «пусто»; empty={null} прячет блок целиком', () => {
    const { container, unmount } = renderState(query({ data: ['x'] }), { empty: <p>Пусто</p>, isEmpty: (d) => d[0] === 'x' })
    expect(screen.getByText('Пусто')).toBeInTheDocument()
    unmount()
    const second = renderState(query({ data: [] }), { empty: null })
    expect(second.container).toBeEmptyDOMElement()
    expect(container).toBeEmptyDOMElement()
  })

  it('errorCardClass оборачивает ошибку в карточку с указанным классом', () => {
    renderState(query({ isError: true, error: new Error('сбой') }), { errorCardClass: 'mb-8' })
    expect(screen.getByRole('alert').parentElement).toHaveClass('mb-8', 'border')
  })
})

describe('ErrorNotice', () => {
  it('без текста ошибки показывает только заголовок', () => {
    render(<ErrorNotice title="Не удалось" onRetry={vi.fn()} />)
    expect(screen.getByText('Не удалось')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument()
  })
})

describe('QueryError', () => {
  it('грузится или успешен — ничего не рисует', () => {
    const { container, rerender } = render(<QueryError query={query()} title="Не удалось" />)
    expect(container).toBeEmptyDOMElement()
    rerender(<QueryError query={query({ data: ['x'] })} title="Не удалось" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('ошибка без данных — заголовок, текст и «Повторить»; с cardClass — в карточке', async () => {
    const refetch = vi.fn()
    render(<QueryError query={query({ isError: true, error: new Error('сбой'), refetch })} title="Не удалось" cardClass="mb-8" />)
    expect(screen.getByText('Не удалось')).toBeInTheDocument()
    expect(screen.getByText('сбой')).toBeInTheDocument()
    expect(screen.getByRole('alert').parentElement).toHaveClass('mb-8')
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(refetch).toHaveBeenCalledOnce()
  })

  it('ошибка при уже имеющихся данных (фоновое обновление) не показывается', () => {
    const { container } = render(<QueryError query={query({ data: [], isError: true, error: new Error('сбой') })} title="Не удалось" />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('RowsSkeleton', () => {
  it('рисует заданное число строк', () => {
    const { container } = render(<RowsSkeleton rows={3} className="h-4" />)
    expect(container.querySelectorAll('.h-4')).toHaveLength(3)
  })
})

describe('FormError', () => {
  it('показывает текст ошибки и принимает дополнительный класс', () => {
    render(<FormError className="mb-4">Имя занято</FormError>)
    expect(screen.getByText('Имя занято')).toHaveClass('text-danger', 'mb-4')
  })
})
