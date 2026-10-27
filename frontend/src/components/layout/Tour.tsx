import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export interface TourStep {
  title: string
  text: string
  target?: string // значение data-tour элемента, который подсвечиваем; без него шаг — карточка по центру
  to?: string // страница, на которой шаг показывается: обучение переходит на неё само
}

interface Rect {
  top: number
  left: number
  width: number
  height: number
}

const PAD = 6 // отступ подсветки от элемента
const GAP = 12 // расстояние от подсветки до карточки
const CARD_MAX = 352
const CARD_HEIGHT = 220 // запас под карточку при выборе стороны

/** Подсвечиваемый элемент, если он есть на странице и виден (в мобильной раскладке сайдбар скрыт — тогда шаг без подсветки) */
function measure(target: string | undefined): Rect | null {
  const el = target ? document.querySelector<HTMLElement>(`[data-tour="${target}"]`) : null
  const r = el?.getBoundingClientRect()
  if (!r || !r.width || !r.height) return null
  return { top: r.top - PAD, left: r.left - PAD, width: r.width + 2 * PAD, height: r.height + 2 * PAD }
}

const sameRect = (a: Rect | null, b: Rect | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height)

/** Положение карточки: под подсветкой, а если места нет — над ней или у нижнего края экрана */
function cardStyle(rect: Rect | null): React.CSSProperties {
  const width = Math.min(CARD_MAX, window.innerWidth - 32)
  if (!rect) return { width, left: (window.innerWidth - width) / 2, top: Math.max(16, window.innerHeight / 2 - CARD_HEIGHT / 2) }
  const left = Math.min(Math.max(16, rect.left), window.innerWidth - width - 16)
  const below = rect.top + rect.height + GAP
  if (below + CARD_HEIGHT <= window.innerHeight) return { width, left, top: below }
  if (rect.top - GAP - CARD_HEIGHT >= 0) return { width, left, bottom: window.innerHeight - rect.top + GAP }
  return { width, left, bottom: 16 }
}

/**
 * Пошаговое обучение поверх интерфейса: затемняет экран, подсвечивает элемент шага и переводит на нужную страницу.
 * Страница под затемнением недоступна, пока обучение идёт. Esc и «Пропустить» закрывают, ←/→ листают, Tab не выходит из карточки.
 */
export function Tour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  const [index, setIndex] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)
  const card = useRef<HTMLDivElement>(null)
  const next = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const step = steps[index]
  const last = index === steps.length - 1

  useEffect(() => {
    if (step.to && pathname !== step.to) navigate(step.to)
  }, [step, pathname, navigate])

  // Элемент появляется после загрузки страницы и двигается при прокрутке и смене размера окна: следим за ним
  useEffect(() => {
    document.querySelector(`[data-tour="${step.target}"]`)?.scrollIntoView?.({ block: 'center' })
    const update = () => setRect((prev) => {
      const found = measure(step.target)
      return sameRect(prev, found) ? prev : found
    })
    update()
    const timer = setInterval(update, 200)
    return () => clearInterval(timer)
  }, [step, pathname])

  useEffect(() => next.current?.focus(), [index])

  const go = (delta: number) => setIndex((i) => Math.min(Math.max(i + delta, 0), steps.length - 1))

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') go(1)
      else if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'Tab') {
        const buttons = [...(card.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? [])]
        const first = buttons[0]
        const lastButton = buttons[buttons.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          lastButton.focus()
        } else if (!e.shiftKey && document.activeElement === lastButton) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  })

  return createPortal(
    <>
      {/* Прозрачный слой не пускает клики на страницу; затемнение рисует подсветка (тень вокруг элемента) или сам слой */}
      <div className={rect ? 'fixed inset-0 z-[60]' : 'fixed inset-0 z-[60] bg-slate-950/55'} />
      {rect && (
        <div
          className="pointer-events-none fixed z-[61] rounded-xl ring-2 ring-primary transition-all duration-200"
          style={{ ...rect, boxShadow: '0 0 0 9999px rgba(2, 6, 23, 0.55)' }}
        />
      )}
      <div
        ref={card}
        role="dialog"
        aria-modal="true"
        aria-label="Обучение"
        className="fixed z-[62] rounded-xl border bg-card p-4 shadow-lift"
        style={cardStyle(rect)}
      >
        <p className="text-xs text-muted-foreground">
          Шаг {index + 1} из {steps.length}
        </p>
        <h2 className="mt-1 text-[15px] font-semibold">{step.title}</h2>
        <p className="mt-1.5 text-[13px] text-muted-foreground">{step.text}</p>
        <div className="mt-4 flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Пропустить
          </Button>
          <div className="flex-1" />
          {index > 0 && (
            <Button variant="outline" size="sm" onClick={() => go(-1)}>
              Назад
            </Button>
          )}
          <Button ref={next} size="sm" onClick={last ? onClose : () => go(1)}>
            {last ? 'Закончить' : 'Далее'}
          </Button>
        </div>
      </div>
    </>,
    document.body,
  )
}
