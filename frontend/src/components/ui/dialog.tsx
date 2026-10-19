import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useRef, type FormEvent, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

const BODY_FIELDS = ['input:not([disabled]):not([type=hidden])', 'select:not([disabled])', 'textarea:not([disabled])']
  .map((s) => `[data-dialog-body] ${s}`)
  .join(', ')

/**
 * Начальный фокус окна: первое поле формы, а если полей нет (подтверждение) — первая доступная кнопка подвала,
 * то есть «Отмена». Без этого Radix фокусирует «Закрыть» в шапке: с клавиатуры пришлось бы пройти Tab до формы.
 */
function focusFirstControl(event: Event) {
  const content = event.currentTarget as HTMLElement
  const target =
    content.querySelector<HTMLElement>(BODY_FIELDS) ??
    content.querySelector<HTMLElement>('[data-dialog-footer] button:not([disabled])')
  if (!target) return
  event.preventDefault()
  target.focus()
}

/**
 * Возвращает фокус на элемент, с которого окно открыли. У окон нет DialogPrimitive.Trigger (открытием управляет
 * родитель), а без него Radix при закрытии оставляет фокус на body. Элемент запоминается в рендере: к эффектам
 * Radix фокус уже ушёл в окно (autoFocus у поля срабатывает раньше).
 */
function useReturnFocus(open: boolean) {
  const opener = useRef<HTMLElement | null>(null)
  const wasOpen = useRef(false)
  if (open && !wasOpen.current) opener.current = document.activeElement as HTMLElement | null
  wasOpen.current = open
  return (event: Event) => {
    event.preventDefault()
    opener.current?.focus()
  }
}

function MaybeForm({ onSubmit, children }: { onSubmit?: (e: FormEvent) => void; children: ReactNode }) {
  return onSubmit ? (
    <form onSubmit={onSubmit} className="flex min-h-0 flex-col">
      {children}
    </form>
  ) : (
    <>{children}</>
  )
}

/** Модальное окно по центру экрана. С onSubmit всё содержимое — форма: Enter в поле отправляет её кнопкой type="submit" из подвала */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  className?: string
  onSubmit?: (e: FormEvent) => void
}) {
  const returnFocus = useReturnFocus(open)
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] animate-fade-in" />
        <DialogPrimitive.Content
          {...(description ? {} : { 'aria-describedby': undefined })}
          onOpenAutoFocus={focusFirstControl}
          onCloseAutoFocus={returnFocus}
          className={cn(
            'fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col',
            'rounded-2xl border bg-card shadow-lift animate-zoom-in focus:outline-none',
            className,
          )}
        >
          <div className="flex items-start justify-between gap-4 px-6 pb-2 pt-5">
            <div>
              <DialogPrimitive.Title className="text-lg font-semibold tracking-tight">{title}</DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description className="mt-1 text-[13px] text-muted-foreground">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close aria-label="Закрыть" className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>
          <MaybeForm onSubmit={onSubmit}>
            <div data-dialog-body className="scroll-thin overflow-y-auto px-6 py-4">{children}</div>
            {footer && <div data-dialog-footer className="flex justify-end gap-2 border-t bg-muted/30 px-6 py-4 rounded-b-2xl">{footer}</div>}
          </MaybeForm>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

/** Боковая панель справа — карточка ПК, история */
export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  const returnFocus = useReturnFocus(open)
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/30 animate-fade-in" />
        <DialogPrimitive.Content
          onCloseAutoFocus={returnFocus}
          className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l bg-card shadow-lift animate-slide-in focus:outline-none">
          <div className="flex items-start justify-between gap-4 border-b px-6 py-5">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-lg font-semibold tracking-tight">{title}</DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description asChild>
                  <div className="mt-1 text-[13px] text-muted-foreground">{description}</div>
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close aria-label="Закрыть" className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="scroll-thin flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t px-6 py-4">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
