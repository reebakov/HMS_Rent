/** Версия сборки (sha коммита): CI вшивает её в бандл через VITE_APP_VERSION; в разработке — «dev». */
export const APP_VERSION: string = import.meta.env.VITE_APP_VERSION || 'dev'

/** Версия сервиса «1.<feat>.<fix>» по истории git (scripts/release_version.sh): CI вшивает её через VITE_APP_RELEASE */
export const APP_RELEASE: string = import.meta.env.VITE_APP_RELEASE || 'dev'
