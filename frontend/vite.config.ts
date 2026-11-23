/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server forwards /api to the backend, so the browser sees one origin for the pages
// and the API, exactly as in production, where a Cloudflare Pages Function
// (functions/api/[[path]].ts) does the forwarding. Same origin is why the SameSite=Strict
// refresh cookie works and why the API needs no CORS setup.
const API_TARGET = process.env.API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "functions/**/*.test.ts"],
    restoreMocks: true,
  },
});
