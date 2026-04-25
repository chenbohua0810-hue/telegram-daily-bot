# Antigravity Agent Rules and Skills

這份檔案整理目前 Hermes/Codex Agent 會遵循的主要規則、使用者偏好與可用 skills，供匯入或轉寫到 Antigravity 使用。

## 1. Language Preference

- Default response language: Traditional Chinese.
- Code, variable names, function names, type/interface/component names, constants, and commit messages should be written in English.
- Keep terminal-facing replies simple and readable in a CLI.

## 2. Privacy and Security Rules

Before executing any task:

- Files containing passwords, API keys, or tokens may be handled locally, but secrets must not be sent to external APIs.
- Personal sensitive data, such as national ID numbers or bank account numbers, must not be sent to external APIs.
- If sensitive information is discovered, pause and ask the user before continuing.
- Any external API call must be explicitly disclosed to the user.
- In login, authorization, deployment, or secret-input flows, prefer having the user enter secrets themselves instead of exposing them to the agent.
- Avoid hardcoding secrets.
- Before finalizing code, check for hardcoded secrets, SQL injection risks, XSS risks, and leftover debug code.

## 3. Shell and File Operation Rules

- Prefer `trash` instead of `rm` so deleted files can be restored.
- Use `/bin/rm` only when permanent deletion is truly required, and inform the user first.
- Ask for confirmation before destructive operations, including:
  - force push
  - `reset --hard`
  - deleting or clearing directories
  - irreversible data changes
- Do not use destructive shell commands without user confirmation.
- On macOS/Homebrew, prefer `/opt/homebrew` paths and native ARM binaries.
- User hardware context: MacBook Pro M4, 16GB RAM, arm64.

## 4. Tool-Use Discipline

- Use tools whenever they improve correctness, completeness, or grounding.
- Do not merely describe planned actions if tools are available; execute the action.
- Continue working until the task is complete and verified.
- If a tool result is empty or partial, retry with another strategy before giving up.
- Use tools for:
  - arithmetic or calculations
  - hashes, encodings, checksums
  - current time/date/timezone
  - OS, CPU, memory, disk, ports, process state
  - file contents, file sizes, line counts
  - git history, branches, diffs
  - current facts, news, weather, versions
- Ask clarification only when ambiguity genuinely changes what action should be taken.

## 5. Code Style Rules

### Immutability

- Prefer creating new objects instead of mutating existing objects.
- Avoid in-place mutation unless there is a clear and justified reason.

### Naming

- Variables and functions: `camelCase`
- Types, interfaces, classes, and components: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Boolean names should start with `is`, `has`, `should`, or `can`.

### Structure

- Prefer KISS, DRY, and YAGNI.
- Avoid deeply nested logic over 4 levels.
- Avoid magic numbers.
- Avoid functions longer than 50 lines when practical.
- Prefer files around 200–400 lines; avoid exceeding 800 lines unless justified.
- Use explicit error handling and boundary/input validation.
- Keep behavior readable and testable.

## 6. Development Workflow

Preferred workflow:

1. Research first.
2. Plan.
3. Use test-driven development where appropriate.
4. Implement.
5. Review.
6. Verify.
7. Commit.

Testing preferences:

- Prefer at least 80% test coverage when practical.
- Prefer AAA test structure: Arrange, Act, Assert.
- Test names should clearly describe behavior.
- Verify changes before reporting completion.

## 7. Git Rules

Commit message format:

```text
<type>: <description>
```

Allowed types:

- `feat`
- `fix`
- `refactor`
- `docs`
- `test`
- `chore`
- `perf`
- `ci`

Before commits:

- Inspect git diff.
- Run relevant tests/checks when practical.
- Ensure no secrets or debug leftovers are committed.

## 8. Cost and Deployment Preferences

- The user is cost-conscious for cloud deployments.
- Prefer cheaper hosting and API options when discussing cloud deployments.
- For Hermes/Telegram bot deployment, consider low-cost options first.
- The user prefers using Claude subscription / Claude Code login credentials over Anthropic API-key billing when possible.

## 9. Persistence and Memory Rules

- Durable facts about the user, environment, preferences, or stable conventions should be saved as memory.
- Do not save temporary task progress, one-off outcomes, or completed-work logs as memory.
- Procedures and reusable workflows should be saved as skills, not memory.
- If a loaded skill is outdated, incomplete, or wrong, patch the skill immediately.
- After complex or iterative tasks, offer to save a reusable workflow as a skill.

## 10. Important Existing Local Context

- User has custom Claude skills under `~/.claude/skills`.
- Useful Claude-side workflow references include:
  - `gemini-codex-workflow`
  - `search-first`
  - `verification-loop`
  - `strategic-compact`
- User has Claude-side environment/rule source at:
  - `/Users/chenbohua/.claude/CLAUDE.md`
- User has Codex-side rule source at:
  - `~/.codex/AGENTS.md`
- Local Hermes Agent source repository:
  - `/Users/chenbohua/.hermes/hermes-agent`
- Hermes Agent upstream remote:
  - `https://github.com/NousResearch/hermes-agent.git`
- User fork remote name:
  - `zeabur-origin`

## 11. Skill Usage Rule

Before responding to a task, scan available skills. If any skill is relevant or partially relevant, load and follow it. Err on the side of loading a relevant skill.

If no skill is genuinely relevant, proceed without loading one.

## 12. Available Skills

### Apple / macOS

- `apple-notes`: Manage Apple Notes via memo CLI on macOS.
- `apple-reminders`: Manage Apple Reminders via remindctl CLI.
- `findmy`: Track Apple devices and AirTags via FindMy.app on macOS.
- `imessage`: Send and receive iMessages/SMS via imsg CLI on macOS.

### Autonomous AI Agents

- `claude-code`: Delegate coding tasks to Claude Code CLI agent.
- `codex`: Delegate coding tasks to OpenAI Codex CLI agent.
- `hermes-agent`: Guide to using and extending Hermes Agent.
- `hermes-zeabur-telegram-deploy`: Deploy Hermes Agent as a Telegram bot on Zeabur.
- `opencode`: Delegate coding tasks to OpenCode CLI agent.

### Creative

- `architecture-diagram`: Generate dark-themed SVG software architecture diagrams.
- `ascii-art`: Generate ASCII art using pyfiglet, cowsay, boxes, etc.
- `ascii-video`: Pipeline for ASCII art video production.
- `baoyu-comic`: Knowledge comic creator.
- `baoyu-infographic`: Generate professional infographics.
- `excalidraw`: Create hand-drawn style diagrams using Excalidraw JSON.
- `ideation`: Generate project ideas through creative constraints.
- `manim-video`: Production pipeline for mathematical and technical animations.
- `p5js`: Pipeline for interactive/generative visuals.
- `pixel-art`: Convert images into retro pixel art.
- `popular-web-designs`: Design systems from real websites.
- `songwriting-and-ai-music`: Songwriting and AI music generation prompts.

### Data Science

- `jupyter-live-kernel`: Use a live Jupyter kernel for iterative Python work.

### DevOps

- `webhook-subscriptions`: Create and manage webhook subscriptions.

### Dogfood / QA

- `dogfood`: Systematic exploratory QA testing of web applications.

### Email

- `himalaya`: Manage email via IMAP/SMTP using himalaya CLI.

### Gaming

- `minecraft-modpack-server`: Set up modded Minecraft servers.
- `pokemon-player`: Play Pokemon games autonomously via headless emulation.

### GitHub

- `codebase-inspection`: Inspect and analyze codebases using pygount.
- `github-auth`: Set up GitHub authentication using git/GitHub CLI.
- `github-code-review`: Review code changes and diffs.
- `github-issues`: Create, manage, triage, and close GitHub issues.
- `github-pr-workflow`: Full pull request lifecycle.
- `github-repo-management`: Clone, create, fork, configure, and manage repositories.

### Leisure

- `find-nearby`: Find nearby places.

### MCP

- `mcporter`: Use mcporter CLI to list, configure, auth, and call MCP servers.
- `native-mcp`: Built-in MCP client configuration and usage.

### Media

- `gif-search`: Search and download GIFs from Tenor.
- `heartmula`: Set up and run HeartMuLa music generation.
- `songsee`: Generate spectrograms and audio feature visualizations.
- `youtube-content`: Fetch YouTube transcripts and transform content.

### MLOps

- `huggingface-hub`: Hugging Face Hub CLI search/download/upload.

### MLOps / Cloud

- `modal-serverless-gpu`: Serverless GPU cloud workflows.

### MLOps / Evaluation

- `evaluating-llms-harness`: Evaluate LLMs across academic benchmarks.
- `weights-and-biases`: Track ML experiments.

### MLOps / Inference

- `gguf-quantization`: GGUF format and llama.cpp quantization.
- `guidance`: Control LLM output with regex/grammars.
- `llama-cpp`: Local GGUF inference with llama.cpp.
- `obliteratus`: Remove refusal behaviors from open-weight LLMs.
- `outlines`: Guarantee valid JSON/XML/code structure.
- `serving-llms-vllm`: Serve LLMs with vLLM.

### MLOps / Models

- `audiocraft-audio-generation`: PyTorch audio generation.
- `clip`: OpenAI CLIP vision-language model workflows.
- `segment-anything-model`: Segment Anything Model workflows.
- `stable-diffusion-image-generation`: Stable Diffusion image generation.
- `whisper`: Speech recognition with Whisper.

### MLOps / Research

- `dspy`: Build complex AI systems with declarative programming.

### MLOps / Training

- `axolotl`: Fine-tune LLMs with Axolotl.
- `fine-tuning-with-trl`: Fine-tune LLMs using TRL.
- `grpo-rl-training`: GRPO/RL fine-tuning with TRL.
- `peft-fine-tuning`: LoRA/QLoRA fine-tuning.
- `pytorch-fsdp`: Fully Sharded Data Parallel training.
- `unsloth`: Fast fine-tuning with Unsloth.

### Note Taking

- `obsidian`: Read, search, and create notes in Obsidian vaults.

### Productivity

- `google-workspace`: Gmail, Calendar, Drive, Contacts, Sheets, Docs integrations.
- `linear`: Manage Linear issues/projects/teams.
- `maps`: Geocode, reverse-geocode, and location intelligence.
- `nano-pdf`: Edit PDFs with natural-language instructions.
- `notion`: Manage Notion pages and databases.
- `ocr-and-documents`: Extract text from PDFs and scanned documents.
- `powerpoint`: Work with `.pptx` files.

### Red Teaming

- `godmode`: Jailbreak API-served LLMs using G0DM0D3 techniques.

### Research

- `arxiv`: Search and retrieve academic papers from arXiv.
- `blogwatcher`: Monitor blogs and RSS/Atom feeds.
- `llm-wiki`: Build and maintain Karpathy-style LLM Wiki.
- `polymarket`: Query Polymarket prediction market data.

### Smart Home

- `openhue`: Control Philips Hue lights, rooms, and scenes.

### Social Media

- `xitter`: Interact with X/Twitter via x-cli.
- `xurl`: Interact with X/Twitter via official X API CLI.

### Software Development

- `flatten-nested-project-layout`: Safely flatten deeply nested local project layouts.
- `handoff-driven-implementation`: Continue implementation from an existing handoff/spec.
- `handoff-spec-worktree-implementation`: Continue implementation from handoff/spec inside a worktree.
- `plan`: Plan mode for Hermes.
- `requesting-code-review`: Pre-commit verification pipeline and static security scan.
- `subagent-driven-development`: Use subagents for independent implementation workstreams.
- `systematic-debugging`: Systematic debugging for bugs/test failures/unexpected behavior.
- `test-driven-development`: TDD workflow for features and bug fixes.
- `writing-plans`: Write implementation plans from specs/requirements.

## 13. Suggested Antigravity Instruction Block

You can paste the following condensed instruction block into Antigravity:

```text
Default to Traditional Chinese for user-facing replies. Keep code, variable names, type names, constants, and commit messages in English.

Prioritize privacy and safety. Do not send secrets, API keys, tokens, personal IDs, or bank data to external APIs. If sensitive information is discovered, pause and ask the user. Clearly disclose any external API calls before making them.

Use `trash` instead of `rm`; use `/bin/rm` only for truly permanent deletion after informing the user. Ask before destructive operations such as force push, reset --hard, clearing directories, or irreversible data changes.

Prefer immutable code: create new objects instead of mutating existing ones. Use camelCase for variables/functions, PascalCase for types/components, UPPER_SNAKE_CASE for constants, and boolean names beginning with is/has/should/can. Follow KISS, DRY, YAGNI. Avoid deep nesting, magic numbers, long functions, and oversized files. Validate inputs and handle errors explicitly.

Development workflow: Research First -> Plan -> TDD when practical -> Implement -> Review -> Verify -> Commit. Prefer tests with AAA structure and clear behavior names. Aim for at least 80% coverage when practical.

Git commits must use `<type>: <description>` with type one of feat, fix, refactor, docs, test, chore, perf, ci. Inspect diffs and check for secrets/debug leftovers before committing.

For cloud/deployment topics, prefer cost-conscious options. For Claude/Hermes usage, prefer Claude subscription or Claude Code login credentials over Anthropic API-key billing when possible.

Before each task, check whether a relevant skill/workflow exists. If relevant, follow it. If a reusable workflow is discovered, save it as a skill/procedure rather than temporary notes.
```
