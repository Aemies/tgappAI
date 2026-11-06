import { useEffect, useState } from "react";
import { explainFinance, getFinance, listClients, refreshFinance, type AIExplain, type Client, type Finance as Fin, type YearReport } from "./api";

const money = (v: number | null | undefined) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  const [d, u] = a >= 1e9 ? [1e9, "млрд"] : a >= 1e6 ? [1e6, "млн"] : [1e3, "тыс."];
  return `${(v / d).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} ${u} ₽`;
};
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`);
const mln = (v: number | null | undefined) => (v == null ? "—" : (v / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 }));
const x = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: 2 }));

const CARDS: { key: string; label: string; f: (v: number | null) => string }[] = [
  { key: "ebit", label: "EBIT", f: money },
  { key: "ebitda", label: "EBITDA", f: money },
  { key: "debt", label: "Процентный долг", f: money },
  { key: "debt_ebitda", label: "Долг / EBITDA", f: x },
  { key: "debt_ebit", label: "Долг / EBIT", f: x },
  { key: "current_ratio", label: "Текущая ликвидность", f: x },
];
const ROWS: { label: string; get: (r: YearReport) => string }[] = [
  { label: "Выручка", get: (r) => mln(r.lines["2110"]) },
  { label: "Рост выручки", get: (r) => pct(r.metrics.revenue_yoy.value) },
  { label: "Прибыль от продаж", get: (r) => mln(r.lines["2200"]) },
  { label: "Чистая прибыль", get: (r) => mln(r.lines["2400"]) },
  { label: "EBIT", get: (r) => mln(r.metrics.ebit.value) },
  { label: "Рентабельность EBIT", get: (r) => pct(r.metrics.ebit_margin.value) },
  { label: "Долг", get: (r) => mln(r.metrics.debt.value) },
  { label: "Чистый долг", get: (r) => mln(r.metrics.net_debt.value) },
  { label: "Собственный капитал", get: (r) => mln(r.lines["1300"]) },
  { label: "Доля капитала", get: (r) => pct(r.metrics.equity_ratio.value) },
];

function Bars({ title, values }: { title: string; values: [string, number | null][] }) {
  const max = Math.max(1, ...values.map(([, v]) => Math.abs(v ?? 0)));
  return (
    <div className="bars">
      <div className="muted small">{title}</div>
      {values.map(([y, v]) => (
        <div key={y} className="bar-row small">
          <span>{y}</span>
          <div className="bar"><div className={(v ?? 0) < 0 ? "neg" : ""} style={{ width: `${(Math.abs(v ?? 0) / max) * 100}%` }} /></div>
          <span className="num">{money(v)}</span>
        </div>
      ))}
    </div>
  );
}

export function Finance({ onSettings }: { onSettings: () => void }) {
  const [clients, setClients] = useState<Client[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [fin, setFin] = useState<Fin | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [how, setHow] = useState<string | null>(null);
  const [aiRes, setAiRes] = useState<AIExplain | null>(null);
  const [aiErr, setAiErr] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);

  useEffect(() => {
    listClients().then((cs) => { const c = cs; setClients(c); if (c[0]) setSel(c[0].id); }).catch((e: Error) => setErr(e.message));
  }, []);
  useEffect(() => {
    if (sel == null) return;
    setFin(null); setAiRes(null); setAiErr(null); setErr(null);
    getFinance(sel).then(setFin).catch((e: Error) => setErr(e.message));
  }, [sel]);

  const load = () => { if (sel == null) return; setBusy(true); setErr(null); refreshFinance(sel).then(setFin).catch((e: Error) => setErr(e.message)).finally(() => setBusy(false)); };
  const explain = () => { if (sel == null) return; setAiBusy(true); setAiErr(null); explainFinance(sel).then(setAiRes).catch((e: Error) => setAiErr(e.message)).finally(() => setAiBusy(false)); };

  if (clients.length === 0) return (<><h1>AI-финансы</h1><p className="muted">Добавьте клиентов во вкладке «Мои клиенты», и здесь появится анализ их отчётности.</p></>);
  const last = fin?.reports?.[fin.reports.length - 1];

  return (
    <>
      <h1>AI-финансы</h1>
      <select style={{ marginBottom: 12 }} value={sel ?? ""} onChange={(e) => setSel(Number(e.target.value))}>
        {clients.map((c) => <option key={c.id} value={c.id}>{c.name ?? c.inn}</option>)}
      </select>
      {err && <p className="bad small">{err}</p>}
      {fin && !fin.loaded && (
        <section className="card" style={{ marginTop: 12 }}>
          <p className="small">Отчётность ещё не загружена.</p>
          <button className="primary" disabled={busy} onClick={load}>{busy ? "Загружаем…" : "Проанализировать"}</button>
          <p className="muted small">Тратит 1 запрос Checko. Данные — бухотчётность РСБУ из ГИР БО за последние 3 года.</p>
        </section>
      )}
      {fin?.loaded && fin.available === false && <p className="muted" style={{ marginTop: 12 }}>{fin.reason}</p>}
      {fin?.available && last && fin.reports && (
        <>
          {fin.flags && fin.flags.length > 0 && (
            <section className="card warnbox"><b className="small">Нужен дополнительный анализ:</b><ul className="small">{fin.flags.map((f) => <li key={f}>{f}</li>)}</ul></section>
          )}
          <section className="card">
            <h2>Коротко за {last.year} год</h2>
            {fin.summary?.map((s) => <p key={s} className="small" style={{ margin: "4px 0" }}>{s}</p>)}
          </section>
          <div className="stats">
            {CARDS.map((c) => {
              const m = last.metrics[c.key];
              return (
                <div key={c.key} className="stat" onClick={() => setHow(how === c.key ? null : c.key)}>
                  <div className="value metric">{m.value == null ? "N/A" : c.f(m.value)}</div>
                  <div className="label">{c.label}</div>
                  {m.note && <div className="muted tiny">{m.note}</div>}
                  <button className="link tiny">{how === c.key ? "Скрыть" : "Как рассчитано"}</button>
                  {how === c.key && <div className="tiny">{fin.formulas?.[c.key]}</div>}
                </div>
              );
            })}
          </div>
          <section className="card">
            <Bars title="Выручка" values={fin.reports.map((r) => [r.year, r.lines["2110"]])} />
            <Bars title="Чистая прибыль" values={fin.reports.map((r) => [r.year, r.lines["2400"]])} />
            <Bars title="Процентный долг" values={fin.reports.map((r) => [r.year, r.metrics.debt.value])} />
          </section>
          <section className="card table-wrap">
            <table className="fin small">
              <thead><tr><th className="muted">млн ₽</th>{fin.reports.map((r) => <th key={r.year}>{r.year}</th>)}</tr></thead>
              <tbody>{ROWS.map((row) => <tr key={row.label}><td>{row.label}</td>{fin.reports!.map((r) => <td key={r.year}>{row.get(r)}</td>)}</tr>)}</tbody>
            </table>
          </section>
          <section className="card">
            <h2>Что спросить у клиента</h2>
            <ul className="small">{fin.questions?.map((q) => <li key={q}>{q}</li>)}</ul>
          </section>
          <section className="card">
            <h2>Пояснение ИИ</h2>
            {!aiRes && <button className="primary" disabled={aiBusy} onClick={explain}>{aiBusy ? "Модель думает…" : "Пояснить с моим ИИ"}</button>}
            {aiErr && <p className="bad small">{aiErr} {aiErr.includes("Мой ИИ") && <button className="link" onClick={onSettings}>Открыть настройки</button>}</p>}
            {aiRes && (
              <>
                <p className="muted tiny">{aiRes.connection.name}, модель {aiRes.connection.model_id}. Передано: {aiRes.data_level >= 2 ? "показатели, название и ИНН" : "только обезличенные показатели"}.</p>
                {aiRes.result.summary && <p className="small">{aiRes.result.summary}</p>}
                {aiRes.result.strengths.length > 0 && <><b className="small ok">Сильные стороны</b><ul className="small">{aiRes.result.strengths.map((s) => <li key={s}>{s}</li>)}</ul></>}
                {aiRes.result.risks.length > 0 && <><b className="small bad">Риски</b><ul className="small">{aiRes.result.risks.map((s) => <li key={s}>{s}</li>)}</ul></>}
                {aiRes.result.questions_for_manager.length > 0 && <><b className="small">Вопросы</b><ul className="small">{aiRes.result.questions_for_manager.map((s) => <li key={s}>{s}</li>)}</ul></>}
                {aiRes.result.limitations.length > 0 && <><b className="small muted">Ограничения</b><ul className="small muted">{aiRes.result.limitations.map((s) => <li key={s}>{s}</li>)}</ul></>}
                {aiRes.result.removed_count > 0 && <p className="warn tiny">Убрано утверждений с числами не из расчёта: {aiRes.result.removed_count}</p>}
                <p className="muted tiny">{aiRes.disclaimer}</p>
              </>
            )}
          </section>
          <p className="muted tiny">
            Отчётность загружена {fin.fetched_at ? new Date(fin.fetched_at).toLocaleDateString("ru-RU") : ""}, методика {fin.method_version}.{" "}
            <button className="link tiny" disabled={busy} onClick={load}>Обновить</button>
            {fin.pdf_links?.[last.year] && <> · <a href={fin.pdf_links[last.year]} target="_blank" rel="noreferrer">PDF в ГИР БО за {last.year}</a></>}
          </p>
          <p className="muted tiny">{fin.disclaimer}</p>
        </>
      )}
    </>
  );
}
