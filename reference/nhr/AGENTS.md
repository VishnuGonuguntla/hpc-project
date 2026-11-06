# AGENTS.md — NHR@FAU HPC clusters (nhr_fau_cluster_mcp)

> **For the human adding this to a project:** copy this file into your project as `AGENTS.md` (or
> into whatever instruction file your AI tool reads: `CLAUDE.md`, `.github/copilot-instructions.md`,
> ...), delete this note, and add a short section of your own at the end (project/account name, your
> usual cluster, where your data lives). If your AI tool supports agent skills, also install the
> `nhr-fau-cluster` skill folder (`SKILL.md`) from the same download into the tool's skills
> directory (for Claude Code: `.claude/skills/` in the project or `~/.claude/skills/`); it carries
> the full guidance and is only loaded when a task needs it. If your tool has no skill support,
> paste the body of `SKILL.md` (everything after its heading) into this file instead of the short
> text below.

This project uses the NHR@FAU HPC clusters through the NHR@FAU cluster MCP server
(`nhr_fau_cluster_mcp`), whose tools are in your tool list.

- If the `nhr-fau-cluster` skill is available, load it before working with the cluster, the
  Slurm tools, job scripts, modules, Python/Apptainer environments or the server's file tools.
- Either way, at the start of every session call `mcp_get_config` and `account_info`. They are the
  live truth about this deployment (enabled features, allowed directories, where `$HOME`/`$WORK`
  really are). `mcp_get_config` also returns `jobScriptRequirements`: read and follow it before
  writing any job script, and fetch the site recommendations you need with its `topics` argument.
- Never run heavy computation on a login node; use `submit_job`.
- Ask the user before anything destructive or irreversible (deleting files, directories or
  environments, releasing workspaces, cancelling jobs they did not mention).
- If a tool is missing or a call is refused, say which configuration is responsible (the message
  names it) and who can change it; never work around a refusal.
