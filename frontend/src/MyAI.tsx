import { useEffect, useState } from "react";
import { addAIConnection, aiConnections, aiProviders, deleteAIConnection, testAIConnection, updateAIConnection, type AIConnection, type AIProvider } from "./api";

const STATUS: Record<string, string> = {
  ok: "подключено", invalid_key: "ключ не принят", no_model: "нет доступа к модели", rate_limited: "превышен лимит или нет средств",
  unavailable: "провайдер недоступен", error: "ошибка", untested: "не проверено",
};

export function MyAI() {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [conns, setConns] = useState<AIConnection[]>([]);
  const [prov, setProv] = useState("openai");
  const [key, setKey] = useState("");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const reload = () => aiConnections().then(setConns).catch((e: Error) => setErr(e.message));
  useEffect(() => { aiProviders().then(setProviders).catch(() => {}); reload(); }, []);

  const p = providers.find((x) => x.code === prov);
  const act = (f: () => Promise<unknown>) => { setBusy(true); setErr(null); f().then(reload).catch((e: Error) => setErr(e.message)).finally(() => setBusy(false)); };

  return (
    <section className="card">
      <h2>Мой ИИ</h2>
      <p className="muted small">Подключите свой ключ ИИ. Он хранится зашифрованным и используется только для ваших запросов. Без ИИ все расчёты работают, нет только текстовых пояснений.</p>
      {conns.map((c) => (
        <div key={c.id} className="conn">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <b>{c.name}{c.is_default ? " · основной" : ""}</b>
            <span className={c.status === "ok" ? "ok small" : "bad small"}>{STATUS[c.status] ?? c.status}</span>
          </div>
          <div className="muted small">{c.provider_title}, ключ {c.masked_secret}. Запросов в этом месяце: {c.used_this_month} из {c.monthly_request_limit}</div>
          {c.last_error && <p className="bad small">{c.last_error}</p>}
          {c.models.length > 0 && (
            <select value={c.model_id ?? ""} disabled={busy} onChange={(e) => act(() => updateAIConnection(c.id, { model_id: e.target.value }))}>
              {!c.model_id && <option value="">Выберите модель…</option>}
              {c.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
          <label className="row small">
            <input type="checkbox" style={{ width: "auto", margin: 0 }} checked={c.data_level >= 2} disabled={busy}
              onChange={(e) => (!e.target.checked || confirm("Передавать в ИИ название компании и ИНН? Проверьте, что это разрешено политикой вашей организации.")) && act(() => updateAIConnection(c.id, { data_level: e.target.checked ? 2 : 1 }))} />
            Передавать название и ИНН (по умолчанию только обезличенные показатели)
          </label>
          <div className="row">
            <span className="small">Лимит в месяц</span>
            <input type="number" min={1} max={10000} defaultValue={c.monthly_request_limit} style={{ width: 90 }}
              onBlur={(e) => Number(e.target.value) !== c.monthly_request_limit && act(() => updateAIConnection(c.id, { monthly_request_limit: Number(e.target.value) }))} />
          </div>
          <div className="row">
            <button className="secondary" disabled={busy} onClick={() => act(() => testAIConnection(c.id))}>Проверить</button>
            {!c.is_default && <button className="secondary" disabled={busy} onClick={() => act(() => updateAIConnection(c.id, { is_default: true }))}>Сделать основным</button>}
            <button className="secondary danger" disabled={busy} onClick={() => confirm(`Удалить «${c.name}»? Ключ будет стёрт.`) && act(() => deleteAIConnection(c.id))}>Удалить</button>
          </div>
        </div>
      ))}
      {adding || conns.length === 0 ? (
        <>
          <select value={prov} onChange={(e) => setProv(e.target.value)}>
            {providers.map((x) => <option key={x.code} value={x.code}>{x.title}</option>)}
          </select>
          {p && <p className="muted small">{p.notes} <a href={p.docs} target="_blank" rel="noreferrer">Где взять ключ</a>. Вход через OAuth этот провайдер для сторонних приложений не поддерживает.</p>}
          <input type="password" autoComplete="off" placeholder={`API-ключ (${p?.key_hint ?? ""})`} value={key} onChange={(e) => setKey(e.target.value)} />
          {p?.needs_folder && <input placeholder="ID каталога Yandex Cloud (b1g…)" value={folder} onChange={(e) => setFolder(e.target.value)} />}
          <button className="primary" disabled={busy || key.trim().length < 8 || (!!p?.needs_folder && !folder.trim())}
            onClick={() => act(() => addAIConnection({ provider: prov, api_key: key.trim(), folder_id: folder.trim() || undefined }).then(() => { setKey(""); setFolder(""); setAdding(false); }))}>
            {busy ? "Проверяем…" : "Подключить"}
          </button>
          <p className="muted small">Проверка запрашивает у провайдера список моделей: данные клиентов не передаются.</p>
        </>
      ) : (
        <button className="link" onClick={() => setAdding(true)}>+ Добавить ещё один ИИ</button>
      )}
      {err && <p className="bad small">{err}</p>}
    </section>
  );
}
