import { Plane } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, setToken } from '../api'
import { Button, ErrorBox, Field, Input } from '../components/ui'

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api<{ token: string }>('/api/auth/login', { method: 'POST', body: { username, password } })
      setToken(res.token)
      onLogin()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-line bg-panel p-6">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-slate-900">
            <Plane size={20} />
          </span>
          <div>
            <div className="text-lg font-semibold">AviaWatch</div>
            <div className="text-xs text-muted">Панель администратора</div>
          </div>
        </div>
        <Field label="Логин">
          <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </Field>
        <Field label="Пароль">
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
        </Field>
        <ErrorBox error={error} />
        <Button type="submit" className="w-full" disabled={busy || !password}>
          {busy ? 'Входим…' : 'Войти'}
        </Button>
      </form>
    </div>
  )
}
