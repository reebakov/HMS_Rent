// Все запросы к API в виде хуков TanStack Query — кэш, повторы, инвалидация

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  Booking, BookingCreate, BookingExtend, Computer, ComputerDetail, ComputerHistory, Department, DepartmentUsage,
  AdminUserRow, AppSettings, AuthConfig, InventoryPage, InventoryRow, Pool, PoolAssignResult, Stats, SyncInfo, SyncRun,
  Tier, TierSummary, Vm, VmCreate, VmOptions, ServiceRequest, OverdueItem, SyncRunDetails, EventPage, ExtensionOut, RequestDetail, VsphereCheck, TermRequestOut, OrderOptions, BuildCreate,
  ClusterCapacity, IdleServers, VmNumbers, NotificationList, ExecutorBuild, ExecutorBuildIssue, PoolShort, ExecutorDiagnostic, ExecutorOrder, ExecutorProblem, ExecutorReject, ExecutorResult, ExecutorVm, ExecutorVmReject, ProblemTransition, Replacement,
} from './types'

export interface ComputerFilters {
  tier?: Tier
  q?: string
  min_ram?: number
  gpu?: 'discrete' | 'integrated' // дискретная или встроенная видеокарта (нет карты — встроенная)
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

/** ОС и типовые сборки для брони ПК и сборки по запросу */
export const useOrderOptions = (enabled = true) =>
  useQuery({ queryKey: ['order-options'], queryFn: () => api.get<OrderOptions>('/catalog/order-options'), enabled, staleTime: 5 * 60_000 })

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

// Сверка версии с сервером: после выкатки backend уже новый, а открытая страница ещё старая
export const useServerVersion = () =>
  useQuery({
    queryKey: ['server-version'],
    queryFn: api.serverVersion,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    staleTime: 0,
    retry: false,
  })

export const useStats = () => useQuery({ queryKey: ['admin', 'stats'], queryFn: () => api.get<Stats>('/admin/stats') })

export const useIdleServers = () =>
  useQuery({ queryKey: ['admin', 'idle'], queryFn: () => api.get<IdleServers>('/admin/idle') })

// vCenter опрашивается на каждый запрос, поэтому обновляем редко
export const useClusterCapacity = () =>
  useQuery({ queryKey: ['admin', 'cluster'], queryFn: () => api.get<ClusterCapacity>('/admin/cluster'), refetchInterval: 300_000 })

// Insight опрашивается на каждый запрос, поэтому обновляем редко
export const useVmNumbers = () =>
  useQuery({ queryKey: ['admin', 'vm-numbers'], queryFn: () => api.get<VmNumbers>('/admin/vm-numbers'), refetchInterval: 300_000 })

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
      q.state.data?.some((v) => ['queued', 'creating', 'checking', 'deleting'].includes(v.status) || (v.status === 'ready' && !v.ip_address))
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

export function useExtendVm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: BookingExtend & { id: number }) => api.post<Vm>(`/vms/${id}/extend`, data),
    // 'admin' — просрочки, продления и список ВМ в админке
    onSettled: () => Promise.all(['my-vms', 'admin'].map((k) => qc.invalidateQueries({ queryKey: [k] }))),
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

export function useCancelBuild() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<void>(`/requests/${id}/cancel`),
    onSettled: () => Promise.all(['my-requests', 'executor'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

export function useCreateBuild() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: BuildCreate) => api.post<ServiceRequest>('/requests/build', data),
    onSettled: () => qc.invalidateQueries({ queryKey: ['my-requests'] }),
  })
}

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
    queryFn: () => api.get<ExtensionOut[]>('/admin/extensions'),
    enabled,
    refetchInterval: 60_000,
  })

export function useAckExtension() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<ExtensionOut>(`/admin/extensions/${id}/ack`),
    onSettled: () => qc.invalidateQueries({ queryKey: ['admin', 'extensions'] }),
  })
}

export const useTermRequests = (enabled = true) =>
  useQuery({
    queryKey: ['admin', 'term-requests'],
    queryFn: () => api.get<TermRequestOut[]>('/admin/term-requests'),
    enabled,
    refetchInterval: 60_000,
  })

/** Согласование заявки на срок: без approved_return_at ставится запрошенный срок */
export function useApproveTermRequest() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, approved_return_at }: { id: number; approved_return_at?: string }) =>
      api.post<TermRequestOut>(`/admin/term-requests/${id}/approve`, { approved_return_at }),
    onSettled: invalidate,
  })
}

export function useRejectTermRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<TermRequestOut>(`/admin/term-requests/${id}/reject`),
    onSettled: () => qc.invalidateQueries({ queryKey: ['admin', 'term-requests'] }),
  })
}

export const useSyncRunDetails = (id: number | null) =>
  useQuery({
    queryKey: ['admin', 'sync-run', id],
    queryFn: () => api.get<SyncRunDetails>(`/admin/sync/runs/${id}`),
    enabled: id !== null,
  })

// ---------- Уведомления (колокольчик) ----------

export const useNotifications = () =>
  useQuery({ queryKey: ['notifications'], queryFn: () => api.get<NotificationList>('/notifications'), refetchInterval: 60_000 })

/** Прочитать одно уведомление, а без id — все */
export function useReadNotifications() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id?: number) => api.post<void>(id === undefined ? '/notifications/read-all' : `/notifications/${id}/read`),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}

// ---------- Исполнитель ----------

/** Активные брони: сначала ждущие подготовки, обновляется сама — новые брони появляются без перезагрузки */
export const useExecutorOrders = (enabled = true) =>
  useQuery({
    queryKey: ['executor', 'orders'],
    queryFn: () => api.get<ExecutorOrder[]>('/executor/orders'),
    enabled,
    refetchInterval: 60_000,
  })

export const useExecutorProblems = (enabled = true) =>
  useQuery({
    queryKey: ['executor', 'problems'],
    queryFn: () => api.get<ExecutorProblem[]>('/executor/problems'),
    enabled,
    refetchInterval: 60_000,
  })

/** Свободные ПК той же категории для замены неисправного в заказе; грузятся, когда исполнитель открыл окно замены */
export const useReplacements = (orderId: number, enabled: boolean) =>
  useQuery({
    queryKey: ['executor', 'replacements', orderId],
    queryFn: () => api.get<Replacement[]>(`/executor/orders/${orderId}/replacements`),
    enabled,
    gcTime: 0,
  })

export function useReplaceComputer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; computer_id: number; comment: string }) =>
      api.post<ExecutorOrder>(`/executor/orders/${id}/replace`, data),
    onSettled: () => Promise.all(['executor', 'my-bookings', 'computers', 'admin'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

/** ПК на диагностике: выведены из пула как неисправные */
export const useExecutorDiagnostics = (enabled = true) =>
  useQuery({
    queryKey: ['executor', 'diagnostics'],
    queryFn: () => api.get<ExecutorDiagnostic[]>('/executor/diagnostics'),
    enabled,
    refetchInterval: 60_000,
  })

export function useRepairComputer() {
  const qc = useQueryClient()
  const invalidate = useInvalidateAll() // ПК снова в каталоге
  return useMutation({
    mutationFn: (id: number) => api.post<ExecutorDiagnostic>(`/executor/diagnostics/${id}/repaired`),
    onSettled: () => Promise.all([invalidate(), qc.invalidateQueries({ queryKey: ['executor'] })]),
  })
}

/** ВМ, созданные в vSphere и ждущие проверки исполнителем */
export const useExecutorVms = (enabled = true) =>
  useQuery({
    queryKey: ['executor', 'vms'],
    queryFn: () => api.get<ExecutorVm[]>('/executor/vms'),
    enabled,
    refetchInterval: 60_000,
  })

function useVmDecision<V>(path: (id: number) => string, body: (v: V) => unknown, idOf: (v: V) => number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: V) => api.post<ExecutorVm>(path(idOf(v)), body(v)),
    onSettled: () => Promise.all(['executor', 'my-vms', 'admin'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

export const useConfirmVm = () => useVmDecision<number>((id) => `/executor/vms/${id}/confirm`, () => undefined, (id) => id)
export const useRecreateVm = () => useVmDecision<number>((id) => `/executor/vms/${id}/recreate`, () => undefined, (id) => id)
export const useRejectVm = () =>
  useVmDecision<ExecutorVmReject & { id: number }>(
    (id) => `/executor/vms/${id}/reject`,
    ({ reason, comment }) => ({ reason, comment }),
    (v) => v.id,
  )

/** Переходы задачи Jira по проблеме; грузятся, только когда исполнитель открыл «Сменить статус» */
export const useProblemTransitions = (id: number, enabled: boolean) =>
  useQuery({
    queryKey: ['executor', 'problem-transitions', id],
    queryFn: () => api.get<ProblemTransition[]>(`/executor/problems/${id}/transitions`),
    enabled,
    gcTime: 0,
  })

export function useMoveProblem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, transitionId, comment }: { id: number; transitionId: string; comment?: string }) =>
      api.post<ExecutorProblem>(`/executor/problems/${id}/transition`, { transition_id: transitionId, ...(comment ? { comment } : {}) }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['executor'] }),
  })
}

/** Заказы на сборку, ждущие выдачи собранного ПК */
export const useExecutorBuilds = () =>
  useQuery({ queryKey: ['executor', 'builds'], queryFn: () => api.get<ExecutorBuild[]>('/executor/builds'), refetchInterval: 60_000 })

/** Пулы для выдачи собранного ПК: после возврата ПК остаётся в выбранном */
export const useExecutorPools = (enabled: boolean) =>
  useQuery({
    queryKey: ['executor', 'pools'],
    queryFn: () => api.get<Pick<PoolShort, 'id' | 'name'>[]>('/executor/pools'),
    enabled,
  })

export function useIssueBuild() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: ExecutorBuildIssue & { id: number }) => api.post<ExecutorOrder>(`/executor/builds/${id}/issue`, data),
    onSettled: () =>
      Promise.all(['executor', 'my-requests', 'my-bookings', 'computers', 'catalog-summary', 'admin'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

export function useRejectBuild() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: ExecutorReject & { id: number }) => api.post<void>(`/executor/builds/${id}/reject`, data),
    onSettled: () => Promise.all(['executor', 'my-requests'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

export const useExecutorOrder = (id: number) =>
  useQuery({ queryKey: ['executor', 'order', id], queryFn: () => api.get<ExecutorOrder>(`/executor/orders/${id}`) })

/** Вернувшиеся ПК, ждущие очистки диска */
export const useExecutorReturns = (enabled = true) =>
  useQuery({
    queryKey: ['executor', 'returns'],
    queryFn: () => api.get<ExecutorOrder[]>('/executor/returns'),
    enabled,
    refetchInterval: 60_000,
  })

export function useConfirmCleaned() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<ExecutorOrder>(`/executor/returns/${id}/cleaned`),
    onSettled: () =>
      Promise.all(['executor', 'computers', 'catalog-summary', 'admin'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

export function useRejectExecutorOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: ExecutorReject & { id: number }) => api.post<ExecutorOrder>(`/executor/orders/${id}/reject`, data),
    onSettled: () => Promise.all(['executor', 'my-bookings', 'admin'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}

export function useSaveExecutorResult() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: ExecutorResult & { id: number }) =>
      api.post<ExecutorOrder>(`/executor/orders/${id}/result`, data),
    onSettled: () => Promise.all(['executor', 'my-bookings'].map((key) => qc.invalidateQueries({ queryKey: [key] }))),
  })
}
