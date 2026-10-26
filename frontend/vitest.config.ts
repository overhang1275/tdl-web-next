import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  test: {
    server: { deps: { inline: ["next-auth"] } },
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    globals: true,
    include: ["test/**/*.test.ts", "test/**/*.test.tsx"],
  },
  resolve: {
    alias: { "@": root },
  },
});
