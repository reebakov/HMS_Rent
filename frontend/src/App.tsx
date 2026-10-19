import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/auth/AuthProvider'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/pages/LoginPage'
import { CatalogPage } from '@/pages/CatalogPage'
import { MyBookingsPage } from '@/pages/MyBookingsPage'
import { AdminOverviewPage } from '@/pages/admin/AdminOverviewPage'
import { InventoryPage } from '@/pages/admin/InventoryPage'
import { JournalPage } from '@/pages/admin/JournalPage'
import { DepartmentsPage } from '@/pages/admin/DepartmentsPage'
import { SyncPage } from '@/pages/admin/SyncPage'
import { PoolsPage } from '@/pages/admin/PoolsPage'
import { EventsPage } from '@/pages/admin/EventsPage'
import { SettingsPage } from '@/pages/admin/SettingsPage'
import { UsersPage } from '@/pages/admin/UsersPage'
import { VmsPage } from '@/pages/admin/VmsPage'
import { OverduePage } from '@/pages/admin/OverduePage'

function RequireAuth({ children }: { children: ReactElement }) {
  const { session } = useAuth()
  return session ? children : <Navigate to="/login" replace />
}

function RequireAdmin({ children }: { children: ReactElement }) {
  const { session } = useAuth()
  return session?.user.role === 'admin' ? children : <Navigate to="/" replace />
}

export default function App() {
  const { loading } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<CatalogPage />} />
        <Route path="my" element={<MyBookingsPage />} />
        <Route path="admin" element={<RequireAdmin><AdminOverviewPage /></RequireAdmin>} />
        <Route path="admin/inventory" element={<RequireAdmin><InventoryPage /></RequireAdmin>} />
        <Route path="admin/pools" element={<RequireAdmin><PoolsPage /></RequireAdmin>} />
        <Route path="admin/journal" element={<RequireAdmin><JournalPage /></RequireAdmin>} />
        <Route path="admin/departments" element={<RequireAdmin><DepartmentsPage /></RequireAdmin>} />
        <Route path="admin/events" element={<RequireAdmin><EventsPage /></RequireAdmin>} />
        <Route path="admin/sync" element={<RequireAdmin><SyncPage /></RequireAdmin>} />
        <Route path="admin/vms" element={<RequireAdmin><VmsPage /></RequireAdmin>} />
        <Route path="admin/overdue" element={<RequireAdmin><OverduePage /></RequireAdmin>} />
        <Route path="admin/users" element={<RequireAdmin><UsersPage /></RequireAdmin>} />
        <Route path="admin/settings" element={<RequireAdmin><SettingsPage /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
