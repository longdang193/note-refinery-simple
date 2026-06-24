# note-refinery-simple

Small Python CLI for three LLM agents over Markdown class notes:

1. reviewer writes `reports/REVIEW.md`
2. patcher writes corrected files to `patched_notes/`
3. verifier writes `reports/VERIFY.md`
4. synthesizer writes `reports/SYNTHESIS.md` and `reports/concept_map.json`

It uses any OpenAI-compatible endpoint, including Opencode and DeepSeek.

Prompt text is centralized in Markdown files under `prompts/`, so you can tune prompt versions without editing Python code.

## Requirements

- Python 3.11+
- `.env` for API key
- `note_refinery.yaml` for provider, models, prompt profile, patch mode, and timeout

## Project layout

```text
note-refinery-simple/
  note_refinery_simple/
  tests/
  pyproject.toml
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
```

Prompt layout:

```text
prompts/
  base/
    system.md
    image_system.md
  profiles/
    default/
      review.md
      patch.md
      verify.md
      synthesize.md
      image_user.md
```

You can create another profile such as `prompts/profiles/strict/` and switch to it with config or CLI.

Secrets stay in `.env`:

```env
OPENAI_COMPATIBLE_API_KEY=your-api-key
```

## Usage

Pipeline overview:

1. `review`
   - reads markdown notes
   - writes `reports/REVIEW.md`
   - finds formula issues, notation problems, missing assumptions, contradictions, and cross-file inconsistencies
2. `patch`
   - reads original notes and `reports/REVIEW.md`
   - writes cleaned notes into `patched_notes/`
3. `verify`
   - checks whether patched notes resolved review findings
   - writes `reports/VERIFY.md`
4. `synthesize`
   - reads all patched notes together
   - writes `reports/SYNTHESIS.md`
   - writes `reports/concept_map.json`
   - makes cross-file relationships, prerequisites, and unified definitions explicit
5. `run`
   - runs `review -> patch -> verify -> synthesize` in one command

From this folder:

```bash
py -3 -m note_refinery_simple run --notes-dir notes --output-root .
```

Outputs:

```text
reports/REVIEW.md
reports/VERIFY.md
reports/SYNTHESIS.md
reports/concept_map.json
patched_notes/*.md
```

If you use `run`, all stages execute automatically.

Commands now print live progress so you can see stage activity during long runs, for example:

```text
review: loaded 12 markdown file(s)
review: enriching 34 image(s)
review: image 1/34 -> full.md (images/page-01.jpg)
patch: sending notes to patcher
verify: wrote VERIFY.md
synthesize: wrote SYNTHESIS.md and concept_map.json
```

Patch mode defaults to `clean-teaching`, which rewrites noisy OCR into distilled study notes. Use `--mode conservative` if you want lighter edits that stay closer to the source layout.

The tool loads `.env` from its own project directory if present.

If `note_refinery.yaml` exists in project root, it is loaded automatically. You can also point to another config file with `--config`.

Useful CLI commands:

Single markdown file:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\path\to\one-note-folder" --output-root ".\out"
```

Batch process folder of markdown notes:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\path\to\notes-folder" --output-root ".\out"
```

Run on your `MinerU` folder:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run"
```

Keep edits closer to source layout:

```powershell
py -3 -m note_refinery_simple run --notes-dir "C:\Users\HOANG PHI LONG DANG\MinerU" --output-root ".\live-run-conservative" --mode conservative
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

You can also run stages one by one:

```bash
py -3 -m note_refinery_simple review --notes-dir notes --output-root .
py -3 -m note_refinery_simple patch --notes-dir notes --output-root . --mode clean-teaching
py -3 -m note_refinery_simple verify --notes-dir notes --output-root .
py -3 -m note_refinery_simple synthesize --notes-dir notes --output-root .
```

Stage notes:

- `review` only creates `reports/REVIEW.md`
- `patch` expects `reports/REVIEW.md` to already exist
- `verify` expects patched notes in `patched_notes/` and checks them against `REVIEW.md`
- `synthesize` expects patched notes in `patched_notes/` and `VERIFY.md` in `reports/`
- `run` is best default when you want full pipeline

## Setup

1. Copy `.env.example` to `.env` and set API key.
2. Copy `note_refinery.yaml.example` to `note_refinery.yaml` and edit provider/models if needed.
3. Run commands above.

## Tests

From this folder:

```powershell
py -3 -m unittest discover -s tests -t . -v
```
