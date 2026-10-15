import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ActivityPoint, SourceInfo, Summary, SystemSample } from '../api'
import { api } from '../api'
import { Button, Card, ErrorBox, Select, Stat, StatusBadge, ago, cx, useApi } from '../components/ui'

const AXIS = { stroke: '#8494b4', fontSize: 11, tickLine: false, axisLine: false }
const GRID = <CartesianGrid stroke="#22304d" strokeDasharray="3 3" vertical={false} />
const TIP = { contentStyle: { background: '#111a2c', border: '1px solid #22304d', borderRadius: 8, fontSize: 12 }, labelStyle: { color: '#e6ecf8' } }
const COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#f472b6', '#a78bfa', '#fb923c', '#22d3ee', '#f87171', '#a3e635']

const hourLabel = (iso: string) => new Date(iso).toLocaleString('ru-RU', { day: '2-digit', hour: '2-digit', minute: '2-digit' })
const timeLabel = (ts: number) => new Date(ts * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

export default function Dashboard() {
  const [hours, setHours] = useState(24)
  const [sysMinutes, setSysMinutes] = useState(60)
  const summary = useApi(() => api<Summary>('/api/dashboard/summary'), [], 15000)
  const activity = useApi(() => api<ActivityPoint[]>(`/api/dashboard/activity?hours=${hours}`), [hours], 30000)
  const latency = useApi(() => api<Record<string, number | string>[]>(`/api/dashboard/latency?hours=${Math.min(hours, 168)}`), [hours], 30000)
  const sources = useApi(() => api<SourceInfo[]>('/api/sources'), [], 15000)
  const system = useApi(() => api<{ info: { cpu_count: number; mem_total_gb: number; uptime_h: number }; series: SystemSample[] }>(`/api/system?minutes=${sysMinutes}`), [sysMinutes], 5000)

  const s = summary.data
  const sourceNames = (sources.data ?? []).map((x) => x.name)
  const last = system.data?.series.at(-1)

  return (
    <div className="space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Дашборд</h1>
          <p className="text-sm text-muted">Состояние системы, нагрузка и активность пользователей. Обновляется автоматически.</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="w-36">
            <option value={6}>за 6 часов</option>
            <option value={24}>за сутки</option>
            <option value={72}>за 3 дня</option>
            <option value={168}>за неделю</option>
            <option value={720}>за месяц</option>
          </Select>
          <Button variant="ghost" onClick={() => [summary, activity, latency, sources, system].forEach((x) => x.reload())} title="Обновить">
            <RefreshCw size={16} />
          </Button>
        </div>
      </header>

      <ErrorBox error={summary.error || activity.error || sources.error} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Пользователи" value={s?.users ?? '—'} hint={s ? `+${s.new_users_24h} за сутки · ${s.blocked} заблок.` : undefined} />
        <Stat label="Активны (сутки / неделя)" value={s ? `${s.dau} / ${s.wau}` : '—'} />
        <Stat label="Активные подписки" value={s?.active_subscriptions ?? '—'} hint={s ? `${s.notifications_24h} уведомлений за сутки` : undefined} />
        <Stat label="Поиски за сутки" value={s?.searches_24h ?? '—'} hint={s?.cache_hit_rate != null ? `из кэша ${Math.round(s.cache_hit_rate * 100)}%` : undefined} />
        <Stat
          label="Запросы к источникам"
          value={s?.source_requests_24h ?? '—'}
          hint={s ? `ошибок: ${s.source_errors_24h}` : undefined}
          tone={s && s.source_requests_24h && s.source_errors_24h / s.source_requests_24h > 0.2 ? 'warn' : undefined}
        />
        <Stat
          label="Источники"
          value={s ? `${s.sources_enabled - s.sources_down.length} / ${s.sources_total}` : '—'}
          hint={s?.sources_down.length ? `отключены: ${s.sources_down.join(', ')}` : 'все включённые работают'}
          tone={s?.sources_down.length ? 'bad' : 'ok'}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Активность">
          <div className="h-64">
            <ResponsiveContainer>
              <AreaChart data={activity.data ?? []}>
                {GRID}
                <XAxis dataKey="ts" tickFormatter={hourLabel} {...AXIS} minTickGap={40} />
                <YAxis {...AXIS} width={36} allowDecimals={false} />
                <Tooltip {...TIP} labelFormatter={(v) => hourLabel(String(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="requests" name="Запросы к источникам" stroke="#38bdf8" fill="#38bdf833" />
                <Area type="monotone" dataKey="searches" name="Поиски" stroke="#34d399" fill="#34d39933" />
                <Area type="monotone" dataKey="errors" name="Ошибки" stroke="#f87171" fill="#f8717133" />
                <Area type="monotone" dataKey="notifications" name="Уведомления" stroke="#fbbf24" fill="#fbbf2422" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Задержка источников, мс (среднее по часам)">
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={latency.data ?? []}>
                {GRID}
                <XAxis dataKey="ts" tickFormatter={hourLabel} {...AXIS} minTickGap={40} />
                <YAxis {...AXIS} width={48} />
                <Tooltip {...TIP} labelFormatter={(v) => hourLabel(String(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {sourceNames.map((n, i) => (
                  <Line key={n} type="monotone" dataKey={n} stroke={COLORS[i % COLORS.length]} dot={false} connectNulls strokeWidth={2} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card
        title="Нагрузка на сервер"
        actions={
          <div className="flex items-center gap-3 text-xs text-muted">
            {system.data && (
              <span>
                {system.data.info.cpu_count} CPU · {system.data.info.mem_total_gb} ГБ · аптайм {system.data.info.uptime_h} ч
              </span>
            )}
            <Select value={sysMinutes} onChange={(e) => setSysMinutes(Number(e.target.value))} className="w-32">
              <option value={15}>15 минут</option>
              <option value={60}>1 час</option>
              <option value={360}>6 часов</option>
              <option value={1440}>сутки</option>
            </Select>
          </div>
        }
      >
        <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="CPU" value={last ? `${last.cpu.toFixed(0)}%` : '—'} tone={last && last.cpu > 85 ? 'bad' : undefined} />
          <Stat label="Память" value={last ? `${last.mem.toFixed(0)}%` : '—'} tone={last && last.mem > 90 ? 'bad' : undefined} />
          <Stat label="Диск" value={last ? `${last.disk.toFixed(0)}%` : '—'} />
          <Stat label="Сеть ↓ / ↑" value={last ? `${fmtKbps(last.net_in_kbps)} / ${fmtKbps(last.net_out_kbps)}` : '—'} />
          <Stat label="Память API" value={last ? `${last.proc_mem_mb} МБ` : '—'} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-48">
            <ResponsiveContainer>
              <LineChart data={system.data?.series ?? []}>
                {GRID}
                <XAxis dataKey="ts" tickFormatter={timeLabel} {...AXIS} minTickGap={40} />
                <YAxis {...AXIS} width={32} domain={[0, 100]} unit="%" />
                <Tooltip {...TIP} labelFormatter={(v) => timeLabel(Number(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="cpu" name="CPU" stroke="#38bdf8" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line dataKey="mem" name="Память" stroke="#a78bfa" dot={false} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="h-48">
            <ResponsiveContainer>
              <AreaChart data={system.data?.series ?? []}>
                {GRID}
                <XAxis dataKey="ts" tickFormatter={timeLabel} {...AXIS} minTickGap={40} />
                <YAxis {...AXIS} width={48} />
                <Tooltip {...TIP} labelFormatter={(v) => timeLabel(Number(v))} formatter={(v) => fmtKbps(Number(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area dataKey="net_in_kbps" name="Входящий трафик" stroke="#34d399" fill="#34d39933" isAnimationActive={false} />
                <Area dataKey="net_out_kbps" name="Исходящий трафик" stroke="#fbbf24" fill="#fbbf2433" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Card>

      <Card title="Источники за сутки">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">Источник</th>
                <th className="py-2 pr-3 font-medium">Статус</th>
                <th className="py-2 pr-3 text-right font-medium">Запросы</th>
                <th className="py-2 pr-3 text-right font-medium">Ошибки</th>
                <th className="py-2 pr-3 text-right font-medium">p50 / p95</th>
                <th className="py-2 pr-3 text-right font-medium">Вариантов в ответе</th>
                <th className="py-2 font-medium">Последняя ошибка</th>
              </tr>
            </thead>
            <tbody>
              {(sources.data ?? []).map((x) => (
                <tr key={x.name} className="border-b border-line/60 last:border-0">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{x.title}</div>
                    <div className="text-xs text-muted">{x.name}</div>
                  </td>
                  <td className="py-2 pr-3"><StatusBadge status={x.status} /></td>
                  <td className="py-2 pr-3 text-right tabular-nums">{x.stats_24h.requests}</td>
                  <td className={cx('py-2 pr-3 text-right tabular-nums', x.stats_24h.error_rate > 0.2 && 'text-bad')}>
                    {x.stats_24h.errors} {x.stats_24h.requests ? `(${Math.round(x.stats_24h.error_rate * 100)}%)` : ''}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {x.stats_24h.requests ? `${(x.stats_24h.latency_p50_ms / 1000).toFixed(1)} / ${(x.stats_24h.latency_p95_ms / 1000).toFixed(1)} с` : '—'}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{x.stats_24h.avg_offers || '—'}</td>
                  <td className="max-w-xs truncate py-2 text-xs text-muted" title={x.last_error ?? ''}>
                    {x.last_error ? `${ago(x.last_error_at)}: ${x.last_error}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 h-48">
          <ResponsiveContainer>
            <BarChart data={(sources.data ?? []).map((x) => ({ name: x.title, ok: x.stats_24h.requests - x.stats_24h.errors, errors: x.stats_24h.errors }))}>
              {GRID}
              <XAxis dataKey="name" {...AXIS} interval={0} fontSize={10} />
              <YAxis {...AXIS} width={36} allowDecimals={false} />
              <Tooltip {...TIP} />
              <Bar dataKey="ok" name="Успешно" stackId="a" fill="#34d399" />
              <Bar dataKey="errors" name="Ошибки" stackId="a" fill="#f87171" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  )
}

function fmtKbps(v: number) {
  return v >= 1024 ? `${(v / 1024).toFixed(1)} Мбит/с` : `${v.toFixed(0)} Кбит/с`
}
