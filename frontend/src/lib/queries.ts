// Все запросы к API в виде хуков TanStack Query — кэш, повторы, инвалидация

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  Booking, BookingCreate, BookingExtend, BookingExtension, Computer, ComputerDetail, ComputerHistory, Department, DepartmentUsage,
  AdminUserRow, AppSettings, AuthConfig, InventoryPage, InventoryRow, Pool, PoolAssignResult, Stats, SyncInfo, SyncRun,
  Tier, TierSummary, Vm, VmCreate, VmOptions, ServiceRequest, OverdueItem, SyncRunDetails, EventPage, RequestDetail, VsphereCheck,
} from './types'

export interface ComputerFilters {
  tier?: Tier
  q?: string
  min_ram?: number
  gpu_only?: boolean
  sort?: 'name' | 'ram_desc' | 'ram_asc'
}

export const useAuthConfig = () => useQuery({ queryKey: ['auth-config'], queryFn: () => api.get<AuthConfig>('/auth/config') })

export const useCatalogSummary = (refreshSec = 15) =>
  useQuery({
    queryKey: ['catalog-summary'],
    queryFn: () => api.get<TierSummary[]>('/catalog/summary'),
    refetchInterval: refreshSec * 1000,
  })

// каталог сам обновляется: забранный кем-то ПК исчезает из списка у всех за пару секунд
export const useComputers = (filters: ComputerFilters, refreshSec = 15) =>
  useQuery({
    queryKey: ['computers', filters],
    queryFn: () => api.get<Computer[]>('/computers', { ...filters }),
    placeholderData: (prev) => prev,
    refetchInterval: refreshSec * 1000,
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

export function useExtendBooking() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, ...data }: BookingExtend & { id: number }) => api.post<Booking>(`/bookings/${id}/extend`, data),
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

export interface EventFilters {
  q?: string
  event_type?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export const useStats = () => useQuery({ queryKey: ['admin', 'stats'], queryFn: () => api.get<Stats>('/admin/stats') })

export const useInventory = (filters: InventoryFilters) =>
  useQuery({
    queryKey: ['admin', 'inventory', filters],
    queryFn: () => api.get<InventoryPage>('/admin/inventory', { ...filters }),
    placeholderData: (prev) => prev,
  })

/** Ссылка на CSV-выгрузку инвентаризации с текущими фильтрами пула и отдела */
export const inventoryExportUrl = ({ department_id, pool_id }: InventoryFilters) =>
  api.url('/admin/inventory/export', { department_id, pool_id })

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

export const useEvents = (filters: EventFilters = { limit: 12, offset: 0 }) =>
  useQuery({ 
    queryKey: ['admin', 'events', filters], 
    queryFn: () => api.get<EventPage>('/admin/events', { ...filters }),
    placeholderData: (prev) => prev,
  })

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
    mutationFn: ({ id, ...data }: { id?: number; name?: string; description?: string | null; is_published?: boolean; department_ids?: number[] }) =>
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

// ---------- Виртуалки ----------

export const useVmOptions = (enabled = true) =>
  useQuery({ queryKey: ['vm-options'], queryFn: () => api.get<VmOptions>('/vms/options'), enabled })

export const useMyVms = () =>
  useQuery({
    queryKey: ['my-vms'],
    queryFn: () => api.get<Vm[]>('/vms/my'),
    // пока ВМ создаётся или удаляется — обновляем чаще
    refetchInterval: (q) =>
      q.state.data?.some((v) => ['queued', 'creating', 'deleting'].includes(v.status) || (v.status === 'ready' && !v.ip_address))
        ? 5000
        : false,
  })

export function useCreateVm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: VmCreate) => api.post<Vm>('/vms', data),
    onSettled: () => Promise.all(['my-vms', 'vm-options', 'admin'].map((k) => qc.invalidateQueries({ queryKey: [k] }))),
  })
}

export function useReleaseVm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<Vm>(`/vms/${id}/release`),
    onSettled: () => Promise.all(['my-vms', 'vm-options', 'admin'].map((k) => qc.invalidateQueries({ queryKey: [k] }))),
  })
}

export const useAdminVms = (includeDeleted = false) =>
  useQuery({
    queryKey: ['admin', 'vms', includeDeleted],
    queryFn: () => api.get<Vm[]>('/admin/vms', { include_deleted: includeDeleted }),
    refetchInterval: 10_000,
  })

// ---------- Настройки и сотрудники ----------

export const useAppSettings = () =>
  useQuery({ queryKey: ['admin', 'settings'], queryFn: () => api.get<AppSettings>('/admin/settings') })

export function useSaveSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Partial<AppSettings>) => api.patch<AppSettings>('/admin/settings', data),
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: ['admin'] }), qc.invalidateQueries({ queryKey: ['vm-options'] })]),
  })
}

export const useVsphereCheck = () =>
  useMutation({ mutationFn: () => api.post<VsphereCheck>('/admin/vsphere/check') })

export const useAdminUsers = () =>
  useQuery({ queryKey: ['admin', 'users'], queryFn: () => api.get<AdminUserRow[]>('/admin/users') })

export function useSaveUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id?: number; email?: string; display_name?: string; department_id?: number | null; is_active?: boolean }) =>
      id ? api.patch<AdminUserRow>(`/admin/users/${id}`, data) : api.post<AdminUserRow>('/admin/users', data),
    onSettled: () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  })
}

// ---------- Service Desk: заявки по ПК и виртуалкам ----------

export const useSdConfig = () =>
  useQuery({ queryKey: ['sd-config'], queryFn: () => api.get<{ enabled: boolean }>('/requests/config'), staleTime: 300_000 })

export const useMyRequests = () =>
  useQuery({ queryKey: ['my-requests'], queryFn: () => api.get<ServiceRequest[]>('/requests/my'), refetchInterval: 30_000 })

export const useRequestDetail = (id: number | null) =>
  useQuery({
    queryKey: ['request', id],
    queryFn: () => api.get<RequestDetail>(`/requests/${id}`),
    enabled: id !== null,
    refetchInterval: 15_000, // новые ответы админов подтягиваются сами
  })

export function useCreateRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { booking_id?: number; vm_id?: number; message: string }) => api.post<ServiceRequest>('/requests', data),
    onSettled: () => qc.invalidateQueries({ queryKey: ['my-requests'] }),
  })
}

export function useAddComment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, message }: { id: number; message: string }) => api.post<void>(`/requests/${id}/comments`, { message }),
    onSettled: (_d, _e, v) => qc.invalidateQueries({ queryKey: ['request', v.id] }),
  })
}

// ---------- Сроки аренды и детали синхронизации ----------

export const useOverdue = (enabled = true) =>
  useQuery({ queryKey: ['admin', 'overdue'], queryFn: () => api.get<OverdueItem[]>('/admin/overdue'), enabled, refetchInterval: 60_000 })

export const useExtensions = (enabled = true) =>
  useQuery({
    queryKey: ['admin', 'extensions'],
    queryFn: () => api.get<BookingExtension[]>('/admin/extensions'),
    enabled,
    refetchInterval: 60_000,
  })

export function useAckExtension() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<BookingExtension>(`/admin/extensions/${id}/ack`),
    onSettled: () => qc.invalidateQueries({ queryKey: ['admin', 'extensions'] }),
  })
}

export const useSyncRunDetails = (id: number | null) =>
  useQuery({
    queryKey: ['admin', 'sync-run', id],
    queryFn: () => api.get<SyncRunDetails>(`/admin/sync/runs/${id}`),
    enabled: id !== null,
  })
