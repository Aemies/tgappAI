import { useEffect, useState } from "react";
import { getOverview, login, monitoringStatus, runMonitoring, saveSettings, type Overview, type Run, type User } from "./api";
import { Clients } from "./Clients";
import { Events } from "./Events";
import { Finance } from "./Finance";
import { Legal } from "./Legal";
import { Programs } from "./Programs";
import { Settings } from "./Settings";

const TABS = [
  { id: "overview", label: "Обзор" },
  { id: "clients", label: "Мои клиенты" },
  { id: "events", label: "События" },
  { id: "programs", label: "Госпрограммы" },
  { id: "finance", label: "AI-финансы" },
] as const;
type Tab = (typeof TABS)[number]["id"] | "settings";


export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [running, setRunning] = useState(false);
  const [programsFor, setProgramsFor] = useState<number | undefined>(undefined);
  const [lastRun, setLastRun] = useState<Run | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);

  const refreshOverview = () => getOverview().then(setOverview).catch(() => {});

  useEffect(() => {
    if (!user) return;
    monitoringStatus().then((s) => { setRunning(s.running); setLastRun(s.last_run); }).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      monitoringStatus().then((s) => {
        setLastRun(s.last_run);
        if (!s.running) { setRunning(false); refreshOverview(); }
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [running]);

  const startRun = () => {
    setRunErr(null);
    runMonitoring().then(() => setRunning(true)).catch((e: Error) => { setRunErr(e.message); if (e.message.includes("ключ Checko")) setTab("settings"); });
  };

  useEffect(() => {
    if (user && tab === "overview") getOverview().then(setOverview).catch(() => {});
  }, [tab]);

  useEffect(() => {
    login()
      .then((u) => { setUser(u); return getOverview(); })
      .then(setOverview)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="center">{error}</div>;
  if (!user) return <div className="center muted">Входим через Telegram…</div>;

  if (!user.accepted_terms_at)
    return (
      <div className="page">
        <h1>Добро пожаловать{user.first_name ? `, ${user.first_name}` : ""}</h1>
        <p>«Клиентский радар» помогает готовить гипотезы и вопросы клиенту. Это не скоринг и не официальное подтверждение права на господдержку.</p>
        <p className="muted">Ваш портфель и ключи видите только вы.</p>
        <details className="card"><summary>Условия и политика конфиденциальности</summary><Legal /></details>
        <button className="primary" onClick={() => saveSettings({ accept_terms: true }).then(setUser).catch((e: Error) => setError(e.message))}>
          Принимаю условия
        </button>
      </div>
    );

  return (
    <div className="layout">
      <header>
        <span className="title">Клиентский радар</span>
        <button className="icon" aria-label="Настройки" onClick={() => setTab("settings")}>⚙️</button>
      </header>
      <main className="page">
        {tab === "overview" && (
          <>
            <h1>Обзор</h1>
            <div className="stats">
              <Stat label="Клиентов" value={overview?.clients} />
              <Stat label="Проверено сегодня" value={overview?.checked_today} />
              <Stat label="Новых событий" value={overview?.new_events} />
              <Stat label="Ошибок" value={overview?.errors} />
            </div>
            {overview?.clients === 0 ? (
              <button className="primary" onClick={() => setTab("clients")}>Добавить ИНН</button>
            ) : (
              <button className="primary" disabled={running} onClick={startRun}>{running ? "Проверяем…" : "Запустить проверку"}</button>
            )}
            {runErr && <p className="bad small">{runErr}</p>}
            {lastRun && (
              <p className="muted small">
                Последняя проверка: {new Date(lastRun.started_at).toLocaleString("ru-RU")}{lastRun.finished_at ? `, клиентов ${lastRun.checked}, новых событий ${lastRun.new_events}, запросов ${lastRun.requests_used}` : ", идёт…"}
                {lastRun.skipped_quota ? `. Не хватило дневного лимита Checko на ${lastRun.skipped_quota}, они проверятся завтра первыми.` : ""}
              </p>
            )}
            <p className="muted small">Автоматическая проверка каждый день в 09:00. Первая проверка только запоминает текущее состояние.</p>
          </>
        )}
        {tab === "settings" && <Settings user={user} onUser={setUser} />}
        {tab === "clients" && <Clients onNeedKey={() => setTab("settings")} onPrograms={(id) => { setProgramsFor(id); setTab("programs"); }} />}
        {tab === "events" && <Events onChanged={refreshOverview} />}
        {tab === "programs" && <Programs key={programsFor ?? 0} clientId={programsFor} />}
        {tab === "finance" && <Finance onSettings={() => setTab("settings")} />}
      </main>
      <nav>
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => { if (t.id === "programs") setProgramsFor(undefined); setTab(t.id); }}>{t.label}</button>
        ))}
      </nav>
    </div>
  );
}

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <div className="stat">
      <div className="value">{value ?? "—"}</div>
      <div className="label">{label}</div>
    </div>
  );
}
