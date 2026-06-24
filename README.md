# note-refinery-simple

Small Python CLI for LLM-based note cleanup.

Pipeline:

1. `review` writes `reports/REVIEW.md` and canonical `reports/image_context.json`
2. `patch` writes cleaned files to `patched_notes/`
3. `verify` writes `reports/VERIFY.md`
4. `synthesize` writes `reports/SYNTHESIS.md` and `reports/concept_map.json`

It uses any OpenAI-compatible endpoint, including Opencode and DeepSeek.

Prompt text lives in Markdown files under `prompts/`, so you can tune prompt versions without editing Python code.

## Requirements

- Python 3.11+
- `.env` for API key
- `note_refinery.yaml` for provider, models, prompt profile, patch mode, patch concurrency, and timeout

## Project layout

```text
note-refinery-simple/
  note_refinery_simple/
  prompts/
  tests/
  .env.example
  note_refinery.yaml.example
  README.md
```

## SSOT config

Runtime config follows SSOT:

- `note_refinery.yaml` is source of truth for provider and model selection
- `prompts/` is source of truth for agent prompt text
- `.env` is source of truth for secrets only
- CLI flags are temporary overrides

Example `note_refinery.yaml`:

```yaml
provider: opencode

models:
  review: deepseek-v4-pro
  patch: deepseek-v4-pro
  verify: deepseek-v4-pro
  synthesize: deepseek-v4-pro
  image: minimax-m3

prompts:
  profile: default
  root_dir: prompts

patch_mode: clean-teaching
patch_concurrency: 3
timeout_seconds: 300
```

For a custom provider:

```yaml
provider: custom
base_url: https://my-gateway.example.com/v1

models:
  review: deepseek-v4-pro
  patch: deepseek-v4-pro
  verify: deepseek-v4-pro
  synthesize: deepseek-v4-pro
  image: minimax-m3

prompts:
  profile: default
  root_dir: prompts

patch_mode: clean-teaching
patch_concurrency: 3
timeout_seconds: 300
```

Secrets stay in `.env`:

```env
OPENAI_COMPATIBLE_API_KEY=your-api-key
```

## Usage

Pipeline overview:

1. `review`
   - reads markdown notes
   - writes `reports/REVIEW.md`
   - writes canonical `reports/image_context.json` for image enrichment context
   - persists `image_context.json` incrementally after each image so partial progress survives aborts and reruns
   - finds formula issues, notation problems, missing assumptions, contradictions, and cross-file inconsistencies
2. `patch`
   - reads original notes and `reports/REVIEW.md`
   - patches each markdown file in its own LLM call
   - uses topic guard before accepting each patched file
   - writes cleaned notes into `patched_notes/`
3. `verify`
   - checks whether patched notes resolved review findings
   - writes `reports/VERIFY.md`
4. `synthesize`
   - reads all patched notes together
   - writes `reports/SYNTHESIS.md`
   - writes `reports/concept_map.json`
5. `run`
   - runs `review -> patch -> verify -> synthesize`
   - if `VERIFY.md` flags specific files, only those files are repatched and re-verified before synthesis

Outputs:

```text
reports/REVIEW.md
reports/VERIFY.md
reports/SYNTHESIS.md
reports/concept_map.json
reports/image_context.json
patched_notes/*.md
```

Commands print live progress, for example:

```text
review: loaded 12 markdown file(s)
review: enriching 34 image(s)
review: image 1/34 -> full.md (images/page-01.jpg)
patch: file 1/12 -> ACT2026_1_Introduction/full.md
patch: topic guard failed -> ACT2026_2_Optimization/full.md
patch: retry 2/3 -> ACT2026_2_Optimization/full.md
verify: wrote VERIFY.md
synthesize: wrote SYNTHESIS.md and concept_map.json
```

Patch mode defaults to `clean-teaching`, which rewrites noisy OCR into distilled study notes. Use `--mode conservative` if you want lighter edits that stay closer to the source layout.

Patch execution defaults to `patch_concurrency: 3`. Increase it only if your provider handles parallel requests cleanly.

The tool loads `.env` from its own project directory if present.

If `note_refinery.yaml` exists in project root, it is loaded automatically. You can also point to another config file with `--config`.

Useful CLI commands:

Run whole pipeline:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run"
```

Keep edits closer to source layout:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run-conservative" --mode conservative
```

Set patch concurrency temporarily:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run" --patch-concurrency 4
```

Use another config file:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run" --config ".\note_refinery.yaml"
```

Override provider or one model temporarily:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run" --provider custom --base-url "https://my-gateway.example.com/v1" --patch-model deepseek-v4-pro --synthesize-model deepseek-v4-pro
```

Try another prompt profile temporarily:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run" --prompt-profile strict
```

Run stages one by one:

```powershell
py -3 -m note_refinery_simple review --notes-dir notes --output-root .
py -3 -m note_refinery_simple patch --notes-dir notes --output-root . --mode clean-teaching
py -3 -m note_refinery_simple verify --notes-dir notes --output-root .
py -3 -m note_refinery_simple synthesize --notes-dir notes --output-root .
```

Fast rerun with cached artifacts:

`--reuse-image-context-from` can point at full or partial `reports/image_context.json`. Missing images are enriched live, then merged back into canonical cache file for current run.


```powershell
py -3 -m note_refinery_simple review --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\rerun-review" --reuse-image-context-from ".\live-run"
py -3 -m note_refinery_simple patch --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\rerun-patch" --reuse-review-from ".\live-run" --reuse-image-context-from ".\live-run"
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\rerun-full" --reuse-review-from ".\live-run" --reuse-image-context-from ".\live-run"
```

Stage notes:

- `review` creates `reports/REVIEW.md` and canonical `reports/image_context.json`
- `patch` expects `reports/REVIEW.md` to already exist
- `verify` expects patched notes in `patched_notes/` and checks them against `REVIEW.md`
- `synthesize` expects patched notes in `patched_notes/` and `VERIFY.md` in `reports/`
- `run` is best default when you want full pipeline

## Setup

1. Copy `.env.example` to `.env` and set API key.
2. Copy `note_refinery.yaml.example` to `note_refinery.yaml` and edit provider/models if needed.
3. Run commands above.

## Tests

```powershell
py -3 -m unittest discover -s tests -t . -v
python -m mypy note_refinery_simple tests
```
