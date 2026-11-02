import { useEffect, useState } from 'react'
import { usePoll, type AppState } from './api'
import { Contacts } from './pages/Contacts'
import { Conversations } from './pages/Conversations'
import { Home } from './pages/Home'
import { Meetings } from './pages/Meetings'
import { Onboarding } from './pages/Onboarding'
import { Queue } from './pages/Queue'
import { Settings } from './pages/Settings'
import { Shell, type Page } from './shell'
import { Logo } from './shell'
import { Spinner, ToastProvider } from './ui'

const PAGES: Page[] = ['home', 'contacts', 'queue', 'chats', 'meetings', 'settings']
const fromHash = (): Page => (PAGES.includes(location.hash.slice(1) as Page) ? (location.hash.slice(1) as Page) : 'home')

export default function App() {
  const { data: state, error, reload } = usePoll<AppState>('/api/state', 4000)
  const [page, setPage] = useState<Page>(fromHash)
  const [queueCount, setQueueCount] = useState(0)

  useEffect(() => {
    const h = () => setPage(fromHash())
    addEventListener('hashchange', h)
    return () => removeEventListener('hashchange', h)
  }, [])
  useEffect(() => {
    if (!state?.settings.setup_done) return
    fetch('/api/queue').then((r) => r.json()).then((d) => setQueueCount(d.drafts.length)).catch(() => {})
  }, [state])
  const go = (p: Page) => { location.hash = p }

  if (!state) {
    return (
      <div className="grid h-full place-items-center">
        <div className="flex flex-col items-center gap-4">
          <Logo />
          {error ? <p className="text-muted">METATRON לא פועל. פתחו אותו מתפריט התחל.</p> : <Spinner />}
        </div>
      </div>
    )
  }

  return (
    <ToastProvider>
      {!state.settings.setup_done ? <Onboarding settings={state.settings} onFinish={() => { reload(); go('home') }} /> : (
        <Shell page={page} go={go} state={state} badges={{ queue: queueCount }}>
          {page === 'home' && <Home state={state} go={go} />}
          {page === 'contacts' && <Contacts state={state} go={go} />}
          {page === 'queue' && <Queue state={state} go={go} />}
          {page === 'chats' && <Conversations state={state} />}
          {page === 'meetings' && <Meetings />}
          {page === 'settings' && <Settings key={JSON.stringify(state.settings)} state={state} onSaved={reload} />}
        </Shell>
      )}
    </ToastProvider>
  )
}
