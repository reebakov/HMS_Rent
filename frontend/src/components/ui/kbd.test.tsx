import { expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Kbd } from './kbd'

it('Kbd рисует клавишу элементом kbd', () => {
  render(<Kbd>Esc</Kbd>)
  expect(screen.getByText('Esc').tagName).toBe('KBD')
})
