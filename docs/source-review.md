# Source review for the initial public facts

The [public-fact dataset](../data/public-facts.jsonl) contains 8 cases with a review date of **2026-09-20 (UTC)**. In that review, an AI agent opened the publishers' pages listed below, read the specified evidence locations, and checked the original Chinese summaries before setting `synthetic: false` and `review_status: reviewed`. The published questions, answers, and locators have since been translated into English without changing their IDs, sources, dates, or claimed evidence scope. **This records one source-support review; translation is not a new source review, independent human certification, institutional endorsement, or completed model evaluation.**

Each question is explicitly limited to a published document. `time_sensitive: false` means the answer describes that version; it does not claim coverage of later revisions, implementation behavior, or the latest standards status. The BIPM cases were checked against its published English text. The page identifies French as the official text, and the review did not compare the English and French versions sentence by sentence.

## Evidence index

| Case ID | Original source opened | Precise location | Review focus |
| --- | --- | --- | --- |
| `rfc8259-duplicate-names` | [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) | Section 4, first paragraph and paragraphs after the grammar block; printed pages 6–7 | Uniqueness uses SHOULD; retain differences in duplicate-name handling across implementations. |
| `rfc8259-nonfinite-numbers` | [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) | Section 6, prohibition before the number grammar; printed page 7 | NaN and Infinity are not values allowed by this JSON number grammar. |
| `rfc2119-must-requirement` | [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) | Section 1, MUST; printed page 1 | MUST expresses an absolute requirement and corresponds to REQUIRED and SHALL. |
| `rfc2119-should-exceptions` | [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) | Section 3, SHOULD; printed page 1 | Exceptions need specific reasons, with consequences understood and carefully weighed first. |
| `rfc8174-uppercase-keywords` | [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) | Section 2, three bullets in the NEW text; printed page 3 | Capitalization affects the keywords' special meaning; text can be normative without them. |
| `cgpm2018-metre-definition` | [Resolution 1 of the 26th CGPM, English text](https://www.bipm.org/en/committees/cg/cgpm/26-2018/resolution-1) | Appendix 3, second bullet, metre | Check the fixed speed-of-light value, m/s unit, and relationship to the definition of the second. |
| `cgpm2018-mole-entities` | [Resolution 1 of the 26th CGPM, English text](https://www.bipm.org/en/committees/cg/cgpm/26-2018/resolution-1) | Appendix 3, mole bullet and following explanatory paragraph | Check the fixed count; elementary entities are not limited to atoms. |
| `rfc9110-safe-side-effects` | [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html) | Section 9.2.1, first 3 paragraphs | Distinguish client-request semantics from implementation side effects; GET and access-log examples both appear in the original. |

The dataset stores brief, originally authored summaries now published in English, titles, locators, and links. It does not reproduce entire standards, website bodies, author contact details, or webpage metadata. Links have no query parameters or fragments; section information is stored separately in `evidence_locator`.

## Coverage and next steps

These 8 records cover only 5 documents from 2 publishers, with several cases sharing a source. They focus on technical standards and SI definitions, and all are short questions with sufficient evidence. The English fixtures do not establish Chinese-language factual-checking coverage and cannot support an overall model ranking on their own. The real dataset still lacks insufficient-evidence, clarification, conflicting-source, and longer-reasoning cases. The original 3 synthetic fixtures remain format tests only.

Next steps include independent human review of question wording, translated summaries, and evidence locations, and expansion to 30 cases and more sources. The review establishes only that the listed sources support the written answers; it does not guarantee continued availability of source pages. Automated tests run offline, do not revisit webpages, and do not judge factual truth.

```sh
python3 -m evidence_bench validate data/public-facts.jsonl --real-only --require-reviewed
python3 -m evidence_bench validate examples/synthetic.jsonl data/public-facts.jsonl
python3 -m unittest discover -s tests -v
```
