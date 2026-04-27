import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    // Mock the vscode module so tests can run outside VS Code.
    alias: {
      vscode: fileURLToPath(new URL("./src/__mocks__/vscode.ts", import.meta.url)),
    },
  },
});
