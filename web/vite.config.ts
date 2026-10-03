import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// En desarrollo, /api va al servidor Arena (ARENA_SERVER o el puerto por defecto 8090).
const server = process.env.ARENA_SERVER ?? "http://127.0.0.1:8090";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { "/api": { target: server, changeOrigin: false } },
  },
  build: { outDir: "dist", emptyOutDir: true, assetsInlineLimit: 0 },
  test: { environment: "jsdom", include: ["tests/**/*.test.ts"] },
});
