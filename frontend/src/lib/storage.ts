/** Отдел, выбранный при последнем бронировании: подставляется в формы брони и конструктора ВМ */
export const LAST_DEPARTMENT_KEY = 'hmsrent:last-department'

/** localStorage, который не роняет приложение: в приватном окне, при запрете cookies и сайт-данных он бросает исключение. */
export const safeStorage = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },
  set(key: string, value: string): void {
    try {
      localStorage.setItem(key, value)
    } catch {
      /* настройка просто не запомнится */
    }
  },
}
