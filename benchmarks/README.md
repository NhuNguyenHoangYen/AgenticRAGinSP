# PDF ingestion benchmark

Run from the project root with the backend dependencies installed.

```sh
LOG_LEVEL=WARNING .venv-api/bin/python -m benchmarks.ingestion > parse.csv
```

The default page counts are 5, 10, 50, 100, 150, 200, 500, and 1,000. Each fixture is a generated text PDF with approximately 2,100 extracted characters per page. The CSV reports the median of three runs per size. The warm-up time goes to stderr. Use `--pages 5 100 --repeats 5` to change the sample sizes or repetitions.

For the full indexing path, start Qdrant and run:

```sh
LOG_LEVEL=WARNING .venv-api/bin/python -m benchmarks.ingestion --index > indexing.csv
```

Indexing uses the backend embedding configuration and a uniquely named Qdrant collection, which the script removes on exit. Cohere requires an explicit `--allow-paid-embeddings` flag. An interrupted process may leave a collection with a `bench-` prefix. The warm-up loads the embedding model and initializes the collection before measured runs. Each timed run adds a new document ID to that collection.

`parse_ms` measures validation and text extraction. `chunk_ms` measures splitting. `index_ms` includes embedding, Qdrant writes, collection checks and the final vector count check. `measured_total_ms` includes hashing, parsing, chunking and optional indexing. PDF generation, HTTP upload, disk reads, MongoDB job writes, queue wait, retries and UI polling are outside these measurements. Compare runs using the same model, device, text density and repeat count.

## Baseline measured on November 13, 2026

See [parse-only results](baseline-parse.csv) for three repetitions per size and
[indexing results](baseline-index.csv) for one repetition per size. The indexing
run used cached `sentence-transformers/all-mpnet-base-v2` embeddings on CPU
and local Qdrant. Warm-up took 6.66 seconds, including model load and collection
creation. The Qdrant client was 1.14.2 and the server was 1.20.0. The client
reported a version compatibility warning and all vector-count checks passed.

## Chat response benchmark

Run from the project root with MongoDB, Qdrant and the backend environment
available. The benchmark creates a temporary database, upload directory and
vector collection. It submits one synthetic PDF through the API and runs the
ingestion worker. Once the document reaches ready status, it deletes the
original PDF and verifies the download endpoint returns 404. The questions
then use the indexed passages. The database, collection and temporary
directory are cleaned up after the run.

```sh
.venv-api/bin/python -m benchmarks.chat > chat-offline.csv
```

Offline mode exercises the real retrieval path with a deterministic model
stub. To measure your configured provider, run the following command. This
sends synthetic evidence to the provider and may incur API charges.

```sh
.venv-api/bin/python -m benchmarks.chat --live-llm > chat-live.csv
```

The default runs three turns in each of three fresh chats, using budgets of
2, 8 and 20. The first turn starts without history. Later turns include
completed history from that chat. Use `--pages`, `--budgets` and `--turns`
to configure the experiment. A Cohere embedding configuration requires
`--allow-paid-embeddings`. Compare the same turn number across chat budgets
to limit the effect of history. For more samples at the same budget, repeat
that budget in the `--budgets` list.

| CSV field | What it measures |
| --- | --- |
| `response_ms` | Full FastAPI request through the in-process test client, including MongoDB and response serialization |
| `llm_setup_ms` | LLM wrapper construction before generation |
| `qdrant_ms` | Sum of successful Qdrant search durations observed during the turn |
| `retrieval_ms` | Whole retrieval calls, including query embedding, Qdrant and passage selection |
| `llm_ms` | Sum of completed model call durations, including refinement and format repair calls |
| `requested_k`, `admitted_passages`, `context_chars` | Requested passage budget, actual unique passages and rendered evidence characters |
| `input_tokens`, `output_tokens` | Token usage reported by the provider, when available |
| `status`, `error_code` | HTTP outcome and response validation or generation error |

Qdrant time is included in retrieval time. Response time excludes browser
rendering and browser-to-server networking. A failed response can still have
valid retrieval and model measurements. Treat blank timing or token fields
as unavailable. Model time includes provider/network latency and varies with
output length, history, and the number of model calls.

The saved November 13 baselines use 20 pages, three budgets and three turns
per chat. The [live run](baseline-chat-live.csv) used the configured Azure
OpenAI deployment and returned seven answers and two citation validation
errors. The [offline run](baseline-chat-offline.csv) returned nine answers.
Both used the configured local embedding model and Qdrant. Use multiple
runs before drawing conclusions about how passage count affects latency.
