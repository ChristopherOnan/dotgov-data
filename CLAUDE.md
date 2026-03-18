# CLAUDE.md — Project Configuration

## Project Overview

This repository contains .gov domain data (federal and full datasets) with supporting analysis tools.

## The Agency — AI Agent Framework

This project is powered by **The Agency** (https://github.com/msitarzewski/agency-agents), a collection of 156 specialized AI agents organized across 13 divisions. Agents are installed in `.claude/agents/` and can be activated by name in any session.

### Agent Divisions

| Division | Count | Key Agents |
|----------|-------|------------|
| Engineering | 24 | Frontend Developer, Backend Architect, Security Engineer, DevOps Automator, Senior Developer, AI Engineer |
| Design | 8 | UI Designer, UX Architect, UX Researcher, Brand Guardian, Whimsy Injector |
| Marketing | 27 | Growth Hacker, Content Creator, SEO Specialist, Social Media Strategist, TikTok Strategist |
| Sales | 8 | Outbound Strategist, Discovery Coach, Deal Strategist, Pipeline Analyst |
| Product | 5 | Product Manager, Sprint Prioritizer, Trend Researcher, Feedback Synthesizer |
| Project Management | 6 | Senior Project Manager, Project Shepherd, Studio Producer, Studio Operations |
| Testing | 8 | Evidence Collector, Reality Checker, API Tester, Performance Benchmarker |
| Support | 6 | Analytics Reporter, Finance Tracker, Infrastructure Maintainer, Legal Compliance |
| Specialized | 27 | Agents Orchestrator, MCP Builder, Workflow Architect, Compliance Auditor |
| Spatial Computing | 6 | XR Interface Architect, visionOS Spatial Engineer, macOS Metal Engineer |
| Game Development | 20 | Unity, Unreal, Godot, Roblox specialists + cross-engine roles |
| Academic | 5 | Historian, Psychologist, Anthropologist, Geographer, Narratologist |
| Paid Media | 7 | PPC Strategist, Programmatic Buyer, Paid Social Strategist |

### Activating Agents

Reference any agent by name in your prompt:

```
Activate Frontend Developer and help me build a React component.
Use the Code Reviewer agent to review this pull request.
Activate Agents Orchestrator in NEXUS-Sprint mode to build [feature].
```

### NEXUS Pipeline Orchestration

NEXUS (Network of EXperts, Unified in Strategy) coordinates multi-agent pipelines:

- **NEXUS-Full**: Complete product build (all agents, all phases)
- **NEXUS-Sprint**: Feature/MVP build (15-25 agents, 2-6 weeks)
- **NEXUS-Micro**: Single task (5-10 agents, 1-5 days)

See `strategy/QUICKSTART.md` for ready-to-use activation prompts.
See `strategy/nexus-strategy.md` for the complete doctrine.

### Quality Gates

1. Every task passes QA before advancing
2. Evidence (screenshots, test results, data) required for all assessments
3. Maximum 3 retries per task before escalation
4. Reality Checker is the final quality authority — defaults to "NEEDS WORK"

### Strategy Documents

- `strategy/QUICKSTART.md` — 5-minute start guide
- `strategy/nexus-strategy.md` — Complete NEXUS doctrine
- `strategy/playbooks/phase-0-discovery.md` through `phase-6-operate.md` — Phase playbooks
- `strategy/runbooks/` — Scenario-specific runbooks (startup MVP, enterprise feature, incident response, marketing campaign)
- `strategy/coordination/` — Agent activation prompts and handoff templates

### Scripts

- `scripts/install.sh` — Install agents to Claude Code, Copilot, Cursor, Aider, Windsurf, and other tools
- `scripts/convert.sh` — Convert agent formats between tools
- `scripts/lint-agents.sh` — Validate agent file format and frontmatter

## Development Guidelines

- Prefer data accuracy and integrity above all else
- CSV files use standard comma-separated format
- Follow existing naming conventions for data files
