import { useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardPaste, FileSpreadsheet, UploadCloud } from 'lucide-react'
import { api, fmtPhone, getDeal, money, propertyLine, type Seller } from '../api'
import { Button, Card, cx, Spinner } from '../ui'

type Issue = { row: number; name: string; phone: string; problem: string }
type Contact = Seller & { existing_status: string | null }
type Summary = { ok: boolean; rent: number; missing: string[]; valid: number; new: number; existing: number; issues: Issue[]; checks: Issue[]; preview: Contact[] }
type Preview = Summary & { token: string; filename: string; headers: string[]; n_rows: number; mapping: Record<string, number | null>; fields: string[]; required: string[] }

const FIELD_HE: Record<string, string> = {
  name: 'שם', phone: 'טלפון', city: 'עיר', address: 'כתובת', rooms: 'חדרים', area_sqm: 'שטח (מ"ר)',
  asking_price: 'מחיר מבוקש', notes: 'הערות', deal_type: 'סוג עסקה', property_type: 'סוג נכס', floor: 'קומה',
  floors_total: 'קומות בבניין', neighborhood: 'שכונה', listing_ref: 'מספר מודעה', listed_on: 'תאריך פרסום',
}

/** Upload an Excel/CSV client list, check the column mapping, then save. Nothing is sent. */
export function ImportWizard({ onDone }: { onDone: (r: { saved: number; new: number }) => void }) {
  const [pre, setPre] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [source, setSource] = useState<'file' | 'text'>('file')
  const [text, setText] = useState('')
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

  const fromText = async () => {
    setBusy(true); setErr(null)
    try { setPre(await api<Preview>('/api/contacts/paste', { method: 'POST', json: { body: text } })) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  if (!pre) {
    return (
      <div>
        <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl bg-slate-100 p-1">
          {([['file', 'קובץ Excel או CSV', FileSpreadsheet], ['text', 'הדבקת טקסט', ClipboardPaste]] as const).map(([m, label, Icon]) => (
            <button key={m} type="button" onClick={() => { setSource(m); setErr(null) }}
              className={cx('flex items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium transition', source === m ? 'bg-white shadow-sm' : 'text-muted')}>
              <Icon className="size-4" />{label}
            </button>
          ))}
        </div>
        {source === 'text' ? (
          <div>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={9} autoFocus
              placeholder={'לקוח בכל שורה, לדוגמה:\nיעל כהן 050-1234567 חיפה, הנשיא 10, 4 חדרים, 2.1 מיליון\nרון לוי 052-7654321 תל אביב, הרצל 5, 95 מ״ר\n\nאפשר גם להדביק תאים שהועתקו מ-Excel או מ-Google Sheets.'}
              className="w-full resize-y rounded-xl border border-line p-3.5 text-[15px] leading-relaxed outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100" />
            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="text-xs text-muted">המספר יכול להופיע בכל מקום בשורה. מה שלפניו הוא השם. מאחריו מזוהים עיר, כתובת, חדרים, מ״ר ומחיר, והשאר נשמר כהערה.</span>
              <Button loading={busy} disabled={!text.trim()} onClick={fromText}>המשך לבדיקה</Button>
            </div>
            {err && <div className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{err}</div>}
          </div>
        ) : <>
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
        </>}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <FileSpreadsheet className="size-5 text-emerald-600" />
        <span className="font-medium">{pre.filename}</span>
        <span className="text-sm text-muted">· <span className="num">{pre.n_rows}</span> שורות</span>
        <button className="mr-auto text-sm text-brand-700 hover:underline" onClick={() => setPre(null)}>{source === 'text' ? 'עריכת הטקסט' : 'קובץ אחר'}</button>
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
          {pre.rent > 0 && getDeal() === 'sale' && <div className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900"><span className="num font-semibold">{pre.rent}</span> מהלקוחות מסומנים "להשכרה" ויישמרו בלשונית השכרה.</div>}
          {pre.rent < pre.valid && getDeal() === 'rent' && <div className="rounded-xl bg-brand-50 p-3 text-sm text-brand-900"><span className="num font-semibold">{pre.valid - pre.rent}</span> מהלקוחות מסומנים "למכירה" ויישמרו בלשונית מכירה.</div>}
          {pre.checks?.length > 0 && (
            <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900">
              <div className="flex items-center gap-2 font-medium"><AlertTriangle className="size-4" />כדאי לבדוק {pre.checks.length === 1 ? 'מודעה אחת' : <><span className="num">{pre.checks.length}</span> מודעות</>} (ייובאו בכל מקרה)</div>
              <ul className="mt-2 space-y-1">{pre.checks.map((i) => <li key={i.phone}>{i.name || '—'} <span className="num">{i.phone}</span> · {i.problem}</li>)}</ul>
            </div>
          )}
          <Card className="max-h-96 overflow-y-auto scroll-thin">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-muted text-xs">
                <tr><th className="text-right font-medium px-4 py-2">שם</th><th className="text-right font-medium px-4 py-2">טלפון</th><th className="text-right font-medium px-4 py-2">נכס</th><th className="text-right font-medium px-4 py-2">מחיר</th><th className="text-right font-medium px-4 py-2">פורסם</th></tr>
              </thead>
              <tbody>
                {pre.preview.map((c) => (
                  <tr key={c.seller_id} className="border-t border-line">
                    <td className="px-4 py-2 font-medium">{c.name}</td>
                    <td className="px-4 py-2 num text-right">{fmtPhone(c.phone)}</td>
                    <td className="px-4 py-2 text-slate-600">{[c.address, c.city].filter(Boolean).join(', ') || <span className="text-slate-300">—</span>}
                      {(propertyLine(c) || c.notes) && <div className="text-xs text-muted">{[propertyLine(c), c.notes].filter(Boolean).join(' · ')}</div>}</td>
                    <td className="px-4 py-2 num text-right">{money(c.asking_price)}</td>
                    <td className="px-4 py-2 num text-right text-xs text-muted">{c.listed_on ? c.listed_on.split('-').reverse().join('/') : ''}</td>
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
