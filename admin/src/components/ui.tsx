import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

/** Знак: точка-самолёт на дуге маршрута. */
export function Mark({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden>
      <path d="M3 15.5C6 8.5 11 5 17 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="0.5 3" />
      <circle cx="17" cy="4.5" r="2.5" fill="var(--accent)" />
      <circle cx="3" cy="15.5" r="1.6" fill="currentColor" />
    </svg>
  )
}

/** Обычная прокручиваемая страница с полями и ограниченной шириной. */
export function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1280px] space-y-6 px-8 py-8 max-md:px-4 max-md:py-5">{children}</div>
}

/** Заголовок страницы: название, одна строка пояснения, действия справа. */
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[22px] leading-tight font-semibold">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Раздел страницы: белая плоскость с тонкой границей, заголовок обычным регистром. */
export function Card({
  title,
  actions,
  children,
  className,
  flush,
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  /** Без внутренних отступов — для таблиц от края до края */
  flush?: boolean
}) {
  return (
    <section className={cx('rounded-xl border border-line bg-panel', className)}>
      {(title || actions) && (
        <div className="flex min-h-12 items-center justify-between gap-3 border-b border-line px-5 py-2.5">
          {title && <h2 className="text-[13px] font-medium">{title}</h2>}
          {actions}
        </div>
      )}
      <div className={flush ? '' : 'p-5'}>{children}</div>
    </section>
  )
}

/** Раздел боковой панели: без рамки, отделён от соседей линией сверху. */
export function Section({ title, actions, children }: { title: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-5 last:border-0">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-medium">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  )
}

/** Ряд крупных показателей, разделённых волосяными линиями (зазор в 1px поверх цвета линии). */
export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('grid gap-px overflow-hidden rounded-xl border border-line bg-line', className)}>{children}</div>
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className="min-w-0 bg-panel px-5 py-4">
      <div className="flex items-center gap-1.5 text-[12px] text-muted">
        {tone && <Dot tone={tone} />}
        <span className="truncate">{label}</span>
      </div>
      <div className={cx('mt-1.5 text-[26px] leading-none font-medium tracking-tight tabular-nums', tone === 'bad' && 'text-bad', tone === 'warn' && 'text-warn')}>
        {value}
      </div>
      {hint && <div className="mt-2 truncate text-[12px] text-faint">{hint}</div>}
    </div>
  )
}

export function Dot({ tone, className }: { tone: 'ok' | 'warn' | 'bad' | 'off' | 'accent'; className?: string }) {
  const color = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', off: 'bg-faint', accent: 'bg-accent' }[tone]
  return <span className={cx('inline-block h-1.5 w-1.5 shrink-0 rounded-full', color, className)} />
}

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' | 'quiet'; size?: 'sm' | 'md' }) {
  return (
    <button
      {...rest}
      className={cx(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        size === 'md' ? 'h-8 px-3 text-[13px]' : 'h-7 px-2.5 text-[12px]',
        variant === 'primary' && 'bg-ink text-bg hover:bg-ink/85',
        variant === 'ghost' && 'border border-line bg-panel text-ink hover:border-line-strong hover:bg-panel-2',
        variant === 'danger' && 'border border-line bg-panel text-bad hover:border-bad/40 hover:bg-bad/5',
        variant === 'quiet' && 'text-muted hover:bg-panel-2 hover:text-ink',
        className,
      )}
    />
  )
}

const FIELD = 'w-full rounded-lg border border-line bg-panel text-[13px] text-ink placeholder:text-faint outline-none transition-colors hover:border-line-strong focus:border-ink/40 focus:ring-3 focus:ring-ink/5'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(FIELD, 'h-8 px-2.5', props.className)} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(FIELD, 'px-2.5 py-2 leading-relaxed', props.className)} />
}

export function CodeArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea spellCheck={false} {...props} className={cx(FIELD, 'px-2.5 py-2 font-mono text-[12px] leading-relaxed', props.className)} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(FIELD, 'h-8 cursor-pointer px-2', props.className)} />
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[12px] leading-snug text-faint">{hint}</span>}
    </label>
  )
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="inline-flex items-center gap-2.5 text-left text-[13px]" aria-pressed={checked}>
      <span className={cx('relative h-[18px] w-8 shrink-0 rounded-full transition-colors', checked ? 'bg-ink' : 'bg-line-strong')}>
        <span className={cx('absolute top-[2px] h-[14px] w-[14px] rounded-full bg-bg shadow-sm transition-all', checked ? 'left-[16px]' : 'left-[2px]')} />
      </span>
      {label}
    </button>
  )
}

const STATUS: Record<string, [string, 'ok' | 'warn' | 'bad' | 'off']> = {
  ok: ['работает', 'ok'],
  degraded: ['с ошибками', 'warn'],
  down: ['отключён', 'bad'],
  disabled: ['выключен', 'off'],
}

export function StatusBadge({ status }: { status: string }) {
  const [text, tone] = STATUS[status] ?? [status, 'off']
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] whitespace-nowrap text-muted">
      <Dot tone={tone} />
      {text}
    </span>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <div className="rounded-lg border border-bad/25 bg-bad/5 px-3 py-2 text-[13px] text-bad">
      {error instanceof Error ? error.message : String(error)}
    </div>
  )
}

export function Notice({ tone = 'warn', children }: { tone?: 'warn' | 'ok'; children: ReactNode }) {
  return (
    <div className={cx('rounded-lg border px-3 py-2.5 text-[13px]', tone === 'warn' ? 'border-warn/30 bg-warn/5' : 'border-ok/30 bg-ok/5')}>
      {children}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-[13px] text-faint">{children}</div>
}

/** Таблица: мелкие приглушённые заголовки, строки через тонкие линии. */
export const TABLE = {
  table: 'w-full text-[13px]',
  head: 'text-left text-[12px] text-muted [&_th]:h-9 [&_th]:px-5 [&_th]:font-normal [&_th]:whitespace-nowrap border-b border-line',
  row: 'border-b border-line last:border-0 [&>td]:px-5 [&>td]:py-2.5',
}

/** Загрузка данных с автообновлением. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[], refreshMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  const reload = useCallback(async () => {
    try {
      setData(await loaderRef.current())
      setError(null)
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    reload()
    if (!refreshMs) return
    const id = setInterval(reload, refreshMs)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, loading, reload, setData }
}

/* ---------- Тема ---------- */

export type ThemeChoice = 'system' | 'light' | 'dark'
const THEME_KEY = 'aw-theme'

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

function applyChoice(choice: ThemeChoice) {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
  window.dispatchEvent(new Event('aw:theme'))
}

applyChoice(readChoice())

export function useThemeChoice(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(readChoice)
  const set = useCallback((c: ThemeChoice) => {
    try {
      if (c === 'system') localStorage.removeItem(THEME_KEY)
      else localStorage.setItem(THEME_KEY, c)
    } catch {
      /* без localStorage тема просто не запомнится */
    }
    applyChoice(c)
    setChoice(c)
  }, [])
  return [choice, set]
}

const VARS = ['ink', 'muted', 'faint', 'line', 'surface', 'subtle', 'accent', 'ok', 'warn', 'bad'] as const
type Palette = Record<(typeof VARS)[number], string>

function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement)
  return Object.fromEntries(VARS.map((v) => [v, css.getPropertyValue(`--${v}`).trim()])) as Palette
}

/** Цвета текущей темы для графиков (SVG-атрибуты не понимают CSS-переменные). */
export function usePalette(): Palette {
  const [p, setP] = useState(readPalette)
  useEffect(() => {
    const update = () => setP(readPalette())
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', update)
    window.addEventListener('aw:theme', update)
    return () => {
      mq.removeEventListener('change', update)
      window.removeEventListener('aw:theme', update)
    }
  }, [])
  return p
}

/** Спокойная категориальная палитра для нескольких линий (источники). */
export const SERIES = ['#d4500f', '#3d5a80', '#2f7d4f', '#8a5a9e', '#b7791f', '#4e8c99', '#9c6644', '#7a7872', '#c2412d']

/* ---------- Форматирование ---------- */

export const rub = (n: number | null | undefined) => (n == null ? '—' : `${Math.round(n).toLocaleString('ru-RU')} ₽`)

export function ago(iso: string | null | undefined): string {
  if (!iso) return '—'
  const sec = (Date.now() - new Date(iso).getTime()) / 1000
  if (sec < 60) return 'только что'
  if (sec < 3600) return `${Math.floor(sec / 60)} мин назад`
  if (sec < 86400) return `${Math.floor(sec / 3600)} ч назад`
  return `${Math.floor(sec / 86400)} дн назад`
}

export const fmtTime = (iso: string) => new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
