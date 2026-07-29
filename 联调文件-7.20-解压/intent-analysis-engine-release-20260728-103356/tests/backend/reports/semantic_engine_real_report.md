# Real Semantic Engine Test Report

- Generated At: `2026-07-28T02:08:12.102367+00:00`
- MODEL_API_URL: `http://127.0.0.1:8001/v1`
- EMBEDDING_MODEL: `bge-m3`
- Milvus Collection: `intent_vectors`
- Semantic Threshold: `0.5`
- TopK: `5`
- Total: `4`
- Passed: `0`
- Failed: `0`
- Blocked: `4`
- Pass Rate: `0.00%`
- Average Elapsed: `2028.294 ms`

## Case Details

| Case | Category | Text | Expected Match | Actual Match | Actual Function | Confidence | Similarity | Status | Elapsed ms | Error |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | ---: | --- |
| REAL-SEM-001 | target | 帮我整理经营情况 | True | None | - | - | - | blocked | 2033.849 | Model service unavailable: /embeddings |
| REAL-SEM-002 | synonym | 帮我看看业务情况 | True | None | - | - | - | blocked | 2016.065 | Model service unavailable: /embeddings |
| REAL-SEM-003 | weak_expression | 最近公司表现怎么样 | True | None | - | - | - | blocked | 2034.288 | Model service unavailable: /embeddings |
| REAL-SEM-004 | wrong_expression | 明天天气如何 | False | None | - | - | - | blocked | 2028.975 | Model service unavailable: /embeddings |

## TopK Candidates

### REAL-SEM-001 `帮我整理经营情况`

- No candidates.

### REAL-SEM-002 `帮我看看业务情况`

- No candidates.

### REAL-SEM-003 `最近公司表现怎么样`

- No candidates.

### REAL-SEM-004 `明天天气如何`

- No candidates.

