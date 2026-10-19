import { Loader2 } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { useSyncRunDetails } from '@/lib/queries'
import { formatDateTime } from '@/lib/utils'

export type DetailsTab = 'updated' | 'created' | 'archived'

const TITLES: Record<DetailsTab, string> = { updated: 'Изменено', created: 'Новые ПК', archived: 'Ушли в архив' }

/** Что поменялось в одном запуске синхронизации: поле, было → стало */
export function SyncRunDialog({ runId, tab, onClose }: { runId: number | null; tab: DetailsTab; onClose: () => void }) {
  const { data, isLoading } = useSyncRunDetails(runId)
  const items = data?.[tab] ?? []

  return (
    <Dialog
      open={runId !== null}
      onOpenChange={(o) => !o && onClose()}
      title={`${TITLES[tab]}: ${items.length}`}
      description={data ? `Синхронизация ${formatDateTime(data.started_at)}` : undefined}
      className="max-w-2xl"
    >
      {isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : !items.length ? (
        <p className="py-6 text-center text-[13px] text-muted-foreground">
          Подробностей нет — запуск был до обновления портала или изменений не было
        </p>
      ) : tab === 'updated' ? (
        <div className="divide-y rounded-xl border">
          {data!.updated.map((item) => (
            <div key={item.id} className="px-4 py-3 text-[13px]">
              <p className="font-semibold">{item.name}</p>
              {item.changes.length ? (
                <ul className="mt-1 space-y-0.5">
                  {item.changes.map((ch, i) => (
                    <li key={i} className="flex flex-wrap gap-x-2">
                      <span className="text-muted-foreground">{ch.field}:</span>
                      <span className="text-danger line-through decoration-danger/40">{ch.old}</span>
                      <span>→</span>
                      <span className="font-medium text-success">{ch.new}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">Вернулся из архива или изменились служебные поля</p>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <span key={item.id} className="rounded-md border px-2 py-1 text-[13px] font-medium">
              {item.name}
            </span>
          ))}
        </div>
      )}
    </Dialog>
  )
}
