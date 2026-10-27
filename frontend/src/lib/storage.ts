/** Отдел, выбранный при последнем бронировании: подставляется в формы брони и конструктора ВМ */
export const LAST_DEPARTMENT_KEY = 'hmsrent:last-department'

/** Метка «обучение уже показывали»: свой ключ у каждого сотрудника, чтобы на общем компьютере оно не пропускалось */
export const tourSeenKey = (username: string) => `hmsrent:tour-seen:${username}`

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
