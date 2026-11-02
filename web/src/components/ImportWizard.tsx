import { useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, FileSpreadsheet, UploadCloud } from 'lucide-react'
import { api, fmtPhone, money } from '../api'
import { Button, Card, cx, Spinner } from '../ui'

type Issue = { row: number; name: string; phone: string; problem: string }
type Contact = { seller_id: string; name: string; phone: string; city: string | null; address: string | null; asking_price: number | null; existing_status: string | null }
type Summary = { ok: boolean; missing: string[]; valid: number; new: number; existing: number; issues: Issue[]; preview: Contact[] }
type Preview = Summary & { token: string; filename: string; headers: string[]; n_rows: number; mapping: Record<string, number | null>; fields: string[]; required: string[] }

const FIELD_HE: Record<string, string> = {
  name: 'שם', phone: 'טלפון', city: 'עיר', address: 'כתובת', rooms: 'חדרים', area_sqm: 'שטח (מ"ר)',
  asking_price: 'מחיר מבוקש', notes: 'הערות',
}

/** Upload an Excel/CSV client list, check the column mapping, then save. Nothing is sent. */
export function ImportWizard({ onDone }: { onDone: (r: { saved: number; new: number }) => void }) {
  const [pre, setPre] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const upload = async (file: File) => {
    setBusy(true); setErr(null)
    const fd = new FormData()
    fd.append('file', file)
    try { setPre(await api<Preview>('/api/contacts/preview', { method: 'POST', body: fd })) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const remap = async (field: string, idx: number | null) => {
    if (!pre) return
    const mapping = { ...pre.mapping, [field]: idx }
    const s = await api<Summary>('/api/contacts/remap', { method: 'POST', json: { token: pre.token, mapping } })
    setPre({ ...pre, ...s, mapping })
  }

  const save = async () => {
    if (!pre) return
    setBusy(true)
    try { onDone(await api('/api/contacts/import', { method: 'POST', json: { token: pre.token, mapping: pre.mapping } })) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  if (!pre) {
    return (
      <div>
        <button type="button" onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) upload(f) }}
          className={cx('w-full rounded-2xl border-2 border-dashed p-10 text-center transition', drag ? 'border-brand-500 bg-brand-50' : 'border-slate-300 hover:border-brand-400 hover:bg-slate-50')}>
          {busy ? <Spinner className="mx-auto size-8" /> : <UploadCloud className="mx-auto size-10 text-brand-600" />}
          <div className="mt-3 font-semibold">גררו לכאן קובץ Excel או CSV</div>
          <div className="text-sm text-muted mt-1">או לחצו לבחירת קובץ · נדרשות עמודות שם וטלפון</div>
        </button>
        <input ref={input} type="file" accept=".xlsx,.xlsm,.csv,.txt" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        {err && <div className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{err}</div>}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <FileSpreadsheet className="size-5 text-emerald-600" />
        <span className="font-medium">{pre.filename}</span>
        <span className="text-sm text-muted">· <span className="num">{pre.n_rows}</span> שורות</span>
        <button className="mr-auto text-sm text-brand-700 hover:underline" onClick={() => setPre(null)}>קובץ אחר</button>
      </div>

      <div>
        <div className="text-sm font-medium mb-2">התאמת עמודות</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {pre.fields.map((f) => (
            <label key={f} className="block">
              <span className="text-xs text-muted">{FIELD_HE[f]}{pre.required.includes(f) && <span className="text-rose-500"> *</span>}</span>
              <select value={pre.mapping[f] ?? ''} onChange={(e) => remap(f, e.target.value === '' ? null : Number(e.target.value))}
                className={cx('mt-1 w-full h-10 rounded-lg border bg-white px-2 text-sm', pre.required.includes(f) && pre.mapping[f] == null ? 'border-rose-300' : 'border-line')}>
                <option value="">— לא קיים —</option>
                {pre.headers.map((h, i) => <option key={i} value={i}>{h || `עמודה ${i + 1}`}</option>)}
              </select>
            </label>
          ))}
        </div>
      </div>

      {pre.ok && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat n={pre.new} label="לקוחות חדשים" tone="text-brand-700" />
            <Stat n={pre.existing} label="כבר ברשימה (יעודכנו)" tone="text-slate-700" />
            <Stat n={pre.issues.length} label="שורות שידולגו" tone={pre.issues.length ? 'text-amber-600' : 'text-slate-400'} />
          </div>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-muted text-xs">
                <tr><th className="text-right font-medium px-4 py-2">שם</th><th className="text-right font-medium px-4 py-2">טלפון</th><th className="text-right font-medium px-4 py-2">כתובת</th><th className="text-right font-medium px-4 py-2">מחיר</th></tr>
              </thead>
              <tbody>
                {pre.preview.map((c) => (
                  <tr key={c.seller_id} className="border-t border-line">
                    <td className="px-4 py-2 font-medium">{c.name}</td>
                    <td className="px-4 py-2 num text-right">{fmtPhone(c.phone)}</td>
                    <td className="px-4 py-2 text-muted">{[c.address, c.city].filter(Boolean).join(', ')}</td>
                    <td className="px-4 py-2 num text-right">{money(c.asking_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {pre.issues.length > 0 && (
            <details className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900">
              <summary className="cursor-pointer flex items-center gap-2 font-medium"><AlertTriangle className="size-4" />{pre.issues.length} שורות לא ייובאו</summary>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto scroll-thin">
                {pre.issues.map((i) => <li key={i.row}>שורה <span className="num">{i.row}</span>: {i.name || '—'} <span className="num">{i.phone}</span> · {i.problem}</li>)}
              </ul>
            </details>
          )}
        </>
      )}
      {!pre.ok && <div className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">בחרו את עמודות החובה: {pre.missing.map((m) => FIELD_HE[m]).join(', ')}</div>}
      {err && <div className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{err}</div>}

      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-muted flex items-center gap-1.5"><CheckCircle2 className="size-4 text-emerald-600" />שמירה לא שולחת שום הודעה</span>
        <Button size="lg" disabled={!pre.ok || pre.valid === 0} loading={busy} onClick={save}>ייבוא <span className="num">{pre.valid}</span> לקוחות</Button>
      </div>
    </div>
  )
}

function Stat({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <div className="rounded-xl border border-line p-3 text-center">
      <div className={cx('num text-2xl font-bold', tone)}>{n}</div>
      <div className="text-xs text-muted mt-0.5">{label}</div>
    </div>
  )
}
