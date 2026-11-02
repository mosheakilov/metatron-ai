import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { CheckCircle2, Loader2, X, XCircle } from 'lucide-react'

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')
export { cx }

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'; size?: 'sm' | 'md' | 'lg'; loading?: boolean
  icon?: ReactNode
}
export function Button({ variant = 'primary', size = 'md', loading, icon, className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: 'bg-brand-600 text-white hover:bg-brand-700 shadow-sm shadow-brand-600/20',
    secondary: 'bg-white text-ink border border-line hover:bg-slate-50',
    ghost: 'text-slate-600 hover:bg-slate-100',
    danger: 'bg-white text-rose-600 border border-rose-200 hover:bg-rose-50',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm shadow-emerald-600/20',
  }[variant]
  const s = { sm: 'h-8 px-3 text-sm gap-1.5', md: 'h-10 px-4 text-sm gap-2', lg: 'h-12 px-6 text-base gap-2' }[size]
  return (
    <button {...p} disabled={disabled || loading}
      className={cx('inline-flex items-center justify-center rounded-xl font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap', v, s, className)}>
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cx('bg-white rounded-2xl border border-line shadow-card', className)}>{children}</div>
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {sub && <p className="text-muted mt-1">{sub}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  )
}

const TONES: Record<string, string> = {
  new: 'bg-slate-100 text-slate-700', awaiting_approval: 'bg-amber-50 text-amber-700 ring-amber-200',
  sent: 'bg-sky-50 text-sky-700 ring-sky-200', in_conversation: 'bg-violet-50 text-violet-700 ring-violet-200',
  slots_offered: 'bg-indigo-50 text-indigo-700 ring-indigo-200', booked: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  not_interested: 'bg-slate-100 text-slate-500', opted_out: 'bg-rose-50 text-rose-700 ring-rose-200',
  rejected: 'bg-slate-100 text-slate-500', broker_took_over: 'bg-orange-50 text-orange-700 ring-orange-200',
}
export function StatusBadge({ status, labels }: { status: string; labels: Record<string, string> }) {
  return <span className={cx('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-transparent', TONES[status] || TONES.new)}>{labels[status] || status}</span>
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted mt-1.5">{hint}</span>}
    </label>
  )
}
export const inputCls = 'w-full h-11 rounded-xl border border-line bg-white px-3.5 text-[15px] outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100 transition'

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} className="inline-flex items-center gap-3">
      <span className={cx('relative h-6 w-11 rounded-full transition-colors', on ? 'bg-brand-600' : 'bg-slate-300')}>
        <span className={cx('absolute top-0.5 size-5 rounded-full bg-white shadow transition-all', on ? 'left-0.5' : 'right-0.5')} />
      </span>
      {label && <span className="text-sm">{label}</span>}
    </button>
  )
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    if (open) addEventListener('keydown', k)
    return () => removeEventListener('keydown', k)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 backdrop-blur-sm p-4 sm:p-10" onMouseDown={onClose}>
      <div className={cx('rise w-full rounded-2xl bg-white shadow-pop', wide ? 'max-w-4xl' : 'max-w-lg')} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-slate-100" aria-label="סגירה"><X className="size-5" /></button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  )
}

export function Empty({ icon, title, sub, action }: { icon: ReactNode; title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="mb-4 grid size-14 place-items-center rounded-2xl bg-brand-50 text-brand-600">{icon}</div>
      <h3 className="font-semibold text-lg">{title}</h3>
      {sub && <p className="text-muted mt-1 max-w-sm">{sub}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx('size-5 animate-spin text-brand-600', className)} />
}

// ---- toasts ----------------------------------------------------------------------------
type Toast = { id: number; text: string; tone: 'ok' | 'err' }
const ToastCtx = createContext<(text: string, tone?: 'ok' | 'err') => void>(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((text: string, tone: 'ok' | 'err' = 'ok') => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, text, tone }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 left-5 z-[60] flex flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className="rise flex items-center gap-2.5 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-pop">
            {t.tone === 'ok' ? <CheckCircle2 className="size-4 text-emerald-400" /> : <XCircle className="size-4 text-rose-400" />}
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
