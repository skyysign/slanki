import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["app/test/**/*.test.ts", "helper/test/**/*.test.ts"],
    environment: "node",
    testTimeout: 60000,
  },
});
