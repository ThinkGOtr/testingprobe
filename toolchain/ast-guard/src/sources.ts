// Kaynak soyutlaması: karşılaştırılan iki taraf ya bir dizin ya da bir git ref'idir.
// Her iki tür de dosya listesini "git blob kimliği" ile verir; böylece dizin ↔ ref karışık
// karşılaştırma da aynı yoldan yapılır.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstatSync, readdirSync, readFileSync, readlinkSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

export interface FileEntry {
  /** git blob kimliği (sha1("blob <len>\0" + içerik)); symlink/submodule için ayırt edici önek */
  id: string;
}

export interface Source {
  readonly kind: "dir" | "git";
  readonly label: string;
  /** Kök göreli POSIX yol → giriş */
  list(): Map<string, FileEntry>;
  read(path: string): string;
}

/** Dizin modunda yok sayılan dizinler (git'te zaten izlenmezler). */
export const IGNORED_DIRS: ReadonlySet<string> = new Set([
  ".git",
  "node_modules",
  "dist",
  "results",
  "test-results",
  "playwright-report",
  "allure-results",
  ".venv",
  "__pycache__",
]);

export function gitBlobId(content: Buffer): string {
  return createHash("sha1")
    .update(`blob ${content.length}\0`)
    .update(content)
    .digest("hex");
}

export class DirSource implements Source {
  readonly kind = "dir" as const;
  readonly label: string;
  private readonly dir: string;
  private cache: Map<string, FileEntry> | undefined;

  constructor(dir: string) {
    this.dir = resolve(dir);
    this.label = this.dir;
  }

  list(): Map<string, FileEntry> {
    if (this.cache) return this.cache;
    const out = new Map<string, FileEntry>();
    const walk = (abs: string, rel: string): void => {
      const names = readdirSync(abs).sort();
      for (const name of names) {
        const childAbs = join(abs, name);
        const childRel = rel === "" ? name : `${rel}/${name}`;
        const st = lstatSync(childAbs);
        if (st.isSymbolicLink()) {
          out.set(childRel, { id: `symlink:${readlinkSync(childAbs)}` });
        } else if (st.isDirectory()) {
          if (!IGNORED_DIRS.has(name)) walk(childAbs, childRel);
        } else if (st.isFile()) {
          out.set(childRel, { id: gitBlobId(readFileSync(childAbs)) });
        }
      }
    };
    walk(this.dir, "");
    this.cache = out;
    return out;
  }

  read(path: string): string {
    return readFileSync(join(this.dir, path), "utf8");
  }
}

function git(repo: string, args: string[]): Buffer {
  return execFileSync("git", ["-C", repo, ...args], {
    maxBuffer: 256 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

export class GitSource implements Source {
  readonly kind = "git" as const;
  readonly label: string;
  readonly commit: string;
  private readonly repo: string;
  private cache: Map<string, FileEntry> | undefined;

  constructor(repo: string, ref: string) {
    this.repo = resolve(repo);
    try {
      this.commit = git(this.repo, ["rev-parse", "--verify", "--quiet", `${ref}^{commit}`])
        .toString("utf8")
        .trim();
    } catch {
      throw new Error(`git ref çözülemedi: ${ref} (repo: ${this.repo})`);
    }
    if (!/^[0-9a-f]{40,64}$/.test(this.commit)) {
      throw new Error(`git ref çözülemedi: ${ref} (repo: ${this.repo})`);
    }
    this.label = `${ref}@${this.commit.slice(0, 12)}`;
  }

  list(): Map<string, FileEntry> {
    if (this.cache) return this.cache;
    const out = new Map<string, FileEntry>();
    const raw = git(this.repo, ["ls-tree", "-r", "-z", "--full-tree", this.commit]).toString("utf8");
    for (const rec of raw.split("\0")) {
      if (rec === "") continue;
      const tab = rec.indexOf("\t");
      const [mode, type, oid] = rec.slice(0, tab).split(" ");
      const path = rec.slice(tab + 1);
      if (type === "blob") {
        out.set(path, { id: mode === "120000" ? `symlink-blob:${oid}` : (oid ?? "") });
      } else if (type === "commit") {
        out.set(path, { id: `submodule:${oid}` });
      }
    }
    this.cache = out;
    return out;
  }

  read(path: string): string {
    const entry = this.list().get(path);
    if (!entry) throw new Error(`${this.label} içinde dosya yok: ${path}`);
    return git(this.repo, ["cat-file", "blob", entry.id]).toString("utf8");
  }
}

/** Var olan bir dizinse dizin kaynağı, değilse `repo` içindeki git ref'i. */
export function openSource(spec: string, repo: string): Source {
  let isDir = false;
  try {
    isDir = statSync(spec).isDirectory();
  } catch {
    isDir = false;
  }
  return isDir ? new DirSource(spec) : new GitSource(repo, spec);
}
