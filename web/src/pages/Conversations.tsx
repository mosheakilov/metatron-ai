import { useEffect, useRef, useState } from 'react'
import { Bot, CalendarCheck, Check, CheckCheck, Clock, Hand, MessagesSquare, Send, TriangleAlert } from 'lucide-react'
import { api, fmtPhone, fmtSlot, fmtTime, mediaUrl, usePoll, type AppState, type Meeting, type Message, type Seller } from '../api'
import { Button, Card, cx, Empty, Spinner, StatusBadge, useToast } from '../ui'

type Convo = Seller & { last_body: string; last_direction: string; last_at: string; n_in: number }
type Thread = { seller: Seller; messages: Message[]; meetings: Meeting[] }

export function Conversations({ state }: { state: AppState }) {
  const { data } = usePoll<{ conversations: Convo[] }>('/api/conversations', 4000)
  const [open, setOpen] = useState<string | null>(null)
  const list = data?.conversations || []
  const current = open ?? list[0]?.seller_id ?? null

  if (!data) return <div className="grid place-items-center py-24"><Spinner /></div>
  if (!list.length) return <Card><Empty icon={<MessagesSquare />} title="עוד אין שיחות" sub="אחרי שהודעה ראשונה תאושר ותישלח, השיחה עם המוכר תופיע כאן." /></Card>

  return (
    <Card className="grid h-[calc(100vh-8rem)] min-h-[520px] overflow-hidden md:grid-cols-[320px_1fr]">
      <div className={cx('border-l border-line overflow-y-auto scroll-thin', open && 'hidden md:block')}>
        <div className="sticky top-0 bg-white/95 backdrop-blur px-4 py-4 border-b border-line font-semibold">שיחות</div>
        {list.map((c) => (
          <button key={c.seller_id} onClick={() => setOpen(c.seller_id)}
            className={cx('flex w-full items-start gap-3 px-4 py-3.5 text-right border-b border-line/70 transition', current === c.seller_id ? 'bg-brand-50' : 'hover:bg-slate-50')}>
            <div className="grid size-11 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-100 to-violet-100 font-bold text-brand-700">{c.name?.[0] || '?'}</div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium truncate">{c.name}</span>
                <span className="text-xs text-muted shrink-0">{fmtTime(c.last_at)}</span>
              </div>
              <div className="text-sm text-muted truncate">{c.last_direction === 'out' ? 'נשלח: ' : ''}{c.last_body}</div>
              <div className="mt-1.5"><StatusBadge status={c.status} labels={state.status_labels} /></div>
            </div>
          </button>
        ))}
      </div>
      <div className={cx('min-w-0', !open && 'hidden md:block')}>
        {current && <ThreadView id={current} state={state} onBack={() => setOpen(null)} />}
      </div>
    </Card>
  )
}

const KIND_HE: Record<string, string> = { outreach: 'פנייה ראשונה', answer: 'תשובה', slots: 'הצעת מועדים', booking: 'אישור פגישה', optout_confirm: 'אישור הסרה', manual: 'נכתב ידנית' }

function ThreadView({ id, state, onBack }: { id: string; state: AppState; onBack: () => void }) {
  const { data, reload } = usePoll<Thread>(`/api/conversations/${id}`, 3000)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const toast = useToast()
  const n = data?.messages.length
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [n, id])
  if (!data) return <div className="grid h-full place-items-center"><Spinner /></div>
  const s = data.seller
  const tookOver = s.status === 'broker_took_over'
  const canWrite = !['new', 'rejected', 'awaiting_approval', 'opted_out'].includes(s.status)

  const send = async () => {
    if (!text.trim()) return
    setBusy(true)
    try { await api(`/api/conversations/${id}/send`, { method: 'POST', json: { body: text } }); setText(''); reload() }
    catch (e) { toast((e as Error).message, 'err') } finally { setBusy(false) }
  }
  const resume = async () => { await api(`/api/conversations/${id}/automation`, { method: 'POST' }); reload(); toast('METATRON חוזר לטפל בשיחה') }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-line px-5 py-3.5">
        <button className="md:hidden text-brand-700 text-sm" onClick={onBack}>חזרה</button>
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{s.name}</div>
          <div className="text-sm text-muted"><span className="num">{fmtPhone(s.phone)}</span>{s.address && ` · ${[s.address, s.city].filter(Boolean).join(', ')}`}</div>
        </div>
        <StatusBadge status={s.status} labels={state.status_labels} />
      </div>

      {tookOver && (
        <div className="flex items-center gap-3 bg-orange-50 px-5 py-2.5 text-sm text-orange-900 border-b border-orange-100">
          <Hand className="size-4" /><span className="flex-1">השיחה בטיפול אישי שלך, ו-METATRON לא עונה בה אוטומטית. בקשת הסרה עדיין תכובד.</span>
          <Button size="sm" variant="secondary" icon={<Bot className="size-4" />} onClick={resume}>החזרה ל-METATRON</Button>
        </div>
      )}
      {data.meetings.map((m) => (
        <div key={m.id} className="flex items-center gap-2 bg-emerald-50 px-5 py-2.5 text-sm text-emerald-900 border-b border-emerald-100">
          <CalendarCheck className="size-4" />פגישה: {fmtSlot(m.start)} · {m.address}
        </div>
      ))}

      <div className="flex-1 overflow-y-auto scroll-thin bg-[#efeae2] px-4 py-5 space-y-2">
        {data.messages.filter((m) => m.status !== 'draft' && m.status !== 'rejected').map((m) => {
          const out = m.direction === 'out'
          return (
            <div key={m.id} className={cx('flex', out ? 'justify-start' : 'justify-end')}>
              <div className={cx('max-w-[78%] rounded-2xl px-3.5 py-2 shadow-sm', out ? 'bg-[#d9fdd3] rounded-tr-sm' : 'bg-white rounded-tl-sm')}>
                {out && KIND_HE[m.kind] && <div className="text-[11px] font-medium text-emerald-800/70 mb-0.5">{KIND_HE[m.kind]}</div>}
                {m.media && <img src={mediaUrl(m.media)} alt="" className="mb-1.5 max-h-72 w-full rounded-xl object-cover" />}
                <div className="whitespace-pre-wrap text-[15px] leading-relaxed">{m.body}</div>
                <div className="mt-1 flex items-center justify-end gap-1 text-[11px] text-slate-500">
                  {fmtTime(m.sent_at || m.created_at)}
                  {out && <Tick status={m.status} note={m.note} />}
                </div>
              </div>
            </div>
          )
        })}
        <div ref={end} />
      </div>

      {canWrite ? (
        <div className="flex items-end gap-2 border-t border-line p-3">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} placeholder="כתיבת הודעה בעצמך…"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            className="max-h-32 flex-1 resize-none rounded-xl border border-line px-3.5 py-2.5 text-[15px] outline-none focus:border-brand-500" />
          <Button loading={busy} onClick={send} aria-label="שליחה" icon={<Send className="size-4 -scale-x-100" />} />
        </div>
      ) : s.status === 'opted_out' ? (
        <div className="border-t border-line p-3 text-center text-sm text-muted">המוכר ביקש להסיר ולא יקבל עוד הודעות.</div>
      ) : null}
    </div>
  )
}

function Tick({ status, note }: { status: string; note: string | null }) {
  if (status === 'sent') return <CheckCheck className="size-3.5 text-sky-600" />
  if (status === 'queued') return <span title="בתור לשליחה"><Clock className="size-3.5" /></span>
  if (status === 'failed') return <span title={note || ''}><TriangleAlert className="size-3.5 text-rose-600" /></span>
  if (status === 'blocked') return <span className="text-rose-600">נחסם</span>
  return <Check className="size-3.5" />
}
