import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input, Select } from '@/components/ui/input'
import type { VmTemplate } from '@/lib/types'

/** Шаблоны ОС для конструктора: подпись, имя шаблона в vCenter, спецификация, минимальный диск */
export function VmTemplatesEditor({ value, onChange }: { value: VmTemplate[]; onChange: (v: VmTemplate[]) => void }) {
  const set = (i: number, patch: Partial<VmTemplate>) => onChange(value.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  const add = () =>
    onChange([
      ...value,
      { key: `os${value.length + 1}`, label: 'Новая ОС', os: 'windows', template: '', customization_spec: '', min_disk_gb: 50, enabled: true },
    ])

  return (
    <div className="p-5">
      <p className="mb-3 text-xs text-muted-foreground">
        Без имени шаблона ОС видна в конструкторе как «скоро». Выключенная — скрыта совсем. Имя шаблона — как в vCenter
        (VMs and Templates), спецификация гостевой настройки — необязательно.
      </p>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-[13px]">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="pb-2 pr-2 font-medium">Название</th>
              <th className="pb-2 pr-2 font-medium">Ключ</th>
              <th className="pb-2 pr-2 font-medium">Тип</th>
              <th className="pb-2 pr-2 font-medium">Шаблон в vCenter</th>
              <th className="pb-2 pr-2 font-medium">Спецификация</th>
              <th className="pb-2 pr-2 font-medium">Диск от, ГБ</th>
              <th className="pb-2 pr-2 font-medium">Вкл.</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {value.map((t, i) => (
              <tr key={i}>
                <td className="py-1 pr-2">
                  <Input aria-label={`Название, строка ${i + 1}`} value={t.label} onChange={(e) => set(i, { label: e.target.value })} />
                </td>
                <td className="w-32 py-1 pr-2">
                  <Input className="font-mono" aria-label={`Ключ, строка ${i + 1}`} value={t.key} onChange={(e) => set(i, { key: e.target.value.toLowerCase() })} />
                </td>
                <td className="w-32 py-1 pr-2">
                  <Select aria-label={`Тип, строка ${i + 1}`} value={t.os} onChange={(e) => set(i, { os: e.target.value as VmTemplate['os'] })}>
                    <option value="windows">Windows</option>
                    <option value="linux">Linux</option>
                  </Select>
                </td>
                <td className="py-1 pr-2">
                  <Input aria-label={`Шаблон в vCenter, строка ${i + 1}`} placeholder="например Template_Win11" value={t.template} onChange={(e) => set(i, { template: e.target.value })} />
                </td>
                <td className="py-1 pr-2">
                  <Input aria-label={`Спецификация, строка ${i + 1}`} value={t.customization_spec} onChange={(e) => set(i, { customization_spec: e.target.value })} />
                </td>
                <td className="w-24 py-1 pr-2">
                  <Input type="number" aria-label={`Диск от, ГБ, строка ${i + 1}`} value={t.min_disk_gb} onChange={(e) => set(i, { min_disk_gb: Number(e.target.value) })} />
                </td>
                <td className="w-12 py-1 pr-2 text-center">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[hsl(var(--primary))]"
                    aria-label={`Включена, строка ${i + 1}`}
                    checked={t.enabled}
                    onChange={(e) => set(i, { enabled: e.target.checked })}
                  />
                </td>
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
        Добавить ОС
      </Button>
    </div>
  )
}
