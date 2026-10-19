import { useState } from 'react'
import { Keyboard } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { useHotkey } from '@/lib/hooks'

/** Всё, что работает с клавиатуры. Окно рисуется из этого списка, поэтому в нём нет ничего, чего нет в интерфейсе */
export const SHORTCUTS: { keys: string[]; action: string }[] = [
  { keys: ['/'], action: 'Перейти к поиску (каталог, инвентаризация, журнал, логи)' },
  { keys: ['?'], action: 'Открыть эту подсказку' },
  { keys: ['Esc'], action: 'Закрыть окно, меню или панель' },
  { keys: ['Tab', 'Shift + Tab'], action: 'Перейти к следующему или предыдущему элементу' },
  { keys: ['Enter'], action: 'Открыть выбранное, отправить форму' },
  { keys: ['Пробел'], action: 'Нажать кнопку, поставить или снять отметку' },
  { keys: ['←', '→', 'Home', 'End'], action: 'Переключить вкладки в карточке компьютера' },
]

/** Кнопка с окном «Горячие клавиши»; клавиша «?» открывает его из любого места */
export function ShortcutsButton() {
  const [open, setOpen] = useState(false)
  useHotkey('?', () => setOpen(true))

  return (
    <>
      <Button variant="ghost" size="icon" title="Горячие клавиши" onClick={() => setOpen(true)}>
        <Keyboard className="h-4 w-4" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title="Горячие клавиши" footer={<Button onClick={() => setOpen(false)}>Понятно</Button>}>
        <table className="w-full text-left text-[13px]">
          <tbody className="divide-y">
            {SHORTCUTS.map(({ keys, action }) => (
              <tr key={action}>
                <td className="whitespace-nowrap py-2 pr-4">
                  <span className="flex flex-wrap gap-1">
                    {keys.map((k) => (
                      <Kbd key={k}>{k}</Kbd>
                    ))}
                  </span>
                </td>
                <td className="py-2 text-muted-foreground">{action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Dialog>
    </>
  )
}
