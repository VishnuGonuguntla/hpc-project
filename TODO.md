# TODO

Status 2026-11-06: steps 0–3 done (MCP server, recorders, `./void` with Pi, Claude Code, OpenCode;
`--continue`, `--sandbox`, `--dir`). Everything runs on the `local` cluster profile so far.

## Now

- [ ] Try the TUIs: `./void pi`, quit, `./void pi --continue`; same with `claude` and `opencode`
- [ ] Connect the test cluster (needs OK for cluster access)
  - [ ] `./deploy.sh test_front_hiwi` (replaces the prototype)
  - [ ] copy `config/clusters/nhr-testcluster.example.toml` to `nhr-testcluster.local.toml`, fill in
  - [ ] `./void pi --cluster nhr-testcluster --task hello-edit`
  - [ ] remove the prototype entry from `~/.pi/agent/mcp.json`
- [ ] Course milestone: one-page plan with hypotheses in the repo (due ~3 weeks after kick-off)

## Roadmap

- [ ] **Step 4: job tools** in the MCP server: `compile`, `submit_job` / `job_status` / `job_output`
  with budgets (max jobs, max walltime, allowed partitions, compiler allowlist) in a policy file;
  job-script rules from `skills/hpc-cluster`; tests
- [ ] **Step 5: inference on a GPU** (TinyGPU; Alex needs the Tier3 form): vLLM or llama.cpp in a
  Slurm job (Apptainer image, digest in the manifest), SSH tunnel, model profile
- [ ] **Step 6: tasks and analysis** for the chosen topic: real tasks with tests and reference
  solution, repetitions, metrics from `llm.jsonl` / `mcp.jsonl` (tokens, turns, model vs tool time),
  performance model vs measurement, plots
- [ ] **Hardening**: harness in a container without SSH keys; then optional `--local-tools`
- [ ] **Run index**: SQLite or DuckDB over `runs/`, maybe a small viewer
- [ ] **mitmproxy** as a second LLM recorder (same `llm.jsonl` format), chosen by config

## Decisions to take

- [ ] Topic (7 harness design and 10 cluster-aware agents fit best)
- [ ] Separate cluster account for the agent (ask the chair)
- [ ] MCP server per session over SSH (now) or long-running on the login node (HTTP + tunnel)
- [ ] Where large runs go (now: `runs/` local, one example in git)

## Known shortcuts (`shortcut:` comments in the code)

- `run.py`: skill text always inlined into the system prompt (~1.5k tokens)
- `run.py`: remote `--dir` paths checked by shape only, not resolved on the cluster
- `harnesses.py`: OpenCode output cap fixed at 4096 tokens instead of per model profile
- `record/llm_proxy.py`: `accept-encoding` dropped so logged responses stay readable

## Known issues

- OpenCode's title request blocks the first ~5 minutes with a thinking model on Ollama
  (one request at a time); consider `OLLAMA_NUM_PARALLEL=2` or a non-thinking title model
- Two sessions in the same sandbox at once can overwrite each other's files (no locking)
- `edit_file` changes files in a `--dir` folder directly: keep it under git

## Cleanup

- [ ] Test cluster: old prototype `~/agent-mcp/calls.jsonl` (replaced by deploy), `~/agent-sandbox/hello.txt`
- [ ] NHR home: unused `~/.claude`, `~/.claude.json`, maybe `~/.venv` (check `pyvenv.cfg` first)
- [ ] Course rule: document AI use for code and documentation
