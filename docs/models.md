# Models: measured performance

What the chat models perform like on the hardware the profiles target. Use this to choose a model per profile. Every
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

## Strix Halo (Ryzen AI Max+ 395, 128 GB unified memory, Radeon 8060S)

Measured 2026-10-16 the same way (same image and flags, 3 repetitions for
gpt-oss-20b, 2 for gpt-oss-120b), machine cool (CPU 44 °C) and the pod stopped.
`-ncmoe N` keeps the expert weights of N layers on the CPU:

| Model | Placement | Generation (tg128) | Generation @ 8K ctx | Prompt (pp512) | Prompt @ 8K ctx |
| --- | --- | ---: | ---: | ---: | ---: |
| gpt-oss-20b | all GPU | **77.0 ± 0.2** | **70.4 ± 0.4** | 1495 ± 19 | 1110 ± 25 |
| gpt-oss-120b (59.0 GiB) | all GPU | **54.5 ± 0.1** | | 610 ± 7 | |
| gpt-oss-120b | `-ncmoe 6` | 41.3 ± 0.0 | | 551 ± 7 | |
| gpt-oss-120b | `-ncmoe 12` | 36.2 ± 0.0 | | 524 ± 2 | |

gpt-oss-20b is 2.7× faster here than on the Radeon 890M, and the
answer-level eval took 21 s per case against 70 s.

### GPU memory on AMD APUs: raise the GTT limit before `workstation`

On an APU the GPU maps system memory through the GTT, which the kernel caps at
half of RAM by default (62.5 GiB on a 128 GB machine). gpt-oss-120b alone is
59 GiB. With the default cap the `workstation` profile *does* load, but leaves
the GTT completely full; in testing, a few minutes of chat later the amdgpu/TTM
memory manager soft-locked every GPU client (the desktop included) for
minutes at a time. Small-context benchmarks run fine and hide this.

`deploy/install.sh` therefore refuses a profile when VRAM + GTT is smaller than
the profile's models plus 16 GiB headroom (`RAG_GPU_HEADROOM_GIB`;
`RAG_SKIP_GPU_CHECK=1` overrides). To raise the cap to ~105 GiB (the limit is
a ceiling, not a reservation; memory the GPU isn't using stays available to the
system):

```bash
sudo grubby --update-kernel=ALL --args="ttm.pages_limit=27648000 ttm.page_pool_size=27648000"
sudo reboot
cat /sys/class/drm/card*/device/mem_info_gtt_total   # ~113 GB afterwards
```

Values are 4 KiB pages. Check `mem_info_gtt_used` while the pod runs.

### Guidance

- **`laptop` profile:** gpt-oss-20b (default, best tool calling and the most
  precise citations in the answer-level eval). Gemma 4 26B-A4B is the
  `laptop-gemma` profile: close behind, with better coverage. Both generate
  ~28 tok/s; gpt-oss reads prompts faster. Answer-level numbers are in
  [ingest-and-search.md](ingest-and-search.md#answer-level-results-which-chat-model).
- **`workstation` profile:** gpt-oss-120b, on 96 GB+ machines with the GTT
  limit raised (see above). With the default limit, use `laptop` (gpt-oss-20b),
  which is fast on these machines too.
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
