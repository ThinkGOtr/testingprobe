"""Çalışan demo-app-web'in hangi commit'ten derlendiği ve istenen commit'le uyumu.

Yerel `/check` ve `/locator-probe` testleri compose'da ÇALIŞAN uygulamaya karşı koşar (GitHub CI
ise uygulamayı checkout'tan `webServer` ile başlatır). Sonuç ancak çalışan uygulamanın kaynak
ağacı (`TP_APP_PATHS`, varsayılan `web`, `api`) istenen commit'inkiyle aynıysa o commit'e aittir.
Karşılaştırma sha eşitliğiyle değil **ağaç kimliğiyle** yapılır: yalnızca `e2e/` değiştiren bir
kod üretimi dalı, uygulaması `main` ile aynı olduğu için `eslesiyor` sayılır; uygulama kodunu
değiştiren bir PR (ör. F2 düzeltmesi, demo/break-locator) `farkli` olur.

Çalışan uygulamanın commit'i: `TP_APP_BUILD_SHA_FILE` (varsayılan `/forge/demo-app-web.sha`;
demo-app-web'i derleyen betik yazar, konteyner yeniden oluşturulmadan güncellenir), yoksa
`DEMO_APP_BUILD_SHA` ortam değişkeni.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from toolchain_common import gitforge, repos
from toolchain_common.settings import Settings
from toolchain_common.validation import SHA_RE

Eslesme = Literal["eslesiyor", "farkli", "dogrulanamadi"]
MAX_FILE = 4096


def build_sha(cfg: Settings) -> tuple[str | None, str]:
    """(sha, kaynak): dosya > ortam; geçersiz/boş → (None, …)."""
    try:
        raw = cfg.app_build_sha_file.read_text(encoding="utf-8")[:MAX_FILE]
        first = (raw.strip().splitlines() or [""])[0].strip()
        if first:
            return first[:64], "dosya"
    except OSError:
        pass
    if cfg.probe_app_sha:
        return cfg.probe_app_sha[:64], "ortam"
    return None, "yok"


@dataclass
class AppMatch:
    eslesme: Eslesme
    uygulama_sha: str | None
    kaynak: str
    farkli_yollar: list[str] = field(default_factory=list)
    uyari: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sha_eslesmesi": self.eslesme,
            "uygulama_sha": self.uygulama_sha,
            "uygulama_sha_kaynagi": self.kaynak,
            "farkli_yollar": list(self.farkli_yollar),
            "uyari": self.uyari,
        }


def match(cfg: Settings, requested: repos.Located) -> AppMatch:
    """Çalışan uygulamanın ağacını `requested` commit'inin ağacıyla karşılaştırır."""
    raw, kaynak = build_sha(cfg)
    if raw is None:
        return AppMatch(
            "dogrulanamadi",
            None,
            kaynak,
            uyari=(
                "Ölçüm/koşu çalışan demo uygulamasında yapıldı; uygulamanın derlendiği commit "
                "bilinmiyor, sonuç istenen sha'ya ait olmayabilir."
            ),
        )
    if not SHA_RE.match(raw):
        return AppMatch(
            "dogrulanamadi",
            None,
            kaynak,
            uyari="Çalışan uygulamanın derleme sha'sı geçersiz; forge'da bulunamadı.",
        )
    try:
        app = repos.locate(cfg, raw, prefer=cfg.forge_path)
    except (gitforge.ForgeError, gitforge.CommitNotFound, ValueError):
        return AppMatch(
            "dogrulanamadi",
            raw,
            kaynak,
            uyari=(
                "Çalışan uygulamanın derleme sha'sı forge'da bulunamadı; sonuç istenen sha'ya "
                "ait olmayabilir."
            ),
        )
    if app.sha == requested.sha:
        return AppMatch("eslesiyor", app.sha, kaynak)
    differs = [
        path
        for path in cfg.app_paths
        if gitforge.tree_id(app.repo, app.sha, path, cfg.git_timeout_s)
        != gitforge.tree_id(requested.repo, requested.sha, path, cfg.git_timeout_s)
    ]
    if not differs:
        return AppMatch("eslesiyor", app.sha, kaynak)
    return AppMatch(
        "farkli",
        app.sha,
        kaynak,
        farkli_yollar=differs,
        uyari=(
            f"Çalışan uygulama {app.sha[:12]} commit'inden derlenmiş; istenen sha "
            f"{requested.sha[:12]} uygulama kodunda farklı ({', '.join(differs)})."
        ),
    )
