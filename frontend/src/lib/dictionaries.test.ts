import { describe, expect, it } from 'vitest'
import { canExtendVm, canReleaseVm, VM_STATUS } from './dictionaries'
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

describe('canExtendVm', () => {
  it.each([
    ['queued', true],
    ['creating', true],
    ['ready', true],
    ['failed', true],
    ['deleting', false],
    ['deleted', false],
  ] as [VmStatus, boolean][])('%s -> %s', (status, expected) => {
    expect(canExtendVm(status)).toBe(expected)
  })
})
