import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, setToken } from '../api'
import { Button, ErrorBox, Field, Input, Mark } from '../components/ui'

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
      <div className="w-full max-w-[340px]">
        <div className="mb-8 flex items-center gap-2.5">
          <Mark size={24} />
          <span className="text-[15px] font-semibold tracking-tight">AviaWatch</span>
        </div>
        <h1 className="text-[22px] font-semibold">Вход в панель</h1>
        <p className="mt-1 mb-6 text-[13px] text-muted">Источники цен, пользователи и настройки бота.</p>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Логин">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" className="h-9" />
          </Field>
          <Field label="Пароль">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus className="h-9" />
          </Field>
          <ErrorBox error={error} />
          <Button type="submit" className="h-9 w-full" disabled={busy || !password}>
            {busy ? 'Входим…' : 'Войти'}
          </Button>
        </form>
      </div>
    </div>
  )
}
