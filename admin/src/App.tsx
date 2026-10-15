import { Bot, LayoutDashboard, LogOut, Plane, ScrollText, Users, Workflow } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { getToken, setToken } from './api'
import { cx } from './components/ui'
import BotPage from './pages/Bot'
import Configurator from './pages/Configurator'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Logs from './pages/Logs'
import UsersPage from './pages/Users'

const NAV = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/configurator', label: 'Конфигуратор', icon: Workflow },
  { to: '/users', label: 'Пользователи', icon: Users },
  { to: '/bot', label: 'Бот', icon: Bot },
  { to: '/logs', label: 'Логи', icon: ScrollText },
]

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
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-panel px-3 py-4 max-md:w-16">
        <div className="mb-6 flex items-center gap-2 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-slate-900">
            <Plane size={18} />
          </span>
          <span className="font-semibold max-md:hidden">AviaWatch</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cx('flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition', isActive ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-panel-2 hover:text-ink')
              }
            >
              <Icon size={18} />
              <span className="max-md:hidden">{label}</span>
            </NavLink>
          ))}
        </nav>
        <button
          onClick={() => {
            setToken(null)
            setAuthed(false)
          }}
          className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm text-muted hover:bg-panel-2 hover:text-ink"
        >
          <LogOut size={18} />
          <span className="max-md:hidden">Выйти</span>
        </button>
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
