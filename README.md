# note-refinery-simple

Small Python CLI for turning lecture source files into cleaned markdown notes.

Supported input source types:

- `.md`
- `.py`
- `.ipynb`

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
- `note_refinery.yaml` for provider, models, prompt profile, patch mode, patch concurrency, review folder concurrency, and timeout

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
review_folder_concurrency: 1
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
review_folder_concurrency: 1
timeout_seconds: 300
```

Secrets stay in `.env`:

```env
OPENAI_COMPATIBLE_API_KEY=your-api-key
```

## Usage

Pipeline stages:

1. `review`
   - writes `REVIEW.md`
   - writes canonical `image_context.json`
2. `patch`
   - writes cleaned markdown into `patched_notes/`
3. `verify`
   - writes `VERIFY.md`
4. `synthesize`
   - writes `SYNTHESIS.md` and `concept_map.json`
5. `run`
   - runs `review -> patch -> verify -> synthesize`

Input contract:

- one lecture set may contain `.md`, `.py`, and `.ipynb` source files
- outputs stay markdown-only under `patched_notes/`
- v1 image enrichment stays scoped to original `.md` files only
- if root contains source files and child folders with source files also exist, run fails fast instead of guessing single-folder or batch mode

Outputs:

```text
reports/REVIEW.md
reports/VERIFY.md
reports/SYNTHESIS.md
reports/concept_map.json
reports/image_context.json
patched_notes/*.md
```

Batch folder output adds:

```text
batch_manifest.json
<folder>/reports/REVIEW.md
<folder>/reports/image_context.json
<folder>/patched_notes/*.md
reports/VERIFY.md
reports/SYNTHESIS.md
reports/concept_map.json
```

Commands print live progress, for example:

```text
review [1/2 intro] start
review [intro] image 1/34
review [intro] send reviewer
patch: file 1/12 [ACT2026_1_Introduction/full.md]
patch: topic guard failed -> ACT2026_2_Optimization/full.md
patch: retry 2/3 -> ACT2026_2_Optimization/full.md
verify: done
synthesize: done
```

Patch mode defaults to `clean-teaching`, which rewrites noisy OCR into distilled study notes. Use `--mode conservative` if you want lighter edits that stay closer to the source layout.

Patch execution defaults to `patch_concurrency: 3`. Increase it only if your provider handles parallel requests cleanly.

Batch folder review defaults to `review_folder_concurrency: 1`. Raise it only for `review` over a folder-of-folders input such as `MinerU`. Each folder review runs independently, but images inside one folder stay sequential.

The tool loads `.env` from its own project directory if present.

If `note_refinery.yaml` exists in project root, it is loaded automatically. You can also point to another config file with `--config`.

### Single Folder

Run whole pipeline for one note folder:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU\ACT2026_11_Genetic Algorithms.pdf-fa380dba-3ab3-4050-b4c3-335013a3597d" --output-root ".\live-run"
```

Keep edits closer to source layout:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU\ACT2026_11_Genetic Algorithms.pdf-fa380dba-3ab3-4050-b4c3-335013a3597d" --output-root ".\live-run-conservative" --mode conservative
```

Set patch concurrency temporarily:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU\ACT2026_11_Genetic Algorithms.pdf-fa380dba-3ab3-4050-b4c3-335013a3597d" --output-root ".\live-run" --patch-concurrency 4
```

Run stages one by one for one note folder:

```powershell
py -3 -m note_refinery_simple review --notes-dir notes --output-root .
py -3 -m note_refinery_simple patch --notes-dir notes --output-root . --mode clean-teaching
py -3 -m note_refinery_simple verify --notes-dir notes --output-root .
py -3 -m note_refinery_simple synthesize --notes-dir notes --output-root .
```

### Folder Batch

Run whole pipeline for folder-of-folders:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\batch-run"
```

Run batch review only:

```powershell
py -3 -m note_refinery_simple review --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\batch-review" --review-folder-concurrency 3
```

Run batch patch only:

```powershell
py -3 -m note_refinery_simple patch --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\batch-review"
```

Run batch verify only:

```powershell
py -3 -m note_refinery_simple verify --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\batch-review"
```

Run batch synthesize only:

```powershell
py -3 -m note_refinery_simple synthesize --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\batch-review"
```

Folder batch flow summary:

```text
run         -> review + patch + verify + synthesize
review      -> writes batch_manifest.json and per-folder REVIEW.md
patch       -> writes per-folder patched_notes/
verify      -> writes one root reports/VERIFY.md
synthesize  -> writes one root reports/SYNTHESIS.md and reports/concept_map.json
```

Important:

```text
single-folder run can do selective repair after verify
folder-batch run does one lazy pass: review -> patch -> verify -> synthesize
batch verify and batch synthesize run once at batch root, not per folder
batch verify requires every folder in batch_manifest.json to already have patched_notes/
```

### Overrides

Use another config file:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU\ACT2026_11_Genetic Algorithms.pdf-fa380dba-3ab3-4050-b4c3-335013a3597d" --output-root ".\live-run" --config ".\note_refinery.yaml"
```

Override provider or one model temporarily:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU\ACT2026_11_Genetic Algorithms.pdf-fa380dba-3ab3-4050-b4c3-335013a3597d" --output-root ".\live-run" --provider custom --base-url "https://my-gateway.example.com/v1" --patch-model deepseek-v4-pro --synthesize-model deepseek-v4-pro
```

Try another prompt profile temporarily:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU\ACT2026_11_Genetic Algorithms.pdf-fa380dba-3ab3-4050-b4c3-335013a3597d" --output-root ".\live-run" --prompt-profile strict
```

Fast rerun with cached artifacts:

`--reuse-image-context-from` can point at full or partial `reports/image_context.json`. Missing images are enriched live, then merged back into canonical cache file for current run. In v1 this cache applies to original `.md` image references only.


```powershell
py -3 -m note_refinery_simple review --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\rerun-review" --reuse-image-context-from ".\live-run"
py -3 -m note_refinery_simple patch --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\rerun-patch" --reuse-review-from ".\live-run" --reuse-image-context-from ".\live-run"
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\rerun-full" --reuse-review-from ".\live-run" --reuse-image-context-from ".\live-run"
```

Stage notes:

- `review` on one note folder creates `reports/REVIEW.md` and canonical `reports/image_context.json`
- `review` on a folder of note folders writes `batch_manifest.json` plus one subtree per folder under `output-root/<folder>/reports/`
- source discovery supports `.md`, `.py`, and `.ipynb`
- if root source files and child source folders are both present, the run fails fast with a mixed-layout error
- `patch` on one note folder expects `reports/REVIEW.md` to already exist
- `patch` on batch root reads `batch_manifest.json` and patches every listed folder into `output-root/<folder>/patched_notes/`
- `verify` on one note folder expects patched notes in `patched_notes/` and checks them against `REVIEW.md`
- `verify` on batch root requires every manifest-listed folder to already have `patched_notes/`, then writes one root `reports/VERIFY.md`
- `synthesize` on one note folder expects patched notes in `patched_notes/` and `VERIFY.md` in `reports/`
- `synthesize` on batch root reads all manifest-listed patched folders together, then writes one root `reports/SYNTHESIS.md` and `reports/concept_map.json`
- `run` works for both one note folder and folder batch
- batch means full discovered folder set for one review run, not review worker chunking
- image enrichment and `image_context.json` stay scoped to original `.md` sources in v1

## Setup

1. Copy `.env.example` to `.env` and set API key.
2. Copy `note_refinery.yaml.example` to `note_refinery.yaml` and edit provider/models if needed.
3. Run commands above.

## Tests

```powershell
py -3 -m unittest discover -s tests -t . -v
python -m mypy note_refinery_simple tests
```
