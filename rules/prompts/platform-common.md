---
id: platform-common
version: 1
kind: platform_ek
host: case-generation
---
These rules apply to every platform section below. They extend the case rules; they never
override the source rules (no invented rule, message, code, threshold or timing).

- **Checklist, not quota.** The categories in a platform section are a checklist. Write a case only
  for a category that is relevant to the story and carries risk. For a category you skip, add one
  `not_covered` entry (`item`: `<Web|Mobil|Desktop|API|Data>:<category>`, at most 40 characters,
  for example `Web:Responsive`, `Mobil:Kesintiler`) with the reason ("story has no …"). Do not write one case per category to fill the
  list. The limits stay: at most 10 cases per story and 8 steps per case.
- **Values in the sections are placeholders.** Numbers in a platform section (versions, sizes,
  durations, breakpoints) are examples. A value becomes an expected result only when the story, an
  acceptance criterion, a PO answer, the analyst options block or an adopted standard states it.
- **Adopted standards.** The analyst options block has a line `Benimsenen standartlar:`. Only the
  standards listed there are adopted by the product. A threshold or rule from an adopted standard
  may be an expected result; put its id in the case's `standard_refs` (for example `WCAG-2.4.11`,
  `MASVS-STORAGE-1`, `API1:2023`, `WACK-CleanInstall`). A rule from a standard or platform guideline
  that is NOT listed (or the line says `yok`) is never an expected result: report it in
  `observations` (`standard_ref` + one-sentence `note`) and do not call it passed or failed. You
  may still tag a case with a non-adopted standard id in `standard_refs` when the case's expected
  result comes from the source itself.
- **Support matrix.** When the options block does not give the browsers, OS versions or devices
  the product supports, do not choose them yourself: record an open question about the product's
  support policy (owner `PO`).
- **Configuration coverage.** When a platform section asks for pairwise configuration coverage,
  fill `config_matrix` with the parameters and their values (`parameters`) and the constraints
  between them (`constraints`, for example `IF Platform = "iOS" THEN Browser = "Safari"`). Do NOT
  write combination rows: a tool generates them from this model. Do not copy cases per
  combination; the functional cases run in every row. Use only values given in the options block
  or the source; when values are missing, leave the parameter out and record an open question.
- **Platform field.** `platform` is the platform the case is specific to (one of the selected
  platforms), or `null` when the case is platform-independent. When two platforms behave
  differently, write separate cases with their own `platform`.
- **Real device.** Set `requires_real_device: true` only for a case that cannot be verified on an
  emulator, simulator or virtual machine (camera, sensors, biometrics, real cellular network,
  battery, incoming call). Otherwise `false`.
- **Testability gaps.** When the story or options name a control that has no stable automation
  identity known to you, add a `testability_gaps` entry (`control`, `missing`: `AutomationId`,
  `accessible_name` or `test_id`) only if the options block names an automation tool; otherwise
  list the need in `automation_open_points`. Never invent selectors, locators or ids.
- **Test-type rules.** Performance: without load, data size, concurrency, a time target and a
  measurement environment in the source, write no threshold; ask for the missing values as open
  questions. Compatibility: without a support matrix, the support policy is an open question.
  Accessibility: keyboard-only flow, focus order, accessible name/role/state; the target level is
  the product's (adopted standards line). Security: only in a permitted test environment with
  synthetic data; attack text only in `test_data` with `is_attack_payload: true`; expected result
  is the rejection or non-disclosure the source supports.
