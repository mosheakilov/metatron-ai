import { useCallback, useState } from 'react'
import { ArrowLeft, Check, Sparkles } from 'lucide-react'
import { api, type SettingsT } from '../api'
import { Availability } from '../components/Availability'
import { ImportWizard } from '../components/ImportWizard'
import { WhatsAppConnect } from '../components/WhatsAppConnect'
import { Logo } from '../shell'
import { Button, Card, cx, Field, inputCls } from '../ui'

const STEPS = ['פרטים', 'וואטסאפ', 'לקוחות', 'זמינות']

export function Onboarding({ settings, onFinish }: { settings: SettingsT; onFinish: () => void }) {
  const [step, setStep] = useState(0)
  const [s, setS] = useState(settings)
  const [waOk, setWaOk] = useState(false)
  const [imported, setImported] = useState<number | null>(null)
  const markWa = useCallback(() => setWaOk(true), [])

  const save = (changes: Partial<SettingsT>) => api('/api/settings', { method: 'PUT', json: changes })
  const next = async () => {
    if (step === 0) await save({ broker_name: s.broker_name.trim(), office_name: s.office_name.trim() })
    if (step === 3) {
      await save({ availability: s.availability, setup_done: true })
      onFinish()
      return
    }
    setStep(step + 1)
  }

  return (
    <div className="min-h-full bg-[radial-gradient(ellipse_at_top,_#e0e7ff_0%,_#f5f6fa_55%)]">
      <div className="mx-auto max-w-2xl px-4 py-10">
        <div className="flex justify-center mb-8"><Logo /></div>

        <ol className="flex items-center justify-center gap-2 mb-8">
          {STEPS.map((t, i) => (
            <li key={t} className="flex items-center gap-2">
              <span className={cx('grid size-7 place-items-center rounded-full text-xs font-bold transition',
                i < step ? 'bg-emerald-500 text-white' : i === step ? 'bg-brand-600 text-white' : 'bg-white text-muted border border-line')}>
                {i < step ? <Check className="size-4" /> : i + 1}
              </span>
              <span className={cx('text-sm hidden sm:inline', i === step ? 'font-semibold' : 'text-muted')}>{t}</span>
              {i < STEPS.length - 1 && <span className="w-8 h-px bg-slate-300 mx-1" />}
            </li>
          ))}
        </ol>

        <Card className="rise p-6 sm:p-8" key={step}>
          {step === 0 && (
            <div className="space-y-5">
              <div>
                <h1 className="text-2xl font-bold">ברוכים הבאים ל-METATRON</h1>
                <p className="text-muted mt-1.5">בכמה דקות נגדיר את המשרד, נחבר את הוואטסאפ ונטען את רשימת הלקוחות. METATRON יפנה למוכרים בשמך, ושום הודעה לא יוצאת בלי האישור שלך.</p>
              </div>
              <Field label="השם שלך" hint="מופיע בחתימה של כל הודעה">
                <input className={inputCls} value={s.broker_name} onChange={(e) => setS({ ...s, broker_name: e.target.value })} placeholder="לדוגמה: דנה לוי" autoFocus />
              </Field>
              <Field label="שם המשרד (לא חובה)">
                <input className={inputCls} value={s.office_name} onChange={(e) => setS({ ...s, office_name: e.target.value })} placeholder='לדוגמה: לוי נדל"ן' />
              </Field>
            </div>
          )}
          {step === 1 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold">חיבור הוואטסאפ שלך</h2>
                <p className="text-muted mt-1">ההודעות יוצאות מהמספר שלך, והתשובות של המוכרים מגיעות ישירות ל-METATRON. אפשר להמשיך להשתמש בוואטסאפ בטלפון כרגיל.</p>
              </div>
              <WhatsAppConnect onConnected={markWa} defaultPhone={settings.wa_phone} />
            </div>
          )}
          {step === 2 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold">רשימת הלקוחות</h2>
                <p className="text-muted mt-1">העלו את הרשימה של המוכרים שאיתם נתחיל לדבר. אפשר להוסיף רשימות נוספות בכל זמן.</p>
              </div>
              {imported === null
                ? <ImportWizard onDone={(r) => setImported(r.saved)} />
                : <div className="flex items-center gap-3 rounded-2xl bg-emerald-50 border border-emerald-200 p-5 text-emerald-900"><Check className="size-6" /><span><span className="num font-bold">{imported}</span> לקוחות נטענו בהצלחה</span></div>}
            </div>
          )}
          {step === 3 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold">מתי נוח לך להיפגש?</h2>
                <p className="text-muted mt-1">כשמוכר מסכים לפגישה, METATRON מציע לו מועדים מתוך הזמינות הזו בלבד.</p>
              </div>
              <Availability value={s.availability} onChange={(availability) => setS({ ...s, availability })} />
            </div>
          )}

          <div className="mt-8 flex items-center justify-between">
            {step > 0 ? <Button variant="ghost" onClick={() => setStep(step - 1)}>חזרה</Button> : <span />}
            <div className="flex items-center gap-3">
              {(step === 1 && !waOk) || (step === 2 && imported === null)
                ? <button className="text-sm text-muted hover:text-ink" onClick={() => setStep(step + 1)}>אעשה את זה אחר כך</button> : null}
              <Button size="lg" onClick={next}
                disabled={(step === 0 && !s.broker_name.trim()) || (step === 1 && !waOk) || (step === 2 && imported === null) || (step === 3 && (!s.availability.weekdays.length || !s.availability.hours.length))}
                icon={step === 3 ? <Sparkles className="size-4" /> : undefined}>
                {step === 3 ? 'סיום והתחלה' : <>המשך <ArrowLeft className="size-4" /></>}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
