from benchmarks.par_eval import ParEval
from models.qwen import QwenModel

def main():
    benchmark = ParEval()
    # qwen = QwenModel()
    # benchmark.generate(model=qwen, output_file="run/result.json")
    benchmark.evaluate(result_file = "run/result.json", output_file = "run/evaluation_results.json")

if __name__ == "__main__":
    main()
