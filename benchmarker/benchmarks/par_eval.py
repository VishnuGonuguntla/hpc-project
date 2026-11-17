from benchmarks.benchmark import Benchmark
from models.model import Model
import subprocess
import json
import sys
from pathlib import Path

from ParEval.generate.generate_groq import perform_benchmark

BASE_DIR = Path(__file__).resolve().parent
PAR_EVAL_DIR = (BASE_DIR / ".." / "ParEval").resolve()
DRIVERS_DIR = f"{PAR_EVAL_DIR}/drivers"
PROMPTS_PATH = PAR_EVAL_DIR / "prompts" / "generation-prompts.json"

ALLOWED_MODELS = {"serial", "omp", "mpi", "mpi+omp"}


class ParEval(Benchmark):
    def __init__(self, filtered_prompts_file: Path = "run/prompts.json"):
        self.filtered_prompts_file = filtered_prompts_file


    def generate(self, model: Model, output_file : Path = "result.json", num_samples : int = 1):
        filtered_prompts_file = self._filter_prompts(self.filtered_prompts_file)

        perform_benchmark(model=model, prompts=filtered_prompts_file, output=output_file, 
                      num_samples_per_prompt=num_samples, max_requests=1
                      )
        
        self._filter(output_file, output_file)

    def evaluate(self, result_file: Path = "result_filtered.json", output_file: Path = "evaluation_results.json"):
        input_json = Path(result_file).resolve()
        output_json = Path(output_file).resolve()

        cmd = [
            sys.executable, f"run-all.py",
            str(input_json),
            "-o", str(output_json),
            "--overwrite",
            "--yes-to-all",
            "--log-build-errors", "--log", "DEBUG",
            "--include-models", *ALLOWED_MODELS,
            "--launch-configs", f"{DRIVERS_DIR}/launch-configs-local.json",
            "--driver-root", str(DRIVERS_DIR),
        ]
        result = subprocess.run(cmd, cwd=DRIVERS_DIR, text=True, capture_output=True)
        print(result.stdout)
        print(result.stderr)
        result.check_returncode()

    def _filter(self, json_file_in, json_file_out):
        with open(json_file_in, "r") as f:
            data = json.load(f)

        keep = [p for p in data if p.get("outputs")]

        with open(json_file_out, "w") as f:
            json.dump(keep, f, indent=2)

    def _filter_prompts(self, output_path: Path) -> Path:
        with open(PROMPTS_PATH) as f:
            data = json.load(f)

        keep = [p for p in data if p["parallelism_model"] in ALLOWED_MODELS]

        with open(output_path, "w") as f:
            json.dump(keep, f, indent=2)

        print(f"{len(keep)} von {len(data)} Prompts behalten")

        return output_path
