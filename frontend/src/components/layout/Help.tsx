import { useRef, useState } from 'react'
import { CircleHelp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { useHotkey } from '@/lib/hooks'
import { APP_RELEASE, APP_VERSION } from '@/lib/version'
import { CUSTOMER_TOUR } from '@/features/help/customerTour'
import { Tour } from './Tour'

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

/** «?» в шапке: версия сервиса, обучение и горячие клавиши; клавиша «?» открывает справку из любого места */
export function HelpButton() {
  const [open, setOpen] = useState(false)
  const [touring, setTouring] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  useHotkey('?', () => !touring && setOpen(true))

  const startTour = () => {
    setOpen(false)
    setTouring(true)
  }
  const endTour = () => {
    setTouring(false)
    opener.current?.focus()
  }

  return (
    <span data-tour="help">
      <Button ref={opener} variant="ghost" size="icon" title="Справка" aria-label="Справка" onClick={() => setOpen(true)}>
        <CircleHelp className="h-4 w-4" />
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title="Справка" footer={<Button onClick={() => setOpen(false)}>Понятно</Button>}>
        <div className="space-y-5">
          <p className="text-[13px] text-muted-foreground">
            Версия сервиса: <span className="font-medium text-foreground">{APP_RELEASE}</span>
            {APP_VERSION !== 'dev' && <span> (сборка {APP_VERSION.slice(0, 7)})</span>}
          </p>
          <div>
            <h3 className="text-sm font-semibold">Обучение</h3>
            <p className="mb-2 mt-1 text-[13px] text-muted-foreground">
              Короткий тур по порталу: как найти компьютер, забронировать его, продлить и вернуть.
            </p>
            <Button variant="outline" onClick={startTour}>
              Пройти обучение
            </Button>
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold">Горячие клавиши</h3>
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
          </div>
        </div>
      </Dialog>
      {touring && <Tour steps={CUSTOMER_TOUR} onClose={endTour} />}
    </span>
  )
}
