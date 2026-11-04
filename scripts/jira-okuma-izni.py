"""security-check 8 alt adımı: Jira okuma hesabı yazma izni taşımaz (AI-ASISTAN-PLANI §5.6, R14).

core-worker içinde çalışır (``compose exec -T core-worker python - < scripts/jira-okuma-izni.py``);
``JIRA_READ_*`` kimliğiyle ``GET /rest/api/3/mypermissions`` sorar. Proje bağlamı verilmez: Jira bu
durumda izni *herhangi bir projede* taşıyıp taşımadığını döndürür (en sıkı yorum; okuma hesabı
yalnız bu ürüne ayrılmış olmalı, docs/GERCEK-SISTEMLER.md §2.2).

Simülatörde atlanır (jira-sim'in izin modeli yok). Kimlik, adres ya da yanıt gövdesi asla
yazdırılmaz; çıktı tek satırdır:

    ATLA <neden> | TAMAM | YAZMA <izin,...> | HATA <sınıf>

Çıkış kodu: ATLA/TAMAM → 0, YAZMA/HATA → 1. Asistanın kod katmanları (yazma yöntemi olmayan
``JiraOkuyucu`` + yalnız-GET transport) bu kontrolden bağımsızdır; bu üçüncü katmandır.
"""

from __future__ import annotations

import sys

import httpx

from tp_core.integrations.jira import JiraSettings

YAZMA_IZINLERI = ("ADD_COMMENTS", "CREATE_ISSUES", "EDIT_ISSUES")
MYPERMISSIONS_YOLU = "/rest/api/3/mypermissions"


def denetle(
    settings: JiraSettings | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = 10.0,
) -> tuple[str, str]:
    """(durum, ayrıntı) döndürür; ayrıntı yalnız sınıf/izin adıdır, değer içermez."""
    s = settings or JiraSettings()
    if s.is_simulator:
        return "ATLA", "simulator"
    eposta = (s.jira_read_email or "").strip()
    token = s.jira_read_token.get_secret_value().strip() if s.jira_read_token else ""
    if not eposta or not token:
        return "HATA", "okuma_kimligi_yok"
    try:
        with httpx.Client(
            base_url=s.jira_base_url.rstrip("/"),
            auth=(eposta, token),
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        ) as istemci:
            yanit = istemci.get(
                MYPERMISSIONS_YOLU,
                params={"permissions": ",".join(YAZMA_IZINLERI)},
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        return "HATA", type(exc).__name__
    if yanit.status_code != 200:
        return "HATA", f"http_{yanit.status_code}"
    try:
        izinler = yanit.json().get("permissions")
    except (ValueError, AttributeError):
        return "HATA", "gecersiz_yanit"
    if not isinstance(izinler, dict):
        return "HATA", "gecersiz_yanit"
    tasinan: list[str] = []
    for ad in YAZMA_IZINLERI:
        kayit = izinler.get(ad)
        # Yanıtta izin yoksa doğrulanamadı sayılır (sessizce TAMAM denmez).
        if not isinstance(kayit, dict) or not isinstance(kayit.get("havePermission"), bool):
            return "HATA", f"izin_yanitta_yok:{ad}"
        if kayit["havePermission"]:
            tasinan.append(ad)
    if tasinan:
        return "YAZMA", ",".join(tasinan)
    return "TAMAM", ""


def main() -> int:
    durum, ayrinti = denetle()
    print(f"{durum} {ayrinti}".rstrip())
    return 0 if durum in ("ATLA", "TAMAM") else 1


if __name__ == "__main__":
    sys.exit(main())
