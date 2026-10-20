import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/ui/card'
import { Tabs } from '@/components/ui/tabs'
import { DepartmentsTab } from '@/features/admin/DepartmentsTab'
import { EmployeesTab } from '@/features/admin/EmployeesTab'

const TABS = ['Сотрудники', 'Отделы'] as const
type Tab = (typeof TABS)[number]

/** Учёт сотрудников и справочник отделов в одном разделе; вкладка хранится в адресе (?tab=departments) */
export function PeoplePage() {
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'departments' ? 'Отделы' : 'Сотрудники'

  return (
    <>
      <PageHeader title="Сотрудники и отделы" description="Назначьте отдел — от него зависит, какие пулы компьютеров человек видит в каталоге" />
      <div className="mb-4 sm:w-80">
        <Tabs tabs={TABS} value={tab} onChange={(t) => setParams(t === 'Отделы' ? { tab: 'departments' } : {}, { replace: true })} />
      </div>
      {tab === 'Отделы' ? <DepartmentsTab /> : <EmployeesTab />}
    </>
  )
}
