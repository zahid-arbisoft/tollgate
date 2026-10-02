import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Build straight into the Python package so FastAPI serves the dashboard.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: path.resolve(__dirname, "../src/tollgate/static"),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/admin": "http://127.0.0.1:8787",
      "/v1": "http://127.0.0.1:8787",
      "/healthz": "http://127.0.0.1:8787",
    },
  },
});
