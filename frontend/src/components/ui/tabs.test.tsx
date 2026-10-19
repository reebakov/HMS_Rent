import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tabs } from './tabs'

const TABS = ['Обзор', 'История', 'События', 'Insight'] as const

function Harness() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('Обзор')
  return (
    <>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <p data-testid="current">{tab}</p>
      <button>после вкладок</button>
    </>
  )
}

const tab = (name: string) => screen.getByRole('button', { name })

describe('Tabs', () => {
  it('клик выбирает вкладку', async () => {
    render(<Harness />)
    await userEvent.click(tab('События'))
    expect(screen.getByTestId('current')).toHaveTextContent('События')
  })

  it('Tab входит в вкладки одной остановкой — на активной — и выходит дальше, минуя остальные', async () => {
    render(<Harness />)
    await userEvent.tab()
    expect(tab('Обзор')).toHaveFocus()
    await userEvent.tab()
    expect(tab('после вкладок')).toHaveFocus()
  })

  it.each([
    ['ArrowRight', 'Обзор', 'История'],
    ['ArrowLeft', 'История', 'Обзор'],
    ['ArrowLeft', 'Обзор', 'Insight'], // по кругу
    ['ArrowRight', 'Insight', 'Обзор'],
    ['End', 'Обзор', 'Insight'],
    ['Home', 'Insight', 'Обзор'],
  ])('%s с вкладки «%s» открывает «%s» и переносит на неё фокус', async (key, from, to) => {
    render(<Harness />)
    await userEvent.click(tab(from))
    await userEvent.keyboard(`{${key}}`)
    expect(screen.getByTestId('current')).toHaveTextContent(to)
    expect(tab(to)).toHaveFocus()
  })

  it('после стрелки Tab снова входит на новую активную вкладку', async () => {
    render(<Harness />)
    await userEvent.tab()
    await userEvent.keyboard('{ArrowRight}{ArrowRight}')
    await userEvent.tab()
    await userEvent.tab({ shift: true })
    expect(tab('События')).toHaveFocus()
  })
})
