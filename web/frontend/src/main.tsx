/*
 * main.tsx - Where the screens start
 * ==================================
 * Puts the whole tool (App) into the page's one empty box (#root in
 * index.html). BrowserRouter lets each screen have its own address
 * (/daily/payouts, /monthly/generate ...), so Back, Forward and Refresh
 * work as on any website.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
