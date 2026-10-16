import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { safeStorage } from '@/lib/storage'

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    safeStorage.set('theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <Button variant="ghost" size="icon" onClick={() => setDark((v) => !v)} title={dark ? 'Светлая тема' : 'Тёмная тема'}>
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}
