# STEP 2 Manual Acceptance

Date: 2026-08-24

Knowledge Workspace v2.11.4.1 received manual visual acceptance from the
user after reviewing the production-bundle review pages. The accepted
candidate is the final STEP 2 commit and is the baseline for STEP 3.

The reviewed representative-page measurements were:

| Scenario | Formal comparator mismatch |
| --- | ---: |
| GM-04 Add Data | 0.126929% |
| GM-10 Dashboard | 0.637037% |
| GM-13 Knowledge Graph | 0.333488% |

The complete 132-pair visual matrix was not executed. This is an explicit
manual visual waiver. The values above must not be described as passing the
automated `<= 0.1%` visual gate, and this waiver does not alter the frozen
baseline, thresholds, masks, or comparator rules.

The final STEP 2 tag created from the accepted commit is:

`knowledge-v2.11.4.1-commercial-step-2`

STEP 3 work must use that final tag as its baseline. The production profile
continues to use the real HTTP/SSE Adapter and fail-closed behavior; the
manual acceptance does not authorize fixtures, mocks, localStorage business
state, or static success in the production import graph.
