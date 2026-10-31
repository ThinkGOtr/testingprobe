"""Kod üretimi (CasesToCode; TEKNIK-TASARIM §8.4): doğrula → eşle → şablon → yerel kontrol → PR.

Modüller: `service` (akış, işler), `api` (uçlar), `jobs` (worker işleyicileri), `browser`
(Playwright MCP vekili), `checks` (deterministik eşleme kontrolleri), `normalize` (beklenen değer
kaynağı normu), `render` (Jinja2 şablonu), `classify` (yerel kontrol sınıfı), `toolchain`
(toolchain-worker istemcisi), `prbody` (PR açıklaması), `views` (portal yanıtları).
"""
