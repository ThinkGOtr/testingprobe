import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after } from "node:test";

const created: string[] = [];
after(() => {
  for (const d of created) rmSync(d, { recursive: true, force: true });
});

export function tmp(prefix = "ast-guard-"): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  created.push(d);
  return d;
}

export type Tree = Record<string, string>;

export function writeTree(dir: string, tree: Tree): string {
  for (const [rel, content] of Object.entries(tree)) {
    const abs = join(dir, rel);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, content);
  }
  return dir;
}

/** İki dizin oluşturur: base ve head (head = base + değişiklikler; null = sil). */
export function makePair(base: Tree, changes: Record<string, string | null>): { base: string; head: string } {
  const root = tmp();
  const b = writeTree(join(root, "base"), base);
  const headTree: Tree = { ...base };
  for (const [k, v] of Object.entries(changes)) {
    if (v === null) delete headTree[k];
    else headTree[k] = v;
  }
  mkdirSync(join(root, "head"), { recursive: true });
  const h = writeTree(join(root, "head"), headTree);
  return { base: b, head: h };
}

export function git(repo: string, ...args: string[]): string {
  return execFileSync("git", ["-C", repo, ...args], {
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: "t",
      GIT_AUTHOR_EMAIL: "t@example.invalid",
      GIT_COMMITTER_NAME: "t",
      GIT_COMMITTER_EMAIL: "t@example.invalid",
      GIT_CONFIG_NOSYSTEM: "1",
      HOME: tmpdir(),
    },
    stdio: ["ignore", "pipe", "pipe"],
  })
    .toString("utf8")
    .trim();
}

export function initRepo(tree: Tree): string {
  const repo = tmp("ast-guard-git-");
  git(repo, "init", "-q", "-b", "main");
  git(repo, "config", "commit.gpgsign", "false");
  writeTree(repo, tree);
  git(repo, "add", "-A");
  git(repo, "commit", "-q", "-m", "base");
  return repo;
}

export function commit(repo: string, changes: Record<string, string | null>, msg = "change"): string {
  for (const [rel, v] of Object.entries(changes)) {
    if (v === null) rmSync(join(repo, rel));
    else writeTree(repo, { [rel]: v });
  }
  git(repo, "add", "-A");
  git(repo, "commit", "-q", "-m", msg);
  return git(repo, "rev-parse", "HEAD");
}

export const CART_LOCATORS = `// Sepet sayfası locator'ları — saf veri.
export const cart = {
  addToCart: {
    testId: "add-to-cart",
    role: "button",
    name: "Sepete ekle",
    intent: "Ürün kartında sepete ekleme butonu",
  },
  cartCount: { testId: "cart-count", role: "status", name: "Sepet", intent: "Sepetteki ürün sayısı" },
} as const;

export const cartLines = {
  subtotal: { testId: "cart-subtotal", role: "cell", name: "Ara toplam", intent: "Sepet ara toplamı" },
} as const;
`;

export const LOGIN_LOCATORS = `export const login = {
  username: { testId: "login-username", role: "textbox", name: "Kullanıcı adı", intent: "Kullanıcı adı alanı" },
  submit: { testId: "login-submit", role: "button", name: "Giriş", intent: "Giriş butonu" },
} as const;
`;

export const BASE_TREE: Tree = {
  "pages/cart/locators.ts": CART_LOCATORS,
  "pages/cart/CartPage.ts": `import { cart } from "./locators";\nexport class CartPage { readonly id = cart.addToCart.testId; }\n`,
  "pages/login/locators.ts": LOGIN_LOCATORS,
  "tests/cart.spec.ts": `import { test } from "@playwright/test";\ntest("x", async () => {});\n`,
  "playwright.config.ts": "export default {};\n",
};
