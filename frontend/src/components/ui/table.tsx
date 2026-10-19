import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Таблица админских списков: горизонтальная прокрутка, шапка и разделители строк. head — ячейки <Th> одной строки,
 * className — минимальная ширина (min-w-[…]), ниже которой таблица прокручивается; children — строки <tr>.
 */
export function DataTable({ head, className, children }: { head: ReactNode; className?: string; children: ReactNode }) {
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className={cn('w-full text-left text-[13px]', className)}>
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>{head}</tr>
        </thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  )
}

/** Ячейка шапки DataTable; без содержимого — пустой столбец под кнопки действий */
export function Th({ right, children }: { right?: boolean; children?: ReactNode }) {
  return <th className={cn('px-4 py-2.5 font-medium', right && 'text-right')}>{children}</th>
}
