"""`.env` okuma ve sır maskeleme.

Prova `.env`'deki parolaları (portal seed kullanıcıları, jira-sim PO) kullanır ama hiçbir değeri
yazdırmaz: rapor ve log'a giden her metin `Sirlar.maskele` ile geçer. Değeri olan ve adı sır
kalıbına uyan her anahtar maskelenir (ANTHROPIC_API_KEY dahil; prova onu hiç kullanmaz).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SIR_KALIBI = re.compile(r"(PASSWORD|PASSWD|TOKEN|SECRET|_KEY|PRIVATE)", re.IGNORECASE)
# Kısa değerler (ör. "sim", "0") metinde her yerde geçer; maskelemek raporu bozar, sızıntı değildir.
EN_KISA_SIR = 6


def env_oku(yol: Path) -> dict[str, str]:
    """Basit KEY=VALUE ayrıştırıcı (yorum, boş satır, `export` öneki, tırnak)."""
    sonuc: dict[str, str] = {}
    if not yol.is_file():
        return sonuc
    for ham in yol.read_text(encoding="utf-8").splitlines():
        satir = ham.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        if satir.startswith("export "):
            satir = satir[len("export ") :]
        anahtar, deger = satir.split("=", 1)
        deger = deger.strip()
        if len(deger) >= 2 and deger[0] == deger[-1] and deger[0] in "'\"":
            deger = deger[1:-1]
        sonuc[anahtar.strip()] = deger
    return sonuc


@dataclass
class Sirlar:
    degerler: list[str] = field(default_factory=list)

    @classmethod
    def ortamdan(cls, env: dict[str, str]) -> Sirlar:
        degerler = {
            v for k, v in env.items() if SIR_KALIBI.search(k) and v and len(v) >= EN_KISA_SIR
        }
        # Uzun değerler önce: biri diğerinin öneki ise kısmi maske kalmasın.
        return cls(sorted(degerler, key=len, reverse=True))

    def maskele(self, metin: str) -> str:
        for d in self.degerler:
            if d in metin:
                metin = metin.replace(d, "***")
        return metin


@dataclass
class Ortam:
    """Prova ayarları. Öncelik: süreç ortamı > `.env` > varsayılan."""

    repo: Path
    env: dict[str, str]
    sirlar: Sirlar

    @classmethod
    def yukle(cls, repo: Path) -> Ortam:
        env = env_oku(repo / ".env")
        return cls(repo=repo, env=env, sirlar=Sirlar.ortamdan({**env, **os.environ}))

    def al(self, anahtar: str, varsayilan: str = "") -> str:
        return os.environ.get(anahtar) or self.env.get(anahtar) or varsayilan

    @property
    def api_url(self) -> str:
        port = self.al("TP_PORTAL_PORT", "8080")
        return self.al("TP_API_URL", f"http://127.0.0.1:{port}/api").rstrip("/")

    @property
    def jira_url(self) -> str:
        port = self.al("JIRA_SIM_PORT", "8090")
        return self.al("JIRA_SIM_URL", f"http://127.0.0.1:{port}").rstrip("/")

    @property
    def portal_parolasi(self) -> str:
        return self.al("TP_PROVA_PAROLA") or self.al("SEED_USER_PASSWORD")

    @property
    def po_parolasi(self) -> str:
        return self.al("JIRA_SIM_PO_PASSWORD")
