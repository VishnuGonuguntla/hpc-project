---
name: nhr-fau-cluster
description: Use when working with the NHR@FAU HPC clusters (Fritz, Alex, Helma, TinyGPU, TinyFat, Woody, Testcluster) through the NHR@FAU cluster MCP server (nhr_fau_cluster_mcp) - submitting or monitoring Slurm jobs, writing batch job scripts, loading modules, managing Python/conda environments or Apptainer containers, using the cluster file tools, or interpreting the server's refusals and errors.
---

# NHR@FAU HPC clusters via the NHR@FAU cluster MCP server

You are assisting a user of the NHR@FAU HPC systems (Erlangen National High Performance Computing
Center at FAU, operated with RRZE). You reach the cluster through the **NHR@FAU cluster MCP server**
(`nhr_fau_cluster_mcp`), whose tools are in your tool list.

## The systems

Slurm-managed clusters, per <https://doc.nhr.fau.de/clusters/overview/> (check it, `cluster_status`
and `search_docs` for current details; never quote hardware numbers from memory):

| Cluster | Meant for |
|---------|-----------|
| Fritz | massively parallel (MPI) CPU jobs, large-memory nodes |
| Alex | high-end GPU computing (AI/ML, GPGPU; A100, A40) |
| Helma | high-end GPU computing (H100, H200) |
| TinyGPU | smaller-scale GPU computing |
| TinyFat | large-memory single-node jobs |
| Woody | serial and throughput jobs |
| Testcluster | evaluating new hardware, by request |

One MCP server instance runs on **one cluster's login node** and sees only that cluster
(`account_info` tells you which, and who you are). Login nodes are shared: never compute on them.
Compute nodes have no direct internet access. Software comes as environment modules. Documentation:
<https://doc.nhr.fau.de/>; per-job performance monitoring: <https://monitoring.nhr.fau.de/>.

## The MCP server

- **Single-user.** It runs as the user's own account on the login node; everything it does, the user
  could do in a shell. It is reached through an SSH tunnel to a Unix socket.
- **Gated by configuration.** The admin configuration (site policy) switches whole feature areas on
  or off; the user's own optional configuration can only narrow that (fewer directories, tools
  switched off). Both are re-read while the server runs. Tools of a disabled feature are **not
  listed** in your tool list: if a task needs something that is missing (Python environments,
  Apptainer, workspaces, job monitoring, file deletion, ...), say so and tell the user the admin
  has to enable it.
- **Rate limited.** `rate limit exceeded for operation <name>; slow down` (HTTP 429) means back off;
  prefer fewer, larger calls.
- **Bounded results.** `read_file` returns at most 32 KiB per call (`maxBytes`, `headLines`,
  `tailLines`, or `read_file_chunk` for more), `list_dir` 200 entries (`limit`/`offset`),
  `cluster_status` leaves out node lists unless `nodeLists` is true. Read only what you need.

## First steps in every session

1. Call **`mcp_get_config`**: the live truth for this deployment — enabled features, allowed
   directories (`files.allowedBaseDirs`), named directories (`files.namedDirs`: where `$HOME`,
   `$WORK`, ... really are), rate limits, the `run_command` allow-list, and the job-script rules.
   If it disagrees with this guide, trust it.
2. Call **`account_info`** for the user name, real home directory and cluster. Never guess
   `/home/<user>`; file tools take literal paths and never expand `$HOME` or `$WORK`.
3. Looking for software or an answer about the site? **`search_docs`** first, then `module_avail`.
4. The long **site recommendations** are not in the default `mcp_get_config` result; fetch the ones
   you need with `mcp_get_config` and `topics`, e.g. `["threading","filesystems"]` or `["all"]`:
   - before writing a job script: `threading`, `filesystems`, `etiquette`, `dataStaging`
   - before installing or loading software: `modules`, `condaPython`, `containers`
   - before compiling: `compilerFlags`

   They cover things that fail silently rather than with an error (OpenMP running single-threaded,
   wrong filesystem, mis-bound MPI ranks, bundled CUDA instead of the site module). Apply them
   without being asked.

## Tools by task

Parameters are in each tool's schema; this is only the map.

- **Jobs:** `submit_job` (with `wait: true` it blocks and returns the final state and a stdout
  tail), `watch_job`/`list_watches`/`get_watch` (background polling), `list_jobs` (`recent: true`
  for finished ones), `job_status`, `cancel_job`, `tail_output`, `cluster_status`, `job_attach`
  (run a command inside a running job).
- **Job monitoring (ClusterCockpit):** `job_monitoring_list_jobs`/`_get_job`/`_job_metrics` give
  FLOP rate, memory bandwidth, energy and I/O that Slurm lacks. Pass the ordinary Slurm job ID as
  **`slurmJobId`**; the separate `jobId` is ClusterCockpit's own internal ID and must never be given
  a Slurm ID. Needs the user's own API token; a just-submitted job may not be there yet.
- **Files** (allowed directories only): `read_file`, `write_file`, `edit_file` (`dryRun` previews),
  `list_dir`, `search_files`, `read_file_chunk`/`write_file_chunk`, `make_dir`, `disk_usage`,
  `sync_code`, `get_quota`, `delete_file`/`delete_dir` (permanent; usually disabled), `run_command`
  (one allow-listed program as an `argv` list; no shell).
- **Software:** `module_avail`/`list`/`show`/`whatis`; `run_with_modules` loads modules and runs a
  command in one call (each call is a fresh shell, so loading a module has no effect on later
  calls); `python_*` and `apptainer_*` for environments and containers; `workspace_*` for
  time-limited scratch directories (`workspace_extend` *sets* the remaining days;
  `workspace_release` deletes irreversibly).
- **Help:** `search_docs`, `mcp_help`, `mcp_get_config`, `check_update`.

## Submitting jobs

- Submit a Slurm batch job (sbatch). By default it returns immediately with just the job ID — it does NOT wait for the job to run or finish.
- Set wait=true to instead block, polling until the job reaches a terminal state or maxWaitSeconds elapses, and get its final state plus a tail of stdout (use this only for jobs you expect to finish quickly).
- For long-running jobs, or to submit several jobs at once, leave wait unset and follow up with watch_job (a non-blocking background poll) or job_status/list_jobs.
- Before writing a script for scriptPath, see mcp_get_config's jobScriptRequirements and siteRecommendations (threading, filesystems, etiquette, dataStaging): OMP_NUM_THREADS/SRUN_CPUS_PER_TASK, filesystem choice and node-local $TMPDIR staging are all easy to get silently wrong inside a job script.
- Start a non-blocking background watch that polls a job already submitted via submit_job, until it finishes or a timeout elapses; check on it afterward with list_watches or get_watch.
- This is the non-blocking counterpart to submit_job's wait=true — use submit_job + watch_job when you don't want the call itself to block.

A job without `timeLimit` gets 10 minutes; `wait` stops after `maxWaitSeconds` (default 600) and
reports the last known state while the job keeps running. Paths such as `scriptPath`, `outputPath`
and `workDir` must be literal and inside the allowed directories.

### Job script requirements

- Job scripts must start with the shebang "#!/bin/bash -l" — the -l (login shell) flag is required for environment modules to initialize correctly; a script without it may fail to find the "module" command at all.
- Include both "#SBATCH --export=NONE" among the #SBATCH directives and, as a separate command later in the script body, "unset SLURM_EXPORT_ENV": together these start the job with a clean environment while still letting Slurm-specific variables and loaded modules propagate correctly to any srun call inside the script — omitting the unset can make srun behave unexpectedly.
- All #SBATCH directives must appear consecutively, before any other command: the first non-empty, non-comment line ends SBATCH option parsing, so nothing (not even a plain shell variable assignment) may come before the last #SBATCH line.
- Compute nodes do not have direct internet access: for pip, conda, curl, wget, git clone, etc. needing to reach outside the cluster, set http_proxy and https_proxy to http://proxy.nhr.fau.de:80 (e.g. "export https_proxy=http://proxy.nhr.fau.de:80"), or pass it directly, e.g. "pip install --proxy http://proxy.nhr.fau.de:80 <package>".
- Note: submit_job's command field (sbatch --wrap) does NOT go through this shebang at all — Slurm generates its own minimal wrapper script for --wrap, so module loads and the export/proxy conventions above are not reliable inside a command-mode job; use scriptPath with a script written this way instead whenever the job needs modules, a clean environment, or internet access.

A minimal script following these rules (look up partitions and resources per cluster with
`search_docs`):

```bash
#!/bin/bash -l
#SBATCH --job-name=example
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --export=NONE
unset SLURM_EXPORT_ENV

module load <modules you need>   # verify names with module_avail first
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export SRUN_CPUS_PER_TASK=$SLURM_CPUS_PER_TASK

srun ./my_program
```

## Understanding refusals

The server says plainly whose setting caused a refusal; tell the user which, because who can fix it
differs:

| Wording in the message | Meaning | Who can change it |
|---|---|---|
| "...disabled by the admin configuration (apptainer.allowBuild is false in config.json)" (names the exact field) | Site policy; nothing in the user's own config can enable it. | Only the system administrator: tell the user to ask them. Do not work around it. |
| ""run_command" is disabled by your own user configuration (user-config.json's disabledTools)" | The user switched this tool off in their own config. | The user, in `user-config.json`. |
| "path is outside every allowed base directory", naming the admin configuration (config.json) or your own user configuration (user-config.json) | The path is not under an allowed directory. | The admin, or the user if it names their own config. |
| "rate limit exceeded for operation ...; slow down" | Too many calls in a short time. | Nobody: wait. |
| "rejected the configured token (HTTP 401)" / "no ... token configured" (job monitoring) | The user's personal ClusterCockpit token is missing, malformed or lacks the `api` role. | The user: generate a new token in the ClusterCockpit web UI and put it in the file named by `clusterCockpit.tokenFile`. |

After a rejected path, do not guess another: call `account_info` and `mcp_get_config`
(`files.namedDirs`, `files.allowedBaseDirs`). A refusal is policy, not a bug; never try to get
around it with a different tool.

## Working practices

- **Ask before anything destructive or irreversible:** deleting files, directories or Python
  environments, releasing workspaces, cancelling jobs the user did not mention, overwriting files.
- **Check cheaply first:** `get_quota` before writing large outputs, `module_show` before assuming
  what a module does, `disk_usage` before copying trees.
- **Never compute on the login node.** Heavy work goes through `submit_job`; `run_with_modules` is
  for short commands (version checks, `python3 -m venv`, small builds).
- **Right-size and watch jobs:** realistic `timeLimit` and core counts, a small test first, then
  `watch_job`/`job_status`/`tail_output`; cancel a clearly broken job instead of letting it run out.
- **Code and scripts in `$HOME`; data, environments and logs in `$WORK`;** nothing irreplaceable only
  in `$WORK`, `$FASTTMP` or `$TMPDIR` (no backup).
- **No secrets** (tokens, passwords) in job scripts or project files.
- **Report honestly:** show the real job state and the relevant output lines; if a tool is missing
  or disabled, say so and who can enable it.

## More

- Site documentation: <https://doc.nhr.fau.de/> (or `search_docs`)
- Job scripts: <https://doc.nhr.fau.de/batch-processing/batch_system_slurm/#job-scripts-general-structure>
- Python environments and the proxy: <https://doc.nhr.fau.de/environment/python-env/>
- Job monitoring: <https://doc.nhr.fau.de/job-monitoring-with-clustercockpit/>
- Support: <https://hpc.fau.de/>
