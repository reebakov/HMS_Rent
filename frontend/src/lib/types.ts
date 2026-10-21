// Типы ответов API (зеркало pydantic-схем из backend/app/schemas)

export type Tier = 'weak' | 'medium' | 'powerful' | 'vm'
export type ComputerStatus = 'available' | 'booked' | 'in_use' | 'maintenance' | 'retired' | 'unknown'
export type BookingStatus = 'active' | 'returned' | 'cancelled'

export interface User {
  id: number
  username: string
  display_name: string
  email: string | null
  avatar_url: string | null
  auth_source: 'bouncer' | 'microsoft' | 'local' | 'dev'
  role: 'user' | 'admin'
  department_id: number | null
}

export interface Session {
  user: User
  app_name: string
  app_subtitle: string
  insight_mode: 'mock' | 'live'
  catalog_refresh_sec: number
}

export interface AuthConfig {
  app_name: string
  bouncer_enabled: boolean
  local_enabled: boolean
  dev_enabled: boolean
}

export interface Ref {
  id: number
  name: string
}

export interface UserShort {
  id: number
  username: string
  display_name: string
}

export interface Computer {
  id: number
  name: string
  hostname: string | null
  insight_key: string | null
  is_virtual: boolean
  tier: Tier
  cpu: string | null
  cpu_cores: number | null
  ram_gb: number | null
  storage: string | null
  storage_gb: number | null
  gpu: string | null
  os: string | null
  location: string | null
  status: ComputerStatus
  insight_status: string | null
  department: Ref | null
  synced_at: string | null
}

export interface ComputerDetail extends Computer {
  serial_number: string | null
  ip_address: string | null
  note: string | null
  attributes: Record<string, string>
}

export interface TierSummary {
  tier: Tier
  available: number
  total: number
  min_ram_gb: number | null
  max_ram_gb: number | null
}

export interface Department {
  id: number
  name: string
  code: string | null
  head_name: string | null
  is_active: boolean
}

export interface ComputerShort {
  id: number
  name: string
  tier: Tier
  is_virtual: boolean
  cpu: string | null
  ram_gb: number | null
  storage: string | null
  gpu: string | null
}

export interface Booking {
  id: number
  order_number: number
  status: BookingStatus
  computer: ComputerShort
  department: Ref
  user: UserShort
  requester_name: string
  requester_nick: string
  purpose: string | null
  os_label: string | null // ОС, которую поставит исполнитель
  booked_at: string
  expected_return_at: string | null
  requested_return_at: string | null // срок из заявки админу, пока она ждёт решения
  returned_at: string | null
  returned_by: UserShort | null
  return_comment: string | null
}

export interface BookingCreate {
  computer_id: number
  department_id: number
  requester_name: string
  requester_nick: string
  purpose?: string
  expected_return_at: string
  os_label?: string
}

/** Что можно выбрать при заказе физического ПК (Админка → «Настройки») */
export interface OrderOptions {
  os: string[]
  builds: string[]
}

/** Сборка по запросу: типовая сборка или своя конфигурация — одно из двух */
export interface BuildCreate {
  build?: string
  custom?: string
  os_label: string
  department_id: number
  requester_name: string
  requester_nick: string
  expected_return_at: string
  wanted_by?: string
  purpose?: string
}

export interface BookingExtend {
  expected_return_at: string
  comment?: string
}

// ---------- Админка ----------

export interface SyncRun {
  id: number
  started_at: string
  finished_at: string | null
  status: 'running' | 'success' | 'failed'
  mode: 'mock' | 'live'
  total: number
  created: number
  updated: number
  archived: number
  error: string | null
}

export interface TierStat {
  tier: Tier
  total: number
  available: number
  booked: number
}

export interface Stats {
  total: number
  by_status: Partial<Record<ComputerStatus, number>>
  by_tier: TierStat[]
  in_pools: number
  active_bookings: number
  departments_using: number
  overdue: number
  issues: number
  last_sync: SyncRun | null
}

export interface IdleServer {
  id: number
  name: string
  idle_days: number
  idle_since: string
}

export interface IdleServers {
  count: number
  average_days: number
  items: IdleServer[]
}

export interface ClusterCapacity {
  ok: boolean
  error: string | null
  cpu_total_ghz: number
  cpu_free_ghz: number
  ram_total_gb: number
  ram_free_gb: number
  storage_total_gb: number
  storage_free_gb: number
}

export interface VmNumbers {
  ok: boolean
  error: string | null
  free: number
  low: boolean // номеров мало или нет совсем
}

export interface InventoryRow extends Computer {
  serial_number: string | null
  is_archived: boolean
  tier_override: Tier | null
  note: string | null
  writeback_error: string | null
  usage_until: string | null
  order_number: number | null
  pool: PoolShort | null
  booking: {
    id: number
    requester_name: string
    requester_nick: string
    booked_at: string
    expected_return_at: string | null
    user: UserShort
  } | null
  issues: string[]
}

export interface DepartmentUsage {
  department_id: number
  name: string
  code: string | null
  head_name: string | null
  is_active: boolean
  active: number
  by_tier: Partial<Record<Tier, number>>
  total_bookings: number
  last_booked_at: string | null
}

export interface AssetEvent {
  id: number
  computer: Ref
  booking_id: number | null
  event_type: string
  from_status: string | null
  to_status: string | null
  message: string
  actor: UserShort | null
  created_at: string
}

export interface EventPage {
  items: AssetEvent[]
  total: number
}

export interface ComputerHistory {
  computer: InventoryRow
  attributes: Record<string, string>
  bookings: Booking[]
  events: AssetEvent[]
}

export interface SyncInfo {
  mode: 'mock' | 'live'
  jira_url: string
  interval_sec: number
  writeback: boolean
  runs: SyncRun[]
}

export interface PoolShort {
  id: number
  name: string
  is_published: boolean
}

export interface Pool extends PoolShort {
  description: string | null
  departments: Ref[]
  total: number
  available: number
  booked: number
}

export interface InventoryPage {
  items: InventoryRow[]
  total: number
}

export interface PoolAssignResult {
  updated: number
  not_found: string[]
}

// ---------- Виртуалки ----------

export type VmStatus = 'queued' | 'creating' | 'ready' | 'failed' | 'deleting' | 'deleted'

export interface Vm {
  id: number
  order_number: number
  name: string
  cpu: number
  ram_gb: number
  disk_gb: number
  template_key: string | null
  os_label: string | null
  status: VmStatus
  error: string | null
  department: Ref
  user: UserShort
  requester_name: string
  requester_nick: string
  purpose: string | null
  expected_return_at: string | null
  requested_return_at: string | null // срок из заявки админу, пока она ждёт решения
  ip_address: string | null
  connection_login: string
  connection_method: 'RDP' | 'VNC' | null // способ подключения по ОС; пусто, если ОС неизвестна
  power_state: string | null
  created_at: string
  ready_at: string | null
  released_at: string | null
  deleted_at: string | null
}

export interface VmOptions {
  enabled: boolean
  reason: string | null
  template: string
  min_cpu: number
  max_cpu: number
  min_ram_gb: number
  max_ram_gb: number
  min_disk_gb: number
  max_disk_gb: number
  max_per_user: number
  used_by_me: number
  templates: VmTemplateOption[]
  sizes: VmSize[] // готовые размеры, которые укладываются в лимиты
}

/** Готовый размер ВМ: ядра, память и диск разом */
export interface VmSize {
  label: string
  cpu: number
  ram_gb: number
  disk_gb: number
}

export interface VmTemplateOption {
  key: string
  label: string
  os: 'windows' | 'linux'
  min_disk_gb: number
  available: boolean // false — шаблон ещё не настроен, в конструкторе «скоро»
}

export interface VmTemplate {
  key: string
  label: string
  os: 'windows' | 'linux'
  template: string
  customization_spec: string
  min_disk_gb: number
  enabled: boolean
}

export interface VmCreate {
  cpu: number
  ram_gb: number
  disk_gb: number
  department_id: number
  requester_name: string
  requester_nick: string
  purpose?: string
  expected_return_at: string
  template_key?: string | null
}

// ---------- Настройки и сотрудники ----------

export interface AppSettings {
  insight_sync_interval_min: number
  insight_writeback: boolean
  vm_enabled: boolean
  vm_max_per_user: number
  vm_min_cpu: number
  vm_max_cpu: number
  vm_min_ram_gb: number
  vm_max_ram_gb: number
  vm_min_disk_gb: number
  vm_max_disk_gb: number
  catalog_refresh_sec: number
  vm_templates: VmTemplate[]
  vm_sizes: VmSize[]
  pc_os_list: string[]
  pc_builds: string[]
  vsphere_configured: boolean
  vcenter_host: string
}

export interface AdminUserRow {
  id: number
  username: string
  display_name: string
  email: string | null
  auth_source: 'bouncer' | 'microsoft' | 'local' | 'dev'
  role: 'user' | 'admin'
  is_active: boolean
  department: Ref | null
  last_login_at: string | null
}

    // ---------- Service Desk ----------

export interface ServiceRequest {
  id: number
  kind: 'problem' | 'return' | 'prepare' | 'build'
  booking_id: number | null
  vm_id: number | null
  department_id: number | null // команда сборки по запросу
  issue_key: string | null
  summary: string
  status: string | null
  status_category: string | null // new / indeterminate / done
  error: string | null
  created_at: string
  url: string | null
}

export interface ServiceComment {
  author: string
  body: string
  created: string | null
  from_portal: boolean
}

export interface RequestDetail {
  request: ServiceRequest
  comments: ServiceComment[]
}

// ---------- Сроки аренды и детали синхронизации ----------

/** Продление срока аренды: у ПК заполнен booking, у ВМ — vm */
export interface ExtensionOut {
  id: number
  kind: 'pc' | 'vm'
  name: string
  booking: Booking | null
  vm: Vm | null
  user: UserShort
  old_return_at: string | null
  new_return_at: string
  comment: string | null
  created_at: string
  acknowledged_at: string | null
  acknowledged_by: UserShort | null
}

/** Заявка админу на срок аренды дольше лимита */
export interface TermRequestOut {
  id: number
  kind: 'pc' | 'vm'
  name: string
  order_number: number
  department: Ref
  requester_name: string
  requester_nick: string
  user: UserShort // кто просит
  current_return_at: string | null
  requested_return_at: string
  comment: string | null
  created_at: string
}

export interface OverdueItem {
  kind: 'pc' | 'vm'
  id: number
  order_number: number | null
  name: string
  department: string
  requester_name: string
  requester_nick: string
  email: string | null
  taken_at: string | null
  due: string
  days: number
}

export interface SyncRunDetails {
  id: number
  started_at: string
  updated: { id: number; name: string; changes: { field: string; old: string; new: string }[] }[]
  created: { id: number; name: string }[]
  archived: { id: number; name: string }[]
}

/** Ответ POST /admin/vsphere/check: «ok» — всё найдено, иначе текст ошибки */
export type VsphereCheck =
  | {
      ok: true
      vcenter: string
      datacenter: string
      pool: string
      folder: string
      template: string
      template_cpu: number
      template_ram_gb: number
      template_disk_gb: number
      templates: Record<string, boolean>
    }
  | { ok: false; error: string }
