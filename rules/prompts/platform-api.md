---
id: platform-api
version: 1
kind: platform_ek
host: case-generation
---
Platform: API / backend. Web, mobile and desktop clients share these services, so business rules
are cheapest to verify here. Input: the API contract in the options block line
`API sözleşmesi (OpenAPI/endpoint tanımı)` (when `API sözleşmesi var: evet` but no contract text
is given, record an open question that the contract is missing) and `Kimlik doğrulama tipi`.
When a contract is given, relate each case to its operation/schema. A response code or field that
is not in the contract or the story is never written as a requirement: open question.

For each endpoint the story touches, consider these categories (checklist, not quota):

1. Schema validation (EP+BVA): per field type, required/optional, null, empty string, min/max,
   value outside the enum, unknown extra field, missing nested object, array with 0/1/max/max+1
   items (limits only from the contract/story).
2. HTTP semantics: the status codes defined in the contract, wrong method, wrong Content-Type,
   missing/broken JSON, large payload.
3. Identity and authorization: no token / expired / invalid signature / another user's resource
   (BOLA/IDOR), role × action decision table, privilege escalation.
4. Business rules (DT/ST): resource lifecycle (create → update → cancel), forbidden transitions.
5. Concurrency: parallel PUT on the same record (optimistic lock / ETag), race that exceeds a limit.
6. Paging and filters: page = 0/1/last/last+1, size = 0/1/max/max+1, invalid sort field.
7. Resilience: dependent service timeout/5xx, partial failure.
8. Data security: no stack trace or SQL in error responses, PII masking, injection.

Idempotency, retry, rate limit and timeout behaviour are expected results ONLY when the contract or
an acceptance criterion states them; otherwise open question.
For each case write the request (method, path, headers, body) in the steps and the expected
response (status, body schema, critical field values, side effect: DB / queue / log) in the
expected results, with `verification_point` `API` (or `DB`/`event`/`log` for the side effect).
Relevant OWASP API Security Top 10 2023 items go to `standard_refs` (`API1:2023` BOLA: another
user's id; `API3:2023` BOPLA: updating a field the role may not change; `API4:2023` resource
consumption: only at a defined limit). The list is an awareness checklist, not a product rule.
Keep the cases translatable to the automation tool in the options block (REST Assured, Postman,
Karate, pytest); without a tool, write no code.
