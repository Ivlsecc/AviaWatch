import { ExternalLink, FlaskConical, RotateCcw, X } from 'lucide-react'
import { useState } from 'react'
import type { AppSettings, SourceInfo, TestResult } from '../api'
import { api } from '../api'
import { Button, Card, ErrorBox, Field, Input, Select, StatusBadge, Toggle, ago, rub } from '../components/ui'

function tomorrowPlus(days: number) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

export default function SourcePanel({
  source,
  pools,
  onChanged,
  onClose,
}: {
  source: SourceInfo
  pools: AppSettings['proxy_pools']
  onChanged: () => void
  onClose: () => void
}) {
  const [form, setForm] = useState({
    enabled: source.enabled,
    priority: source.priority,
    rate_limit_per_min: source.rate_limit_per_min,
    timeout_s: source.timeout_s,
    retries: source.retries,
    proxy: source.proxy ?? '',
    params: JSON.stringify(source.params ?? {}, null, 2),
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const [test, setTest] = useState({ origin: 'HRG', destination: 'MOW', date: tomorrowPlus(30) })
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<TestResult | null>(null)

  const proxyKnown = form.proxy === '' || form.proxy === 'direct' || pools.some((p) => p.url === form.proxy)

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      let params: Record<string, unknown>
      try {
        params = JSON.parse(form.params || '{}')
      } catch {
        throw new Error('Параметры — некорректный JSON')
      }
      await api(`/api/sources/${source.name}`, {
        method: 'PATCH',
        body: { ...form, params, proxy: form.proxy },
      })
      setSaved(true)
      onChanged()
    } catch (e) {
      setError(e)
    } finally {
      setSaving(false)
    }
  }

  async function runTest() {
    setTesting(true)
    setResult(null)
    setError(null)
    try {
      setResult(await api<TestResult>(`/api/sources/${source.name}/test`, { method: 'POST', body: test }))
      onChanged()
    } catch (e) {
      setError(e)
    } finally {
      setTesting(false)
    }
  }

  async function reset() {
    try {
      await api(`/api/sources/${source.name}/reset`, { method: 'POST' })
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  const s = source.stats_24h
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-lg font-semibold">{source.title}</div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <span>{source.name}</span>
            <StatusBadge status={source.status} />
          </div>
        </div>
        <button onClick={onClose} className="rounded p-1 text-muted hover:bg-panel-2 hover:text-ink" title="Закрыть">
          <X size={18} />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-lg bg-panel-2 p-2"><div className="text-muted">запросов</div><div className="text-base font-semibold">{s.requests}</div></div>
        <div className="rounded-lg bg-panel-2 p-2"><div className="text-muted">ошибок</div><div className="text-base font-semibold">{Math.round(s.error_rate * 100)}%</div></div>
        <div className="rounded-lg bg-panel-2 p-2"><div className="text-muted">p95</div><div className="text-base font-semibold">{(s.latency_p95_ms / 1000).toFixed(1)} с</div></div>
      </div>

      {(source.status === 'down' || source.consecutive_failures > 0) && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
          <div className="font-medium text-warn">
            {source.status === 'down' ? `Отключён до ${new Date(source.disabled_until!).toLocaleTimeString('ru-RU')}` : `Ошибок подряд: ${source.consecutive_failures}`}
          </div>
          {source.last_error && <div className="mt-1 break-words text-xs text-muted">{ago(source.last_error_at)}: {source.last_error}</div>}
          <Button variant="ghost" className="mt-2" onClick={reset}><RotateCcw size={14} /> Сбросить и включить</Button>
        </div>
      )}

      <Card title="Настройки">
        <div className="space-y-3">
          <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label={form.enabled ? 'Включён' : 'Выключен'} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Приоритет" hint="меньше — раньше">
              <Input type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} />
            </Field>
            <Field label="Запросов в минуту" hint="0 — без лимита">
              <Input type="number" min={0} value={form.rate_limit_per_min} onChange={(e) => setForm({ ...form, rate_limit_per_min: Number(e.target.value) })} />
            </Field>
            <Field label="Таймаут, с">
              <Input type="number" min={1} value={form.timeout_s} onChange={(e) => setForm({ ...form, timeout_s: Number(e.target.value) })} />
            </Field>
            <Field label="Повторы при ошибке">
              <Input type="number" min={0} max={5} value={form.retries} onChange={(e) => setForm({ ...form, retries: Number(e.target.value) })} />
            </Field>
          </div>
          <Field label="Прокси">
            <Select value={proxyKnown ? form.proxy : '__custom'} onChange={(e) => setForm({ ...form, proxy: e.target.value === '__custom' ? 'http://' : e.target.value })}>
              <option value="">Глобальный (из .env / системный)</option>
              <option value="direct">Напрямую, мимо системного прокси</option>
              {pools.map((p) => <option key={p.name} value={p.url}>Пул: {p.name}</option>)}
              <option value="__custom">Свой URL…</option>
            </Select>
          </Field>
          {!proxyKnown && (
            <Input value={form.proxy} onChange={(e) => setForm({ ...form, proxy: e.target.value })} placeholder="socks5://user:pass@host:1080" />
          )}
          <Field label="Параметры (JSON)" hint={Object.entries(source.param_schema).map(([k, v]) => `${k} — ${v}`).join('; ') || 'у источника нет параметров'}>
            <textarea
              value={form.params}
              onChange={(e) => setForm({ ...form, params: e.target.value })}
              rows={4}
              className="w-full rounded-lg border border-line bg-bg px-3 py-2 font-mono text-xs outline-none focus:border-accent"
            />
          </Field>
          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={saving}>{saving ? 'Сохраняю…' : 'Сохранить'}</Button>
            {saved && <span className="text-sm text-ok">Сохранено, применяется сразу</span>}
          </div>
        </div>
      </Card>

      <Card title="Тестовый запрос">
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <Field label="Откуда"><Input value={test.origin} onChange={(e) => setTest({ ...test, origin: e.target.value.toUpperCase() })} maxLength={3} /></Field>
            <Field label="Куда"><Input value={test.destination} onChange={(e) => setTest({ ...test, destination: e.target.value.toUpperCase() })} maxLength={3} /></Field>
            <Field label="Дата"><Input type="date" value={test.date} onChange={(e) => setTest({ ...test, date: e.target.value })} /></Field>
          </div>
          <Button variant="ghost" onClick={runTest} disabled={testing}>
            <FlaskConical size={14} /> {testing ? 'Запрашиваю…' : 'Тест'}
          </Button>
          {result && (
            <div className="space-y-2">
              <div className={result.ok ? 'text-sm text-ok' : 'text-sm text-bad'}>
                {result.ok ? `OK: ${result.offers} вариантов за ${result.elapsed_s} с` : `Ошибка за ${result.elapsed_s} с: ${result.error}`}
              </div>
              {result.sample.map((o, i) => (
                <div key={i} className="rounded-lg border border-line px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{rub(o.price_rub)}</span>
                    <a href={o.link} target="_blank" rel="noreferrer" className="text-accent hover:underline" title="Открыть">
                      <ExternalLink size={13} />
                    </a>
                  </div>
                  <div className="text-muted">
                    {new Date(o.departure_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', ...(o.time_known ? { hour: '2-digit', minute: '2-digit' } : {}) })} · {o.route} · {o.flights.join(', ') || '—'}
                    {o.self_transfer ? ' · самост. пересадка' : ''}
                  </div>
                  {o.note && <div className="text-muted/80">{o.note}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
      <ErrorBox error={error} />
    </div>
  )
}
