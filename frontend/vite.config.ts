import { fileURLToPath, URL } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  base: "./",
  input: {
    preview: fileURLToPath(new URL("./index.html", import.meta.url)),
    subtitle: fileURLToPath(new URL("./subtitle.html", import.meta.url)),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
})
