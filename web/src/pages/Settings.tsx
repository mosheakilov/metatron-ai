import { useEffect, useState, type ReactNode } from 'react'
import { LogOut, Pause, Play } from 'lucide-react'
import { api, type AppState, type SettingsT } from '../api'
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
          <TemplateEditor value={s.message_template} onChange={(message_template) => setS({ ...s, message_template })} />
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

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <Card className="grid gap-6 p-6 lg:grid-cols-[240px_1fr]">
      <div><h2 className="font-semibold">{title}</h2>{sub && <p className="text-sm text-muted mt-1">{sub}</p>}</div>
      <div>{children}</div>
    </Card>
  )
}

const PLACEHOLDERS: [string, string][] = [['{שם}', 'שם פרטי'], ['{נכס}', 'הנכס והכתובת'], ['{עיר}', 'עיר'], ['{חתימה}', 'השם והמשרד']]

function TemplateEditor({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [preview, setPreview] = useState<{ text: string; seller: string } | null>(null)
  useEffect(() => {
    const t = setTimeout(() => api<{ text: string; seller: string }>('/api/template/preview', { method: 'POST', json: { body: value } }).then(setPreview).catch(() => {}), 300)
    return () => clearTimeout(t)
  }, [value])
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
        <div className="whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-[#d9fdd3] p-3.5 text-[15px] leading-relaxed shadow-sm">{preview?.text}</div>
      </div>
    </div>
  )
}
