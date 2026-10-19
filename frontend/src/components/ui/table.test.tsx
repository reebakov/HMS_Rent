import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { DataTable, Th } from './table'

const renderTable = () =>
  render(
    <DataTable
      className="min-w-[900px]"
      head={
        <>
          <Th>Отдел</Th>
          <Th right>Сейчас ПК</Th>
          <Th />
        </>
      }
    >
      <tr>
        <td>Разработка</td>
        <td>3</td>
        <td />
      </tr>
    </DataTable>,
  )

describe('DataTable', () => {
  it('шапка из заголовков столбцов и строки данных под ней', () => {
    renderTable()
    expect(screen.getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['Отдел', 'Сейчас ПК', ''])
    const [, body] = screen.getAllByRole('rowgroup')
    expect(within(body).getByRole('cell', { name: 'Разработка' })).toBeInTheDocument()
  })

  it('className задаёт минимальную ширину таблицы', () => {
    renderTable()
    expect(screen.getByRole('table')).toHaveClass('w-full', 'min-w-[900px]')
  })

  it('ячейка шапки выравнивается вправо только с right', () => {
    renderTable()
    expect(screen.getByRole('columnheader', { name: 'Сейчас ПК' })).toHaveClass('text-right')
    expect(screen.getByRole('columnheader', { name: 'Отдел' })).not.toHaveClass('text-right')
  })
})
