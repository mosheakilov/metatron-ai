import type { ReactNode } from 'react'
import { CalendarDays, Inbox, KeyRound, LayoutDashboard, MessagesSquare, Settings, Tag, Users } from 'lucide-react'
import { DEAL_HE, type AppState, type Deal } from './api'
import { cx } from './ui'

export type Page = 'home' | 'contacts' | 'queue' | 'chats' | 'meetings' | 'settings'

export function Logo({ light }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 64 64" className="size-9"><rect x="4" y="4" width="56" height="56" rx="16" fill="#4f46e5" /><path d="M32 14 50 32 32 50 14 32Z" fill="#fff" /><path d="M32 24 40 32 32 40 24 32Z" fill="#4f46e5" /></svg>
      <span className={cx('text-lg font-extrabold tracking-wide', light ? 'text-white' : 'text-ink')}>METATRON</span>
    </div>
  )
}

const NAV: { id: Page; label: string; icon: typeof Users }[] = [
  { id: 'home', label: 'סקירה', icon: LayoutDashboard },
  { id: 'queue', label: 'לאישור', icon: Inbox },
  { id: 'chats', label: 'שיחות', icon: MessagesSquare },
  { id: 'meetings', label: 'פגישות', icon: CalendarDays },
  { id: 'contacts', label: 'לקוחות', icon: Users },
  { id: 'settings', label: 'הגדרות', icon: Settings },
]

/** Sales and rentals work the same way; the switch decides which clients every screen shows. */
function DealSwitch({ deal, onDeal, dark }: { deal: Deal; onDeal: (d: Deal) => void; dark?: boolean }) {
  return (
    <div role="tablist" aria-label="סוג עסקה" className={cx('grid grid-cols-2 gap-1 rounded-xl p-1', dark ? 'bg-white/8' : 'bg-slate-100')}>
      {(['sale', 'rent'] as const).map((d) => {
        const Icon = d === 'sale' ? Tag : KeyRound
        const on = deal === d
        return (
          <button key={d} role="tab" aria-selected={on} onClick={() => onDeal(d)}
            className={cx('flex items-center justify-center gap-1.5 rounded-lg py-2 text-sm font-semibold transition',
              on ? (d === 'sale' ? 'bg-white text-brand-800 shadow-sm' : 'bg-emerald-400 text-emerald-950 shadow-sm')
                : dark ? 'text-indigo-200/80 hover:text-white' : 'text-muted')}>
            <Icon className="size-4" />{DEAL_HE[d]}
          </button>
        )
      })}
    </div>
  )
}

export function Shell({ page, go, state, badges, deal, onDeal, children }: {
  page: Page; go: (p: Page) => void; state: AppState; badges: Partial<Record<Page, number>>
  deal: Deal; onDeal: (d: Deal) => void; children: ReactNode
}) {
  const wa = state.whatsapp
  const waOk = wa.status === 'open'
  return (
    <div className="flex h-full">
      <aside className="hidden md:flex w-64 shrink-0 flex-col bg-brand-900 text-indigo-100">
        <div className="px-5 pt-6 pb-5"><Logo light /></div>
        <div className="px-3 pb-5"><DealSwitch deal={deal} onDeal={onDeal} dark /></div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => go(id)}
              className={cx('flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition',
                page === id ? 'bg-white/12 text-white font-semibold' : 'text-indigo-200/80 hover:bg-white/6 hover:text-white')}>
              <Icon className="size-5" />
              <span className="flex-1 text-right">{label}</span>
              {!!badges[id] && <span className="num rounded-full bg-amber-400 px-2 text-xs font-bold text-amber-950">{badges[id]}</span>}
            </button>
          ))}
        </nav>
        <button onClick={() => go('settings')} className="m-3 rounded-xl bg-white/6 p-3 text-right hover:bg-white/10">
          <div className="flex items-center gap-2 text-sm">
            <span className={cx('size-2.5 rounded-full', waOk ? 'bg-emerald-400 shadow-[0_0_0_4px_rgb(52_211_153/0.2)]' : 'bg-rose-400')} />
            <span className="text-white">{waOk ? 'וואטסאפ מחובר' : 'וואטסאפ לא מחובר'}</span>
          </div>
          <div className="mt-1 text-xs text-indigo-200/70">
            {state.settings.paused ? 'השליחה מושהית' : `נשלחו היום ${state.outbox.sent_today} מתוך ${state.outbox.daily_cap}`}
          </div>
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="md:hidden flex items-center justify-between gap-3 bg-brand-900 px-4 py-3"><Logo light /><div className="w-44"><DealSwitch deal={deal} onDeal={onDeal} dark /></div></header>
        <main className="flex-1 overflow-y-auto scroll-thin">
          <div className="mx-auto max-w-6xl px-4 sm:px-8 py-8 pb-24 md:pb-8">{children}</div>
        </main>
        <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 grid grid-cols-6 border-t border-line bg-white">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => go(id)} className={cx('flex flex-col items-center gap-0.5 py-2 text-[11px]', page === id ? 'text-brand-700' : 'text-muted')}>
              <Icon className="size-5" />{label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  )
}
