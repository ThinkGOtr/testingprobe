---
id: platform-data
version: 1
kind: platform_ek
host: case-generation
---
Platform: Data / integration (database, message queue, batch). Tests the data flow behind the UI
and API (ETL, messaging, scheduled jobs). Input: the options block lines `Sistemler` (source and
target systems), `Mesaj şeması`, `Dönüşüm kuralları` and `Teslim garantisi` (at-most-once,
at-least-once, exactly-once). When one is missing and a case depends on it, open question.

Consider these categories for the story (checklist, not quota):

1. Each transformation rule: source → target mapping with EP/BVA (null, empty, maximum length,
   type conversion, character encoding, time zone, decimal precision, truncation).
2. Message scenarios ONLY when meaningful for the product behaviour: duplicate, out of order,
   delayed, missing, malformed (outside the schema), redelivered, poison message / DLQ. The
   expected handling comes from the delivery guarantee and the source; otherwise open question.
3. Atomicity, rollback, re-run, idempotency and partial failure (for example an error in the
   middle of a batch).
4. Batch limits: 0 records, 1 record, batch size-1 / size / +1, time window boundary
   (23:59:59 / 00:00:00), two overlapping runs. Sizes only from the source.
5. Write UI/API behaviour and data consistency checks as SEPARATE cases; the data check has
   `verification_point` `DB`, `event` (queue) or `log`.
6. Use synthetic data and state the cleanup in `teardown`; never production data.
