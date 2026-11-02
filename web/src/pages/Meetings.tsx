import { CalendarDays, MapPin, Phone } from 'lucide-react'
import { DAY_NAMES, fmtPhone, usePoll, type Meeting } from '../api'
import { Card, Empty, PageHeader, Spinner } from '../ui'

export function Meetings() {
  const { data } = usePoll<{ meetings: Meeting[] }>('/api/meetings', 15000)
  if (!data) return <div className="grid place-items-center py-24"><Spinner /></div>
  const local = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
  const now = local.toISOString().slice(0, 16) // meetings are stored in local time
  const upcoming = data.meetings.filter((m) => m.start >= now)
  const past = data.meetings.filter((m) => m.start < now).reverse()
  const days = new Map<string, Meeting[]>()
  for (const m of upcoming) days.set(m.start.slice(0, 10), [...(days.get(m.start.slice(0, 10)) || []), m])

  return (
    <div>
      <PageHeader title="פגישות" sub="פגישות גיוס שהמוכרים בחרו מתוך הזמינות שלך" />
      {!data.meetings.length ? (
        <Card><Empty icon={<CalendarDays />} title="עוד אין פגישות" sub="כשמוכר יסכים וייבחר מועד, הפגישה תופיע כאן." /></Card>
      ) : (
        <div className="space-y-6">
          {[...days].map(([day, ms]) => {
            const d = new Date(day + 'T12:00')
            return (
              <div key={day}>
                <div className="mb-2 text-sm font-semibold text-muted">יום {DAY_NAMES[(d.getDay() + 6) % 7]} · {d.toLocaleDateString('he-IL', { day: 'numeric', month: 'long' })}</div>
                <div className="grid gap-3 md:grid-cols-2">{ms.map((m) => <MeetingCard key={m.id} m={m} />)}</div>
              </div>
            )
          })}
          {past.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-semibold text-muted">פגישות שעברו</div>
              <div className="grid gap-3 md:grid-cols-2 opacity-70">{past.map((m) => <MeetingCard key={m.id} m={m} />)}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MeetingCard({ m }: { m: Meeting }) {
  const t = (iso: string) => new Date(iso).toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })
  return (
    <Card className="flex gap-4 p-5">
      <div className="flex w-16 shrink-0 flex-col items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
        <span className="num text-lg font-bold">{t(m.start)}</span>
        <span className="num text-xs">{t(m.end)}</span>
      </div>
      <div className="min-w-0">
        <div className="font-semibold">{m.name}</div>
        <div className="mt-1 flex items-center gap-1.5 text-sm text-muted"><MapPin className="size-4" />{m.address}</div>
        <a href={`tel:${m.phone}`} className="mt-1 flex items-center gap-1.5 text-sm text-brand-700"><Phone className="size-4" /><span className="num">{fmtPhone(m.phone)}</span></a>
      </div>
    </Card>
  )
}
