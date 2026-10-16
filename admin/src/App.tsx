import { Bot, LayoutGrid, LogOut, Monitor, Moon, ScrollText, Sun, Users, Workflow } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { getToken, setToken } from './api'
import type { ThemeChoice } from './components/ui'
import { Mark, cx, useThemeChoice } from './components/ui'
import BotPage from './pages/Bot'
import Configurator from './pages/Configurator'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Logs from './pages/Logs'
import UsersPage from './pages/Users'

const NAV = [
  { to: '/', label: 'Обзор', icon: LayoutGrid },
  { to: '/configurator', label: 'Источники', icon: Workflow },
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/bot', label: 'Бот', icon: Bot },
  { to: '/logs', label: 'Журнал', icon: ScrollText },
]

function ThemeSwitch() {
  const [choice, setChoice] = useThemeChoice()
  const items: [ThemeChoice, typeof Sun, string][] = [
    ['light', Sun, 'Светлая'],
    ['system', Monitor, 'Как в системе'],
    ['dark', Moon, 'Тёмная'],
  ]
  return (
    <div className="flex rounded-lg border border-line p-0.5 max-md:hidden">
      {items.map(([value, Icon, title]) => (
        <button
          key={value}
          type="button"
          title={title}
          onClick={() => setChoice(value)}
          className={cx('grid h-6 flex-1 place-items-center rounded-md transition-colors', choice === value ? 'bg-panel-2 text-ink' : 'text-faint hover:text-muted')}
        >
          <Icon size={13} strokeWidth={1.75} />
        </button>
      ))}
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())

  useEffect(() => {
    const onLogout = () => setAuthed(false)
    window.addEventListener('aw:logout', onLogout)
    return () => window.removeEventListener('aw:logout', onLogout)
  }, [])

  if (!authed) return <Login onLogin={() => setAuthed(true)} />

  return (
    <div className="flex h-full">
      <aside className="flex w-52 shrink-0 flex-col border-r border-line px-3 py-5 max-md:w-14 max-md:px-2">
        <div className="mb-8 flex items-center gap-2 px-2 text-ink">
          <Mark />
          <span className="text-[14px] font-semibold tracking-tight max-md:hidden">AviaWatch</span>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              title={label}
              className={({ isActive }) =>
                cx(
                  'relative flex h-8 items-center gap-2.5 rounded-lg px-2 text-[13px] transition-colors max-md:justify-center',
                  isActive ? 'bg-panel-2 font-medium text-ink' : 'text-muted hover:text-ink',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute top-2 bottom-2 -left-3 w-0.5 rounded-r bg-accent max-md:-left-2" />}
                  <Icon size={16} strokeWidth={1.75} />
                  <span className="max-md:hidden">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2">
          <ThemeSwitch />
          <button
            onClick={() => {
              setToken(null)
              setAuthed(false)
            }}
            title="Выйти"
            className="flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-[13px] text-muted transition-colors hover:text-ink max-md:justify-center"
          >
            <LogOut size={16} strokeWidth={1.75} />
            <span className="max-md:hidden">Выйти</span>
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/configurator" element={<Configurator />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/bot" element={<BotPage />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}

