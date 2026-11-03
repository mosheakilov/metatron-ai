import { useCallback, useEffect, useRef, useState } from 'react'

export type Seller = {
  seller_id: string; name: string; phone: string; city: string | null; address: string | null
  rooms: number | null; area_sqm: number | null; asking_price: number | null; notes: string | null
  status: string; rank: number | null; updated_at: string
}
export type Message = {
  id: number; seller_id: string; direction: 'in' | 'out'; kind: string; body: string
  status: string; note: string | null; created_at: string; sent_at: string | null; name?: string
  media?: string | null
}
export type Draft = Seller & { message_id: number; kind: string; body: string; media: string | null }
export type WhatsApp = {
  status: 'offline' | 'disconnected' | 'connecting' | 'qr' | 'pairing' | 'open' | 'reconnecting' | 'logged_out' | 'expired' | 'error'
  qr: string | null; pairingCode: string | null; me: { phone: string; name: string | null } | null
  error: string | null
}
export type Limits = { daily_new: number; start_hour: number; end_hour: number; min_gap_sec: number; max_gap_sec: number; send_on_weekend: boolean }
export type SettingsT = {
  setup_done: boolean; broker_name: string; wa_phone: string; office_name: string; meeting_minutes: number; message_template: string
  include_opt_out: boolean; outreach_image: string
  availability: { weekdays: number[]; hours: number[]; days_ahead: number }
  limits: Limits; paused: boolean; ai: { proxy_url: string; license_key: string }
}
export type OutboxT = { queued: number; sent_today: number; daily_cap: number; paused: boolean; waiting: string | null; next_at: string | null }
export type AppState = { settings: SettingsT; whatsapp: WhatsApp; ai: boolean; outbox: OutboxT; status_labels: Record<string, string> }
export type Meeting = { id: number; seller_id: string; start: string; end: string; address: string; name: string; phone: string; city?: string }
export type Stats = {
  total: number; contacted: number; replied: number; booked: number; opted_out: number
  pending_approval: number; by_status: Record<string, number>; upcoming: Meeting[]; activity: Message[]
}

export async function api<T = unknown>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init || {}
  const r = await fetch(path, {
    ...rest,
    headers: json !== undefined ? { 'content-type': 'application/json' } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error((data as { detail?: string }).detail || `שגיאה ${r.status}`)
  return data as T
}

/** Fetch now and every `ms` while mounted; `reload` refetches immediately. */
export function usePoll<T>(path: string | null, ms = 5000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)
  const reload = useCallback(async () => {
    if (!path) return
    try {
      const d = await api<T>(path)
      if (alive.current) { setData(d); setError(null) }
    } catch (e) {
      if (alive.current) setError((e as Error).message)
    }
  }, [path])
  useEffect(() => {
    alive.current = true
    reload()
    const t = ms ? setInterval(reload, ms) : undefined
    return () => { alive.current = false; clearInterval(t) }
  }, [reload, ms])
  return { data, error, reload }
}

export const DAYS = ['ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳', 'א׳'] // Python weekday order (Mon=0)
export const DAY_NAMES = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']

export function fmtPhone(p: string) {
  const d = (p || '').replace(/\D/g, '')
  const local = d.startsWith('972') ? '0' + d.slice(3) : d
  return local.length === 10 ? `${local.slice(0, 3)}-${local.slice(3)}` : p
}
export function fmtTime(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  const today = new Date()
  const same = d.toDateString() === today.toDateString()
  return same ? d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('he-IL', { day: 'numeric', month: 'numeric' }) + ' ' +
      d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })
}
export function fmtSlot(iso: string) {
  const d = new Date(iso)
  return `יום ${DAY_NAMES[(d.getDay() + 6) % 7]} ${d.toLocaleDateString('he-IL', { day: 'numeric', month: 'numeric' })} · ${d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })}`
}
export const WAIT_HE: Record<string, string> = {
  empty: 'אין הודעות בתור', paused: 'השליחה מושהית', daily_cap: 'הגעת למכסה היומית',
  outside_hours: 'מחוץ לשעות השליחה', pacing: 'ממתין בין הודעות',
}
/** Why a queued message has not gone out yet, in words. */
export function queuedNote(m: Message, ob: OutboxT, connected: boolean) {
  if (!connected) return 'ממתינה לחיבור הוואטסאפ'
  if (ob.paused) return 'השליחה מושהית'
  if (m.kind !== 'outreach') return 'נשלחת עכשיו…'
  const when = ob.next_at ? ` · תצא ב-${fmtTime(ob.next_at)}` : ''
  return (WAIT_HE[ob.waiting || ''] || 'ממתינה בתור') + when
}
export async function sendNow(id: number) {
  return api<{ status: string }>(`/api/outbox/${id}/send-now`, { method: 'POST' })
}
export const mediaUrl = (name: string) => `/api/media/${name}`
export const money = (n: number | null) => (n ? '₪' + n.toLocaleString('he-IL') : '')
