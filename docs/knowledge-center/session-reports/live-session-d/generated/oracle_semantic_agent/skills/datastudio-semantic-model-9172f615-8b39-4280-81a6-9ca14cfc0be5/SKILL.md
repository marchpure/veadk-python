---
name: datastudio-semantic-model-9172f615-8b39-4280-81a6-9ca14cfc0be5
description: Governed Oracle semantic model over sanitized DuckDB snapshot.
metadata:
  asset_type: semantic_model
  asset_id: 9172f615-8b39-4280-81a6-9ca14cfc0be5
  capability_kind: semantic_skill
  version: v1
  query_url: /api/external/assets/semantic_model/9172f615-8b39-4280-81a6-9ca14cfc0be5/query
---

# Oracle Sales Semantic Model session-h-oracle-20260818145458

Use this skill when answering questions that rely on this governed Byaan Data Studio asset.

## Asset

- Type: `semantic_model`
- ID: `9172f615-8b39-4280-81a6-9ca14cfc0be5`
- Capability: `semantic_skill`
- Version: `v1`
- Gate score: `100.0`

## Metrics

- ticket_count

## Dimensions

- store
- sell_date
- sell_state
- sell_type

## Time Field

- `hd.SELLDATE`

## Permission Boundary

- Use only governed aggregate data returned by Byaan.
- Do not expose masked fields or raw row-level identifiers unless the asset policy explicitly allows it.
- Treat the REST response policyDecision and evidence fields as authoritative.
- If the user asks for customer names, phone numbers, addresses, documents, or member-card identifiers, return the Byaan policy denial and do not issue a raw-data workaround.

## Example Questions

- Not declared

## Evidence Rules

- Every answer must include the returned numeric value or table result.
- Every answer must cite SQL, metric definition, lineage, or sample evidence returned by Byaan.
- Every answer must mention the permission or policy boundary that allowed the response.
- Every answer must include snapshot freshness when Byaan returns snapshot, dataThrough, snapshotId, or snapshotHash fields.
- Never infer SQL results from the prompt. Call the generated Data Studio REST function tool for every answer.

## Snapshot Provenance

- {"kind":"metric_definition","title":"Ticket Count","metric":"ticket_count","definition":"Count of distinct sales bill IDs for posted, non-cancelled tickets in the 2026-07-17 through 2026-08-15 snapshot window.","formula":"count(distinct hd.BILLID)","filter":"hd.CANCELSIGN = 'N' AND hd.STATUS = '002' AND hd.SELLSTATEID IN ('01','02') AND hd.SELLDATE >= DATE '2026-07-17' AND hd.SELLDATE <= DATE '2026-08-15'","lineage":[{"id":"oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw","snapshot_id":"oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw","hash":"c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb","sha256":"c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb","data_through":"2026-08-15","manifest_schema":"oracle.sales.snapshot.manifest.v2","provenance":"sanitized-from-snapshot"},{"policy":"oracle.sales.privacy.v1","filters":{"CANCELSIGN":"N","STATUS":"002","SELLSTATEID":["01","02"],"SELLDATE":["2026-07-17","2026-08-15"]},"golden_results":{"cross_country_sales_amount":"blocked_pending_currency_confirmation","customer_name_phone_policy":"denied","relative_time_anchor":"max(SELLDATE)=2026-08-15","ticket_count_last_30_snapshot_days":86,"top_3_stores_by_ticket_count":[{"store":"VNPTTE","ticket_count":56},{"store":"SG - ANTA VIVO City","ticket_count":9},{"store":"HARAVAN_ANTA_VN","ticket_count":5}]}}]}

## Seed Evidence

- {"kind":"metric_definition","title":"Ticket Count","metric":"ticket_count","definition":"Count of distinct sales bill IDs for posted, non-cancelled tickets in the 2026-07-17 through 2026-08-15 snapshot window.","formula":"count(distinct hd.BILLID)","filter":"hd.CANCELSIGN = 'N' AND hd.STATUS = '002' AND hd.SELLSTATEID IN ('01','02') AND hd.SELLDATE >= DATE '2026-07-17' AND hd.SELLDATE <= DATE '2026-08-15'","lineage":[{"id":"oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw","snapshot_id":"oracle-local-extract-sanitized/20260818-knowledge-center-4-arkclaw","hash":"c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb","sha256":"c67a52d9f8d2eaf92d6a7ca1b09aee321cf4da176499c618ef0e53214eb166eb","data_through":"2026-08-15","manifest_schema":"oracle.sales.snapshot.manifest.v2","provenance":"sanitized-from-snapshot"},{"policy":"oracle.sales.privacy.v1","filters":{"CANCELSIGN":"N","STATUS":"002","SELLSTATEID":["01","02"],"SELLDATE":["2026-07-17","2026-08-15"]},"golden_results":{"cross_country_sales_amount":"blocked_pending_currency_confirmation","customer_name_phone_policy":"denied","relative_time_anchor":"max(SELLDATE)=2026-08-15","ticket_count_last_30_snapshot_days":86,"top_3_stores_by_ticket_count":[{"store":"VNPTTE","ticket_count":56},{"store":"SG - ANTA VIVO City","ticket_count":9},{"store":"HARAVAN_ANTA_VN","ticket_count":5}]}}]}
- {"kind":"permission_policy","title":"Semantic model external query policy","policy":{"allowedMetrics":["ticket_count"],"allowedDimensions":["store","sell_date","sell_state","sell_type"]}}
