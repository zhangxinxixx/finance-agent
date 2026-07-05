import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const proxyTarget = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000";
const dagsterTarget = process.env.VITE_DAGSTER_TARGET || "http://127.0.0.1:3333";

const spaRoutes = new Set([
  "/dashboard",
  "/gold-mainlines",
  "/rates-dollar",
  "/oil-geopolitics",
  "/data-ingestion",
  "/market-monitor",
  "/cme-options",
  "/reports",
  "/event-flow",
  "/knowledge-base",
  "/agent-tasks",
  "/processing-monitor",
  "/review-center",
  "/settings",
  "/scheduler",
  "/knowledge",
  "/strategy",
]);

const spaRoutePrefixes = [
  "/reports/",
  "/data-sources/",
  "/event-flow/",
  "/agent-tasks/",
  "/dashboard/analysis",
  "/settings/audit",
  "/scheduler/",
  "/processing-monitor/",
  "/knowledge/",
];

function financeSpaRouteFallback(): Plugin {
  return {
    name: "finance-spa-route-fallback",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const pathname = req.url?.split("?")[0];
        if (
          pathname &&
          (spaRoutes.has(pathname) || spaRoutePrefixes.some((prefix) => pathname.startsWith(prefix)))
        ) {
          req.url = "/index.html";
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [financeSpaRouteFallback(), react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
      "/dagster": {
        target: dagsterTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/dagster/, ""),
      },
    },
  },
});
