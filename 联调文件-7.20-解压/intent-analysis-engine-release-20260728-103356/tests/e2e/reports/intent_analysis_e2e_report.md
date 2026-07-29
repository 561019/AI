# Intent Analysis E2E Test Report

- Generated At: `2026-07-09T14:03:52.200060+00:00`
- Total Cases: `100`
- Accuracy: `100.00%`
- Average Elapsed: `4.042 ms`

## Level Ratios

| Level | Count | Ratio |
| --- | ---: | ---: |
| level_1 | 30 | 30.00% |
| level_2 | 30 | 30.00% |
| level_3 | 40 | 40.00% |

## Category Accuracy

| Category | Count | Accuracy |
| --- | ---: | ---: |
| rule_hit | 30 | 100.00% |
| semantic_hit | 30 | 100.00% |
| complex_llm | 20 | 100.00% |
| missing_parameter | 10 | 100.00% |
| meaningless | 10 | 100.00% |

## Case Details

| Case | Category | Expected Level | Actual Level | Expected Function | Actual Function | Correct | Elapsed ms |
| --- | --- | ---: | ---: | --- | --- | --- | ---: |
| RULE-001 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 4.913 |
| RULE-002 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 3.785 |
| RULE-003 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 4.212 |
| RULE-004 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 4.656 |
| RULE-005 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 3.738 |
| RULE-006 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 3.626 |
| RULE-007 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 4.356 |
| RULE-008 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 3.933 |
| RULE-009 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 3.611 |
| RULE-010 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 4.36 |
| RULE-011 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 3.496 |
| RULE-012 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 3.325 |
| RULE-013 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 4.07 |
| RULE-014 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 3.48 |
| RULE-015 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 3.493 |
| RULE-016 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.448 |
| RULE-017 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 4.072 |
| RULE-018 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.496 |
| RULE-019 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.358 |
| RULE-020 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 4.548 |
| RULE-021 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 3.533 |
| RULE-022 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 3.344 |
| RULE-023 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 4.575 |
| RULE-024 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.895 |
| RULE-025 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 3.452 |
| RULE-026 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 4.278 |
| RULE-027 | rule_hit | 1 | 1 | CALCULATION | CALCULATION | yes | 3.551 |
| RULE-028 | rule_hit | 1 | 1 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.301 |
| RULE-029 | rule_hit | 1 | 1 | REPORT_CREATE | REPORT_CREATE | yes | 3.736 |
| RULE-030 | rule_hit | 1 | 1 | DATA_QUERY | DATA_QUERY | yes | 4.467 |
| SEM-001 | semantic_hit | 2 | 2 | REPORT_CREATE | REPORT_CREATE | yes | 3.24 |
| SEM-002 | semantic_hit | 2 | 2 | REPORT_CREATE | REPORT_CREATE | yes | 3.426 |
| SEM-003 | semantic_hit | 2 | 2 | REPORT_CREATE | REPORT_CREATE | yes | 4.784 |
| SEM-004 | semantic_hit | 2 | 2 | REPORT_CREATE | REPORT_CREATE | yes | 3.795 |
| SEM-005 | semantic_hit | 2 | 2 | DATA_QUERY | DATA_QUERY | yes | 3.651 |
| SEM-006 | semantic_hit | 2 | 2 | DATA_QUERY | DATA_QUERY | yes | 5.01 |
| SEM-007 | semantic_hit | 2 | 2 | DATA_QUERY | DATA_QUERY | yes | 3.821 |
| SEM-008 | semantic_hit | 2 | 2 | DATA_QUERY | DATA_QUERY | yes | 3.452 |
| SEM-009 | semantic_hit | 2 | 2 | CALCULATION | CALCULATION | yes | 4.269 |
| SEM-010 | semantic_hit | 2 | 2 | CALCULATION | CALCULATION | yes | 3.572 |
| SEM-011 | semantic_hit | 2 | 2 | CALCULATION | CALCULATION | yes | 3.637 |
| SEM-012 | semantic_hit | 2 | 2 | CALCULATION | CALCULATION | yes | 4.872 |
| SEM-013 | semantic_hit | 2 | 2 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.915 |
| SEM-014 | semantic_hit | 2 | 2 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.902 |
| SEM-015 | semantic_hit | 2 | 2 | DATA_SUMMARY | DATA_SUMMARY | yes | 5.191 |
| SEM-016 | semantic_hit | 2 | 2 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.947 |
| SEM-017 | semantic_hit | 2 | 2 | CONTENT_CREATE | CONTENT_CREATE | yes | 3.903 |
| SEM-018 | semantic_hit | 2 | 2 | CONTENT_CREATE | CONTENT_CREATE | yes | 5.462 |
| SEM-019 | semantic_hit | 2 | 2 | CONTENT_CREATE | CONTENT_CREATE | yes | 4.022 |
| SEM-020 | semantic_hit | 2 | 2 | CONTENT_CREATE | CONTENT_CREATE | yes | 4.114 |
| SEM-021 | semantic_hit | 2 | 2 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 4.64 |
| SEM-022 | semantic_hit | 2 | 2 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 4.044 |
| SEM-023 | semantic_hit | 2 | 2 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 4.39 |
| SEM-024 | semantic_hit | 2 | 2 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 4.48 |
| SEM-025 | semantic_hit | 2 | 2 | IMAGE_RECOGNITION | IMAGE_RECOGNITION | yes | 3.871 |
| SEM-026 | semantic_hit | 2 | 2 | IMAGE_RECOGNITION | IMAGE_RECOGNITION | yes | 4.056 |
| SEM-027 | semantic_hit | 2 | 2 | WORKFLOW_AGENT | WORKFLOW_AGENT | yes | 4.357 |
| SEM-028 | semantic_hit | 2 | 2 | WORKFLOW_AGENT | WORKFLOW_AGENT | yes | 3.92 |
| SEM-029 | semantic_hit | 2 | 2 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.15 |
| SEM-030 | semantic_hit | 2 | 2 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.216 |
| LLM-001 | complex_llm | 3 | 3 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.688 |
| LLM-002 | complex_llm | 3 | 3 | DATA_QUERY | DATA_QUERY | yes | 4.041 |
| LLM-003 | complex_llm | 3 | 3 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.121 |
| LLM-004 | complex_llm | 3 | 3 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 4.225 |
| LLM-005 | complex_llm | 3 | 3 | IMAGE_RECOGNITION | IMAGE_RECOGNITION | yes | 5.463 |
| LLM-006 | complex_llm | 3 | 3 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.189 |
| LLM-007 | complex_llm | 3 | 3 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.706 |
| LLM-008 | complex_llm | 3 | 3 | DATA_QUERY | DATA_QUERY | yes | 4.685 |
| LLM-009 | complex_llm | 3 | 3 | DATA_SUMMARY | DATA_SUMMARY | yes | 3.744 |
| LLM-010 | complex_llm | 3 | 3 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 3.741 |
| LLM-011 | complex_llm | 3 | 3 | DATA_QUERY | DATA_QUERY | yes | 4.961 |
| LLM-012 | complex_llm | 3 | 3 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 3.805 |
| LLM-013 | complex_llm | 3 | 3 | IMAGE_RECOGNITION | IMAGE_RECOGNITION | yes | 4.0 |
| LLM-014 | complex_llm | 3 | 3 | DATA_QUERY | DATA_QUERY | yes | 5.563 |
| LLM-015 | complex_llm | 3 | 3 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.019 |
| LLM-016 | complex_llm | 3 | 3 | CALCULATION | CALCULATION | yes | 4.4 |
| LLM-017 | complex_llm | 3 | 3 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 5.025 |
| LLM-018 | complex_llm | 3 | 3 | IMAGE_RECOGNITION | IMAGE_RECOGNITION | yes | 4.075 |
| LLM-019 | complex_llm | 3 | 3 | DATA_SUMMARY | DATA_SUMMARY | yes | 4.127 |
| LLM-020 | complex_llm | 3 | 3 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.512 |
| MISS-001 | missing_parameter | 3 | 3 | REPORT_CREATE | REPORT_CREATE | yes | 4.286 |
| MISS-002 | missing_parameter | 3 | 3 | REPORT_CREATE | REPORT_CREATE | yes | 4.062 |
| MISS-003 | missing_parameter | 3 | 3 | DATA_QUERY | DATA_QUERY | yes | 3.985 |
| MISS-004 | missing_parameter | 3 | 3 | CALCULATION | CALCULATION | yes | 3.738 |
| MISS-005 | missing_parameter | 3 | 3 | DATA_SUMMARY | DATA_SUMMARY | yes | 4.153 |
| MISS-006 | missing_parameter | 3 | 3 | CONTENT_CREATE | CONTENT_CREATE | yes | 4.061 |
| MISS-007 | missing_parameter | 3 | 3 | WORKFLOW_AGENT | WORKFLOW_AGENT | yes | 3.634 |
| MISS-008 | missing_parameter | 3 | 3 | DOCUMENT_PARSE | DOCUMENT_PARSE | yes | 4.483 |
| MISS-009 | missing_parameter | 3 | 3 | IMAGE_RECOGNITION | IMAGE_RECOGNITION | yes | 3.664 |
| MISS-010 | missing_parameter | 3 | 3 | KNOWLEDGE_QA | KNOWLEDGE_QA | yes | 3.935 |
| NONE-001 | meaningless | 3 | 3 | - | - | yes | 3.665 |
| NONE-002 | meaningless | 3 | 3 | - | - | yes | 4.339 |
| NONE-003 | meaningless | 3 | 3 | - | - | yes | 3.423 |
| NONE-004 | meaningless | 3 | 3 | - | - | yes | 3.335 |
| NONE-005 | meaningless | 3 | 3 | - | - | yes | 4.207 |
| NONE-006 | meaningless | 3 | 3 | - | - | yes | 3.912 |
| NONE-007 | meaningless | 3 | 3 | - | - | yes | 3.508 |
| NONE-008 | meaningless | 3 | 3 | - | - | yes | 4.295 |
| NONE-009 | meaningless | 3 | 3 | - | - | yes | 3.715 |
| NONE-010 | meaningless | 3 | 3 | - | - | yes | 3.525 |
