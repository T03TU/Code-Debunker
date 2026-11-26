#!/usr/bin/env python3
"""CLI utility to slice source code into a 1-hop JSON IR."""
import argparse
import json
import os
import sys

# Ensure backend is in python path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.parser.ir_builder import build_program_ir
from app.parser.graph_slicer import GraphSlicer


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic AST & JSON IR Slicing CLI")
    parser.add_argument("--file", required=True, help="Path to target source file")
    parser.add_argument("--symbol", default=None, help="Target callable symbol ID")
    parser.add_argument("--hops", type=int, default=1, help="Number of dependency hops (default: 1)")

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8") as f:
        code = f.read()

    ir = build_program_ir(source_code=code, file_path=args.file)
    slicer = GraphSlicer(ir)

    ir_slice = slicer.extract_1hop_slice(target_symbol_id=args.symbol)
    print(ir_slice.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
