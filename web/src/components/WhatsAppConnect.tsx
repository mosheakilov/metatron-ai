import { useEffect, useState } from 'react'
import { CheckCircle2, KeyRound, QrCode, ShieldAlert, Smartphone } from 'lucide-react'
import { api, fmtPhone, usePoll, type WhatsApp } from '../api'
import { Button, cx, inputCls, Spinner } from '../ui'

/** Link the broker's WhatsApp as a linked device: QR scan or an 8-character code by phone number. */
export function WhatsAppConnect({ onConnected, defaultPhone = '' }: { onConnected?: () => void; defaultPhone?: string }) {
  const { data: wa, reload } = usePoll<WhatsApp>('/api/whatsapp', 2000)
  const [mode, setMode] = useState<'phone' | 'qr'>('phone')
  const [phone, setPhone] = useState(defaultPhone)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const start = async () => {
    setBusy(true); setErr(null)
    try {
      await api('/api/whatsapp/connect', { method: 'POST', json: { mode, phone } })
      await reload()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  useEffect(() => { if (wa?.status === 'open') onConnected?.() }, [wa?.status, onConnected])

  if (!wa) return <div className="py-10 grid place-items-center"><Spinner /></div>

  if (wa.status === 'open') {
    return (
      <div className="flex items-center gap-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
        <div className="grid size-12 place-items-center rounded-full bg-emerald-600 text-white"><CheckCircle2 className="size-6" /></div>
        <div>
          <div className="font-semibold text-emerald-900">וואטסאפ מחובר</div>
          <div className="text-sm text-emerald-800">
            <span className="num">{fmtPhone(wa.me?.phone || '')}</span>{wa.me?.name ? ` · ${wa.me.name}` : ''}
          </div>
        </div>
      </div>
    )
  }

  if (wa.status === 'offline') {
    return <div className="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">רכיב הוואטסאפ לא פועל. סגרו את METATRON ופתחו מחדש.</div>
  }

  const waiting = wa.status === 'pairing' || wa.status === 'qr'
  return (
    <div className="space-y-5">
      {!waiting && (
        <>
          <div className="grid grid-cols-2 gap-2 rounded-xl bg-slate-100 p-1">
            {([['phone', 'לפי מספר טלפון', Smartphone], ['qr', 'סריקת קוד QR', QrCode]] as const).map(([m, label, Icon]) => (
              <button key={m} onClick={() => setMode(m)}
                className={cx('flex items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium transition', mode === m ? 'bg-white shadow-sm' : 'text-muted')}>
                <Icon className="size-4" />{label}
              </button>
            ))}
          </div>
          {mode === 'phone' && (
            <input className={cx(inputCls, 'num text-right')} dir="ltr" inputMode="tel" placeholder="050-0000000"
              value={phone} onChange={(e) => setPhone(e.target.value)} />
          )}
          <Button size="lg" className="w-full" loading={busy || wa.status === 'connecting' || wa.status === 'reconnecting'}
            disabled={mode === 'phone' && phone.replace(/\D/g, '').length < 9} onClick={start}>
            {mode === 'phone' ? 'קבלת קוד חיבור' : 'הצגת קוד QR'}
          </Button>
        </>
      )}

      {wa.status === 'pairing' && wa.pairingCode && (
        <div className="rise text-center space-y-4">
          <div className="inline-flex items-center gap-2 text-sm text-muted"><KeyRound className="size-4" />קוד החיבור שלך</div>
          <div className="num text-4xl font-bold tracking-[0.3em] text-brand-700">{wa.pairingCode.slice(0, 4)}-{wa.pairingCode.slice(4)}</div>
          <Steps items={['פתחו וואטסאפ בטלפון', 'הגדרות ← מכשירים מקושרים ← קישור מכשיר', 'בחרו "קישור באמצעות מספר טלפון" והקלידו את הקוד']} />
        </div>
      )}
      {wa.status === 'qr' && wa.qr && (
        <div className="rise flex flex-col sm:flex-row items-center gap-6">
          <img src={wa.qr} alt="קוד QR לחיבור וואטסאפ" className="size-56 rounded-xl border border-line p-2 bg-white" />
          <Steps items={['פתחו וואטסאפ בטלפון', 'הגדרות ← מכשירים מקושרים ← קישור מכשיר', 'סרקו את הקוד']} />
        </div>
      )}
      {waiting && <div className="flex items-center justify-center gap-2 text-sm text-muted"><Spinner className="size-4" />ממתין לאישור בטלפון…</div>}
      {waiting && <button className="block mx-auto text-sm text-brand-700 hover:underline" onClick={start}>קוד חדש</button>}
      {(err || wa.error) && <div className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{err || wa.error}</div>}

      <div className="flex gap-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">
        <ShieldAlert className="size-5 shrink-0" />
        <div>
          METATRON מתחבר כמו WhatsApp Web, כמכשיר מקושר. זה לא החיבור הרשמי של וואטסאפ לעסקים.
          כדי להגן על המספר שלך, הודעות ראשונות יוצאות לאט ובמכסה יומית, ורק אחרי שאישרת כל אחת מהן.
        </div>
      </div>
    </div>
  )
}

function Steps({ items }: { items: string[] }) {
  return (
    <ol className="space-y-2.5 text-right">
      {items.map((t, i) => (
        <li key={i} className="flex items-start gap-3 text-sm">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700 text-xs font-bold">{i + 1}</span>
          <span className="pt-0.5">{t}</span>
        </li>
      ))}
    </ol>
  )
}
