
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Agent-a-thon hackathon project with two AI agents:

- **`main.py`** — Production agent: OpenTable reservation assistant using Claude + Playwright browser automation (human-in-the-loop)
- **`demo.py`** — Starter/demo agent: Lehigh University campus assistant using OpenAI + Tavily + Gradio, designed to run in Google Colab

## Running the agents

```bash
# main.py — OpenTable agent (runs locally)
pip install anthropic playwright python-dotenv
playwright install chromium
python main.py

# First run: browser opens → log in to OpenTable manually → press Enter
# Session saved to auth_state.json; subsequent runs skip login
```

`demo.py` is structured as Colab cells and is not meant to run locally — copy/paste cells into Google Colab.

## Environment variables

`key.env` holds `TAVILY_API_KEY` and `OPENAI_API_KEY` (for `demo.py`).  
`main.py` reads `ANTHROPIC_API_KEY` via `python-dotenv` (add it to `key.env` or `.env`).

## Architecture: main.py

**Browser layer** (`Browser` class): wraps a persistent Playwright Chromium context. Saves/restores login state via `auth_state.json`.

**Tool layer** — four async functions Claude can call:
- `search_restaurants` — navigates OpenTable search, scrapes result cards
- `open_restaurant` — clicks a card by index
- `select_time_slot` — clicks a time button on the detail page
- `prepare_booking` — fills special-requests field, scrolls to confirm button, **stops there**

**Agent loop** (`chat_loop`): standard Anthropic tool-use loop. On `stop_reason == "tool_use"`, dispatches each tool call via `dispatch()`, appends results, and continues until Claude returns plain text.

**Human-in-the-loop invariant**: `prepare_booking` never clicks the final confirm — the user must do that in the browser. The system prompt reinforces this.

## Architecture: demo.py

Standard OpenAI tool-use loop with two tools: `search_web` (Tavily) and `post_to_discord` (webhook). Every agent reply is also auto-posted to Discord via `_post_discord`. UI is a Gradio `ChatInterface` launched with `share=True`.