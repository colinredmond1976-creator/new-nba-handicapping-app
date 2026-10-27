# Codex Operational Constraints (GPT-6.1 Terra)

## 1. Context & File Inspection Rules
- **No Recursive Scans:** Never run open-ended searches like `find .`, `ls -R`, or unbounded `grep`/`ripgrep`. Inspect only specific files named in the prompt or immediately adjacent imports.
- **Selective Reading:** When inspecting files longer than 100 lines, read only target functions or specific line ranges rather than loading the entire file into context.
- **Strict Exclusions:** Never inspect, read, or search inside:
  - Dependency trees (`node_modules/`, `vendor/`, `target/`, `.venv/`, `env/`)
  - Build/distribution outputs (`dist/`, `build/`, `out/`, `.next/`)
  - Lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`)
  - Minified bundles (`*.min.js`, `*.bundle.css`), source maps (`*.map`), and media assets

## 2. Terminal & Tool Execution Clamps
- **Truncate Output:** Always pipe shell commands with potentially large output through `head -n 40` or equivalent filters. Do not permit command output to exceed 50 lines.
- **Silent & Targeted Tests:** Run only the specific test file or unit test relevant to the task (e.g., `npm test -- path/to/test.ts` or `pytest tests/test_specific.py`). Always pass quiet/reporter flags (e.g., `--silent`, `-q`) to suppress passing-test telemetry.
- **Fail Fast:** If a build, lint, or test command fails, halt immediately and report the primary failure. Do not run secondary diagnostics, multi-command recovery scripts, or wide sweeps.

## 3. Reasoning & Execution Controls (GPT-6.1 Terra)
- **Direct Path Execution:** Do not explore alternative patterns, architectural re-evaluations, or hypothetical edge cases during internal reasoning. Implement the minimal path necessary to fulfill the prompt.
- **Single-Command Turn Limit:** Execute only one terminal command per tool-call turn. Evaluate stdout/stderr before issuing subsequent commands rather than chaining multiple commands together.
- **Stop on Ambiguous Errors:** If a command returns a syntax error, unexpected state, or missing dependency not referenced in the prompt, stop and ask. Do not attempt speculative `npm install`, package upgrades, or autonomous environment mutations.

## 4. Modification & Code Generation
- **Surgical Edits Only:** Apply targeted diffs to existing logic. Do not rewrite, reformat, or alter whitespace in surrounding functions or untouched lines.
- **Preserve Comments:** Retain existing comments; do not insert explanatory remarks, documentation blocks, or boilerplate unless explicitly instructed.

## 5. Output Brevity
- **Zero Conversational Filler:** Omit preambles, summaries of intentions, conversational acknowledgments, and sign-offs.
- **Report Format:** Conclude runs with strictly:
  1. Modified or created file paths.
  2. Verification command executed and status.
  3. Errors or blocking ambiguities (if any).
- **Ambiguity Halt:** If the target file or execution path is ambiguous, stop immediately and prompt for clarification rather than inferring across the codebase.