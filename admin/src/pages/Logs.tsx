import { useState } from 'react'
import { api } from '../api'
import { Card, Empty, ErrorBox, Page, PageHeader, Select, TABLE, cx, fmtTime, rub, useApi } from '../components/ui'

type ErrorRow = { source: string; error: string | null; route: string | null; ms: number; at: string }
type SearchRow = { route: string; dates: string; results: number; min_price: number | null; ms: number; cached: boolean; at: string; user: string }

export default function Logs() {
  const [source, setSource] = useState('')
  const errors = useApi(() => api<ErrorRow[]>(`/api/logs/errors?limit=200${source ? `&source=${source}` : ''}`), [source], 20000)
  const searches = useApi(() => api<SearchRow[]>('/api/logs/searches?limit=200'), [], 20000)
  const names = [...new Set((errors.data ?? []).map((e) => e.source))]

  return (
    <Page>
      <PageHeader title="Журнал" description="Последние поиски пользователей и ошибки источников." />
      <ErrorBox error={errors.error || searches.error} />
      <div className="grid items-start gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card title="Поиски" flush>
          {searches.data?.length === 0 ? (
            <Empty>Поисков ещё не было</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className={TABLE.table}>
                <thead className={TABLE.head}>
                  <tr>
                    <th>Когда</th>
                    <th>Кто</th>
                    <th>Маршрут</th>
                    <th className="text-right">Вариантов</th>
                    <th className="text-right">Минимум</th>
                    <th className="text-right">Время</th>
                  </tr>
                </thead>
                <tbody>
                  {(searches.data ?? []).map((s, i) => (
                    <tr key={i} className={TABLE.row}>
                      <td className="font-mono text-[12px] whitespace-nowrap text-muted">{fmtTime(s.at)}</td>
                      <td className="max-w-32 truncate text-[12px] text-muted">{s.user}</td>
                      <td>
                        <div className="font-medium whitespace-nowrap">{s.route}</div>
                        <div className="text-[12px] whitespace-nowrap text-faint">{s.dates}</div>
                      </td>
                      <td className="text-right tabular-nums">{s.results}</td>
                      <td className="text-right whitespace-nowrap tabular-nums">{rub(s.min_price)}</td>
                      <td className={cx('text-right font-mono text-[12px] whitespace-nowrap', s.cached ? 'text-faint' : 'text-muted')}>
                        {s.cached ? 'кэш' : `${(s.ms / 1000).toFixed(1)} с`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card
          title="Ошибки источников"
          flush
          actions={
            <Select value={source} onChange={(e) => setSource(e.target.value)} className="h-7 w-40 text-[12px]">
              <option value="">Все источники</option>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          }
        >
          {errors.data?.length === 0 ? (
            <Empty>Ошибок нет</Empty>
          ) : (
            <div className="divide-y divide-line">
              {(errors.data ?? []).map((e, i) => (
                <div key={i} className="px-5 py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-mono text-[12px] font-medium text-bad">{e.source}</span>
                    <span className="font-mono text-[11px] whitespace-nowrap text-faint">
                      {fmtTime(e.at)} · {(e.ms / 1000).toFixed(1)} с
                    </span>
                  </div>
                  {e.route && <div className="mt-0.5 text-[12px] text-muted">{e.route}</div>}
                  <div className="mt-1 text-[12px] leading-relaxed break-words text-muted">{e.error}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </Page>
  )
}
