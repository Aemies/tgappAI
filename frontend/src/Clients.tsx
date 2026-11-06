import { useEffect, useState } from "react";
import { addClient, deleteClient, getClient, importClients, listClients, refreshClient, type Card, type Client } from "./api";

const FETCH: Record<string, string> = { pending: "карточка не загружена", not_found: "не найден в реестре", error: "ошибка загрузки" };

export function Clients({ onNeedKey }: { onNeedKey: () => void }) {
  const [items, setItems] = useState<Client[] | null>(null);
  const [inn, setInn] = useState("");
  const [bulk, setBulk] = useState("");
  const [showBulk, setShowBulk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [card, setCard] = useState<Card | null>(null);
  const [q, setQ] = useState("");

  const reload = () => listClients().then(setItems).catch((e: Error) => setMsg({ text: e.message, bad: true }));
  useEffect(() => { reload(); }, []);

  const fail = (e: Error) => {
    setMsg({ text: e.message, bad: true });
    if (e.message.includes("ключ Checko")) onNeedKey();
  };

  const add = () => {
    setBusy(true); setMsg(null);
    addClient(inn).then((c) => { setInn(""); setCard(c); reload(); }).catch(fail).finally(() => setBusy(false));
  };

  const doImport = () => {
    setBusy(true); setMsg(null);
    importClients(bulk)
      .then((r) => {
        setBulk(""); setShowBulk(false); reload();
        setMsg({ text: `Добавлено: ${r.added}. Уже были: ${r.duplicates}.${r.invalid.length ? ` Некорректные: ${r.invalid.join(", ")}` : ""} Карточки загружаются по кнопке «Обновить» в карточке клиента.` });
      })
      .catch(fail).finally(() => setBusy(false));
  };

  const readFile = (f: File) => f.text().then((t) => setBulk(t));

  if (card) return <CardView card={card} onBack={() => { setCard(null); reload(); }} onChange={setCard} onError={fail} />;

  const shown = (items ?? []).filter((c) => !q || c.inn.includes(q) || (c.name ?? "").toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <h1>Мои клиенты</h1>
      <section className="card">
        <div className="row">
          <input inputMode="numeric" placeholder="ИНН организации или ИП" value={inn} onChange={(e) => setInn(e.target.value)} onKeyDown={(e) => e.key === "Enter" && inn && add()} />
          <button className="primary narrow" disabled={busy || !inn.trim()} onClick={add}>{busy ? "…" : "Добавить"}</button>
        </div>
        <button className="link" onClick={() => setShowBulk(!showBulk)}>{showBulk ? "Скрыть" : "Загрузить списком или из CSV"}</button>
        {showBulk && (
          <>
            <textarea rows={5} placeholder="ИНН через запятую, пробел или с новой строки" value={bulk} onChange={(e) => setBulk(e.target.value)} />
            <div className="row">
              <label className="secondary file">Файл CSV<input type="file" accept=".csv,.txt" hidden onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])} /></label>
              <button className="primary narrow" disabled={busy || !bulk.trim()} onClick={doImport}>Загрузить</button>
            </div>
          </>
        )}
        {msg && <p className={`small ${msg.bad ? "bad" : "muted"}`}>{msg.text}</p>}
      </section>

      {items && items.length > 3 && <input placeholder="Поиск по ИНН или названию" value={q} onChange={(e) => setQ(e.target.value)} />}
      {items === null ? <p className="muted">Загрузка…</p> : items.length === 0 ? (
        <p className="muted">Портфель пуст. Добавьте первый ИНН.</p>
      ) : (
        <ul className="list">
          {shown.map((c) => (
            <li key={c.id} onClick={() => getClient(c.id).then(setCard).catch(fail)}>
              <div className="name">{c.name ?? c.inn}</div>
              <div className="muted small">ИНН {c.inn}{c.status ? ` · ${c.status}` : ""}{c.region ? ` · ${c.region}` : ""}{c.fetch_status !== "ok" ? ` · ${FETCH[c.fetch_status] ?? c.fetch_status}` : ""}</div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

const FIELDS: [string, string][] = [
  ["full_name", "Полное наименование"], ["status", "Статус"], ["ogrn", "ОГРН"], ["registered", "Дата регистрации"],
  ["region", "Регион"], ["address", "Адрес"], ["okved", "Основной ОКВЭД"], ["head", "Руководитель"],
  ["sme_category", "Категория МСП"], ["employees", "Сотрудников"],
];

function CardView({ card, onBack, onChange, onError }: { card: Card; onBack: () => void; onChange: (c: Card) => void; onError: (e: Error) => void }) {
  const [busy, setBusy] = useState(false);
  const s = card.summary ?? {};
  return (
    <>
      <button className="link" onClick={onBack}>← Все клиенты</button>
      <h1>{card.name ?? `ИНН ${card.inn}`}</h1>
      <p className="muted small">ИНН {card.inn} · {card.subject_type === "ip" ? "ИП" : "Организация"}</p>
      {card.fetch_status !== "ok" && <p className="bad small">{card.fetch_error ?? FETCH[card.fetch_status]}</p>}
      {card.summary && (
        <dl className="card fields">
          {FIELDS.filter(([k]) => s[k] != null && s[k] !== "").map(([k, label]) => (
            <div key={k}><dt>{label}</dt><dd>{String(s[k])}</dd></div>
          ))}
        </dl>
      )}
      {card.summary && <p className="muted small">Источник: Checko{s.source_date ? `, выписка от ${s.source_date}` : ""}. Загружено {card.fetched_at ? new Date(card.fetched_at).toLocaleString("ru-RU") : "—"}.</p>}
      <div className="row">
        <button className="secondary" disabled={busy} onClick={() => { setBusy(true); refreshClient(card.id).then(onChange).catch(onError).finally(() => setBusy(false)); }}>
          {busy ? "Обновляем…" : "Обновить"}
        </button>
        <button className="secondary danger" onClick={() => confirm("Убрать клиента из портфеля?") && deleteClient(card.id).then(onBack).catch(onError)}>Убрать</button>
      </div>
      <p className="muted small">Обновление тратит 1 запрос Checko.</p>
    </>
  );
}
