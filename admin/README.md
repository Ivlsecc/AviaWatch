# AviaWatch — веб-админка

React + TypeScript + Vite + Tailwind CSS, графики — Recharts, конфигуратор — React Flow (`@xyflow/react`).

```bash
npm install
npm run dev     # http://localhost:5173, /api проксируется на http://127.0.0.1:8000
npm run build   # admin/dist — его раздаёт API (python -m api.main)
```

Страницы: `src/pages/` — Dashboard, Configurator (+ SourcePanel), Users, Bot, Logs, Login.
Обёртка над API и типы — `src/api.ts`, общие компоненты — `src/components/ui.tsx`.
