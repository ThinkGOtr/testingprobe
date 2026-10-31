// ESLint düz yapılandırması. Komut satırında --no-inline-config ile koşar (yorumla kural kapatılamaz).
import js from "@eslint/js";
import playwright from "eslint-plugin-playwright";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules/", "results/", "playwright-report/", "test-results/"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/await-thenable": "error",
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    ...playwright.configs["flat/recommended"],
    files: ["tests/**/*.ts", "pages/**/*.ts"],
    rules: {
      ...playwright.configs["flat/recommended"].rules,
      // Doğrulamalar page object'lerin expect* metotlarındadır.
      "playwright/expect-expect": ["error", { assertFunctionPatterns: ["^expect", "^audit$"] }],
      "playwright/no-skipped-test": "error",
      "playwright/no-focused-test": "error",
      "playwright/no-wait-for-timeout": "error",
      "playwright/no-force-option": "error",
      "playwright/no-page-pause": "error",
      "playwright/no-networkidle": "error",
      "playwright/no-standalone-expect": "off",
    },
  },
  {
    files: ["**/*.js"],
    ...tseslint.configs.disableTypeChecked,
  },
);
