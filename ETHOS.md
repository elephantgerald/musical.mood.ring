# Project Ethos

## Philosophy: Mise en Place

Every element of this workspace has a designated place, and that place is respected without exception. Parsimony is a virtue — nothing is added without purpose, nothing is left where it does not belong.

---

## Structure

```
./
├── src/                  # All source code. May contain multiple sub-projects.
├── tests/
│   ├── unit/             # Isolated unit tests
│   ├── integration/      # Tests across system boundaries
│   └── end-to-end/       # Full-stack behavioral tests
├── build/                # Build scripts, deploy scripts, CI helpers
├── docs/                 # Documentation, specs, diagrams
├── README.md             # Project overview, quickstart, and usage
├── CLAUDE.md             # Instructions and context for AI-assisted development
├── ETHOS.md              # This file — the guiding principles of the workspace
├── .gitignore            # What git must never see
└── .gitattributes        # How git must treat what it does see
```

## Rules

**Source belongs in `src/`.** If it runs, it lives here. Sub-projects get their own subdirectories within `src/`.

**Tests belong in `tests/`.** Organized by scope: unit tests prove a function, integration tests prove a seam, end-to-end tests prove a behavior. Each tier is a separate concern.

**Build and deploy logic belongs in `build/`.** Not in the root, not in `src/`, not scattered across ad-hoc shell history.

**Documentation belongs in `docs/`.** Decisions, architecture, API references — written down, not just understood.

**The root is sacred.** Only top-level project artifacts live here: `README.md`, `CLAUDE.md`, `ETHOS.md`, `.gitignore`, `.gitattributes`, and configuration files with no better home.

---

## Security

API keys, secrets, tokens, and credentials are **never** committed to version control — not in code, not in comments, not in config files. They live in environment variables or a secrets manager. `.gitignore` is the first line of defense; discipline is the second.

When in doubt: if a file could expose a secret, it does not get committed.

---

## Parsimony

Add what is needed. Remove what is not. Resist the accumulation of files that exist "just in case." A tidy workspace is a workspace that can be understood — by a collaborator, by a future self, by an AI assistant returning to the project after time away.

The goal is not minimalism for its own sake, but clarity for everyone's sake.
