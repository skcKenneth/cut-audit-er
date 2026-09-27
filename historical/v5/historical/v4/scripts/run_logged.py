"""Run a bounded local command, preserving its output, timing, and exit status."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command required")
    args.out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path("src").resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    # Apply before child interpreter startup, including its spawned workers.
    env["PYTHONHASHSEED"] = "0"
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        env[name] = "1"
    metadata = {"command": command, "cwd": str(Path.cwd()),
                "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "timeout_seconds": args.timeout, "cpu_threads": 1,
                "python_hash_seed": env["PYTHONHASHSEED"],
                "python_hash_seed_scope": "child environment set before interpreter startup"}
    start = time.perf_counter()
    with (args.out / "stdout.txt").open("w", encoding="utf-8") as stdout, \
            (args.out / "stderr.txt").open("w", encoding="utf-8") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env)
        try:
            code = child.wait(timeout=args.timeout)
            metadata["timed_out"] = False
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            code = 124
            metadata["timed_out"] = True
    metadata.update(exit_code=code, elapsed_seconds=time.perf_counter()-start)
    metadata["output_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (args.out / "stdout.txt", args.out / "stderr.txt")}
    (args.out / "command.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(metadata))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
