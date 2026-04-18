import { defineConfig } from "vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [
    tailwindcss(), // 2. Aktywacja Tailwinda
    react(),
    babel({ presets: [reactCompilerPreset()] }),
  ],
  // 3. Konfiguracja serwera dla środowiska Docker Dev
  server: {
    host: true,
    port: 5173,
    watch: { usePolling: true },
    // TO DODAJEMY:
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL || "http://localhost:3000",
        changeOrigin: true,
        rewrite: (path) => path,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@components": path.resolve(__dirname, "./src/components"),
      "@lib": path.resolve(__dirname, "./src/lib"),
      "@utils": path.resolve(__dirname, "./src/utils"),
      "@assets": path.resolve(__dirname, "./src/assets"),
      "@constants": path.resolve(__dirname, "./src/constants"),
      "@hooks": path.resolve(__dirname, "./src/hooks"),
      "@sections": path.resolve(__dirname, "./src/sections"),
      "@pages": path.resolve(__dirname, "./src/pages"),
      "@typings": path.resolve(__dirname, "./src/types"),
    },
  },
});
