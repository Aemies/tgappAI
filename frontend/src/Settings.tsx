import { useEffect, useState } from "react";
import { MyAI } from "./MyAI";
import { deleteChecko, getChecko, saveChecko, saveSettings, testChecko, type Credential, type User } from "./api";

const STATUS: Record<string, string> = { ok: "работает", invalid: "ключ не принят", error: "ошибка проверки", untested: "не проверен" };

export function Settings({ user, onUser }: { user: User; onUser: (u: User) => void }) {
  const [cred, setCred] = useState<Credential | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { getChecko().then(setCred).catch((e: Error) => setErr(e.message)); }, []);

  const run = (p: Promise<Credential>) => {
    setBusy(true); setErr(null);
    p.then((c) => { setCred(c); setKey(""); }).catch((e: Error) => setErr(e.message)).finally(() => setBusy(false));
  };

  return (
    <>
      <h1>Настройки</h1>
      <section className="card">
        <h2>Источник данных: Checko</h2>
        {cred?.connected ? (
          <>
            <p>Ключ {cred.key_mask}: <b className={cred.status === "ok" ? "ok" : "bad"}>{STATUS[cred.status ?? ""] ?? cred.status}</b></p>
            {cred.last_error && <p className="bad small">{cred.last_error}</p>}
            {cred.requests_today != null && <p className="muted small">Запросов сегодня: {cred.requests_today} из 100 (бесплатный тариф)</p>}
            <div className="row">
              <button className="secondary" disabled={busy} onClick={() => run(testChecko())}>Проверить</button>
              <button className="secondary danger" disabled={busy} onClick={() => confirm("Удалить ключ Checko?") && run(deleteChecko())}>Удалить</button>
            </div>
          </>
        ) : (
          <p className="muted small">Ключ можно получить в личном кабинете checko.ru. Он хранится зашифрованным, видите его только вы.</p>
        )}
        <input type="password" autoComplete="off" placeholder={cred?.connected ? "Новый ключ для замены" : "API-ключ Checko"} value={key} onChange={(e) => setKey(e.target.value)} />
        <button className="primary" disabled={busy || key.trim().length < 8} onClick={() => run(saveChecko(key.trim()))}>
          {busy ? "Проверяем…" : cred?.connected ? "Заменить ключ" : "Подключить"}
        </button>
        <p className="muted small">Проверка ключа тратит 1 запрос из дневного лимита.</p>
        {err && <p className="bad small">{err}</p>}
      </section>
      <MyAI />
      <section className="card">
        <h2>Профиль</h2>
        <p className="small">Часовой пояс: {user.timezone}</p>
        <label className="row small">
          <input type="checkbox" style={{ width: "auto", margin: 0 }} checked={user.notifications_enabled}
            onChange={(e) => saveSettings({ notifications_enabled: e.target.checked }).then(onUser).catch((er: Error) => setErr(er.message))} />
          Присылать уведомления о событиях в Telegram
        </label>
      </section>
    </>
  );
}
