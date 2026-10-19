import { describe, expect, it } from 'vitest'
import { canReleaseVm, VM_STATUS } from './dictionaries'
import type { VmStatus } from './types'

describe('VM_STATUS', () => {
  it('словарь подписей содержит все статусы ВМ', () => {
    expect(Object.keys(VM_STATUS).sort()).toEqual(['creating', 'deleted', 'deleting', 'failed', 'queued', 'ready'])
  })
})

describe('canReleaseVm', () => {
  it.each([
    ['queued', true],
    ['ready', true],
    ['failed', true],
    ['creating', false],
    ['deleting', false],
    ['deleted', false],
  ] as [VmStatus, boolean][])('%s -> %s', (status, expected) => {
    expect(canReleaseVm(status)).toBe(expected)
  })
})
