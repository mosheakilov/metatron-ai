import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, ImagePlus, LogOut, Pause, Play, Trash2 } from 'lucide-react'
import { api, mediaUrl, type AppState, type SettingsT } from '../api'
import { Availability } from '../components/Availability'
import { WhatsAppConnect } from '../components/WhatsAppConnect'
import { Button, Card, cx, Field, inputCls, PageHeader, Toggle, useToast } from '../ui'

export function Settings({ state, onSaved }: { state: AppState; onSaved: () => void }) {
  const [s, setS] = useState<SettingsT>(state.settings)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const dirty = JSON.stringify(s) !== JSON.stringify(state.settings)
  const lim = s.limits
  const setLim = (k: keyof typeof lim, v: number | boolean) => setS({ ...s, limits: { ...lim, [k]: v } })

  const save = async (changes: Partial<SettingsT> = s) => {
    setBusy(true)
    try { await api('/api/settings', { method: 'PUT', json: changes }); toast('ההגדרות נשמרו'); onSaved() }
    catch (e) { toast((e as Error).message, 'err') } finally { setBusy(false) }
  }
  const logout = async () => { await api('/api/whatsapp/logout', { method: 'POST' }); onSaved() }
  const pause = (paused: boolean) => { setS({ ...s, paused }); save({ paused }) }

  return (
    <div className="pb-20">
      <PageHeader title="הגדרות" />
      <div className="space-y-5">
        <Section title="וואטסאפ" sub="המספר שממנו יוצאות ההודעות ואליו מגיעות התשובות">
          <WhatsAppConnect />
          {state.whatsapp.status === 'open' && <Button className="mt-4" variant="danger" size="sm" icon={<LogOut className="size-4" />} onClick={logout}>ניתוק המספר</Button>}
        </Section>

        <Section title="שליחה" sub="הקצב שומר על המספר שלך: הודעות ראשונות יוצאות לאט ובשעות סבירות. תשובות בשיחה פעילה יוצאות מיד.">
          <div className="flex items-center justify-between rounded-xl bg-slate-50 p-4 mb-5">
            <div>
              <div className="font-medium">{s.paused ? 'השליחה מושהית' : 'השליחה פעילה'}</div>
              <div className="text-sm text-muted">{s.paused ? 'שום הודעה לא יוצאת עד לחידוש השליחה' : 'הודעות שאושרו יוצאות לפי הקצב שהוגדר'}</div>
            </div>
            <Button variant={s.paused ? 'success' : 'secondary'} icon={s.paused ? <Play className="size-4" /> : <Pause className="size-4" />} onClick={() => pause(!s.paused)}>
              {s.paused ? 'חידוש שליחה' : 'השהיה'}
            </Button>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="פניות חדשות ביום" hint="מומלץ עד 20">
              <input type="number" min={0} max={60} className={inputCls} value={lim.daily_new} onChange={(e) => setLim('daily_new', +e.target.value)} />
            </Field>
            <Field label="שעת התחלה">
              <input type="number" min={6} max={22} className={inputCls} value={lim.start_hour} onChange={(e) => setLim('start_hour', +e.target.value)} />
            </Field>
            <Field label="שעת סיום">
              <input type="number" min={7} max={23} className={inputCls} value={lim.end_hour} onChange={(e) => setLim('end_hour', +e.target.value)} />
            </Field>
            <Field label="מרווח מינימלי (שניות)">
              <input type="number" min={30} className={inputCls} value={lim.min_gap_sec} onChange={(e) => setLim('min_gap_sec', +e.target.value)} />
            </Field>
            <Field label="מרווח מקסימלי (שניות)">
              <input type="number" min={30} className={inputCls} value={lim.max_gap_sec} onChange={(e) => setLim('max_gap_sec', +e.target.value)} />
            </Field>
            <div className="flex items-end pb-2"><Toggle on={lim.send_on_weekend} onChange={(v) => setLim('send_on_weekend', v)} label="שליחה גם בשישי ושבת" /></div>
          </div>
        </Section>

        <Section title="הודעת פתיחה" sub="הבסיס להודעה הראשונה לכל מוכר. כשהבינה המלאכותית מחוברת, היא מתאימה את הנוסח לכל מוכר ושומרת על הכוונה שלך.">
          <TemplateEditor value={s.message_template} onChange={(message_template) => setS({ ...s, message_template })}
            optOut={s.include_opt_out} image={s.outreach_image} />
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <ImagePicker image={s.outreach_image} onChange={(outreach_image) => { setS((cur) => ({ ...cur, outreach_image })); onSaved() }} />
            <div>
              <Checkbox checked={s.include_opt_out} onChange={(include_opt_out) => setS({ ...s, include_opt_out })}
                label='להוסיף בסוף כל הודעה: להסרה השיבו "הסר".' />
              <p className="mt-1.5 ps-8 text-xs text-muted leading-relaxed">
                {s.include_opt_out
                  ? 'מומלץ: חוק התקשורת (סעיף 30א) מחייב דרך הסרה בהודעה שיווקית, והשורה גם מקטינה את הסיכון שוואטסאפ יחסום את המספר.'
                  : 'ההודעות יישלחו בלי שורת הסרה. מוכר שבכל זאת יכתוב "הסר" לא יקבל יותר הודעות.'}
              </p>
            </div>
          </div>
        </Section>

        <Section title="פגישות" sub="המועדים ש-METATRON מציע למוכרים">
          <Availability value={s.availability} onChange={(availability) => setS({ ...s, availability })} />
          <div className="mt-5 max-w-48">
            <Field label="אורך פגישה (דקות)">
              <input type="number" min={15} step={15} className={inputCls} value={s.meeting_minutes} onChange={(e) => setS({ ...s, meeting_minutes: +e.target.value })} />
            </Field>
          </div>
        </Section>

        <Section title="פרטים" sub="החתימה בסוף כל הודעה">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="השם שלך"><input className={inputCls} value={s.broker_name} onChange={(e) => setS({ ...s, broker_name: e.target.value })} /></Field>
            <Field label="שם המשרד"><input className={inputCls} value={s.office_name} onChange={(e) => setS({ ...s, office_name: e.target.value })} /></Field>
          </div>
        </Section>

        <Section title="בינה מלאכותית" sub={state.ai ? 'מחובר: ההודעות מנוסחות באופן אישי לכל מוכר.' : 'לא מחובר: ההודעות נכתבות מתבנית קבועה. כל השאר עובד כרגיל.'}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="קוד רישיון"><input className={cx(inputCls, 'num')} dir="ltr" value={s.ai.license_key} onChange={(e) => setS({ ...s, ai: { ...s.ai, license_key: e.target.value } })} placeholder="MTR-XXXX-XXXX" /></Field>
            <Field label="כתובת שרת" hint="מתקבלת יחד עם הרישיון"><input className={cx(inputCls, 'num')} dir="ltr" value={s.ai.proxy_url} onChange={(e) => setS({ ...s, ai: { ...s.ai, proxy_url: e.target.value } })} placeholder="https://" /></Field>
          </div>
        </Section>
      </div>

      {dirty && (
        <div className="fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 rise flex items-center gap-4 rounded-2xl bg-slate-900 px-5 py-3 text-white shadow-pop">
          <span className="text-sm">יש שינויים שלא נשמרו</span>
          <Button size="sm" variant="ghost" className="text-slate-300 hover:bg-white/10" onClick={() => setS(state.settings)}>ביטול</Button>
          <Button size="sm" loading={busy} onClick={() => save()}>שמירה</Button>
        </div>
      )}
    </div>
  )
}

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 select-none">
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className={cx('mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border-2 transition peer-focus-visible:ring-4 peer-focus-visible:ring-brand-100',
        checked ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 bg-white')}>
        {checked && <Check className="size-3.5" strokeWidth={3} />}
      </span>
      <span className="text-sm font-medium">{label}</span>
    </label>
  )
}

function ImagePicker({ image, onChange }: { image: string; onChange: (name: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const upload = async (file?: File) => {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api<SettingsT>('/api/media/outreach', { method: 'POST', body: fd })
      onChange(r.outreach_image)
      toast('התמונה תצורף להודעות הראשונות מעכשיו')
    } catch (e) { toast((e as Error).message, 'err') } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }
  const remove = async () => {
    const r = await api<SettingsT>('/api/media/outreach', { method: 'DELETE' })
    onChange(r.outreach_image)
    toast('ההודעות הראשונות יישלחו בלי תמונה')
  }
  return (
    <div>
      <div className="text-sm font-medium mb-1.5">תמונה עם ההודעה הראשונה (לא חובה)</div>
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
      {image ? (
        <div className="flex items-center gap-3">
          <img src={mediaUrl(image)} alt="" className="size-20 rounded-xl border border-line object-cover" />
          <div className="flex flex-col gap-1.5">
            <Button size="sm" variant="secondary" loading={busy} icon={<ImagePlus className="size-4" />} onClick={() => input.current?.click()}>החלפת תמונה</Button>
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" />} onClick={remove}>הסרת התמונה</Button>
          </div>
        </div>
      ) : (
        <button type="button" disabled={busy} onClick={() => input.current?.click()}
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files[0]) }}
          className="flex w-full items-center gap-3 rounded-xl border-2 border-dashed border-line p-4 text-start text-sm text-muted transition hover:border-brand-400 hover:bg-brand-50/40">
          <ImagePlus className="size-6 shrink-0 text-brand-600" />
          {busy ? <span>מעלה…</span> : (
            <span>גררו לכאן תמונה או לחצו לבחירה
              <span className="block text-xs">לוגו, כרטיס ביקור או תמונה שלך. הטקסט יופיע ככיתוב מתחת לתמונה, בהודעה אחת.</span>
            </span>
          )}
        </button>
      )}
    </div>
  )
}

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <Card className="grid gap-6 p-6 lg:grid-cols-[240px_1fr]">
      <div><h2 className="font-semibold">{title}</h2>{sub && <p className="text-sm text-muted mt-1">{sub}</p>}</div>
      <div>{children}</div>
    </Card>
  )
}

const PLACEHOLDERS: [string, string][] = [['{שם}', 'שם פרטי'], ['{נכס}', 'הנכס והכתובת'], ['{עיר}', 'עיר'], ['{חתימה}', 'השם והמשרד']]

function TemplateEditor({ value, onChange, optOut, image }: { value: string; onChange: (v: string) => void; optOut: boolean; image: string }) {
  const [preview, setPreview] = useState<{ text: string; seller: string } | null>(null)
  useEffect(() => {
    const t = setTimeout(() => api<{ text: string; seller: string }>('/api/template/preview', { method: 'POST', json: { body: value, include_opt_out: optOut } }).then(setPreview).catch(() => {}), 300)
    return () => clearTimeout(t)
  }, [value, optOut])
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div>
        <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={7}
          className="w-full resize-y rounded-xl border border-line p-3.5 text-[15px] leading-relaxed outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100" />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {PLACEHOLDERS.map(([p, label]) => (
            <button key={p} type="button" onClick={() => onChange(value + p)} title={label}
              className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs text-slate-700 hover:bg-brand-50 hover:text-brand-700">{label} <span className="text-muted">{p}</span></button>
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs text-muted mb-1.5">תצוגה מקדימה{preview?.seller ? ` · ${preview.seller}` : ''}</div>
        <div className="rounded-2xl rounded-tr-sm bg-[#d9fdd3] p-1.5 shadow-sm">
          {image && <img src={mediaUrl(image)} alt="" className="mb-1 max-h-64 w-full rounded-xl object-cover" />}
          <div className="whitespace-pre-wrap p-2 text-[15px] leading-relaxed">{preview?.text}</div>
        </div>
      </div>
    </div>
  )
}
