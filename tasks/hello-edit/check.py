"""Pass if hello.txt in the sandbox snapshot has exactly the expected content."""
import sys
from pathlib import Path

text = (Path(sys.argv[1]) / "hello.txt").read_text()
expected = "Hello from the sandbox.\nstatus: done\n"
print(f"hello.txt = {text!r}")
sys.exit(0 if text == expected else 1)
