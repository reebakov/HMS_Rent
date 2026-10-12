// Все запросы к API в виде хуков TanStack Query — кэш, повторы, инвалидация

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  Booking, BookingCreate, Computer, ComputerDetail, ComputerHistory, Department, DepartmentUsage,
  AssetEvent, InventoryPage, InventoryRow, Pool, PoolAssignResult, Stats, SyncInfo, SyncRun, Tier, TierSummary,
} from './types'

export interface ComputerFilters {
  tier?: Tier
  q?: string
  min_ram?: number
  gpu_only?: boolean
  sort?: 'name' | 'ram_desc' | 'ram_asc'
}

export const useCatalogSummary = () =>
  useQuery({ queryKey: ['catalog-summary'], queryFn: () => api.get<TierSummary[]>('/catalog/summary') })

export const useComputers = (filters: ComputerFilters) =>
  useQuery({
    queryKey: ['computers', filters],
    queryFn: () => api.get<Computer[]>('/computers', { ...filters }),
    placeholderData: (prev) => prev,
  })

export const useComputer = (id: number | null) =>
  useQuery({
    queryKey: ['computer', id],
    queryFn: () => api.get<ComputerDetail>(`/computers/${id}`),
    enabled: id !== null,
  })

export const useDepartments = () =>
  useQuery({ queryKey: ['departments'], queryFn: () => api.get<Department[]>('/departments'), staleTime: 5 * 60_000 })

export const useMyBookings = () =>
  useQuery({ queryKey: ['my-bookings'], queryFn: () => api.get<Booking[]>('/bookings/my') })

/** После любого изменения брони обновляем всё, где фигурируют статусы ПК */
function useInvalidateAll() {
  const qc = useQueryClient()
  return () =>
    Promise.all(
      ['computers', 'catalog-summary', 'my-bookings', 'computer', 'admin'].map((key) =>
        qc.invalidateQueries({ queryKey: [key] }),
      ),
    )
}

export function useCreateBooking() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (data: BookingCreate) => api.post<Booking>('/bookings', data),
    onSettled: invalidate,
  })
}

export function useReturnBooking() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, comment }: { id: number; comment?: string }) =>
      api.post<Booking>(`/bookings/${id}/return`, { comment }),
    onSettled: invalidate,
  })
}

// ---------- Админка ----------

export interface InventoryFilters {
  q?: string
  status?: string
  tier?: string
  department_id?: number
  pool_id?: string // id пула или 'none'
  issues_only?: boolean
  include_archived?: boolean
  limit?: number
  offset?: number
}

export interface JournalFilters {
  q?: string
  status?: string
  department_id?: number
  date_from?: string
  date_to?: string
}

export const useStats = () => useQuery({ queryKey: ['admin', 'stats'], queryFn: () => api.get<Stats>('/admin/stats') })

export const useInventory = (filters: InventoryFilters) =>
  useQuery({
    queryKey: ['admin', 'inventory', filters],
    queryFn: () => api.get<InventoryPage>('/admin/inventory', { ...filters }),
    placeholderData: (prev) => prev,
  })

export const useComputerHistory = (id: number | null) =>
  useQuery({
    queryKey: ['admin', 'computer', id],
    queryFn: () => api.get<ComputerHistory>(`/admin/computers/${id}`),
    enabled: id !== null,
  })

export const useJournal = (filters: JournalFilters) =>
  useQuery({
    queryKey: ['admin', 'journal', filters],
    queryFn: () => api.get<Booking[]>('/admin/bookings', { ...filters }),
    placeholderData: (prev) => prev,
  })

export const useEvents = (limit = 12) =>
  useQuery({ queryKey: ['admin', 'events', limit], queryFn: () => api.get<AssetEvent[]>('/admin/events', { limit }) })

export const useDepartmentUsage = () =>
  useQuery({ queryKey: ['admin', 'departments'], queryFn: () => api.get<DepartmentUsage[]>('/admin/departments') })

export const useSyncInfo = () =>
  useQuery({ queryKey: ['admin', 'sync'], queryFn: () => api.get<SyncInfo>('/admin/sync') })

export function useRunSync() {
  const invalidate = useInvalidateAll()
  return useMutation({ mutationFn: () => api.post<SyncRun>('/admin/sync'), onSettled: invalidate })
}

export function useUpdateComputer() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; tier_override?: Tier | null; note?: string | null }) =>
      api.patch<InventoryRow>(`/admin/computers/${id}`, data),
    onSettled: invalidate,
  })
}

export function useSaveDepartment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id?: number; name?: string; code?: string | null; head_name?: string | null; is_active?: boolean }) =>
      id ? api.patch<Department>(`/admin/departments/${id}`, data) : api.post<Department>('/admin/departments', data),
    onSettled: () =>
      Promise.all([qc.invalidateQueries({ queryKey: ['admin'] }), qc.invalidateQueries({ queryKey: ['departments'] })]),
  })
}

// ---------- Пулы ----------

export const usePools = () => useQuery({ queryKey: ['admin', 'pools'], queryFn: () => api.get<Pool[]>('/admin/pools') })

export function useSavePool() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, ...data }: { id?: number; name?: string; description?: string | null; is_published?: boolean }) =>
      id ? api.patch<Pool>(`/admin/pools/${id}`, data) : api.post<Pool>('/admin/pools', data),
    onSettled: invalidate,
  })
}

export function useDeletePool() {
  const invalidate = useInvalidateAll()
  return useMutation({ mutationFn: (id: number) => api.del(`/admin/pools/${id}`), onSettled: invalidate })
}

export function useAssignPool() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (data: { pool_id: number | null; computer_ids?: number[]; names?: string }) =>
      api.post<PoolAssignResult>('/admin/pools/assign', data),
    onSettled: invalidate,
  })
}
