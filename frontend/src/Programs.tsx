import { useEffect, useState } from "react";
import { checkPrograms, listClients, type Client, type ProgramsResponse } from "./api";

const STATUS: Record<string, { label: string; cls: string }> = {
  LIKELY_MATCH: { label: "Потенциально подходит", cls: "ok" },
  NEEDS_MORE_INFO: { label: "Нужно больше данных", cls: "warn" },
  PROGRAM_UNVERIFIED: { label: "Условия требуют проверки", cls: "muted" },
  KNOWN_MISMATCH: { label: "Не подходит", cls: "bad" },
};
const ICON: Record<string, string> = { pass: "✓", fail: "✗", unknown: "?", ask: "?" };
const SUMMARY: Record<string, string> = { amount: "Сумма", rate: "Ставка", term: "Срок", purpose: "Цели" };

export function Programs({ clientId }: { clientId?: number }) {
  const [clients, setClients] = useState<Client[]>([]);
  const [sel, setSel] = useState<string>(clientId ? String(clientId) : "");
  const [inn, setInn] = useState("");
  const [res, setRes] = useState<ProgramsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { listClients().then(setClients).catch(() => {}); }, []);
  useEffect(() => { if (clientId) run({ client_id: clientId }); }, [clientId]);

  const run = (body: { client_id?: number; inn?: string }) => {
    setBusy(true); setErr(null); setRes(null);
    checkPrograms(body).then(setRes).catch((e: Error) => setErr(e.message)).finally(() => setBusy(false));
  };

  const shown = res ? res.results.filter((r) => showAll || r.status !== "KNOWN_MISMATCH") : [];
  const hidden = res ? res.results.length - shown.length : 0;

  return (
    <>
      <h1>Госпрограммы</h1>
      <section className="card">
        {clients.length > 0 && (
          <div className="row">
            <select value={sel} onChange={(e) => setSel(e.target.value)}>
              <option value="">Клиент из портфеля…</option>
              {clients.filter((c) => c.fetch_status === "ok").map((c) => <option key={c.id} value={c.id}>{c.name ?? c.inn}</option>)}
            </select>
            <button className="primary narrow" disabled={busy || !sel} onClick={() => run({ client_id: Number(sel) })}>Проверить</button>
          </div>
        )}
        <div className="row">
          <input inputMode="numeric" placeholder="Или любой ИНН (1 запрос Checko)" value={inn} onChange={(e) => setInn(e.target.value)} />
          <button className="secondary narrow" disabled={busy || !inn.trim()} onClick={() => run({ inn })}>Проверить</button>
        </div>
        {err && <p className="bad small">{err}</p>}
      </section>
      {busy && <p className="muted">Проверяем…</p>}
      {res && (
        <>
          <h2>{res.name ?? `ИНН ${res.inn}`}</h2>
          {shown.map((r) => (
            <section key={r.program_id} className="card program">
              <div className={`small ${STATUS[r.status]?.cls}`}><b>{STATUS[r.status]?.label ?? r.status}</b></div>
              <div className="name">{r.title}</div>
              <div className="muted small">{r.authority}</div>
              <ul className="checks">
                {r.checks.map((c, i) => <li key={i} className={c.result}><span>{ICON[c.result]}</span> {c.text}</li>)}
              </ul>
              {Object.entries(r.summary).length > 0 && (
                <dl className="fields small">
                  {Object.entries(r.summary).map(([k, v]) => <div key={k}><dt>{SUMMARY[k] ?? k}</dt><dd>{v}</dd></div>)}
                </dl>
              )}
              <p className="muted small">
                <a href={r.official_url} target="_blank" rel="noreferrer">Официальная страница</a> · условия проверены {new Date(r.verified_at).toLocaleDateString("ru-RU")}
              </p>
            </section>
          ))}
          {hidden > 0 && <button className="link" onClick={() => setShowAll(!showAll)}>{showAll ? "Скрыть неподходящие" : `Показать неподходящие (${hidden})`}</button>}
          <p className="muted small">{res.disclaimer}</p>
        </>
      )}
    </>
  );
}
