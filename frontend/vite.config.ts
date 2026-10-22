import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": `${import.meta.dirname}/src` },
  },
  server: {
    port: Number(process.env.VITE_DEV_SERVER_PORT ?? "15172"),
    strictPort: true,
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:18082", changeOrigin: true },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/react-hook-form/") || id.includes("/node_modules/@hookform/") || id.includes("/node_modules/zod/")) return "forms";
          if (id.includes("/node_modules/@tanstack/") || id.includes("/node_modules/openapi-fetch/")) return "query";
          if (id.includes("/node_modules/@radix-ui/")) return "ui";
          if (id.includes("/node_modules/react/") || id.includes("/node_modules/react-dom/") || id.includes("/node_modules/react-router/")) return "react";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
  },
});
