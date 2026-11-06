type WebApp = {
  initData: string;
  colorScheme: "light" | "dark";
  ready(): void;
  expand(): void;
  close?(): void;
};

export const tg: WebApp | undefined = (window as unknown as { Telegram?: { WebApp?: WebApp } }).Telegram?.WebApp;
