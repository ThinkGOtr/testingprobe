"""Dış sistem adaptörleri (Jira, test yönetimi, forge).

Her adaptör `tp_core.ports` içindeki bir Protocol'ü uygular; seçim ortam değişkeniyle yapılır
(ör. `TP_FORGE=local|github` → `tp_core.integrations.forge.get_forge`). Modüller burada
içe aktarılmaz; tüketici ihtiyaç duyduğu adaptör modülünü doğrudan içe aktarır.
"""
