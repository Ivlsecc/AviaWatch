import { Send } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { AppSettings } from '../api'
import { api } from '../api'
import { Button, Card, ErrorBox, Field, Input, Textarea, Toggle, useApi } from '../components/ui'

type Job = { id: string; total: number; sent: number; failed: number; done: boolean; dry_run: boolean; errors: { tg_id: number; error: string }[] }

export default function BotPage() {
  const settings = useApi(() => api<AppSettings>('/api/settings'), [])
  const [form, setForm] = useState<AppSettings | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const [filtersJson, setFiltersJson] = useState('{}')

  useEffect(() => {
    if (settings.data) {
      setForm(settings.data)
      setFiltersJson(JSON.stringify(settings.data.default_filters ?? {}, null, 2))
    }
  }, [settings.data])

  async function save() {
    if (!form) return
    setError(null)
    setSaved(false)
    try {
      let default_filters: Record<string, unknown>
      try {
        default_filters = JSON.parse(filtersJson || '{}')
      } catch {
        throw new Error('Фильтры по умолчанию — некорректный JSON')
      }
      const { proxy_pools: _p, board_layout: _b, ...rest } = form
      void _p
      void _b
      const next = await api<AppSettings>('/api/settings', { method: 'PUT', body: { ...rest, default_filters } })
      settings.setData(next)
      setSaved(true)
    } catch (e) {
      setError(e)
    }
  }

  return (
    <div className="space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold">Бот</h1>
        <p className="text-sm text-muted">Тексты, режим техработ и умолчания. Бот подхватывает изменения в течение 15 секунд, перезапуск не нужен.</p>
      </header>
      <ErrorBox error={error || settings.error} />
      {form && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Режим работы">
            <div className="space-y-3">
              <Toggle checked={form.maintenance} onChange={(v) => setForm({ ...form, maintenance: v })} label={form.maintenance ? 'Техработы: бот отвечает только админам' : 'Бот работает для всех'} />
              <Field label="Текст во время техработ">
                <Textarea rows={2} value={form.maintenance_text} onChange={(e) => setForm({ ...form, maintenance_text: e.target.value })} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Проверять подписки раз в, мин">
                  <Input type="number" min={5} value={form.subscription_check_minutes} onChange={(e) => setForm({ ...form, subscription_check_minutes: Number(e.target.value) })} />
                </Field>
                <Field label="Лимит подписок для новых">
                  <Input type="number" min={0} value={form.default_max_subscriptions} onChange={(e) => setForm({ ...form, default_max_subscriptions: Number(e.target.value) })} />
                </Field>
              </div>
              <Field label="Фильтры по умолчанию для новых (JSON)" hint='например {"max_transfers": 1, "self_combos": true}'>
                <textarea
                  rows={4}
                  value={filtersJson}
                  onChange={(e) => setFiltersJson(e.target.value)}
                  className="w-full rounded-lg border border-line bg-bg px-3 py-2 font-mono text-xs outline-none focus:border-accent"
                />
              </Field>
            </div>
          </Card>

          <Card title="Тексты">
            <div className="space-y-3">
              <Field label="Приветствие (/start)" hint="Пусто — встроенный текст. {name} подставит имя. Разметка HTML Telegram.">
                <Textarea rows={6} value={form.welcome_text} onChange={(e) => setForm({ ...form, welcome_text: e.target.value })} placeholder="✈️ <b>Привет{name}!</b> …" />
              </Field>
              <Field label="Справка (/help)" hint="Пусто — встроенный текст">
                <Textarea rows={6} value={form.help_text} onChange={(e) => setForm({ ...form, help_text: e.target.value })} />
              </Field>
            </div>
          </Card>
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={!form}>Сохранить настройки</Button>
        {saved && <span className="text-sm text-ok">Сохранено</span>}
      </div>
      <Broadcast />
    </div>
  )
}

function Broadcast() {
  const [text, setText] = useState('')
  const [days, setDays] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!job || job.done) return
    const id = setInterval(async () => {
      try {
        setJob(await api<Job>(`/api/broadcast/${job.id}`))
      } catch (e) {
        setError(e)
      }
    }, 1500)
    return () => clearInterval(id)
  }, [job])

  async function start(dry: boolean) {
    setError(null)
    if (!dry && !confirm('Отправить сообщение всем выбранным пользователям? Отменить отправку нельзя.')) return
    try {
      setJob(await api<Job>('/api/broadcast', { method: 'POST', body: { text, dry_run: dry, only_active_days: days ? Number(days) : null } }))
    } catch (e) {
      setError(e)
    }
  }

  return (
    <Card title="Рассылка">
      <div className="space-y-3">
        <Field label="Сообщение" hint="HTML Telegram: <b>, <i>, <a href>. До 4000 символов.">
          <Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Добавили новый источник — чартеры из Telegram! 🎉" />
        </Field>
        <Field label="Только тем, кто заходил за последние N дней" hint="Пусто — всем незаблокированным">
          <Input type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} className="w-40" />
        </Field>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => start(true)} disabled={!text.trim()}>Сколько получат?</Button>
          <Button onClick={() => start(false)} disabled={!text.trim() || (job != null && !job.done)}>
            <Send size={14} /> Отправить
          </Button>
        </div>
        <ErrorBox error={error} />
        {job && (
          <div className="rounded-lg border border-line p-3 text-sm">
            {job.dry_run ? (
              <span>Получат: <b>{job.total}</b></span>
            ) : (
              <span>
                {job.done ? 'Готово' : 'Отправляю…'} — отправлено {job.sent} из {job.total}, ошибок {job.failed}
              </span>
            )}
            {job.errors.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-muted">
                {job.errors.map((e, i) => <li key={i}>{e.tg_id}: {e.error}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
