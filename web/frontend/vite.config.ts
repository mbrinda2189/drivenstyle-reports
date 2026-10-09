/*
 * vite.config.ts - How the screens are run and built
 * ==================================================
 *
 * WHAT THIS FILE DOES
 * -------------------
 * Vite is the tool that turns the TypeScript files in src/ into what a
 * browser can run.
 *
 *   npm run dev     While developing: the screens open at
 *                   http://localhost:5173 and refresh as files are saved.
 *                   Every address starting with /api is passed on to the
 *                   Python server on port 8000 (the "proxy" below), so the
 *                   browser sees ONE site and the sign-in cookie works.
 *
 *   npm run build   For the real server: checks the TypeScript, then
 *                   writes the finished screens to dist/. The Python server
 *                   serves that folder itself (web/backend/main.py).
 */
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
