"""Yığın yardımcıları: `docker compose exec` ile salt okuma denetimleri ve `make` hedefleri.

- core-worker'ın model kipini (`TP_MODEL_MODE`, `TP_REPLAY_STRICT`) okur — yalnızca bu iki sır
  olmayan değişkeni `printenv` ile ister; ortamın geri kalanı okunmaz.
- `ai_call` tablosundan prova başından beri yapılan model çağrılarının kiplerini sayar (salt okuma
  SELECT): REPLAY-MISS ya da sahte "live" varsa prova FAIL olur (Constitution VIII).
- Bot kimliğiyle forge main'e doğrudan commit dener (LocalForge.commit_files): korunan dal
  koruması ForgeProtectionError vermeli, main değişmemeli (§13 kontrol listesi).
- Sunucunun terminalde koşturduğu hedefleri (`make demo-break`) çalıştırır; çıktı maskelenip
  rapora yazılır.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tp_rehearsal.env import Sirlar

# core-worker'da koşar; yalnızca JSON özet yazar. Koruma bozuksa commit gerçekten main'e girer
# (prova FAIL olur; yığın `make reset` ile temizlenir).
BOT_PUSH_BETIGI = """
import json
from tp_core.integrations.forge import ForgeProtectionError, get_forge
f = get_forge()
once = f.head_sha()
sonuc = {"reddedildi": False, "hata_turu": None}
try:
    f.commit_files("main", {"PROVA-SAHTE-PUSH.txt": "x"}, "prova: bot main'e dogrudan push")
except ForgeProtectionError as e:
    sonuc["reddedildi"] = True
    sonuc["hata_turu"] = type(e).__name__
except Exception as e:
    sonuc["hata_turu"] = type(e).__name__
sonuc["main_degismedi"] = f.head_sha() == once
print(json.dumps(sonuc))
"""


@dataclass
class KomutSonucu:
    komut: str
    kod: int
    cikti: str
    sure_s: float


@dataclass
class Yigin:
    repo: Path
    sirlar: Sirlar
    komutlar: list[KomutSonucu] = field(default_factory=list)

    def _calistir(
        self, argv: list[str], zaman_asimi_s: float = 120.0, kaydet: bool = True
    ) -> KomutSonucu:
        t0 = time.monotonic()
        try:
            p = subprocess.run(
                argv,
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=zaman_asimi_s,
                check=False,
            )
            kod, cikti = p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired as e:
            kod = 124
            cikti = f"zaman aşımı ({zaman_asimi_s:.0f} sn)\n{e.stdout or ''}{e.stderr or ''}"
        except FileNotFoundError as e:
            kod, cikti = 127, str(e)
        sonuc = KomutSonucu(
            " ".join(argv), kod, self.sirlar.maskele(cikti), round(time.monotonic() - t0, 1)
        )
        if kaydet:
            self.komutlar.append(sonuc)
        return sonuc

    def worker_ortami(self) -> dict[str, str]:
        """core-worker'daki model kipi bayrakları (sır değil)."""
        anahtarlar = ["TP_MODEL_MODE", "TP_REPLAY_STRICT", "TP_FORGE"]
        sonuc: dict[str, str] = {}
        for a in anahtarlar:
            r = self._calistir(
                ["docker", "compose", "exec", "-T", "core-worker", "printenv", a], 30, kaydet=False
            )
            sonuc[a] = r.cikti.strip() if r.kod == 0 else ""
        return sonuc

    def psql(self, sql: str) -> list[list[str]] | None:
        """Çekirdek veritabanında salt okuma sorgusu; erişilemezse None."""
        r = self._calistir(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                "tp",
                "-v",
                "ON_ERROR_STOP=1",
                "-AtF",
                "\t",
                "-c",
                sql,
            ],
            60,
            kaydet=False,
        )
        if r.kod != 0:
            return None
        return [s.split("\t") for s in r.cikti.splitlines() if s.strip()]

    def ai_call_kipleri(self, baslangic_iso: str) -> list[dict[str, Any]] | None:
        """Prova başından beri model çağrıları: [{mod, amac, sayi}]."""
        # baslangic_iso bizim ürettiğimiz ISO zaman damgasıdır (dışarıdan gelmez).
        satirlar = self.psql(
            "SELECT mod, amac, count(*) FROM ai_call "
            f"WHERE olusturma >= '{baslangic_iso}'::timestamptz GROUP BY 1, 2 ORDER BY 1, 2"
        )
        if satirlar is None:
            return None
        return [{"mod": s[0], "amac": s[1], "sayi": int(s[2])} for s in satirlar if len(s) == 3]

    def bot_main_push_dene(self) -> dict[str, Any] | None:
        """Sahte bot push'u: main'e doğrudan commit. {reddedildi, main_degismedi, hata_turu}."""
        r = self._calistir(
            ["docker", "compose", "exec", "-T", "core-worker", "python", "-c", BOT_PUSH_BETIGI],
            60,
        )
        if r.kod != 0:
            return None
        satir = next((s for s in reversed(r.cikti.splitlines()) if s.startswith("{")), "")
        try:
            return json.loads(satir)
        except ValueError:
            return None

    def make(self, hedef: str, zaman_asimi_s: float = 600.0) -> KomutSonucu:
        return self._calistir(["make", hedef], zaman_asimi_s)
