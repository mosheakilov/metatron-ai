import { useMemo, useState } from 'react'
import { Search, Sparkles, Trash2, Upload, Users } from 'lucide-react'
import { api, fmtPhone, money, usePoll, type AppState, type Seller } from '../api'
import { ImportWizard } from '../components/ImportWizard'
import type { Page } from '../shell'
import { Button, Card, cx, Empty, inputCls, Modal, PageHeader, Spinner, StatusBadge, useToast } from '../ui'

const FILTERS = ['', 'new', 'awaiting_approval', 'sent', 'in_conversation', 'booked', 'not_interested', 'opted_out']
const DRAFTABLE = ['new', 'rejected']

export function Contacts({ state, go }: { state: AppState; go: (p: Page) => void }) {
  const [filter, setFilter] = useState('')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [importing, setImporting] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const { data, reload } = usePoll<{ contacts: Seller[]; total: number }>('/api/contacts', 10000)
  const labels = state.status_labels

  const rows = useMemo(() => (data?.contacts || []).filter((c) =>
    (!filter || c.status === filter) &&
    (!q || [c.name, c.phone, c.city, c.address].some((v) => v?.includes(q)))), [data, filter, q])
  const counts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const c of data?.contacts || []) m[c.status] = (m[c.status] || 0) + 1
    return m
  }, [data])
  const selectable = rows.filter((r) => DRAFTABLE.includes(r.status))

  const toggle = (id: string) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const draft = async (ids: string[]) => {
    setBusy(true)
    try {
      const r = await api<{ drafted: number }>('/api/drafts', { method: 'POST', json: { seller_ids: ids } })
      toast(`${r.drafted} הודעות נוסחו ומחכות לאישורך`)
      setSel(new Set()); reload(); go('queue')
    } catch (e) { toast((e as Error).message, 'err') } finally { setBusy(false) }
  }
  const remove = async (id: string) => {
    try { await api(`/api/contacts/${id}`, { method: 'DELETE' }); reload() } catch (e) { toast((e as Error).message, 'err') }
  }
  const nextBatch = selectable.slice(0, state.settings.limits.daily_new).map((r) => r.seller_id)

  return (
    <div>
      <PageHeader title="לקוחות" sub={data ? <><span className="num">{data.total}</span> מוכרים ברשימה</> : undefined}
        actions={<Button variant="secondary" icon={<Upload className="size-4" />} onClick={() => setImporting(true)}>ייבוא רשימה</Button>} />

      {!data ? <div className="grid place-items-center py-24"><Spinner /></div> : data.total === 0 ? (
        <Card><Empty icon={<Users />} title="הרשימה ריקה" sub="ייבאו קובץ Excel או CSV עם שמות וטלפונים של מוכרים." action={<Button icon={<Upload className="size-4" />} onClick={() => setImporting(true)}>ייבוא רשימה</Button>} /></Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <div className="relative w-full sm:w-72">
              <Search className="absolute right-3 top-3 size-5 text-muted" />
              <input className={cx(inputCls, 'pr-10')} placeholder="חיפוש שם, טלפון, עיר…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {FILTERS.filter((f) => !f || counts[f]).map((f) => (
                <button key={f} onClick={() => setFilter(f)}
                  className={cx('h-9 rounded-full px-3.5 text-sm transition', filter === f ? 'bg-ink text-white' : 'bg-white border border-line text-slate-600 hover:bg-slate-50')}>
                  {f ? labels[f] : 'הכל'} <span className="num opacity-60">{f ? counts[f] : data.total}</span>
                </button>
              ))}
            </div>
          </div>

          {selectable.length > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl bg-brand-50 border border-brand-100 px-4 py-3">
              <Sparkles className="size-5 text-brand-600" />
              <span className="text-sm flex-1">
                {sel.size ? <>נבחרו <span className="num font-bold">{sel.size}</span> מוכרים</> : <>METATRON ינסח לכל מוכר הודעה אישית, וכל אחת תחכה לאישורך לפני שהיא נשלחת.</>}
              </span>
              {sel.size ? <Button loading={busy} onClick={() => draft([...sel])}>ניסוח הודעות לנבחרים</Button>
                : <Button loading={busy} onClick={() => draft(nextBatch)}>ניסוח ל-<span className="num">{nextBatch.length}</span> הבאים ברשימה</Button>}
            </div>
          )}

          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="w-10 px-4 py-3"><input type="checkbox" className="size-4 accent-brand-600" checked={selectable.length > 0 && selectable.every((r) => sel.has(r.seller_id))}
                    onChange={(e) => setSel(e.target.checked ? new Set(selectable.map((r) => r.seller_id)) : new Set())} /></th>
                  <th className="text-right font-medium px-3 py-3">שם</th><th className="text-right font-medium px-3 py-3">טלפון</th>
                  <th className="text-right font-medium px-3 py-3 hidden lg:table-cell">נכס</th><th className="text-right font-medium px-3 py-3 hidden lg:table-cell">מחיר</th>
                  <th className="text-right font-medium px-3 py-3">סטטוס</th><th className="w-10" />
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 500).map((c) => (
                  <tr key={c.seller_id} className="border-b border-line last:border-0 hover:bg-slate-50/70">
                    <td className="px-4 py-3">{DRAFTABLE.includes(c.status) && <input type="checkbox" className="size-4 accent-brand-600" checked={sel.has(c.seller_id)} onChange={() => toggle(c.seller_id)} />}</td>
                    <td className="px-3 py-3 font-medium">{c.name || '—'}{c.notes && <div className="text-xs text-muted font-normal truncate max-w-48">{c.notes}</div>}</td>
                    <td className="px-3 py-3 num text-right text-slate-600">{fmtPhone(c.phone)}</td>
                    <td className="px-3 py-3 text-slate-600 hidden lg:table-cell">{[c.rooms && `${c.rooms} חד׳`, c.address, c.city].filter(Boolean).join(' · ')}</td>
                    <td className="px-3 py-3 num text-right text-slate-600 hidden lg:table-cell">{money(c.asking_price)}</td>
                    <td className="px-3 py-3"><StatusBadge status={c.status} labels={labels} /></td>
                    <td className="px-2">{c.status === 'new' && <button aria-label="מחיקה" onClick={() => remove(c.seller_id)} className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 className="size-4" /></button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <p className="py-10 text-center text-muted">אין תוצאות</p>}
          </Card>
        </>
      )}

      <Modal open={importing} onClose={() => setImporting(false)} title="ייבוא רשימת לקוחות" wide>
        <ImportWizard onDone={(r) => { toast(`${r.saved} לקוחות נשמרו (${r.new} חדשים)`); setImporting(false); reload() }} />
      </Modal>
    </div>
  )
}
