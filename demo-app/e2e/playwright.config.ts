import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  outputDir: "./results/artifacts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["junit", { outputFile: "results/junit.xml" }],
    ["allure-playwright", { resultsDir: "results/allure-results" }],
  ],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8081",
    testIdAttribute: "data-testid",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
