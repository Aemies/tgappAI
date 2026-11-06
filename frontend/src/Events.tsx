import { useEffect, useState } from "react";
import { listEvents, markRead, type Event } from "./api";

const TYPE: Record<string, string> = { REGISTRY_CHANGE: "Изменение в реестре", NEW_RELATED_ENTITY: "Новая связь" };

export function Events({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<Event[] | null>(null);
  const [unread, setUnread] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = () => listEvents(unread).then(setItems).catch((e: Error) => setErr(e.message));
  useEffect(() => { load(); }, [unread]);

  const read = (ids?: number[]) => markRead(ids).then(() => { load(); onChanged(); }).catch((e: Error) => setErr(e.message));
  const hasUnread = items?.some((e) => !e.read);

  return (
    <>
      <h1>События</h1>
      <div className="row">
        <button className={`secondary ${unread ? "" : "on"}`} onClick={() => setUnread(false)}>Все</button>
        <button className={`secondary ${unread ? "on" : ""}`} onClick={() => setUnread(true)}>Непрочитанные</button>
        {hasUnread && <button className="link" onClick={() => read()}>Прочитать все</button>}
      </div>
      {err && <p className="bad small">{err}</p>}
      {items === null ? <p className="muted">Загрузка…</p> : items.length === 0 ? (
        <p className="muted">Изменений пока нет. Первая проверка запоминает текущее состояние компаний, события появятся, когда что-то изменится.</p>
      ) : (
        <ul className="list">
          {items.map((e) => (
            <li key={e.id} className={e.read ? "" : "unread"} onClick={() => !e.read && read([e.id])}>
              <div className="muted small">{TYPE[e.event_type] ?? e.event_type} · {new Date(e.effective_date ?? e.detected_at).toLocaleDateString("ru-RU")}</div>
              <div className="name">{e.company ?? `ИНН ${e.inn}`}</div>
              <div className="small">{e.title}</div>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">Источник: Checko. Проверка каждый день в 09:00 по вашему часовому поясу.</p>
    </>
  );
}
