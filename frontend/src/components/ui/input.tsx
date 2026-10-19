import { forwardRef, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { ChevronDown, Search } from 'lucide-react'
import type { Department } from '@/lib/types'
import { cn } from '@/lib/utils'

const base =
  'w-full rounded-lg border bg-card px-3 text-sm shadow-sm transition-colors placeholder:text-muted-foreground/70 ' +
  'focus:outline-none focus:ring-2 focus:ring-ring/30 focus:border-ring disabled:cursor-not-allowed disabled:opacity-60'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn(base, 'h-9', className)} {...props} />
))
Input.displayName = 'Input'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn(base, 'min-h-[76px] resize-none py-2', className)} {...props} />,
)
Textarea.displayName = 'Textarea'

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <div className="relative">
      <select ref={ref} className={cn(base, 'h-9 cursor-pointer appearance-none pr-9', className)} {...props}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  ),
)
Select.displayName = 'Select'

export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string
  hint?: ReactNode
  error?: string
  required?: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <label className={cn('block space-y-1.5', className)}>
      <span className="text-[13px] font-medium">
        {label}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </span>
      {children}
      {error ? (
        <span className="block text-xs text-danger">{error}</span>
      ) : (
        hint && <span className="block text-xs text-muted-foreground">{hint}</span>
      )}
    </label>
  )
}

/** Поле поиска со значком лупы; className задаёт ширину обёртки (sm:w-64). Дебаунс — useDebouncedSearch в lib/hooks */
export function SearchInput({
  value,
  onChange,
  label,
  placeholder,
  className,
}: {
  value: string
  onChange: (value: string) => void
  label: string
  placeholder: string
  className?: string
}) {
  return (
    <div className={cn('relative w-full', className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input className="pl-9" aria-label={label} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

/** Фильтр «с … по …»: два поля даты с подписями «Дата с» и «Дата по»; пустое поле даёт undefined */
export function DateRange({
  from,
  to,
  onChange,
}: {
  from?: string
  to?: string
  onChange: (patch: { date_from?: string; date_to?: string }) => void
}) {
  return (
    <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
      с
      <Input type="date" className="w-40" aria-label="Дата с" value={from ?? ''} onChange={(e) => onChange({ date_from: e.target.value || undefined })} />
      по
      <Input type="date" className="w-40" aria-label="Дата по" value={to ?? ''} onChange={(e) => onChange({ date_to: e.target.value || undefined })} />
    </div>
  )
}

/** <option> на каждый отдел; пока список не загружен — пусто. Первую («Все отделы», «Выберите отдел») пишет вызывающий */
export function DepartmentOptions({ departments }: { departments?: Department[] }) {
  return (
    <>
      {departments?.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name}
        </option>
      ))}
    </>
  )
}
