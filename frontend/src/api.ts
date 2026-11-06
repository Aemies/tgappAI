import { tg } from "./telegram";

export type User = { id: number; first_name: string | null; username: string | null; timezone: string; accepted_terms_at: string | null };
export type Overview = { clients: number; checked_today: number; new_events: number; errors: number };

let token: string | null = null;

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Ошибка ${res.status}`);
  return res.json();
}

export async function login(): Promise<User> {
  // Сервер проверяет подпись initData. Данные initDataUnsafe не используем как доказательство личности.
  const initData = tg?.initData ?? "";
  if (!initData) throw new Error("Откройте кабинет из Telegram-бота.");
  const r = await call<{ token: string; user: User }>("/auth/telegram", { method: "POST", body: JSON.stringify({ init_data: initData }) });
  token = r.token;
  return r.user;
}

export const getOverview = () => call<Overview>("/overview");
export const saveSettings = (body: { timezone?: string; accept_terms?: boolean }) => call<User>("/settings", { method: "PUT", body: JSON.stringify(body) });
