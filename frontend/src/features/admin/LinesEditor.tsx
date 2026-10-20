import { Field, Textarea } from '@/components/ui/input'

/** Список строк в «Настройках»: по одной в строке. Пустые строки отбрасываются при сохранении (cleanLines) */
export function LinesEditor({ label, hint, value, onChange }: { label: string; hint?: string; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <Field label={label} hint={hint}>
      <Textarea className="min-h-[160px] font-mono text-[13px]" value={value.join('\n')} onChange={(e) => onChange(e.target.value.split('\n'))} />
    </Field>
  )
}

export const cleanLines = (lines: string[]) => lines.map((l) => l.trim()).filter(Boolean)
