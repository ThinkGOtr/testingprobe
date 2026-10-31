"""Gereksinim özelliği: Jira/serbest metin gereksinimi → ön inceleme → tutarlılık denetimi →
analist kararları → doküman düzeltmesi → PO teyidi (TEKNIK-TASARIM §2 adım 1–3, §8.2, §8.2a,
§8.2b; MIMARI-SOZLESME §5).

Modüller:

- `api`        — HTTP uçları (registry otomatik bağlar)
- `jobs`       — worker işleri (`@job_handler`; worker `discover()` ile yükler)
- `flow`       — iş mantığı (durum geçişleri yalnızca `workflow.service.transition`)
- `content`    — içerik hash'i, AC ayrıştırma, deterministik düzeltme birleştirme kuralları
- `sqlguard`, `datatools` — `db_schema`/`db_query` (tek SELECT, izin listesi, salt okuma)
- `codetools`  — forge üzerinde salt okuma kod araçları (sabit commit)
- `verifier`   — LLM'siz kanıt doğrulayıcı (Constitution XI)
- `services`   — dış bağımlılık fabrikaları (Jira, forge, model geçidi, demo DB); testler değiştirir
"""
