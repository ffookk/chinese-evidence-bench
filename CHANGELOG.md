# Changelog

## 0.2.0-alpha.1

- Add private offline run preparation and deterministic scoring of supplied responses and manual or declared assisted judgments. Strict schemas retain declared generation/review metadata and prompt overrides, bind complete records to dataset/case hashes, and separate unknown judgments from incorrect ones.
- Add paired comparison of two verified scored runs on the same cases, with explicit quality and coverage denominators, improved/regressed/unchanged eligible pairs, fixed answerability/synthetic strata, setup-change indicators, and per-case transitions.
- Save local artifacts with exclusive POSIX publication, mode `0600`, protected directory traversal, and no replacement of existing files. Default artifact directories remain ignored by Git; artifacts can contain sensitive supplied data.

This alpha provides reproducible scoring and descriptive comparison. It does not call models, authenticate declared provenance, verify factual truth automatically, establish human certification, or publish measured model performance. Existing case schema v1 and validation defaults remain unchanged. See the [offline evaluation guide](docs/offline-evaluation.md) for schemas, scoring rules, privacy boundaries, and sample limitations.
