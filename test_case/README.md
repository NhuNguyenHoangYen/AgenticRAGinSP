# Document QA evaluation cases

40 data fixtures across eight category JSON files; five cases per category. These are evaluation data, not executable Python tests. Each category file contains a JSON array in the requested schema.

## Source and numbering

The only knowledge base is the supplied Artificial Intelligence Index Report 2025 (2504.07139v3.pdf), identified as doc_001. source_manifest.json records the source hash. document_ids retains the requested array field but always contains only doc_001. No case requires another document.

Evidence page numbers are ONE-BASED PHYSICAL PDF pages (the first PDF page is 1), not printed report page labels. For example PDF page 18 has printed page 17. PyMuPDF/LangChain metadata may be zero-based: convert page to metadata page minus one when matching. Evidence text is verbatim extracted text with whitespace normalized; line-wrap hyphens may remain. Evidence excerpts and page associations were programmatically matched against the supplied PDF.

## Answerability and grading

- answerable=true: all requested information is supported by this source.
- answerable=false in unanswerable_question: abstain; evidence is empty because absence is not an affirmative quotation. These cases request future realized outcomes or nonpublic individual/credential data rather than treating an unrelated passage as evidence.
- answerable=false in partially_answerable: the COMPLETE question cannot be answered. Supply the supported part, cite its evidence, and explicitly identify the unsupported part. Category plus the partial tag distinguish these from fully unanswerable cases.
- expected.answer is a semantic reference, not an exact-string match. required_facts include answer-content and explicit behavioral requirements.
- Calculations must preserve units and distinguish percentage points from relative percentage changes. Arithmetic may be derived from the cited operands; it need not occur verbatim in the source.
- Every conversation is single_turn. Multi-hop means a bridge/entity/ranking lookup inside ONE document; multi-fact synthesis integrates statements without that dependency.
- Language-switching cases specify the answer language in the question. dimensions.language describes the input/output language pattern; judge factual correctness and language adherence separately.
- document_structure=prose describes the evidence actually used, including numbered highlights. This dataset does not claim coverage of tables, figures, OCR, or all 457 pages. It concentrates on verified chapter highlights (PDF pages 13–23), which are useful for repeatable baseline checks.

## Later DeepEval use

Run each question against the application with fresh conversation memory. Use question as input, the actual new answer as actual_output, and the passages actually retrieved during that execution as retrieval_context. expected.answer is a reviewed-reference candidate for expected_output; expected.evidence is gold evidence, not the runtime retrieval_context. For abstention/partial/language cases, use a rubric that checks the category-specific behavior rather than grading only generic answer relevance. No application code, API calls, or Python test files were created for this task.
