import { useEffect, useState } from "react";
import { getOverview, login, saveSettings, type Overview, type User } from "./api";

const TABS = [
  { id: "overview", label: "Обзор" },
  { id: "clients", label: "Мои клиенты" },
  { id: "events", label: "События" },
  { id: "programs", label: "Госпрограммы" },
  { id: "finance", label: "AI-финансы" },
] as const;
type Tab = (typeof TABS)[number]["id"] | "settings";

const EMPTY: Record<Exclude<Tab, "overview" | "settings">, string> = {
  clients: "Здесь будет ваш портфель ИНН. Добавление клиентов появится на следующем этапе.",
  events: "Здесь появятся изменения в ЕГРЮЛ и новые связанные компании по вашим клиентам.",
  programs: "Здесь будут подходящие госпрограммы и причины подбора.",
  finance: "Здесь будут выручка, прибыль, долг и выводы по отчётности.",
};

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);

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
            <p className="muted">Портфель пока пуст.</p>
          </>
        )}
        {tab === "settings" && (
          <>
            <h1>Настройки</h1>
            <p>Часовой пояс: {user.timezone}</p>
            <p className="muted">Источники данных (Checko) и «Мой ИИ» появятся на следующих этапах.</p>
          </>
        )}
        {tab in EMPTY && (
          <>
            <h1>{TABS.find((t) => t.id === tab)?.label}</h1>
            <p className="muted">{EMPTY[tab as keyof typeof EMPTY]}</p>
          </>
        )}
      </main>
      <nav>
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>{t.label}</button>
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
