# Technical source recovery, second batch — 2026-09-27

Public HTTP only; no database access, user browser, source/default changes or commits.

- **Samsung Research Israel:** old `/sril/careers` endpoint is404. The official
  [SRIL page](https://research.samsung.com/sril) links Samsung's Workday board.
  Exact Israel facets return6jobs; only1 has `hiringOrganization.name` equal to
  `Samsung R&D Institute Israel`. The bounded adapter retains R119315 with its
  full2,889-character description and explicit Herzliya location. Other Samsung
  sales/marketing subsidiaries are not relabeled as Research. Live result passes
  scanner validation and remains partial.
- **Chain Reaction:** official careers page publishes Comeet companyA6.00D.
  Public company metadata confirms `chainreaction`, matching employer domain and
  name. The positions feed currently returns literal `[]`. Route now uses the
  existing typed Comeet adapter. This recognized empty result is partial and
  cannot retire history; malformed payloads still fail. A fixture verifies full
  requirements, country and stable UID handling when future jobs appear.
- **Rafael:** official search returns the known247challenge. The configured
  Drushim company fallback returns404. Old candidate URLs do not prove usable
  full mirror descriptions. No speculative hydration bypass was applied.
- **Tower Semiconductor:** official page and Japanese-domain variant return403.
  The indexed official Japanese page links `https://careers.towersemi.com/`;
  this endpoint also returns403 directly. No validated feed recovered.
- **Pliops:** both official www/non-www career endpoints return403. No verified
  replacement ATS found. Existing jobs remain protected.

Samsung adds no database queries: at most1discovery+2listing+40detail public
requests,4MB per response,4 concurrent details,40returned jobs,24K description
characters. Chain Reaction makes1public request,4MB maximum,200rows maximum.
Root owns production egress impact documentation and deployment gating.

170targeted tests passed: Samsung/Chain, pending source audit, Webv3/v4, and the
independent agent's tech-board recovery suite. Full suite and production rollout
were not performed by this agent. Samsung live full result and blocked-source
URLs/statuses are recorded in the adjacent JSON artifact.
