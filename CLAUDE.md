# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Repository of reusable Claude Code skills. Each skill is a directory containing a `SKILL.md` file with YAML frontmatter (`name`, `description`) and markdown body providing domain-specific guidance.

## Skill Format

```
skill-name/
  SKILL.md          # frontmatter + reference content
```

Frontmatter fields:
- `name` — skill identifier (kebab-case)
- `description` — trigger description: when the skill activates and on which keywords

## Adding a Skill

1. Create `skill-name/SKILL.md` with `---` frontmatter block
2. Write concise, actionable reference (setup, patterns, pitfalls)
3. Keep examples minimal — show the canonical way, not every variation
