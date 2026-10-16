# Models: measured performance

What the chat models perform like on the hardware the `laptop` and
`laptop-light` profiles target. Use this to choose a model per profile. Every
model here passed the project's origin check (no Chinese-origin weights); see
`models/models.tsv` and CLAUDE.md.

## Radeon 890M (Ryzen AI 9 HX 370, 64 GB, 32 GB GPU carve-out)

Measured 2026-10-16 with `llama-bench` from the pod's pinned RamaLama image
(llama.cpp `b29c606`, Vulkan/RADV), all layers on the GPU, flash attention on,
3 repetitions, laptop cool (CPU below 65 °C) and otherwise idle. Tokens per
second, mean ± sd:

| Model | GGUF | Size | Generation (tg128) | Generation @ 8K ctx | Prompt (pp512) | Prompt @ 8K ctx |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| gpt-oss-20b | `ggml-org/gpt-oss-20b-GGUF` MXFP4 | 11.3 GiB | **28.3 ± 0.1** | **26.3 ± 0.1** | 616 ± 2 | 389 ± 12 |
| Gemma 4 26B-A4B-it | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` | 13.4 GiB | **28.4 ± 0.1** | 24.5 ± 0.0 | 512 ± 16 | 423 ± 9 |
| Granite 4.0-H-Micro | `ibm-granite/granite-4.0-h-micro-GGUF` Q4_K_M | 1.8 GiB | 31.8 ± 0.1 | 30.3 ± 0.2 | 622 ± 1 | 583 ± 12 |
| Gemma 4 12B-it | `google/gemma-4-12B-it-qat-q4_0-gguf` | 6.5 GiB | 11.0 ± 0.0 | 10.2 ± 0.0 | 276 ± 6 | 212 ± 3 |
| Granite 4.0-H-Small | `ibm-granite/granite-4.0-h-small-GGUF` Q4_K_M | 18.1 GiB | 10.2 ± 1.8 | 12.0 ± 0.2 | 153 ± 0 | 157 ± 3 |

Granite rows were measured without the temperature gate; the others with it.

### Guidance

- **`laptop` profile:** gpt-oss-20b (default, best tool calling and the most
  precise citations in the answer-level eval). Gemma 4 26B-A4B is the
  `laptop-gemma` profile: close behind, with better coverage. Both generate
  ~28 tok/s; gpt-oss reads prompts faster. Answer-level numbers are in
  [ingest-and-search.md](ingest-and-search.md#answer-level-results-which-chat-model).
- **`laptop-light` profile:** Granite 4.0-H-Micro, fast and small; fine for
  pipeline tests, but it doesn't produce reliable cited answers.
- **Prefer mixture-of-experts models on iGPUs:** generation is bound by memory
  bandwidth, so the 26B MoE (~4B active) is ~2.5× faster than dense Gemma 12B.
- **Don't ingest while chatting:** CPU and iGPU share memory bandwidth. Docling
  ingestion on the CPU cut iGPU generation by up to ~3.7× in testing. Schedule
  ingestion for idle time.
- **Expect throttling in long sessions:** back-to-back runs pushed the CPU to
  ~80 °C, and throughput became noisy. Cool, idle numbers are the ceiling.

### Reproduce

```bash
IMG=$(grep ^RAMALAMA_IMAGE deploy/images.env | cut -d= -f2)
podman run --rm --device /dev/dri --entrypoint llama-bench \
  -v "$RAG_MODELS":/models:ro,Z "$IMG" \
  -m /models/<file>.gguf -p 512 -n 128 -d 0,8192 -fa 1 -r 3
```

Run on an idle machine (no ingestion, no other GPU work), and record the CPU
temperature; results from a hot or busy machine aren't comparable.
