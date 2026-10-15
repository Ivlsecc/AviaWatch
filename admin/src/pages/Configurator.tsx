import { Background, Controls, Handle, MiniMap, Position, ReactFlow, useEdgesState, useNodesState } from '@xyflow/react'
import type { Connection, Edge, Node, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Globe, Plus, Shield, Zap } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AppSettings, SourceInfo } from '../api'
import { api } from '../api'
import { Button, Card, ErrorBox, Field, Input, StatusBadge, cx, useApi } from '../components/ui'
import SourcePanel from './SourcePanel'

type Board = { layout: AppSettings['board_layout']; proxy_pools: AppSettings['proxy_pools'] }

const PIPELINE = [
  { id: 'normalize', title: 'Нормализация', text: 'Единый формат, рубли, часовые пояса' },
  { id: 'dedup', title: 'Склейка дублей', text: 'Один рейс с разных сайтов — одна строка' },
  { id: 'filters', title: 'Фильтры', text: 'Пересадки, стыковки, смена аэропорта' },
  { id: 'analytics', title: 'Аналитика', text: 'Средняя цена, тренд, «покупать или ждать»' },
  { id: 'notify', title: 'Уведомления', text: 'Порог, новый минимум, сводки' },
]

const STATUS_RING: Record<string, string> = {
  ok: 'border-ok/70 shadow-[0_0_0_3px_#34d39922]',
  degraded: 'border-warn/70 shadow-[0_0_0_3px_#fbbf2422]',
  down: 'border-bad/80 shadow-[0_0_0_3px_#f8717133]',
  disabled: 'border-line opacity-60',
}

function SourceNode({ data, selected }: NodeProps<Node<{ src: SourceInfo }>>) {
  const s = data.src
  return (
    <div className={cx('w-56 rounded-xl border-2 bg-panel px-3 py-2 text-left', STATUS_RING[s.status], selected && 'ring-2 ring-accent')}>
      <Handle type="target" position={Position.Left} className="!bg-accent" />
      <div className="flex items-center justify-between gap-2">
        <div className="truncate text-sm font-semibold">{s.title}</div>
        <StatusBadge status={s.status} />
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-muted">
        <span className="rounded bg-panel-2 px-1.5 py-0.5 uppercase">{s.method}</span>
        <span>{s.stats_24h.requests} запр.</span>
        <span className={s.stats_24h.error_rate > 0.2 ? 'text-bad' : ''}>{Math.round(s.stats_24h.error_rate * 100)}% ош.</span>
        <span>{s.stats_24h.latency_p50_ms ? `${(s.stats_24h.latency_p50_ms / 1000).toFixed(1)} с` : ''}</span>
      </div>
      <Handle type="source" position={Position.Right} id="out" className="!bg-accent" />
      <Handle type="source" position={Position.Bottom} id="proxy" className="!bg-warn" />
    </div>
  )
}

function ProxyNode({ data }: NodeProps<Node<{ title: string; url: string; kind: string; count: number }>>) {
  const Icon = data.kind === 'direct' ? Zap : data.kind === 'global' ? Globe : Shield
  return (
    <div className="w-52 rounded-xl border border-dashed border-warn/60 bg-panel-2 px-3 py-2">
      <Handle type="target" position={Position.Top} className="!bg-warn" />
      <div className="flex items-center gap-2 text-sm font-medium">
        <Icon size={14} className="text-warn" /> {data.title}
      </div>
      <div className="truncate text-[11px] text-muted" title={data.url}>{data.url}</div>
      <div className="text-[11px] text-muted">источников: {data.count}</div>
    </div>
  )
}

function StepNode({ data }: NodeProps<Node<{ title: string; text: string; first?: boolean; last?: boolean }>>) {
  return (
    <div className="w-52 rounded-xl border border-accent/40 bg-accent/5 px-3 py-2">
      {!data.first && <Handle type="target" position={Position.Left} id="in-left" className="!bg-accent" />}
      {!data.first && <Handle type="target" position={Position.Top} id="in-top" className="!bg-accent" />}
      <div className="text-sm font-semibold text-accent">{data.title}</div>
      <div className="text-[11px] text-muted">{data.text}</div>
      {data.first && <Handle type="source" position={Position.Right} id="out" className="!bg-accent" />}
      {!data.first && !data.last && <Handle type="source" position={Position.Bottom} id="down" className="!bg-accent" />}
    </div>
  )
}

const nodeTypes = { source: SourceNode, proxy: ProxyNode, step: StepNode }

function proxyNodeId(proxy: string | null, pools: Board['proxy_pools']): string {
  if (!proxy) return 'proxy:global'
  if (proxy === 'direct') return 'proxy:direct'
  const pool = pools.find((p) => p.url === proxy)
  return pool ? `proxy:pool:${pool.name}` : `proxy:custom:${proxy}`
}

export default function Configurator() {
  const sources = useApi(() => api<SourceInfo[]>('/api/sources'), [], 20000)
  const board = useApi(() => api<Board>('/api/board'), [])
  const [selected, setSelected] = useState<string | null>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [error, setError] = useState<unknown>(null)
  const [poolName, setPoolName] = useState('')
  const [poolUrl, setPoolUrl] = useState('')

  const pools = useMemo(() => board.data?.proxy_pools ?? [], [board.data])
  const layout = useMemo(() => board.data?.layout ?? {}, [board.data])

  // Строим граф из источников, пулов прокси и шагов пайплайна
  useEffect(() => {
    if (!sources.data || !board.data) return
    const list = sources.data
    const pos = (id: string, x: number, y: number) => layout[id] ?? { x, y }
    const proxyIds = new Map<string, { title: string; url: string; kind: string }>([
      ['proxy:global', { title: 'Глобальный прокси', url: 'HTTP_PROXY из .env / системный', kind: 'global' }],
      ['proxy:direct', { title: 'Напрямую', url: 'мимо системного прокси', kind: 'direct' }],
      ...pools.map((p) => [`proxy:pool:${p.name}`, { title: p.name, url: p.url, kind: 'pool' }] as [string, { title: string; url: string; kind: string }]),
    ])
    for (const s of list) {
      const id = proxyNodeId(s.proxy, pools)
      if (!proxyIds.has(id)) proxyIds.set(id, { title: 'Свой прокси', url: s.proxy ?? '', kind: 'pool' })
    }
    const counts = new Map<string, number>()
    list.forEach((s) => counts.set(proxyNodeId(s.proxy, pools), (counts.get(proxyNodeId(s.proxy, pools)) ?? 0) + 1))

    const n: Node[] = [
      { id: 'trigger', type: 'step', position: pos('trigger', 0, Math.max(0, (list.length * 96) / 2 - 40)), data: { title: 'Запросы', text: 'Поиски пользователей и проверка подписок', first: true } },
      ...list.map((s, i) => ({
        id: `src:${s.name}`,
        type: 'source',
        position: s.board_x != null && s.board_y != null ? { x: s.board_x, y: s.board_y } : { x: 280, y: i * 96 },
        data: { src: s },
      })),
      ...[...proxyIds.entries()].map(([id, p], i) => ({
        id,
        type: 'proxy',
        position: pos(id, 0 + (i % 2) * 240, list.length * 96 + 40 + Math.floor(i / 2) * 90),
        data: { ...p, count: counts.get(id) ?? 0 },
      })),
      ...PIPELINE.map((p, i) => ({
        id: p.id,
        type: 'step',
        position: pos(p.id, 600, i * 120),
        data: { title: p.title, text: p.text, last: i === PIPELINE.length - 1 },
      })),
    ]
    const e: Edge[] = [
      ...list.map((s) => ({ id: `t-${s.name}`, source: 'trigger', sourceHandle: 'out', target: `src:${s.name}`, animated: s.enabled, style: { stroke: s.enabled ? '#38bdf8' : '#22304d' } })),
      ...list.map((s) => ({ id: `n-${s.name}`, source: `src:${s.name}`, sourceHandle: 'out', target: 'normalize', targetHandle: 'in-left', style: { stroke: s.enabled ? '#38bdf888' : '#22304d' } })),
      ...list.map((s) => ({
        id: `p-${s.name}`,
        source: `src:${s.name}`,
        sourceHandle: 'proxy',
        target: proxyNodeId(s.proxy, pools),
        style: { stroke: '#fbbf24aa', strokeDasharray: '4 4' },
      })),
      ...PIPELINE.slice(1).map((p, i) => ({ id: `pipe-${p.id}`, source: PIPELINE[i].id, sourceHandle: 'down', target: p.id, targetHandle: 'in-top', animated: true, style: { stroke: '#38bdf8' } })),
    ]
    setNodes(n)
    setEdges(e)
  }, [sources.data, board.data, layout, pools, setNodes, setEdges])

  const onConnect = useCallback(
    async (c: Connection) => {
      // Источник → узел прокси: меняем прокси источника
      if (!c.source?.startsWith('src:') || !c.target?.startsWith('proxy:')) return
      const name = c.source.slice(4)
      let proxy: string | null = null
      if (c.target === 'proxy:direct') proxy = 'direct'
      else if (c.target.startsWith('proxy:pool:')) proxy = pools.find((p) => `proxy:pool:${p.name}` === c.target)?.url ?? null
      else if (c.target.startsWith('proxy:custom:')) proxy = c.target.slice('proxy:custom:'.length)
      try {
        await api(`/api/sources/${name}`, { method: 'PATCH', body: { proxy: proxy ?? '' } })
        await sources.reload()
      } catch (e) {
        setError(e)
      }
    },
    [pools, sources],
  )

  const onNodeDragStop = useCallback(
    async (_: unknown, node: Node) => {
      try {
        if (node.id.startsWith('src:')) {
          await api(`/api/sources/${node.id.slice(4)}`, { method: 'PATCH', body: { board_x: node.position.x, board_y: node.position.y } })
        } else {
          const next = { ...layout, [node.id]: { x: node.position.x, y: node.position.y } }
          const saved = await api<Board>('/api/board', { method: 'PUT', body: { layout: next } })
          board.setData(saved)
        }
      } catch (e) {
        setError(e)
      }
    },
    [layout, board],
  )

  async function addPool() {
    if (!poolName.trim() || !poolUrl.trim()) return
    try {
      const saved = await api<Board>('/api/board', { method: 'PUT', body: { layout, proxy_pools: [...pools, { name: poolName.trim(), url: poolUrl.trim() }] } })
      board.setData(saved)
      setPoolName('')
      setPoolUrl('')
    } catch (e) {
      setError(e)
    }
  }

  async function removePool(name: string) {
    try {
      const saved = await api<Board>('/api/board', { method: 'PUT', body: { layout, proxy_pools: pools.filter((p) => p.name !== name) } })
      board.setData(saved)
    } catch (e) {
      setError(e)
    }
  }

  const current = sources.data?.find((s) => s.name === selected) ?? null

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-6">
        <div>
          <h1 className="text-xl font-semibold">Конфигуратор</h1>
          <p className="text-sm text-muted">
            Нажмите на источник, чтобы настроить его. Перетащите связь от жёлтой точки источника к узлу прокси, чтобы сменить прокси. Позиции сохраняются.
          </p>
        </div>
      </header>
      <ErrorBox error={error || sources.error || board.error} />
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeDragStop={onNodeDragStop}
            onNodeClick={(_, n) => setSelected(n.id.startsWith('src:') ? n.id.slice(4) : null)}
            onPaneClick={() => setSelected(null)}
            fitView
            fitViewOptions={{ padding: 0.08 }}
            colorMode="dark"
            style={{ background: 'var(--color-bg)' }}
            minZoom={0.2}
          >
            <Background color="#22304d" gap={24} />
            <Controls />
            <MiniMap pannable zoomable nodeColor={(n) => (n.type === 'source' ? '#38bdf8' : n.type === 'proxy' ? '#fbbf24' : '#8494b4')} />
          </ReactFlow>
        </div>
        <aside className="w-[380px] shrink-0 overflow-y-auto border-l border-line bg-panel p-4 max-lg:hidden">
          {current ? (
            <SourcePanel
              key={current.name}
              source={current}
              pools={pools}
              onChanged={() => sources.reload()}
              onClose={() => setSelected(null)}
            />
          ) : (
            <div className="space-y-4">
              <Card title="Пулы прокси">
                <div className="space-y-2">
                  {pools.length === 0 && <div className="text-sm text-muted">Пока нет. Добавьте прокси и протяните к нему связь от источника.</div>}
                  {pools.map((p) => (
                    <div key={p.name} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                      <div className="min-w-0">
                        <div className="font-medium">{p.name}</div>
                        <div className="truncate text-xs text-muted">{p.url}</div>
                      </div>
                      <Button variant="danger" onClick={() => removePool(p.name)}>Удалить</Button>
                    </div>
                  ))}
                  <Field label="Название">
                    <Input value={poolName} onChange={(e) => setPoolName(e.target.value)} placeholder="ru-residential" />
                  </Field>
                  <Field label="URL" hint="http://user:pass@host:port или socks5://host:1080">
                    <Input value={poolUrl} onChange={(e) => setPoolUrl(e.target.value)} placeholder="socks5://127.0.0.1:1080" />
                  </Field>
                  <Button onClick={addPool} disabled={!poolName.trim() || !poolUrl.trim()}>
                    <Plus size={14} /> Добавить пул
                  </Button>
                </div>
              </Card>
              <Card title="Как это работает">
                <ul className="list-disc space-y-1 pl-4 text-sm text-muted">
                  <li>Цвет рамки — состояние: зелёный работает, жёлтый с ошибками, красный отключён автоматически после серии ошибок.</li>
                  <li>Изменения применяются сразу, без перезапуска бота: настройки читаются из базы перед каждым поиском.</li>
                  <li>«Тест» в панели источника делает реальный запрос с текущими настройками.</li>
                </ul>
              </Card>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
