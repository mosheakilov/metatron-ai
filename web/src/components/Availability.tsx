import { DAYS } from '../api'
import type { SettingsT } from '../api'
import { cx } from '../ui'

const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
const WEEK = [6, 0, 1, 2, 3, 4, 5] // shown Sunday first

type Av = SettingsT['availability']

/** Days and start hours the scheduling agent may offer to sellers. */
export function Availability({ value, onChange }: { value: Av; onChange: (v: Av) => void }) {
  const toggle = <K extends 'weekdays' | 'hours'>(key: K, x: number) => {
    const set = new Set(value[key])
    if (set.has(x)) set.delete(x)
    else set.add(x)
    onChange({ ...value, [key]: [...set].sort((a, b) => a - b) })
  }
  return (
    <div className="space-y-5">
      <div>
        <div className="text-sm font-medium mb-2">ימים לפגישות</div>
        <div className="flex flex-wrap gap-2">
          {WEEK.map((d) => (
            <Chip key={d} on={value.weekdays.includes(d)} onClick={() => toggle('weekdays', d)}>{DAYS[d]}</Chip>
          ))}
        </div>
      </div>
      <div>
        <div className="text-sm font-medium mb-2">שעות התחלה אפשריות</div>
        <div className="flex flex-wrap gap-2">
          {HOURS.map((h) => (
            <Chip key={h} on={value.hours.includes(h)} onClick={() => toggle('hours', h)}><span className="num">{h}:00</span></Chip>
          ))}
        </div>
        <p className="text-xs text-muted mt-2">כשמוכר מסכים, הוא מקבל שלושה מועדים פנויים בימים הקרובים, אחד לכל יום.</p>
      </div>
    </div>
  )
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={cx('h-10 min-w-12 rounded-xl px-3 text-sm font-medium border transition', on ? 'bg-brand-600 border-brand-600 text-white' : 'bg-white border-line text-slate-600 hover:border-brand-300')}>
      {children}
    </button>
  )
}
