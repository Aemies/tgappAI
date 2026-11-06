import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import { tg } from "./telegram";

tg?.ready();
tg?.expand();
createRoot(document.getElementById("root")!).render(<App />);
