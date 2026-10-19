import type { KeyboardEvent } from 'react'
import { cn } from '@/lib/utils'

/**
 * Переключатель вкладок. С клавиатуры: в фокусе одна вкладка (активная), ←/→ переходят к соседней по кругу,
 * Home/End — к первой и последней; вкладка активируется вместе с фокусом.
 */
export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: readonly T[]; value: T; onChange: (tab: T) => void }) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.indexOf(value)
    const target: Record<string, number> = {
      ArrowRight: (i + 1) % tabs.length,
      ArrowLeft: (i - 1 + tabs.length) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }
    const next = target[e.key]
    if (next === undefined) return
    e.preventDefault()
    onChange(tabs[next])
    e.currentTarget.querySelectorAll('button')[next].focus()
  }

  return (
    <div className="flex gap-1 rounded-lg bg-muted p-1" onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t}
          type="button"
          tabIndex={t === value ? 0 : -1}
          onClick={() => onChange(t)}
          className={cn(
            'flex-1 rounded-md px-2 py-1.5 text-[13px] font-medium transition-colors',
            t === value ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {t}
        </button>
      ))}
    </div>
  )
}
