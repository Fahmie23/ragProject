# Deterministic Citations and Provenance

## Trust boundary

The LLM does **not** generate human-facing source locations such as page numbers or clause strings.

Generation emits claim text and request-local evidence references. Backend code resolves citations through the frozen artifact chain:

```text
claim
 ↓
request-local evidence ID
 ↓
frozen Stage 5 chunk
 ↓
source_element_ids / pages / section path
 ↓
resolved canonical structure
 ↓
validated structural locator
 ↓
PDF page / clause / definition / appendix citation
```

This separation reduces the chance that a plausible-looking citation is fabricated by the model.

## Validation

Citation construction validates that the referenced source locator stays inside the provenance of the cited evidence/chunk. Unknown evidence IDs or source relationships that escape the frozen provenance fail closed.

A deterministic citation status of `valid` means the provenance chain resolves correctly. It does **not** mean that a human has judged the citation to semantically entail the claim.

## Semantic entailment is a different metric

For the frozen Stage 11 benchmark, humans label whether cited evidence actually supports a generated claim. That semantic label must not be inferred for arbitrary live Search & Ask questions.

The distinction is:

```text
citation present   → the claim references a citation
citation valid     → deterministic provenance resolves
citation entails   → frozen human semantic review supports the claim
```

## API response

`POST /api/generation/answer` returns the cited answer, evidence, claim-to-citation relationships and deterministic citation objects/validation summary used by the UI.

## Frontend provenance explorer

Search & Ask can open an inline citation into a read-only provenance drawer showing:

1. deterministic validation status;
2. citation/evidence/chunk/PDF summary;
3. claims using the citation;
4. exact evidence text on demand;
5. deeper source-element lineage on demand;
6. an action to open the source PDF at the cited page.

Opening the drawer performs no new retrieval or generation call.
