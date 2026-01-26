# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ClickClickClick** - LLM-powered automation framework for Android and macOS. Enables autonomous device control through vision-based element detection and natural language task execution.

## Common Commands

```bash
# Development install
pip install -e .

# Install with test dependencies
pip install -e ".[test]"

# Run tests
pytest tests/

# Run single test
pytest tests/test_android.py -v

# Run CLI
click3 run "task description" --platform=android --planner-model=openai --finder-model=gemini
click3 gradio  # Web interface
click3 setup   # Configure API keys

# Start REST API
uvicorn api:app --host 0.0.0.0 --port 8000

# Code formatting
black --line-length=100 .

# Agent CLI (new system)
python agent_cli.py run vera_lx --device emulator-5554 --cycles 10
python agent_cli.py status vera_lx
python agent_cli.py test-nav --device emulator-5554
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Interfaces: CLI (main.py), API (api.py), Gradio (interface.py) │
├─────────────────────────────────────────────────────────────────┤
│  Execution: planner/task.py (main loop), utils.py (factories)   │
├─────────────────────────────────────────────────────────────────┤
│  Core Components (Abstract + Implementations):                   │
│  ├── Executor (executor/android.py, executor/osx.py)            │
│  ├── Planner (planner/openai.py, gemini.py, anthropic.py, etc)  │
│  └── Finder (finder/openai.py, gemini.py, anthropic.py, etc)    │
├─────────────────────────────────────────────────────────────────┤
│  Agent System (NEW - under development):                        │
│  ├── agent/ (orchestrator, session, scheduler)                  │
│  ├── navigator/ (UIAutomator XML parsing, no LLM)               │
│  └── memory/ (MongoDB persistence)                              │
├─────────────────────────────────────────────────────────────────┤
│  Config: config/models.yaml, prompts.yaml, function_declarations│
└─────────────────────────────────────────────────────────────────┘
```

**Three Core Roles:**
- **Executor**: Device control (screenshots, clicks, swipes, text input)
- **Planner**: LLM reasoning - analyzes screenshots, plans next actions
- **Finder**: Element detection - locates UI elements, returns coordinates

**Execution Flow:** screenshot → Planner LLM decides action → Finder LLM locates element → Executor performs action → repeat

## Key Implementation Patterns

### Adding a New LLM Provider
1. Create `planner/provider_name.py` implementing `Planner` base class
2. Create `finder/provider_name.py` implementing `BaseFinder` base class
3. Add configuration to `config/models.yaml`
4. Update `utils.py` factory functions

### Coordinate System
- LLM outputs coordinates in 512-1000 normalized range
- `scale_coordinates()` converts to actual screen dimensions via ADB
- Finder returns bounding boxes as `(ymin, xmin, ymax, xmax)`

### Configuration Files
- `config/models.yaml`: LLM settings, API keys (via `!ENV VAR_NAME`), image dimensions
- `config/prompts.yaml`: System prompts per platform/model
- `config/function_declarations/`: Platform-specific action definitions (common.yaml, android.yaml, osx.yaml)
- `config/agents/*.yaml`: Agent personality configs

## Environment Variables

```bash
OPENAI_API_KEY      # OpenAI models
ANTHROPIC_API_KEY   # Claude models
GEMINI_API_KEY      # Google Gemini models
OLLAMA_MODEL_NAME   # Local Ollama (default: llama3.2:latest)
```

## Platform-Specific Notes

**Android:**
- All operations via ADB (`adb shell` commands)
- Requires USB debugging enabled
- Device serial from `adb devices`
- Screenshots via `adb shell screencap`

**macOS:**
- Uses py-applescript for accessibility
- pyautogui for mouse/keyboard
- Requires Terminal/IDE accessibility permissions

## Model Selection (from testing)

| Use Case | Setup |
|----------|-------|
| Best overall | Planner: GPT-4o, Finder: Gemini Flash |
| Cost effective | Planner: GPT-4o-mini, Finder: Gemini Flash |
| Privacy/offline | Planner: Ollama, Finder: Ollama |

## Agent System (New Architecture)

Located in `agent/`, `navigator/`, `memory/`. Uses UIAutomator XML parsing for navigation (no LLM) and LLM only for reasoning tasks like comment generation.

**Key files:**
- `agent/orchestrator.py`: Main controller
- `navigator/uiautomator.py`: Parses accessibility tree from `adb shell uiautomator dump`
- `memory/store.py`: MongoDB operations
- `config/agents/vera_lx.yaml`: Agent personality example

**Model requirements for agent:**
- Complex tasks (Planner, reasoning): Gemini 3 series (`gemini-3-flash-preview`)
- Simple tasks (Finder, coordinates): Gemini 2.5+ (`gemini-2.5-flash-lite`)
