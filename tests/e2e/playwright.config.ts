import { defineConfig } from "@playwright/test";

// Points at a running Tollgate (uv run tollgate serve, default port).
// Set TOLLGATE_E2E_URL + TOLLGATE_E2E_TOKEN env vars to override.
export default defineConfig({
  use: {
    baseURL: process.env.TOLLGATE_E2E_URL ?? "http://127.0.0.1:8787",
  },
  testDir: ".",
  timeout: 30_000,
});
