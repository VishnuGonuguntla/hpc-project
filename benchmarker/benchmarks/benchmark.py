# benchmarks/benchmark.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from models.model import Model


class Benchmark(ABC):
    name: str

    @abstractmethod
    def generate(self, model: Model, output_file: Path,
                 num_samples: int = 1, max_tasks: Optional[int] = None) -> None:
        """Prompts bereitstellen, das Modell aufrufen und die Antworten in run_dir speichern."""

    @abstractmethod
    def evaluate(self, result_file: Path = "result_filtered.json", output_file: Path = "evaluation_results.json"):
        """Gespeicherte Antworten auswerten und Kennzahlen zurückgeben,
        z. B. {"samples": 3, "build": 2, "run": 2, "correct": 1}."""
        