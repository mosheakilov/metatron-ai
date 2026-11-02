import { ArrowDownLeft, ArrowUpLeft, CalendarCheck, Clock, Inbox, MessageCircle, Send, Users, WifiOff } from 'lucide-react'
import { fmtSlot, fmtTime, usePoll, type AppState, type Stats } from '../api'
import type { Page } from '../shell'
import { Button, Card, cx, Empty, Spinner } from '../ui'

const WAIT_HE: Record<string, string> = {
  empty: 'אין הודעות בתור', paused: 'השליחה מושהית', daily_cap: 'הגעת למכסה היומית',
  outside_hours: 'מחוץ לשעות השליחה', pacing: 'ממתין בין הודעות',
}

export function Home({ state, go }: { state: AppState; go: (p: Page) => void }) {
  const { data: st } = usePoll<Stats>('/api/stats', 5000)
  const name = state.settings.broker_name.split(' ')[0]
  const hour = new Date().getHours()
  const hello = hour < 12 ? 'בוקר טוב' : hour < 18 ? 'צהריים טובים' : 'ערב טוב'
  if (!st) return <div className="grid place-items-center py-24"><Spinner /></div>

  const ob = state.outbox
  const funnel = [
    { label: 'ברשימה', n: st.total }, { label: 'פנינו', n: st.contacted },
    { label: 'השיבו', n: st.replied }, { label: 'פגישות', n: st.booked },
  ]
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{hello}{name ? `, ${name}` : ''}</h1>
        <p className="text-muted mt-1">זה מה שקורה עם המוכרים שלך היום.</p>
      </div>

      {state.whatsapp.status !== 'open' && (
        <Alert tone="rose" icon={<WifiOff className="size-5" />} text="הוואטסאפ לא מחובר, אז הודעות לא נשלחות ותשובות לא מתקבלות." action={<Button size="sm" variant="danger" onClick={() => go('settings')}>חיבור</Button>} />
      )}
      {st.pending_approval > 0 && (
        <Alert tone="amber" icon={<Inbox className="size-5" />} text={<><span className="num font-bold">{st.pending_approval}</span> הודעות מחכות לאישור שלך</>} action={<Button size="sm" onClick={() => go('queue')}>לאישור</Button>} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi icon={<Users />} label="לקוחות ברשימה" n={st.total} tone="bg-slate-100 text-slate-700" />
        <Kpi icon={<Send />} label="קיבלו פנייה" n={st.contacted} tone="bg-sky-50 text-sky-600" />
        <Kpi icon={<MessageCircle />} label="השיבו" n={st.replied} tone="bg-violet-50 text-violet-600" sub={st.contacted ? `${Math.round((100 * st.replied) / st.contacted)}% מענה` : undefined} />
        <Kpi icon={<CalendarCheck />} label="פגישות שנקבעו" n={st.booked} tone="bg-emerald-50 text-emerald-600" />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <Card className="p-6 lg:col-span-2">
          <h2 className="font-semibold mb-5">המשפך</h2>
          <div className="space-y-3.5">
            {funnel.map((f, i) => {
              const pct = st.total ? Math.max(2, (100 * f.n) / st.total) : 0
              return (
                <div key={f.label} className="flex items-center gap-4">
                  <span className="w-16 text-sm text-muted">{f.label}</span>
                  <div className="h-9 flex-1 rounded-lg bg-slate-100 overflow-hidden">
                    <div className="h-full rounded-lg transition-all duration-700" style={{ width: `${pct}%`, background: ['#c7d2fe', '#818cf8', '#6366f1', '#10b981'][i] }} />
                  </div>
                  <span className="num w-12 text-left font-semibold">{f.n}</span>
                </div>
              )
            })}
          </div>
          {st.opted_out > 0 && <p className="text-xs text-muted mt-4">{st.opted_out === 1 ? 'מוכר אחד ביקש' : <><span className="num">{st.opted_out}</span> מוכרים ביקשו</>} להסיר ולא יקבלו עוד הודעות.</p>}
        </Card>

        <Card className="p-6">
          <h2 className="font-semibold mb-4">שליחה היום</h2>
          <div className="flex items-end gap-2">
            <span className="num text-4xl font-bold">{ob.sent_today}</span>
            <span className="text-muted pb-1">/ <span className="num">{ob.daily_cap}</span> פניות חדשות</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-slate-100 overflow-hidden">
            <div className="h-full bg-brand-600 rounded-full" style={{ width: `${Math.min(100, (100 * ob.sent_today) / Math.max(1, ob.daily_cap))}%` }} />
          </div>
          <div className="mt-5 space-y-2 text-sm">
            <Row label="בתור לשליחה" value={<span className="num">{ob.queued}</span>} />
            <Row label="מצב" value={ob.queued ? WAIT_HE[ob.waiting || ''] || 'שולח…' : 'הכל נשלח'} />
            {ob.next_at && ob.waiting !== 'empty' && <Row label="השליחה הבאה" value={<span className="num">{fmtTime(ob.next_at)}</span>} />}
          </div>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">פגישות קרובות</h2>
            <button className="text-sm text-brand-700 hover:underline" onClick={() => go('meetings')}>לכל הפגישות</button>
          </div>
          {st.upcoming.length === 0 ? <p className="text-sm text-muted py-6 text-center">עוד אין פגישות. הן יופיעו כאן ברגע שמוכר יבחר מועד.</p> : (
            <ul className="divide-y divide-line">
              {st.upcoming.map((m) => (
                <li key={m.id} className="flex items-center gap-3 py-3">
                  <div className="grid size-10 place-items-center rounded-xl bg-emerald-50 text-emerald-600"><CalendarCheck className="size-5" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{m.name}</div>
                    <div className="text-sm text-muted truncate">{m.address}</div>
                  </div>
                  <div className="text-sm font-medium text-left">{fmtSlot(m.start)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-6">
          <h2 className="font-semibold mb-4">פעילות אחרונה</h2>
          {st.activity.length === 0 ? <Empty icon={<Clock />} title="עוד אין פעילות" sub="אחרי אישור ההודעות הראשונות, הפעילות תופיע כאן." /> : (
            <ul className="space-y-3">
              {st.activity.slice(0, 7).map((m) => (
                <li key={m.id} className="flex items-start gap-3">
                  <span className={cx('mt-0.5 grid size-7 shrink-0 place-items-center rounded-full', m.direction === 'in' ? 'bg-violet-50 text-violet-600' : 'bg-sky-50 text-sky-600')}>
                    {m.direction === 'in' ? <ArrowDownLeft className="size-4" /> : <ArrowUpLeft className="size-4" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm"><span className="font-medium">{m.name}</span> <span className="text-muted">· {fmtTime(m.created_at)}</span></div>
                    <div className="text-sm text-slate-600 truncate">{m.body}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

function Kpi({ icon, label, n, tone, sub }: { icon: React.ReactNode; label: string; n: number; tone: string; sub?: string }) {
  return (
    <Card className="p-5">
      <div className={cx('grid size-10 place-items-center rounded-xl [&>svg]:size-5', tone)}>{icon}</div>
      <div className="num text-3xl font-bold mt-4">{n.toLocaleString('he-IL')}</div>
      <div className="text-sm text-muted mt-0.5">{label}{sub && <span className="text-slate-500"> · {sub}</span>}</div>
    </Card>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="flex justify-between"><span className="text-muted">{label}</span><span className="font-medium">{value}</span></div>
}

function Alert({ tone, icon, text, action }: { tone: 'rose' | 'amber'; icon: React.ReactNode; text: React.ReactNode; action: React.ReactNode }) {
  return (
    <div className={cx('flex items-center gap-3 rounded-2xl border p-4', tone === 'rose' ? 'bg-rose-50 border-rose-200 text-rose-900' : 'bg-amber-50 border-amber-200 text-amber-900')}>
      {icon}<div className="flex-1 text-sm">{text}</div>{action}
    </div>
  )
}
