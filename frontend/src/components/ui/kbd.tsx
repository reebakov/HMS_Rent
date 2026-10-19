import type { ReactNode } from 'react'

/** Клавиша в тексте и подсказках */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex min-w-[1.5rem] items-center justify-center rounded-md border bg-muted px-1.5 py-0.5 font-mono text-xs font-medium text-foreground shadow-sm">
      {children}
    </kbd>
  )
}
