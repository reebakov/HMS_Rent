import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('api.url', () => {
  it('добавляет префикс и пропускает пустые параметры', () => {
    expect(api.url('/computers', { tier: 'weak', q: '', min_ram: undefined, gpu_only: false, x: null })).toBe(
      '/api/v1/computers?tier=weak&gpu_only=false',
    )
  })
  it('без параметров — чистый путь', () => {
    expect(api.url('/bookings/my')).toBe('/api/v1/bookings/my')
  })
})

describe('запросы', () => {
  it('GET отправляет cookie и без тела', async () => {
    fetchMock.mockResolvedValue(json([{ id: 1 }]))
    const data = await api.get('/computers', { tier: 'medium' })
    expect(data).toEqual([{ id: 1 }])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/computers?tier=medium')
    expect(init).toMatchObject({ method: 'GET', credentials: 'include', body: undefined })
  })

  it('POST сериализует тело в JSON', async () => {
    fetchMock.mockResolvedValue(json({ id: 5 }, 201))
    await api.post('/bookings', { computer_id: 1 })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body)).toEqual({ computer_id: 1 })
  })

  it('204 -> undefined', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(api.del('/admin/pools/1')).resolves.toBeUndefined()
  })
})

describe('ошибки', () => {
  it('строковый detail становится сообщением ApiError', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'Компьютер уже забронирован' }, 409))
    const err = (await api.post('/bookings', {}).catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.message).toBe('Компьютер уже забронирован')
  })

  it('массив detail (422) склеивается через «; »', async () => {
    fetchMock.mockResolvedValue(json({ detail: [{ msg: 'поле a' }, { msg: 'поле b' }] }, 422))
    await expect(api.post('/bookings', {})).rejects.toThrow('поле a; поле b')
  })

  it('не-JSON тело -> «Ошибка <код>»', async () => {
    fetchMock.mockResolvedValue(new Response('<html>boom</html>', { status: 502 }))
    await expect(api.get('/computers')).rejects.toThrow('Ошибка 502')
  })

  it('401 вне /auth/ рассылает auth:expired', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'нет сессии' }, 401))
    const listener = vi.fn()
    window.addEventListener('auth:expired', listener)
    await expect(api.get('/computers')).rejects.toBeInstanceOf(ApiError)
    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener('auth:expired', listener)
  })

  it('401 на /auth/* (неверный пароль) событие не рассылает', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'Неверный пароль' }, 401))
    const listener = vi.fn()
    window.addEventListener('auth:expired', listener)
    await expect(api.post('/auth/login', {})).rejects.toThrow('Неверный пароль')
    expect(listener).not.toHaveBeenCalled()
    window.removeEventListener('auth:expired', listener)
  })
})
