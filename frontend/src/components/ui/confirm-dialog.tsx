import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'

/**
 * Подтверждение опасного действия вместо window.confirm: диалог с кнопками «Отмена» и подтверждения.
 * Закрывает окно родитель (onClose) — после успеха; при ошибке окно остаётся, можно повторить.
 */
export function ConfirmDialog({
  open,
  onClose,
  title,
  description,
  confirmLabel,
  pending,
  onConfirm,
  children,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  confirmLabel: string
  pending?: boolean
  onConfirm: () => void
  children?: ReactNode
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button variant="danger" loading={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  )
}
