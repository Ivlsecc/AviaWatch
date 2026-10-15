import { useState } from 'react'
import { api } from '../api'
import { Card, Empty, ErrorBox, Select, cx, fmtTime, rub, useApi } from '../components/ui'

type ErrorRow = { source: string; error: string | null; route: string | null; ms: number; at: string }
type SearchRow = { route: string; dates: string; results: number; min_price: number | null; ms: number; cached: boolean; at: string; user: string }

export default function Logs() {
  const [source, setSource] = useState('')
  const errors = useApi(() => api<ErrorRow[]>(`/api/logs/errors?limit=200${source ? `&source=${source}` : ''}`), [source], 20000)
  const searches = useApi(() => api<SearchRow[]>('/api/logs/searches?limit=200'), [], 20000)
  const names = [...new Set((errors.data ?? []).map((e) => e.source))]

  return (
    <div className="space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-xl font-semibold">Логи</h1>
        <p className="text-sm text-muted">Ошибки источников и последние поиски пользователей.</p>
      </header>
      <ErrorBox error={errors.error || searches.error} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card
          title="Ошибки источников"
          actions={
            <Select value={source} onChange={(e) => setSource(e.target.value)} className="w-44">
              <option value="">Все источники</option>
              {names.map((n) => <option key={n} value={n}>{n}</option>)}
            </Select>
          }
        >
          {errors.data?.length === 0 && <Empty>Ошибок нет 🎉</Empty>}
          <div className="space-y-2">
            {(errors.data ?? []).map((e, i) => (
              <div key={i} className="rounded-lg border border-line px-3 py-2 text-xs">
                <div className="flex justify-between gap-2">
                  <span className="font-medium text-bad">{e.source}</span>
                  <span className="text-muted">{fmtTime(e.at)} · {e.route ?? '—'} · {(e.ms / 1000).toFixed(1)} с</span>
                </div>
                <div className="mt-1 break-words text-muted">{e.error}</div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Поиски">
          {searches.data?.length === 0 && <Empty>Поисков ещё не было</Empty>}
          <table className="w-full text-xs">
            <tbody>
              {(searches.data ?? []).map((s, i) => (
                <tr key={i} className="border-b border-line/60 last:border-0">
                  <td className="py-1.5 pr-2 text-muted">{fmtTime(s.at)}</td>
                  <td className="py-1.5 pr-2">{s.user}</td>
                  <td className="py-1.5 pr-2 font-medium">{s.route}</td>
                  <td className="py-1.5 pr-2 text-muted">{s.dates}</td>
                  <td className="py-1.5 pr-2 text-right">{s.results}</td>
                  <td className="py-1.5 pr-2 text-right">{rub(s.min_price)}</td>
                  <td className={cx('py-1.5 text-right', s.cached ? 'text-muted' : '')}>{s.cached ? 'кэш' : `${(s.ms / 1000).toFixed(1)} с`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
