/** Версия сборки (sha коммита): CI вшивает её в бандл через VITE_APP_VERSION; в разработке — «dev». */
export const APP_VERSION: string = import.meta.env.VITE_APP_VERSION || 'dev'
