---
name: hpc-cluster
description: Use when working on the NHR@FAU HPC clusters (Fritz, Alex, Helma, TinyGPU, TinyFat, Woody, Testcluster) through an MCP server - writing or submitting Slurm job scripts, choosing file systems, loading modules, installing software, or interpreting refused tool calls.
---

# Working on the NHR@FAU clusters

Adapted from the NHR@FAU `SKILL.md` (see `reference/nhr/SKILL.md`). This version does not
assume a particular MCP server: the server you are connected to describes its own tools and
limits in its instructions. Where this guide and the server disagree, the server wins.

## The systems

Slurm-managed clusters, per <https://doc.nhr.fau.de/clusters/overview/>. Check the docs for
current hardware; never quote hardware numbers from memory.

| Cluster | Meant for |
|---------|-----------|
| Fritz | massively parallel (MPI) CPU jobs, large-memory nodes |
| Alex | high-end GPU computing (AI/ML, GPGPU; A100, A40) |
| Helma | high-end GPU computing (H100, H200) |
| TinyGPU | smaller-scale GPU computing |
| TinyFat | large-memory single-node jobs |
| Woody | serial and throughput jobs |
| Testcluster | evaluating new hardware, by request |

- An MCP server runs on **one** cluster's login node and sees only that cluster.
- Login nodes are shared: never compute on them. Short commands (version checks, small builds)
  are fine; everything else goes through a job.
- Compute nodes have **no direct internet access** (see the proxy below).
- Software comes as environment modules (`module avail`, `module load`).

## File systems

- **Code and scripts in `$HOME`; data, environments and logs in `$WORK`.**
- Nothing irreplaceable only in `$WORK`, `$FASTTMP` or `$TMPDIR`: they have no backup.
- `$HOME` is shared across all NHR@FAU clusters.
- Tools usually take literal paths and do not expand `$HOME` or `$WORK`. Use the paths the
  server reports.

## Job scripts

- Start with the shebang `#!/bin/bash -l`. The `-l` (login shell) is needed for the `module`
  command to exist.
- Put `#SBATCH --export=NONE` among the directives **and** `unset SLURM_EXPORT_ENV` as a command
  in the body. Together they give a clean environment that still propagates to `srun`.
- All `#SBATCH` lines come first and consecutively: the first other non-comment line (even a
  variable assignment) ends option parsing.
- Set a realistic `--time`. Start with a small test, then scale up.
- For internet access inside a job (pip, conda, curl, git clone), set
  `export http_proxy=http://proxy.nhr.fau.de:80 https_proxy=http://proxy.nhr.fau.de:80`, or
  pass it directly: `pip install --proxy http://proxy.nhr.fau.de:80 <package>`.
- A one-line command mode (`sbatch --wrap`) skips the shebang, so modules, the clean
  environment and the proxy are not reliable there. Use a script file whenever the job needs them.

Minimal script (look up partitions and resources per cluster in the docs):

```bash
#!/bin/bash -l
#SBATCH --job-name=example
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --export=NONE
unset SLURM_EXPORT_ENV

module load <modules you need>   # verify names with module avail first
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export SRUN_CPUS_PER_TASK=$SLURM_CPUS_PER_TASK

srun ./my_program
```

Things that fail silently rather than with an error: OpenMP running single-threaded
(`OMP_NUM_THREADS` unset), MPI ranks bound wrongly, writing to the wrong file system, and
using a bundled CUDA instead of the site module.

## Refused calls

A refusal is policy, not a bug. Tell the user what the message says and who can change it:

| Message names | Who can change it |
|---|---|
| a path outside the allowed directory / sandbox | the person who configured the MCP server |
| a tool disabled by the server or its policy | the person who configured the MCP server |
| a budget or limit (job count, walltime, size) | the person who configured the MCP server |
| a site / admin setting | the cluster administrators |
| a rate limit | nobody: wait, then make fewer, larger calls |

Never retry a refused call with a different tool, a different path or a generated script.

## Working practices

- Ask before anything destructive or irreversible: deleting files, overwriting files,
  cancelling jobs the user did not mention.
- Check cheaply first: quota before large outputs, `module show` before assuming what a module
  does, sizes before copying trees.
- Right-size jobs (realistic time and cores), watch them, and cancel a clearly broken job
  instead of letting it run out.
- No secrets in job scripts or project files.
- Report the real job state and the relevant output lines.

## More

- Site documentation: <https://doc.nhr.fau.de/>
- Job scripts: <https://doc.nhr.fau.de/batch-processing/batch_system_slurm/#job-scripts-general-structure>
- Python environments and the proxy: <https://doc.nhr.fau.de/environment/python-env/>
- Job monitoring: <https://doc.nhr.fau.de/job-monitoring-with-clustercockpit/>
- Support: <https://hpc.fau.de/>
