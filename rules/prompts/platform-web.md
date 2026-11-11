---
id: platform-web
version: 1
kind: platform_ek
host: case-generation
---
Platform: Web. Web-specific risks are browser behaviour, session, URL and multiple tabs. Targets
come from the options block lines `Tarayıcılar` and `Çözünürlükler`; when they are missing, the
support policy is an open question (common rules). Test what the user sees; do not depend on
implementation details such as CSS classes.

Besides the functional cases, consider these categories for the story (checklist, not quota):

1. Browser behaviour: Back/Forward, page refresh in the middle of a form, double click / double
   submit, autofill, copy-paste.
2. Session and state: session timeout (only when the source gives the duration: timeout-1 s /
   timeout / +1 s), the same record edited in two tabs, Back after logout, cleared
   cookies/localStorage, "remember me".
3. URL and authorization: direct URL to a page the role may not open, changing an id in the URL
   (IDOR), query parameter manipulation, login redirect after a deep link.
4. Responsive: breakpoints defined in the design (for example 767/768/769 px), zoom 200 %,
   horizontal scrolling. Only breakpoints the source or options give.
5. Input security (permitted test environment only): XSS, SQL injection, HTML injection, very long
   input, Unicode/emoji/RTL text, leading/trailing spaces. Attack text only in `test_data`.
6. Network: slow connection, connection lost during a request, the UI on a 500/503/timeout
   response, loading state and button lock. The UI reaction is an expected result only when the
   source states it; otherwise open question.
7. Accessibility: keyboard-only completion, focus order, screen reader labels, error message tied
   to its field (aria-describedby), contrast. Tag with WCAG 2.2 criterion numbers (for example
   `WCAG-2.4.11` focus not obscured, `WCAG-2.5.7` dragging alternative, `WCAG-3.3.8` accessible
   authentication, `WCAG-3.2.6` consistent help, `WCAG-3.3.7` redundant entry). For
   `WCAG-2.5.8` target size (24×24 CSS px) also evaluate the spacing, equivalent control, inline,
   user-agent and essential exceptions; do not fail a small target without checking them.
8. Localization: language switch, date/currency/decimal format (1.234,56 vs 1,234.56), Turkish
   characters (İ/ı, Ş/ş) in search and sorting.

Security cases are tagged with OWASP WSTG codes (for example `WSTG-SESS-01`); WSTG is a test
method guide, not a product rule.

Configuration coverage: apply pairwise to browser × viewport × language × role with the values in
the options block and source, as `config_matrix` (common rules; no rows, no copied cases).
Keep tests isolated; third-party services are stubbed or mocked (state the need).
Selectors: only when the options block names an automation tool, suggest role/label/data-testid
based selectors in `automation_open_points`; otherwise suggest none.
