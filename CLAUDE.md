# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

macOS System Cleaner — Auto-scans and cleans unnecessary cache/build files on macOS.
Version is derived from git tags (single source of truth via `app/config.py:_get_version()`).
Uses only Python stdlib (zero external dependencies). Frontend is a single-file vanilla JS SPA.

## Commands

```bash
python3 run.py          # Dev run (auto-opens localhost:8787)
./build_app.sh          # Build .app (PyInstaller, auto-installed by script)
python3 -m pytest tests/ # Run tests (unittest-based, no external deps)
```

Tests are in `tests/` (unittest-based). Build verification via `./build_app.sh`.

## Git Workflow

- Branch model: git flow (feature -> develop -> release -> main + tag)
- Working branch: `develop`
- Version tags on `main` only

## Key Rules

- `sys.frozen` branching: resource paths change to `sys._MEIPASS` base in PyInstaller bundle. Present in config.py, server.py
- Path security: delete/query APIs only allow paths starting with `HOME` or `/var/log`
- `learned_folders.json` keys must be lowercase folder names, values are `{desc, risk}`
- Frontend is a single file `app/web/index.html` (no build step)

## Documentation Maintenance Rule (MANDATORY)

**After completing ANY feature branch or hotfix branch work, you MUST update `.claude-context/` documentation before the final commit.**

Checklist:
1. If new API endpoints were added/changed → update `architecture.json` `api` section
2. If new components/files were created → update `architecture.json` `components` section
3. If new coding patterns or gotchas were discovered → update `conventions.json`
4. If build process changed → update `architecture.json` `build` section
5. If version, commands, or key rules changed → update this file (`CLAUDE.md`)
6. Update `CLAUDE.ko.md` to reflect the same changes (Korean version for humans)

All three layers must stay in sync: `CLAUDE.md` ↔ `.claude-context/*.json` ↔ `CLAUDE.ko.md`.
This rule applies to every branch merge, no exceptions. Documentation drift causes future context loss.

## Detailed Context

Architecture, API specs, component relationships, and conventions are in structured JSON:

- [.claude-context/architecture.json](.claude-context/architecture.json) — Components, API routes, data flow, build config
- [.claude-context/conventions.json](.claude-context/conventions.json) — Coding patterns, gotchas, design decisions

Korean documentation for human readers: [CLAUDE.ko.md](CLAUDE.ko.md)
