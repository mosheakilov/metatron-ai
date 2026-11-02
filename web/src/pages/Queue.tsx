import { useEffect, useState } from 'react'
import { Check, CheckCheck, ImageOff, ImagePlus, Inbox, MapPin, MessageCircleQuestion, X } from 'lucide-react'
import { api, fmtPhone, mediaUrl, money, usePoll, type AppState, type Draft } from '../api'
import type { Page } from '../shell'
import { Button, Card, Empty, PageHeader, Spinner, useToast } from '../ui'

const OPT_OUT = 'להסרה השיבו "הסר".'

export function Queue({ state, go }: { state: AppState; go: (p: Page) => void }) {
  const { data, reload } = usePoll<{ drafts: Draft[] }>('/api/queue', 6000)
  const [edits, setEdits] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | 'all' | null>(null)
  const [gone, setGone] = useState<Set<number>>(new Set())
  const toast = useToast()
  const drafts = (data?.drafts || []).filter((d) => !gone.has(d.message_id))

  useEffect(() => { setGone(new Set()) }, [data])

  const act = async (d: Draft, kind: 'approve' | 'reject') => {
    setBusy(d.message_id)
    try {
      const body = edits[d.message_id]
      await api(`/api/queue/${d.message_id}/${kind}`, { method: 'POST', json: kind === 'approve' ? { body } : {} })
      setGone((g) => new Set(g).add(d.message_id))
      toast(kind === 'approve' ? `ההודעה ל${d.name} אושרה ונכנסה לתור השליחה` : 'הטיוטה נדחתה')
      reload()
    } catch (e) { toast((e as Error).message, 'err') } finally { setBusy(null) }
  }
  const setMedia = async (d: Draft, attach: boolean) => {
    try { await api(`/api/queue/${d.message_id}/media`, { method: 'POST', json: { attach } }); reload() }
    catch (e) { toast((e as Error).message, 'err') }
  }
  const image = state.settings.outreach_image
  const approveAll = async () => {
    const unedited = drafts.filter((d) => edits[d.message_id] === undefined)
    setBusy('all')
    try {
      const r = await api<{ approved: number }>('/api/queue/approve', { method: 'POST', json: { message_ids: unedited.map((d) => d.message_id) } })
      toast(`${r.approved} הודעות אושרו ונכנסו לתור השליחה`)
      reload()
    } catch (e) { toast((e as Error).message, 'err') } finally { setBusy(null) }
  }

  return (
    <div>
      <PageHeader title="לאישור" sub="כל הודעה שנכתבה למוכר מחכה כאן לאישורך. אפשר לערוך לפני האישור."
        actions={drafts.length > 1 ? <Button variant="success" icon={<CheckCheck className="size-4" />} loading={busy === 'all'} onClick={approveAll}>אישור כל ההודעות ({drafts.length})</Button> : undefined} />

      {state.whatsapp.status !== 'open' && drafts.length > 0 && (
        <div className="mb-4 rounded-2xl bg-amber-50 border border-amber-200 p-4 text-sm text-amber-900">
          אפשר לאשר עכשיו. ההודעות יחכו בתור עד שהוואטסאפ יתחבר.
        </div>
      )}

      {!data ? <div className="grid place-items-center py-24"><Spinner /></div> : drafts.length === 0 ? (
        <Card><Empty icon={<Inbox />} title="אין הודעות שמחכות לאישור" sub="בחרו מוכרים במסך הלקוחות, ו-METATRON ינסח לכל אחד מהם הודעה אישית."
          action={<Button onClick={() => go('contacts')}>למסך הלקוחות</Button>} /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {drafts.map((d) => {
            const body = edits[d.message_id] ?? d.body
            const isAnswer = d.kind === 'answer'
            return (
              <Card key={d.message_id} className="rise flex flex-col p-5">
                <div className="flex items-start gap-3">
                  <div className="grid size-11 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700 font-bold">{d.name?.[0] || '?'}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{d.name}</span>
                      {isAnswer && <span className="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-xs text-violet-700"><MessageCircleQuestion className="size-3.5" />תשובה לשאלה</span>}
                    </div>
                    <div className="text-sm text-muted flex flex-wrap gap-x-3">
                      <span className="num">{fmtPhone(d.phone)}</span>
                      {(d.address || d.city) && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{[d.address, d.city].filter(Boolean).join(', ')}</span>}
                      {d.asking_price ? <span className="num">{money(d.asking_price)}</span> : null}
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex-1 rounded-2xl rounded-tl-sm bg-[#e7ffdb] p-1">
                  {d.media && (
                    <div className="relative">
                      <img src={mediaUrl(d.media)} alt="" className="max-h-56 w-full rounded-xl object-cover" />
                      <button type="button" onClick={() => setMedia(d, false)}
                        className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white hover:bg-black/75">
                        <ImageOff className="size-3.5" />בלי תמונה</button>
                    </div>
                  )}
                  <textarea value={body} onChange={(e) => setEdits({ ...edits, [d.message_id]: e.target.value })}
                    rows={Math.max(5, body.split('\n').length + 1)}
                    className="w-full resize-none bg-transparent p-3 text-[15px] leading-relaxed outline-none" />
                </div>
                {!d.media && image && d.kind === 'outreach' && (
                  <button type="button" onClick={() => setMedia(d, true)} className="mt-2 inline-flex items-center gap-1 self-start text-xs text-brand-700 hover:underline">
                    <ImagePlus className="size-3.5" />צירוף התמונה</button>
                )}
                {state.settings.include_opt_out && !body.includes(OPT_OUT) && <p className="mt-2 text-xs text-muted">שורת ההסרה תתווסף אוטומטית בשליחה.</p>}
                {edits[d.message_id] !== undefined && <p className="mt-2 text-xs text-brand-700">ההודעה נערכה. הגרסה הערוכה היא שתישלח.</p>}

                <div className="mt-4 flex gap-2">
                  <Button className="flex-1" variant="success" icon={<Check className="size-4" />} loading={busy === d.message_id} onClick={() => act(d, 'approve')}>אישור ושליחה</Button>
                  <Button variant="secondary" icon={<X className="size-4" />} disabled={busy === d.message_id} onClick={() => act(d, 'reject')}>דחייה</Button>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
