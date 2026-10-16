import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ActivityPoint, SourceInfo, Summary, SystemSample } from '../api'
import { api } from '../api'
import { Button, Card, Dot, ErrorBox, Page, PageHeader, SERIES, Stat, StatRow, StatusBadge, TABLE, ago, cx, usePalette, useApi } from '../components/ui'

const hourLabel = (iso: string) => new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
const shortHour = (iso: string) => new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
const timeLabel = (ts: number) => new Date(ts * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })

const PERIODS: [number, string][] = [
  [6, '6 ч'],
  [24, 'Сутки'],
  [72, '3 дня'],
  [168, 'Неделя'],
  [720, 'Месяц'],
]

function useChart() {
  const p = usePalette()
  return {
    p,
    axis: { stroke: p.faint, fontSize: 11, tickLine: false, axisLine: false, fontFamily: 'Geist Mono Variable, monospace' },
    grid: <CartesianGrid stroke={p.line} vertical={false} />,
    tip: {
      contentStyle: { background: p.surface, border: `1px solid ${p.line}`, borderRadius: 8, fontSize: 12, boxShadow: '0 4px 16px rgb(0 0 0 / 0.06)', padding: '8px 10px' },
      labelStyle: { color: p.muted, marginBottom: 4 },
      itemStyle: { color: p.ink, padding: 0 },
      cursor: { stroke: p.line, strokeWidth: 1 },
    },
  }
}

/** Легенда строкой в шапке раздела — вместо стандартной легенды под графиком. */
function Legend({ items }: { items: [string, string, boolean?][] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
      {items.map(([label, color, dashed]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <span className={cx('h-0 w-3 border-t-2', dashed && 'border-dashed')} style={{ borderColor: color }} />
          {label}
        </span>
      ))}
    </div>
  )
}

function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="flex rounded-lg border border-line bg-panel p-0.5">
      {options.map(([v, label]) => (
        <button
          key={String(v)}
          type="button"
          onClick={() => onChange(v)}
          className={cx('h-7 rounded-md px-2.5 text-[12px] whitespace-nowrap transition-colors', v === value ? 'bg-panel-2 font-medium text-ink' : 'text-muted hover:text-ink')}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [hours, setHours] = useState(24)
  const [sysMinutes, setSysMinutes] = useState(60)
  const summary = useApi(() => api<Summary>('/api/dashboard/summary'), [], 15000)
  const activity = useApi(() => api<ActivityPoint[]>(`/api/dashboard/activity?hours=${hours}`), [hours], 30000)
  const latency = useApi(() => api<Record<string, number | string>[]>(`/api/dashboard/latency?hours=${Math.min(hours, 168)}`), [hours], 30000)
  const sources = useApi(() => api<SourceInfo[]>('/api/sources'), [], 15000)
  const system = useApi(() => api<{ info: { cpu_count: number; mem_total_gb: number; uptime_h: number }; series: SystemSample[] }>(`/api/system?minutes=${sysMinutes}`), [sysMinutes], 5000)
  const { p, axis, grid, tip } = useChart()

  const s = summary.data
  const list = sources.data ?? []
  const last = system.data?.series.at(-1)
  const tick = hours <= 24 ? shortHour : hourLabel
  const errorShare = s && s.source_requests_24h ? s.source_errors_24h / s.source_requests_24h : 0

  return (
    <Page>
      <PageHeader
        title="Обзор"
        description="Пользователи, нагрузка на источники и сервер. Данные обновляются сами."
        actions={
          <>
            <Segmented value={hours} options={PERIODS} onChange={setHours} />
            <Button variant="quiet" onClick={() => [summary, activity, latency, sources, system].forEach((x) => x.reload())} title="Обновить сейчас">
              <RefreshCw size={14} strokeWidth={1.75} />
            </Button>
          </>
        }
      />

      <ErrorBox error={summary.error || activity.error || sources.error} />

      <StatRow className="grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Пользователи" value={s?.users ?? '—'} hint={s ? `+${s.new_users_24h} за сутки${s.blocked ? ` · ${s.blocked} заблок.` : ''}` : undefined} />
        <Stat label="Активны, сутки / неделя" value={s ? `${s.dau} / ${s.wau}` : '—'} />
        <Stat label="Подписки" value={s?.active_subscriptions ?? '—'} hint={s ? `${s.notifications_24h} уведомлений за сутки` : undefined} />
        <Stat label="Поиски за сутки" value={s?.searches_24h ?? '—'} hint={s?.cache_hit_rate != null ? `${Math.round(s.cache_hit_rate * 100)}% из кэша` : undefined} />
        <Stat
          label="Запросы к сайтам"
          value={s?.source_requests_24h ?? '—'}
          hint={s ? (s.source_errors_24h ? `${s.source_errors_24h} с ошибкой` : 'без ошибок') : undefined}
          tone={errorShare > 0.2 ? 'warn' : undefined}
        />
        <Stat
          label="Источники в работе"
          value={s ? `${s.sources_enabled - s.sources_down.length} из ${s.sources_total}` : '—'}
          hint={s?.sources_down.length ? `отключены: ${s.sources_down.join(', ')}` : 'все включённые отвечают'}
          tone={s?.sources_down.length ? 'bad' : undefined}
        />
      </StatRow>

      <div className="grid gap-6 xl:grid-cols-2">
        <Chart
          title="Активность"
          legend={<Legend items={[['поиски', p.accent], ['запросы к сайтам', p.ink], ['уведомления', p.faint, true], ['ошибки', p.bad, true]]} />}
        >
          <AreaChart data={activity.data ?? []} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
            <defs>
              <linearGradient id="fill-req" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={p.ink} stopOpacity={0.06} />
                <stop offset="100%" stopColor={p.ink} stopOpacity={0} />
              </linearGradient>
            </defs>
            {grid}
            <XAxis dataKey="ts" tickFormatter={tick} {...axis} minTickGap={48} />
            <YAxis {...axis} width={40} allowDecimals={false} />
            <Tooltip {...tip} labelFormatter={(v) => hourLabel(String(v))} />
            <Area type="monotone" dataKey="requests" name="Запросы к сайтам" stroke={p.ink} strokeWidth={1.25} fill="url(#fill-req)" isAnimationActive={false} />
            <Area type="monotone" dataKey="searches" name="Поиски" stroke={p.accent} strokeWidth={1.75} fill="none" isAnimationActive={false} />
            <Area type="monotone" dataKey="errors" name="Ошибки" stroke={p.bad} strokeWidth={1.75} strokeDasharray="1 3" strokeLinecap="round" fill="none" isAnimationActive={false} />
            <Area type="monotone" dataKey="notifications" name="Уведомления" stroke={p.faint} strokeWidth={1.5} strokeDasharray="4 3" fill="none" isAnimationActive={false} />
          </AreaChart>
        </Chart>

        <Chart title="Время ответа источников, мс" legend={<Legend items={list.map((x, i) => [x.title, SERIES[i % SERIES.length]] as [string, string])} />}>
          <LineChart data={latency.data ?? []} margin={{ top: 4, right: 4, left: -4, bottom: 0 }}>
            {grid}
            <XAxis dataKey="ts" tickFormatter={tick} {...axis} minTickGap={48} />
            <YAxis {...axis} width={48} />
            <Tooltip {...tip} labelFormatter={(v) => hourLabel(String(v))} />
            {list.map((x, i) => (
              <Line key={x.name} type="monotone" dataKey={x.name} name={x.title} stroke={SERIES[i % SERIES.length]} dot={false} connectNulls strokeWidth={1.5} isAnimationActive={false} />
            ))}
          </LineChart>
        </Chart>
      </div>

      <Card
        title="Сервер"
        actions={
          <div className="flex items-center gap-4">
            {system.data && (
              <span className="text-[12px] text-faint max-md:hidden">
                {system.data.info.cpu_count} CPU · {system.data.info.mem_total_gb} ГБ · работает {system.data.info.uptime_h} ч
              </span>
            )}
            <Segmented value={sysMinutes} options={[[15, '15 мин'], [60, 'Час'], [360, '6 ч'], [1440, 'Сутки']]} onChange={setSysMinutes} />
          </div>
        }
        flush
      >
        <div className="grid grid-cols-2 gap-px border-b border-line bg-line md:grid-cols-5">
          <Stat label="Процессор" value={last ? `${last.cpu.toFixed(0)}%` : '—'} tone={last && last.cpu > 85 ? 'bad' : undefined} />
          <Stat label="Память" value={last ? `${last.mem.toFixed(0)}%` : '—'} tone={last && last.mem > 90 ? 'bad' : undefined} />
          <Stat label="Диск" value={last ? `${last.disk.toFixed(0)}%` : '—'} />
          <Stat
            label="Сеть, приём / отдача, Кбит/с"
            value={last ? `${Math.round(last.net_in_kbps)} / ${Math.round(last.net_out_kbps)}` : '—'}
          />
          <Stat label="Память API" value={last ? `${last.proc_mem_mb} МБ` : '—'} />
        </div>
        <div className="grid gap-6 p-5 lg:grid-cols-2">
          <div>
            <div className="mb-3">
              <Legend items={[['процессор', p.accent], ['память', p.ink]]} />
            </div>
            <div className="h-44">
              <ResponsiveContainer>
                <LineChart data={system.data?.series ?? []} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
                  {grid}
                  <XAxis dataKey="ts" tickFormatter={timeLabel} {...axis} minTickGap={48} />
                  <YAxis {...axis} width={40} domain={[0, 100]} unit="%" />
                  <Tooltip {...tip} labelFormatter={(v) => timeLabel(Number(v))} formatter={(v) => `${Number(v).toFixed(0)}%`} />
                  <Line dataKey="cpu" name="Процессор" stroke={p.accent} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  <Line dataKey="mem" name="Память" stroke={p.ink} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div>
            <div className="mb-3">
              <Legend items={[['приём', p.accent], ['отдача', p.faint, true]]} />
            </div>
            <div className="h-44">
              <ResponsiveContainer>
                <LineChart data={system.data?.series ?? []} margin={{ top: 4, right: 4, left: -4, bottom: 0 }}>
                  {grid}
                  <XAxis dataKey="ts" tickFormatter={timeLabel} {...axis} minTickGap={48} />
                  <YAxis {...axis} width={48} />
                  <Tooltip {...tip} labelFormatter={(v) => timeLabel(Number(v))} formatter={(v) => fmtKbps(Number(v))} />
                  <Line dataKey="net_in_kbps" name="Приём" stroke={p.accent} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  <Line dataKey="net_out_kbps" name="Отдача" stroke={p.faint} strokeDasharray="4 3" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </Card>

      <Card title="Источники за сутки" flush>
        <div className="overflow-x-auto">
          <table className={TABLE.table}>
            <thead className={TABLE.head}>
              <tr>
                <th>Источник</th>
                <th>Состояние</th>
                <th className="w-48">Запросы</th>
                <th className="text-right">Ответ, p50 / p95</th>
                <th className="text-right">Вариантов</th>
                <th>Последняя ошибка</th>
              </tr>
            </thead>
            <tbody>
              {list.map((x) => {
                const st = x.stats_24h
                const okShare = st.requests ? (st.requests - st.errors) / st.requests : 0
                return (
                  <tr key={x.name} className={TABLE.row}>
                    <td>
                      <div className="font-medium">{x.title}</div>
                      <div className="font-mono text-[11px] text-faint">{x.name}</div>
                    </td>
                    <td>
                      <StatusBadge status={x.status} />
                    </td>
                    <td>
                      <div className="flex items-center gap-3">
                        <span className="w-10 text-right tabular-nums">{st.requests}</span>
                        <span className="relative h-1 flex-1 overflow-hidden rounded-full bg-panel-2" title={`${st.errors} с ошибкой`}>
                          {st.requests > 0 && (
                            <>
                              <span className="absolute inset-y-0 left-0 bg-ink/70" style={{ width: `${okShare * 100}%` }} />
                              <span className="absolute inset-y-0 bg-bad" style={{ left: `${okShare * 100}%`, right: 0 }} />
                            </>
                          )}
                        </span>
                        <span className={cx('w-9 text-right text-[12px] tabular-nums', st.error_rate > 0.2 ? 'text-bad' : 'text-faint')}>
                          {st.requests ? `${Math.round(st.error_rate * 100)}%` : ''}
                        </span>
                      </div>
                    </td>
                    <td className="text-right font-mono text-[12px] whitespace-nowrap">
                      {st.requests ? `${(st.latency_p50_ms / 1000).toFixed(1)} / ${(st.latency_p95_ms / 1000).toFixed(1)} с` : <span className="text-faint">—</span>}
                    </td>
                    <td className="text-right tabular-nums">{st.avg_offers ? Math.round(st.avg_offers).toLocaleString('ru-RU') : <span className="text-faint">—</span>}</td>
                    <td className="max-w-xs truncate text-[12px] text-muted" title={x.last_error ?? ''}>
                      {x.last_error ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Dot tone="bad" />
                          {ago(x.last_error_at)}: {x.last_error}
                        </span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </Page>
  )
}

function Chart({ title, legend, children }: { title: string; legend?: ReactNode; children: React.ReactElement }) {
  return (
    <Card title={title}>
      {legend && <div className="mb-4">{legend}</div>}
      <div className="h-60">
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </Card>
  )
}

function fmtKbps(v: number) {
  return v >= 1024 ? `${(v / 1024).toFixed(1)} Мбит/с` : `${v.toFixed(0)} Кбит/с`
}
