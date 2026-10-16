import { Send } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { AppSettings } from '../api'
import { api } from '../api'
import { Button, Card, CodeArea, ErrorBox, Field, Input, Page, PageHeader, Textarea, Toggle, useApi } from '../components/ui'

type Job = { id: string; total: number; sent: number; failed: number; done: boolean; dry_run: boolean; errors: { tg_id: number; error: string }[] }

/** Строка настроек: слева что это и зачем, справа поля. */
function Row({ title, text, children }: { title: string; text?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-4 border-b border-line px-5 py-5 last:border-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] md:gap-10">
      <div>
        <div className="text-[13px] font-medium">{title}</div>
        {text && <p className="mt-1 text-[12px] leading-relaxed text-muted">{text}</p>}
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </div>
  )
}

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
    <Page>
      <PageHeader
        title="Бот"
        description="Тексты, техработы и настройки для новых пользователей. Бот подхватывает изменения за 15 секунд, перезапуск не нужен."
        actions={
          <>
            {saved && <span className="text-[12px] text-muted">Сохранено</span>}
            <Button onClick={save} disabled={!form}>
              Сохранить
            </Button>
          </>
        }
      />
      <ErrorBox error={error || settings.error} />
      {form && (
        <>
          <Card flush>
            <Row title="Техработы" text="Пока включено, бот отвечает только администраторам, остальным — текстом ниже.">
              <Toggle checked={form.maintenance} onChange={(v) => setForm({ ...form, maintenance: v })} label={form.maintenance ? 'Идут техработы' : 'Бот открыт для всех'} />
              <Textarea rows={2} value={form.maintenance_text} onChange={(e) => setForm({ ...form, maintenance_text: e.target.value })} />
            </Row>
            <Row title="Подписки" text="Как часто бот перепроверяет цены по подпискам и сколько подписок можно новому пользователю.">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Проверять раз в, мин">
                  <Input type="number" min={5} value={form.subscription_check_minutes} onChange={(e) => setForm({ ...form, subscription_check_minutes: Number(e.target.value) })} />
                </Field>
                <Field label="Лимит для новых">
                  <Input type="number" min={0} value={form.default_max_subscriptions} onChange={(e) => setForm({ ...form, default_max_subscriptions: Number(e.target.value) })} />
                </Field>
              </div>
            </Row>
            <Row title="Фильтры по умолчанию" text={<>Применяются к новым пользователям. Например <code className="font-mono text-[11px]">{'{"max_transfers": 1}'}</code>.</>}>
              <CodeArea rows={4} value={filtersJson} onChange={(e) => setFiltersJson(e.target.value)} />
            </Row>
          </Card>

          <Card flush>
            <Row title="Приветствие" text="Ответ на /start. Пусто — встроенный текст. {name} подставит имя, разметка — HTML Telegram.">
              <Textarea rows={6} value={form.welcome_text} onChange={(e) => setForm({ ...form, welcome_text: e.target.value })} placeholder="✈️ <b>Привет{name}!</b> …" />
            </Row>
            <Row title="Справка" text="Ответ на /help. Пусто — встроенный текст.">
              <Textarea rows={6} value={form.help_text} onChange={(e) => setForm({ ...form, help_text: e.target.value })} />
            </Row>
          </Card>
        </>
      )}
      <Broadcast />
    </Page>
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
    <Card flush>
      <Row title="Рассылка" text="Сообщение всем незаблокированным пользователям. HTML Telegram, до 4000 символов. Сначала проверьте, сколько человек его получат.">
        <Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Добавили новый источник цен…" />
        <Field label="Только заходившим за последние N дней" hint="Пусто — всем">
          <Input type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} className="w-32" />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={() => start(true)} disabled={!text.trim()}>
            Сколько получат?
          </Button>
          <Button onClick={() => start(false)} disabled={!text.trim() || (job != null && !job.done)}>
            <Send size={13} strokeWidth={1.75} /> Отправить
          </Button>
          {job && (
            <span className="text-[13px] text-muted">
              {job.dry_run ? (
                <>
                  Получат: <b className="font-medium text-ink tabular-nums">{job.total}</b>
                </>
              ) : (
                <>
                  {job.done ? 'Готово' : 'Отправляю…'} {job.sent} из {job.total}
                  {job.failed ? `, ошибок ${job.failed}` : ''}
                </>
              )}
            </span>
          )}
        </div>
        {job && job.errors.length > 0 && (
          <ul className="space-y-1 font-mono text-[11px] text-muted">
            {job.errors.map((e, i) => (
              <li key={i}>
                {e.tg_id}: {e.error}
              </li>
            ))}
          </ul>
        )}
        <ErrorBox error={error} />
      </Row>
    </Card>
  )
}
