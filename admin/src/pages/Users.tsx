import { Ban, Search, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { UserDetail, UserRow } from '../api'
import { api } from '../api'
import { Button, Card, Dot, Empty, ErrorBox, Input, Page, PageHeader, Section, TABLE, Toggle, ago, cx, fmtTime, rub, useApi } from '../components/ui'

function Avatar({ name }: { name: string }) {
  return (
    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-panel-2 text-[12px] font-medium text-muted">
      {(name.trim()[0] ?? '?').toUpperCase()}
    </span>
  )
}

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
      <div className="min-w-0 flex-1 overflow-y-auto">
        <Page>
          <PageHeader
            title="Пользователи"
            description={`Всего ${total}. Откройте пользователя, чтобы посмотреть подписки и историю поисков.`}
            actions={
              <div className="relative w-72 max-md:w-full">
                <Search size={14} className="absolute top-2 left-2.5 text-faint" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Имя, @username или Telegram ID" className="pl-8" />
              </div>
            }
          />
          <ErrorBox error={list.error} />
          <Card flush>
            {list.data && list.data.items.length === 0 ? (
              <Empty>Никого не нашлось</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className={TABLE.table}>
                  <thead className={TABLE.head}>
                    <tr>
                      <th>Пользователь</th>
                      <th>Telegram ID</th>
                      <th className="text-right">Подписки</th>
                      <th className="text-right">Поиски</th>
                      <th>Был</th>
                      <th>С нами с</th>
                      <th>Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(list.data?.items ?? []).map((u) => (
                      <tr
                        key={u.id}
                        onClick={() => setOpenId(u.id)}
                        className={cx(TABLE.row, 'cursor-pointer transition-colors hover:bg-panel-2/60', openId === u.id && 'bg-panel-2')}
                      >
                        <td>
                          <div className="flex items-center gap-2.5">
                            <Avatar name={u.first_name || u.username || '?'} />
                            <div className="min-w-0">
                              <div className="truncate font-medium">{u.first_name || '—'}</div>
                              <div className="truncate text-[12px] text-faint">{u.username ? `@${u.username}` : 'без username'}</div>
                            </div>
                          </div>
                        </td>
                        <td className="font-mono text-[12px] text-muted">{u.tg_id}</td>
                        <td className="text-right tabular-nums">
                          {u.subscriptions}
                          <span className="text-faint"> / {u.max_subscriptions}</span>
                        </td>
                        <td className="text-right tabular-nums">{u.searches}</td>
                        <td className="text-[12px] whitespace-nowrap text-muted">{ago(u.last_seen_at)}</td>
                        <td className="text-[12px] whitespace-nowrap text-muted">{fmtTime(u.created_at)}</td>
                        <td>
                          <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
                            <Dot tone={u.is_blocked ? 'bad' : 'ok'} />
                            {u.is_blocked ? 'заблокирован' : 'активен'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {total > 50 && (
              <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3 text-[12px]">
                <Button variant="ghost" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>
                  Назад
                </Button>
                <span className="text-muted tabular-nums">
                  {page} из {Math.ceil(total / 50)}
                </span>
                <Button variant="ghost" size="sm" disabled={page * 50 >= total} onClick={() => setPage(page + 1)}>
                  Дальше
                </Button>
              </div>
            )}
          </Card>
        </Page>
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
    <aside className="w-[400px] shrink-0 overflow-y-auto border-l border-line bg-panel max-lg:fixed max-lg:inset-0 max-lg:z-20 max-lg:w-full">
      <div className="flex items-start justify-between gap-2 border-b border-line px-5 py-5">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={d?.user.first_name || d?.user.username || '?'} />
          <div className="min-w-0">
            <div className="truncate text-[16px] font-semibold tracking-tight">{d?.user.first_name || 'Пользователь'}</div>
            <div className="truncate text-[12px] text-faint">
              {d?.user.username ? `@${d.user.username} · ` : ''}
              <span className="font-mono">{d?.user.tg_id}</span>
            </div>
          </div>
        </div>
        <Button variant="quiet" size="sm" onClick={onClose} title="Закрыть">
          <X size={15} />
        </Button>
      </div>
      {Boolean(error || detail.error) && (
        <div className="px-5 pt-4">
          <ErrorBox error={error || detail.error} />
        </div>
      )}
      {d && (
        <>
          <Section title="Доступ">
            <div className="space-y-4">
              <div className="flex items-end gap-2">
                <label className="flex-1">
                  <span className="mb-1.5 block text-[12px] font-medium text-muted">Лимит подписок</span>
                  <Input type="number" min={0} value={limit ?? d.user.max_subscriptions} onChange={(e) => setLimit(Number(e.target.value))} />
                </label>
                <Button variant="ghost" disabled={limit == null || limit === d.user.max_subscriptions} onClick={() => patchUser({ max_subscriptions: limit })}>
                  Сохранить
                </Button>
              </div>
              <Button variant={d.user.is_blocked ? 'ghost' : 'danger'} onClick={() => patchUser({ is_blocked: !d.user.is_blocked })}>
                <Ban size={14} strokeWidth={1.75} /> {d.user.is_blocked ? 'Разблокировать' : 'Заблокировать'}
              </Button>
            </div>
          </Section>

          <Section title={<>Подписки <span className="font-normal text-faint">{d.subscriptions.length}</span></>}>
            {d.subscriptions.length === 0 && <p className="text-[13px] text-faint">Подписок нет</p>}
            <div className="space-y-2">
              {d.subscriptions.map((s) => (
                <div key={s.id} className={cx('rounded-lg border border-line px-3 py-2.5', !s.is_active && 'opacity-60')}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-[13px] font-medium">
                      {s.origin_name || s.origin} → {s.destination_name || s.destination}
                    </div>
                    <div className="flex items-center gap-2">
                      <Toggle checked={s.is_active} onChange={(v) => patchSub(s.id, { is_active: v })} />
                      <button onClick={() => deleteSub(s.id)} className="text-faint transition-colors hover:text-bad" title="Удалить">
                        <Trash2 size={14} strokeWidth={1.75} />
                      </button>
                    </div>
                  </div>
                  <div className="mt-1 text-[12px] text-muted">
                    {s.date_from === s.date_to ? s.date_from : `${s.date_from} — ${s.date_to}`} · {s.adults} взр. · минимум {rub(s.last_min_price)}
                    {s.threshold_rub ? ` · порог ${rub(s.threshold_rub)}` : ''}
                  </div>
                  <div className="mt-0.5 text-[11px] text-faint">
                    проверено {ago(s.last_checked_at)} · уведомлён {ago(s.last_notified_at)}
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Последние поиски">
            {d.searches.length === 0 && <p className="text-[13px] text-faint">Поисков не было</p>}
            <div className="divide-y divide-line">
              {d.searches.map((x, i) => (
                <div key={i} className="flex justify-between gap-3 py-1.5 text-[12px]">
                  <span className="truncate">
                    {x.route} <span className="text-faint">· {x.dates}</span>
                  </span>
                  <span className="shrink-0 text-muted tabular-nums">{rub(x.min_price)}</span>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Уведомления">
            {d.notifications.length === 0 && <p className="text-[13px] text-faint">Не отправлялись</p>}
            <div className="divide-y divide-line">
              {d.notifications.map((n, i) => (
                <div key={i} className="flex justify-between gap-3 py-1.5 text-[12px]">
                  <span className={n.ok ? '' : 'text-bad'}>
                    {n.kind}
                    {n.ok ? '' : ' · не доставлено'}
                  </span>
                  <span className="shrink-0 text-muted tabular-nums">
                    {rub(n.price)} <span className="text-faint">· {fmtTime(n.at)}</span>
                  </span>
                </div>
              ))}
            </div>
          </Section>
        </>
      )}
    </aside>
  )
}
