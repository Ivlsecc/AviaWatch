import { Ban, Search, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { UserDetail, UserRow } from '../api'
import { api } from '../api'
import { Button, Card, Empty, ErrorBox, Input, Toggle, ago, cx, fmtTime, rub, useApi } from '../components/ui'

export default function UsersPage() {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState<number | null>(null)
  const list = useApi(() => api<{ total: number; items: UserRow[] }>(`/api/users?q=${encodeURIComponent(query)}&page=${page}&size=50`), [query, page], 30000)

  useEffect(() => {
    const id = setTimeout(() => {
      setPage(1)
      setQuery(q)
    }, 300)
    return () => clearTimeout(id)
  }, [q])

  const total = list.data?.total ?? 0
  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1 space-y-4 overflow-y-auto p-4 md:p-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">Пользователи</h1>
            <p className="text-sm text-muted">Всего: {total}. Нажмите на пользователя, чтобы увидеть его подписки и поиски.</p>
          </div>
          <div className="relative w-72">
            <Search size={14} className="absolute top-2.5 left-3 text-muted" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Имя, @username или Telegram ID" className="pl-8" />
          </div>
        </header>
        <ErrorBox error={list.error} />
        <Card>
          {list.data && list.data.items.length === 0 ? (
            <Empty>Никого не нашлось</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-medium">Пользователь</th>
                    <th className="py-2 pr-3 font-medium">Telegram ID</th>
                    <th className="py-2 pr-3 text-right font-medium">Подписки</th>
                    <th className="py-2 pr-3 text-right font-medium">Поиски</th>
                    <th className="py-2 pr-3 font-medium">Был</th>
                    <th className="py-2 pr-3 font-medium">С нами с</th>
                    <th className="py-2 font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {(list.data?.items ?? []).map((u) => (
                    <tr
                      key={u.id}
                      onClick={() => setOpenId(u.id)}
                      className={cx('cursor-pointer border-b border-line/60 last:border-0 hover:bg-panel-2', openId === u.id && 'bg-panel-2')}
                    >
                      <td className="py-2 pr-3">
                        <div className="font-medium">{u.first_name || '—'}</div>
                        <div className="text-xs text-muted">{u.username ? `@${u.username}` : 'без username'}</div>
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs">{u.tg_id}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{u.subscriptions} / {u.max_subscriptions}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{u.searches}</td>
                      <td className="py-2 pr-3 text-xs text-muted">{ago(u.last_seen_at)}</td>
                      <td className="py-2 pr-3 text-xs text-muted">{fmtTime(u.created_at)}</td>
                      <td className="py-2">{u.is_blocked ? <span className="text-xs text-bad">заблокирован</span> : <span className="text-xs text-ok">активен</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {total > 50 && (
            <div className="mt-3 flex items-center justify-end gap-2 text-sm">
              <Button variant="ghost" disabled={page === 1} onClick={() => setPage(page - 1)}>Назад</Button>
              <span className="text-muted">стр. {page} из {Math.ceil(total / 50)}</span>
              <Button variant="ghost" disabled={page * 50 >= total} onClick={() => setPage(page + 1)}>Дальше</Button>
            </div>
          )}
        </Card>
      </div>
      {openId != null && <UserDrawer id={openId} onClose={() => setOpenId(null)} onChanged={() => list.reload()} />}
    </div>
  )
}

function UserDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const detail = useApi(() => api<UserDetail>(`/api/users/${id}`), [id])
  const [error, setError] = useState<unknown>(null)
  const [limit, setLimit] = useState<number | null>(null)
  const d = detail.data

  async function patchUser(body: Record<string, unknown>) {
    try {
      await api(`/api/users/${id}`, { method: 'PATCH', body })
      await detail.reload()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  async function patchSub(subId: number, body: Record<string, unknown>) {
    try {
      await api(`/api/subscriptions/${subId}`, { method: 'PATCH', body })
      await detail.reload()
    } catch (e) {
      setError(e)
    }
  }

  async function deleteSub(subId: number) {
    if (!confirm('Удалить подписку? Пользователь перестанет получать уведомления по этому маршруту.')) return
    try {
      await api(`/api/subscriptions/${subId}`, { method: 'DELETE' })
      await detail.reload()
      onChanged()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <aside className="w-[420px] shrink-0 space-y-4 overflow-y-auto border-l border-line bg-panel p-4 max-lg:fixed max-lg:inset-0 max-lg:z-20 max-lg:w-full">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-lg font-semibold">{d?.user.first_name || 'Пользователь'}</div>
          <div className="text-xs text-muted">{d?.user.username ? `@${d.user.username} · ` : ''}ID {d?.user.tg_id}</div>
        </div>
        <button onClick={onClose} className="rounded p-1 text-muted hover:bg-panel-2 hover:text-ink"><X size={18} /></button>
      </div>
      <ErrorBox error={error || detail.error} />
      {d && (
        <>
          <Card title="Управление">
            <div className="space-y-3">
              <Button variant={d.user.is_blocked ? 'ghost' : 'danger'} onClick={() => patchUser({ is_blocked: !d.user.is_blocked })}>
                <Ban size={14} /> {d.user.is_blocked ? 'Разблокировать' : 'Заблокировать'}
              </Button>
              <div className="flex items-end gap-2">
                <label className="flex-1">
                  <span className="mb-1 block text-xs text-muted">Лимит подписок</span>
                  <Input type="number" min={0} value={limit ?? d.user.max_subscriptions} onChange={(e) => setLimit(Number(e.target.value))} />
                </label>
                <Button variant="ghost" disabled={limit == null || limit === d.user.max_subscriptions} onClick={() => patchUser({ max_subscriptions: limit })}>
                  Сохранить
                </Button>
              </div>
            </div>
          </Card>

          <Card title={`Подписки (${d.subscriptions.length})`}>
            {d.subscriptions.length === 0 && <Empty>Подписок нет</Empty>}
            <div className="space-y-2">
              {d.subscriptions.map((s) => (
                <div key={s.id} className="rounded-lg border border-line p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium">{s.origin_name || s.origin} → {s.destination_name || s.destination}</div>
                    <button onClick={() => deleteSub(s.id)} className="text-muted hover:text-bad" title="Удалить"><Trash2 size={14} /></button>
                  </div>
                  <div className="text-xs text-muted">
                    {s.date_from === s.date_to ? s.date_from : `${s.date_from} … ${s.date_to}`} · {s.adults} взр. · минимум {rub(s.last_min_price)}
                    {s.threshold_rub ? ` · порог ${rub(s.threshold_rub)}` : ''}
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted">
                    <span>проверено {ago(s.last_checked_at)} · уведомлён {ago(s.last_notified_at)}</span>
                    <Toggle checked={s.is_active} onChange={(v) => patchSub(s.id, { is_active: v })} />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Последние поиски">
            {d.searches.length === 0 && <Empty>Поисков не было</Empty>}
            <div className="space-y-1">
              {d.searches.map((x, i) => (
                <div key={i} className="flex justify-between gap-2 text-xs">
                  <span>{x.route} · {x.dates}</span>
                  <span className="text-muted">{rub(x.min_price)} · {fmtTime(x.at)}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Уведомления">
            {d.notifications.length === 0 && <Empty>Не отправлялись</Empty>}
            <div className="space-y-1">
              {d.notifications.map((n, i) => (
                <div key={i} className="flex justify-between gap-2 text-xs">
                  <span className={n.ok ? '' : 'text-bad'}>{n.kind}{n.ok ? '' : ' (не доставлено)'}</span>
                  <span className="text-muted">{rub(n.price)} · {fmtTime(n.at)}</span>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </aside>
  )
}
