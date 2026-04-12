# Claude Code Skills

Reusable [Agent Skills](https://agentskills.io/specification) for Claude Code, Codex, Cursor, and other AI coding agents that support the `SKILL.md` standard.

## Installation

### Install all skills

```bash
npx skills add https://github.com/w01fgang/skills
```

### Install a specific skill

```bash
npx skills add https://github.com/w01fgang/skills --skill react-relay
```

### List available skills

```bash
npx skills add https://github.com/w01fgang/skills --list
```

### Install globally (available in every project)

```bash
npx skills add https://github.com/w01fgang/skills -g
```

Global skills land in `~/.claude/skills/`. Project-level installs land in `.claude/skills/` of the current directory.

## Available Skills

| Skill | Description |
|---|---|
| [`react-relay`](./react-relay) | Comprehensive reference for React Relay — hooks, directives, mutations, caching, network layer, resolvers, entrypoints, runtime, testing, debugging, principles, and codemods. Sourced from [relay.dev](https://relay.dev). |

## Skill Format

Each skill is a directory containing a `SKILL.md` with YAML frontmatter:

```
skill-name/
  SKILL.md          # required — frontmatter + reference content
  <topic>.md        # optional — deep reference files
```

Required frontmatter:

```yaml
---
name: skill-name
description: Use when [triggering conditions and keywords]
---
```

See the [Agent Skills specification](https://agentskills.io/specification) for full details.

## Contributing

1. Create a new directory matching your skill name (kebab-case).
2. Add a `SKILL.md` with valid frontmatter.
3. Keep `SKILL.md` concise; move deep reference into sibling `.md` files linked from it.
4. Validate: `npx skills-ref validate ./your-skill`
5. Open a PR.

## License

MIT
