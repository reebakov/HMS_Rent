import { useEffect, useState } from 'react'
import { LayoutGrid, List } from 'lucide-react'
import { cn } from '@/lib/utils'

type ViewMode = 'cards' | 'compact'

/** Режим отображения списка, запоминается в браузере отдельно для каждой страницы */
export function useViewMode(key: string): [ViewMode, (mode: ViewMode) => void] {
  const storageKey = `hmsrent:view:${key}`
  const [mode, setMode] = useState<ViewMode>(() => (localStorage.getItem(storageKey) as ViewMode) || 'cards')
  useEffect(() => localStorage.setItem(storageKey, mode), [storageKey, mode])
  return [mode, setMode]
}

export function ViewToggle({ value, onChange }: { value: ViewMode; onChange: (mode: ViewMode) => void }) {
  const items = [
    { mode: 'cards' as const, icon: LayoutGrid, title: 'Подробно' },
    { mode: 'compact' as const, icon: List, title: 'Списком — только номера' },
  ]
  return (
    <div className="flex h-9 rounded-lg border bg-card p-0.5">
      {items.map(({ mode, icon: Icon, title }) => (
        <button
          key={mode}
          title={title}
          onClick={() => onChange(mode)}
          className={cn(
            'flex w-8 items-center justify-center rounded-md transition-colors',
            value === mode ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Icon className="h-4 w-4" />
        </button>
      ))}
    </div>
  )
}
