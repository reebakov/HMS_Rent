import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { VmSize } from '@/lib/types'

const NUMBERS = [
  ['cpu', 'Ядра'],
  ['ram_gb', 'Память, ГБ'],
  ['disk_gb', 'Диск, ГБ'],
] as const

/** Готовые размеры ВМ: кнопка в конструкторе ставит ядра, память и диск разом */
export function VmSizesEditor({ value, onChange }: { value: VmSize[]; onChange: (v: VmSize[]) => void }) {
  const set = (i: number, patch: Partial<VmSize>) => onChange(value.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const add = () => onChange([...value, { label: `Размер ${value.length + 1}`, cpu: 2, ram_gb: 4, disk_gb: 50 }])

  return (
    <div className="p-5">
      <p className="mb-3 text-xs text-muted-foreground">
        Размер, который не укладывается в лимиты конструктора (ядра, память, диск выше), в конструкторе не показывается.
      </p>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-[13px]">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="pb-2 pr-2 font-medium">Название</th>
              {NUMBERS.map(([, title]) => (
                <th key={title} className="pb-2 pr-2 font-medium">
                  {title}
                </th>
              ))}
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {value.map((s, i) => (
              <tr key={i}>
                <td className="py-1 pr-2">
                  <Input aria-label={`Название размера, строка ${i + 1}`} value={s.label} onChange={(e) => set(i, { label: e.target.value })} />
                </td>
                {NUMBERS.map(([key, title]) => (
                  <td key={key} className="w-28 py-1 pr-2">
                    <Input
                      type="number"
                      aria-label={`${title}, строка ${i + 1}`}
                      value={s[key]}
                      onChange={(e) => set(i, { [key]: Number(e.target.value) })}
                    />
                  </td>
                ))}
                <td className="w-10 py-1">
                  <Button size="icon" variant="ghost" title="Удалить" onClick={() => onChange(value.filter((_, j) => j !== i))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button className="mt-3" size="sm" variant="outline" onClick={add}>
        <Plus className="h-3.5 w-3.5" />
        Добавить размер
      </Button>
    </div>
  )
}
