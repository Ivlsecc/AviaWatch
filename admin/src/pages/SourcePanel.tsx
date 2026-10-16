import { ArrowUpRight, FlaskConical, RotateCcw, X } from 'lucide-react'
import { useState } from 'react'
import type { AppSettings, SourceInfo, TestResult } from '../api'
import { api } from '../api'
import { Button, CodeArea, ErrorBox, Field, Input, Notice, Section, Select, StatusBadge, Toggle, ago, rub } from '../components/ui'

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
    <div>
      <div className="flex items-start justify-between gap-2 border-b border-line px-5 py-5">
        <div className="min-w-0">
          <div className="text-[16px] font-semibold tracking-tight">{source.title}</div>
          <div className="mt-1 flex items-center gap-3">
            <span className="font-mono text-[11px] text-faint">{source.name}</span>
            <StatusBadge status={source.status} />
          </div>
        </div>
        <Button variant="quiet" size="sm" onClick={onClose} title="Закрыть">
          <X size={15} />
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-px border-b border-line bg-line">
        {[
          ['запросов за сутки', String(s.requests)],
          ['с ошибкой', `${Math.round(s.error_rate * 100)}%`],
          ['ответ, p95', s.requests ? `${(s.latency_p95_ms / 1000).toFixed(1)} с` : '—'],
        ].map(([label, value]) => (
          <div key={label} className="bg-panel px-5 py-3">
            <div className="text-[18px] font-medium tabular-nums">{value}</div>
            <div className="text-[11px] text-faint">{label}</div>
          </div>
        ))}
      </div>

      {(source.status === 'down' || source.consecutive_failures > 0) && (
        <div className="border-b border-line px-5 py-4">
          <Notice>
            <div className="font-medium text-warn">
              {source.status === 'down' ? `Отключён до ${new Date(source.disabled_until!).toLocaleTimeString('ru-RU')}` : `Ошибок подряд: ${source.consecutive_failures}`}
            </div>
            {source.last_error && <div className="mt-1 text-[12px] break-words text-muted">{ago(source.last_error_at)}: {source.last_error}</div>}
            <Button variant="ghost" size="sm" className="mt-2.5" onClick={reset}>
              <RotateCcw size={13} /> Сбросить и включить
            </Button>
          </Notice>
        </div>
      )}

      <Section title="Настройки">
        <div className="space-y-4">
          <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label={form.enabled ? 'Участвует в поиске' : 'Выключен'} />
          <div className="grid grid-cols-2 gap-x-3 gap-y-4">
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
              {pools.map((p) => (
                <option key={p.name} value={p.url}>
                  Пул: {p.name}
                </option>
              ))}
              <option value="__custom">Свой адрес…</option>
            </Select>
          </Field>
          {!proxyKnown && <Input value={form.proxy} onChange={(e) => setForm({ ...form, proxy: e.target.value })} placeholder="socks5://user:pass@host:1080" className="font-mono" />}
          <Field
            label="Параметры, JSON"
            hint={
              Object.entries(source.param_schema)
                .map(([k, v]) => `${k} — ${v}`)
                .join('; ') || 'У источника нет параметров'
            }
          >
            <CodeArea value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })} rows={4} />
          </Field>
          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={saving}>
              {saving ? 'Сохраняю…' : 'Сохранить'}
            </Button>
            {saved && <span className="text-[12px] text-muted">Сохранено, применяется сразу</span>}
          </div>
        </div>
      </Section>

      <Section title="Проверка">
        <div className="space-y-3">
          <div className="grid grid-cols-[1fr_1fr_1.6fr] gap-2">
            <Field label="Откуда">
              <Input value={test.origin} onChange={(e) => setTest({ ...test, origin: e.target.value.toUpperCase() })} maxLength={3} className="font-mono" />
            </Field>
            <Field label="Куда">
              <Input value={test.destination} onChange={(e) => setTest({ ...test, destination: e.target.value.toUpperCase() })} maxLength={3} className="font-mono" />
            </Field>
            <Field label="Дата">
              <Input type="date" value={test.date} onChange={(e) => setTest({ ...test, date: e.target.value })} />
            </Field>
          </div>
          <Button variant="ghost" onClick={runTest} disabled={testing}>
            <FlaskConical size={14} strokeWidth={1.75} /> {testing ? 'Запрашиваю…' : 'Проверить'}
          </Button>
          {result && (
            <div className="space-y-2 pt-1">
              <div className={result.ok ? 'text-[13px] text-ok' : 'text-[13px] text-bad'}>
                {result.ok ? `${result.offers} вариантов за ${result.elapsed_s} с` : `Ошибка за ${result.elapsed_s} с: ${result.error}`}
              </div>
              <div className="divide-y divide-line rounded-lg border border-line">
                {result.sample.map((o, i) => (
                  <a key={i} href={o.link} target="_blank" rel="noreferrer" className="group block px-3 py-2 transition-colors hover:bg-panel-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium tabular-nums">{rub(o.price_rub)}</span>
                      <ArrowUpRight size={13} className="text-faint group-hover:text-ink" />
                    </div>
                    <div className="text-[12px] text-muted">
                      {new Date(o.departure_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', ...(o.time_known ? { hour: '2-digit', minute: '2-digit' } : {}) })} · {o.route} ·{' '}
                      <span className="font-mono text-[11px]">{o.flights.join(', ') || '—'}</span>
                      {o.self_transfer ? ' · самост. пересадка' : ''}
                    </div>
                    {o.note && <div className="text-[12px] text-faint">{o.note}</div>}
                  </a>
                ))}
              </div>
            </div>
          )}
          <ErrorBox error={error} />
        </div>
      </Section>
    </div>
  )
}
