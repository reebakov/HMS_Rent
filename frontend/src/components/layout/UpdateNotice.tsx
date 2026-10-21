import { useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import { Button } from '@/components/ui/button'
import { useServerVersion } from '@/lib/queries'
import { isTransient } from '@/lib/queryRetry'
import { APP_VERSION } from '@/lib/version'

/** Идёт ли повтор запроса из-за перезапуска сервера: тогда вместо красной ошибки показываем «Сервис обновляется» */
function useServiceUpdating(): boolean {
  const cache = useQueryClient().getQueryCache()
  return useSyncExternalStore(
    (notify) => cache.subscribe(notify),
    () => cache.findAll({ fetchStatus: 'fetching' }).some((q) => q.state.fetchFailureCount > 0 && isTransient(q.state.fetchFailureReason)),
  )
}

/**
 * Две тихие плашки внизу экрана. «Сервис обновляется» — пока сервер перезапускается и запросы повторяются сами.
 * «Доступна новая версия» — когда backend (уже обновлённый) отдаёт другую версию, чем та, что загружена на вкладке;
 * страница сама не перезагружается, пользователь обновляет её, когда ему удобно.
 */
export function UpdateNotice() {
  const updating = useServiceUpdating()
  const { data: serverVersion } = useServerVersion()
  const outdated = !!serverVersion && APP_VERSION !== 'dev' && serverVersion !== 'dev' && serverVersion !== APP_VERSION

  if (updating) {
    return (
      <div role="status" className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-[13px] shadow-lg">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        Сервис обновляется, повторяем запрос…
      </div>
    )
  }
  if (!outdated) return null
  return (
    <div role="status" className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-lg border bg-card px-4 py-2.5 text-[13px] shadow-lg">
      <RefreshCw className="h-4 w-4 text-primary" />
      Доступна новая версия портала
      <Button size="sm" onClick={() => window.location.reload()}>
        Обновить
      </Button>
    </div>
  )
}
