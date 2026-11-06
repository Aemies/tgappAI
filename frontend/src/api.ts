import { tg } from "./telegram";

export type User = { id: number; first_name: string | null; username: string | null; timezone: string; accepted_terms_at: string | null; notifications_enabled: boolean };
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

export const deleteMe = () => call<{ ok: boolean }>("/me", { method: "DELETE" });
export const getOverview = () => call<Overview>("/overview");
export const saveSettings = (body: { timezone?: string; accept_terms?: boolean; notifications_enabled?: boolean }) => call<User>("/settings", { method: "PUT", body: JSON.stringify(body) });

export type Credential = { connected: boolean; key_mask?: string | null; status?: string | null; last_tested_at?: string | null; last_error?: string | null; requests_today?: number | null };
export type Client = { id: number; inn: string; subject_type: string; label: string | null; fetch_status: string; fetch_error: string | null; name: string | null; status: string | null; region: string | null };
export type Card = Client & { summary: Record<string, string | number | null> | null; fetched_at: string | null; last_checked_at: string | null; last_check_error: string | null };

export const getChecko = () => call<Credential>("/integrations/checko");
export const saveChecko = (api_key: string) => call<Credential>("/integrations/checko", { method: "POST", body: JSON.stringify({ api_key }) });
export const testChecko = () => call<Credential>("/integrations/checko/test", { method: "POST" });
export const deleteChecko = () => call<Credential>("/integrations/checko", { method: "DELETE" });

export const listClients = () => call<Client[]>("/clients");
export const addClient = (inn: string) => call<Card>("/clients", { method: "POST", body: JSON.stringify({ inn }) });
export const importClients = (text: string) => call<{ added: number; duplicates: number; invalid: string[] }>("/clients/import", { method: "POST", body: JSON.stringify({ text }) });
export const getClient = (id: number) => call<Card>(`/clients/${id}`);
export const refreshClient = (id: number) => call<Card>(`/clients/${id}/refresh`, { method: "POST" });
export const deleteClient = (id: number) => call<{ ok: boolean }>(`/clients/${id}`, { method: "DELETE" });

export type Run = { id: number; started_at: string; finished_at: string | null; trigger: string; checked: number; errors: number; skipped_quota: number; new_events: number; requests_used: number };
export type Event = { id: number; client_id: number; inn: string; company: string | null; event_type: string; title: string; effective_date: string | null; detected_at: string; read: boolean };

export const runMonitoring = () => call<{ started: boolean; running: boolean }>("/monitoring/run", { method: "POST" });
export const monitoringStatus = () => call<{ running: boolean; last_run: Run | null }>("/monitoring/status");
export const listEvents = (unread = false) => call<Event[]>(`/events${unread ? "?unread=true" : ""}`);
export const markRead = (ids?: number[]) => call<{ ok: boolean }>("/events/read", { method: "POST", body: JSON.stringify(ids ?? null) });

export type ProgramCheck = { result: "pass" | "fail" | "unknown" | "ask"; text: string };
export type ProgramResult = { program_id: string; title: string; authority: string; official_url: string; verified_at: string; status: string; checks: ProgramCheck[]; summary: Record<string, string>; note: string };
export type ProgramsResponse = { inn: string; name: string | null; rule_version: string; results: ProgramResult[]; disclaimer: string };

export const checkPrograms = (body: { client_id?: number; inn?: string }) => call<ProgramsResponse>("/programs/check", { method: "POST", body: JSON.stringify(body) });

export type Metric = { value: number | null; note: string | null };
export type YearReport = { year: string; lines: Record<string, number | null>; metrics: Record<string, Metric> };
export type Finance = {
  loaded: boolean; available?: boolean; reason?: string; fetched_at?: string; years?: string[]; unit?: string; method_version?: string;
  line_labels?: Record<string, string>; formulas?: Record<string, string>; reports?: YearReport[]; summary?: string[]; questions?: string[];
  flags?: string[]; disclaimer?: string; pdf_links?: Record<string, string>;
};
export type AIResult = { summary: string; strengths: string[]; risks: string[]; questions_for_manager: string[]; limitations: string[]; confidence: string | null; removed_count: number };
export type AIExplain = { connection: { id: number; name: string; provider: string; model_id: string }; data_level: number; sent_package: unknown; result: AIResult; tokens: { input: number | null; output: number | null }; disclaimer: string };

export const getFinance = (id: number) => call<Finance>(`/clients/${id}/finance`);
export const refreshFinance = (id: number) => call<Finance>(`/clients/${id}/finance/refresh`, { method: "POST" });
export const explainFinance = (id: number, connection_id?: number) => call<AIExplain>(`/clients/${id}/finance/ai`, { method: "POST", body: JSON.stringify({ connection_id }) });

export type AIProvider = { code: string; title: string; has_model_list: boolean; fixed_models: string[]; needs_folder: boolean; key_hint: string; docs: string; notes: string; oauth_supported: boolean };
export type AIConnection = {
  id: number; provider: string; provider_title: string; name: string; model_id: string | null; masked_secret: string; status: string; last_error: string | null;
  is_default: boolean; data_level: number; monthly_request_limit: number; max_tokens: number; used_this_month: number; models: string[]; folder_id: string | null;
};
export const aiProviders = () => call<AIProvider[]>("/ai/providers");
export const aiConnections = () => call<AIConnection[]>("/ai/connections");
export const addAIConnection = (body: { provider: string; api_key: string; name?: string; model_id?: string; folder_id?: string }) =>
  call<AIConnection>("/ai/connections", { method: "POST", body: JSON.stringify(body) });
export const updateAIConnection = (id: number, body: Partial<Pick<AIConnection, "name" | "model_id" | "is_default" | "data_level" | "monthly_request_limit">>) =>
  call<AIConnection>(`/ai/connections/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const testAIConnection = (id: number) => call<AIConnection>(`/ai/connections/${id}/test`, { method: "POST" });
export const deleteAIConnection = (id: number) => call<{ ok: boolean }>(`/ai/connections/${id}`, { method: "DELETE" });
