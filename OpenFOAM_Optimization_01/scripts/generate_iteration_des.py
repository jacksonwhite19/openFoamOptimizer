#!/usr/bin/env python3
"""
Generate an iteration-specific .des file from baseline.des without modifying baseline.

Inputs:
- Baseline DES file (read-only source)
- Optimization problem definition (for variable bounds and DES bindings)
- Design variable values (JSON file and/or --set key=value)

Output:
- New DES file with updated bound parameters
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    base_des: Path
    output_des: Path
    problem_file: Path
    design_json: Path | None
    overrides: list[str]


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Create a new DES file for an optimizer iteration.")
    parser.add_argument(
        "--base-des",
        type=Path,
        default=Path("geometry/source/baseline.des"),
        help="Source baseline DES file (never modified).",
    )
    parser.add_argument(
        "--output-des",
        type=Path,
        required=True,
        help="Output DES file path for this iteration.",
    )
    parser.add_argument(
        "--problem-file",
        type=Path,
        default=Path("optimization_problem_definition.json"),
        help="Optimization problem definition JSON.",
    )
    parser.add_argument(
        "--design-json",
        type=Path,
        default=None,
        help="JSON file with variable values, e.g. {\"wing_sweep_deg\": 28.0}.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Inline override in key=value form. Can be repeated.",
    )
    args = parser.parse_args()
    return Config(
        base_des=args.base_des,
        output_des=args.output_des,
        problem_file=args.problem_file,
        design_json=args.design_json,
        overrides=args.set,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def parse_override_pairs(pairs: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid --set '{pair}', expected key=value")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --set '{pair}', empty key")
        result[key] = float(raw.strip())
    return result


def collect_design_values(cfg: Config) -> dict[str, float]:
    values: dict[str, float] = {}
    if cfg.design_json is not None:
        payload = read_json(cfg.design_json)
        for k, v in payload.items():
            values[k] = float(v)
    values.update(parse_override_pairs(cfg.overrides))
    return values


def parse_des_lines(base_des: Path) -> tuple[str, list[str], dict[str, tuple[int, str, float]]]:
    if not base_des.exists():
        raise FileNotFoundError(f"Missing base DES file: {base_des}")
    raw_lines = base_des.read_text().splitlines()
    if not raw_lines:
        raise RuntimeError(f"DES file is empty: {base_des}")

    header = raw_lines[0]
    body = raw_lines[1:]
    parsed: dict[str, tuple[int, str, float]] = {}

    for idx, line in enumerate(body):
        s = line.strip()
        if not s:
            continue
        if ":" not in s:
            continue
        # Format: <ID>:<Geom>:<Group>:<Parm>: <value>
        left, right = s.rsplit(":", 1)
        param_id = left.split(":", 1)[0].strip()
        value = float(right.strip())
        parsed[param_id] = (idx, left, value)
    return header, body, parsed


def validate_design_bounds(problem: dict[str, Any], design_values: dict[str, float]) -> None:
    var_map = {v["name"]: v for v in problem.get("design_variables", [])}
    for name, val in design_values.items():
        if name not in var_map:
            raise KeyError(f"Unknown design variable: {name}")
        lo = float(var_map[name]["min"])
        hi = float(var_map[name]["max"])
        if not (lo <= val <= hi):
            raise ValueError(
                f"Variable '{name}'={val} outside bounds [{lo}, {hi}]"
            )


def build_des_updates(problem: dict[str, Any], design_values: dict[str, float]) -> dict[str, float]:
    var_map = {v["name"]: v for v in problem.get("design_variables", [])}
    updates: dict[str, float] = {}

    for name, meta in var_map.items():
        binding = meta.get("des_binding")
        if not binding:
            continue

        mode = binding.get("mode", "direct")
        scale = float(binding.get("unit_scale", 1.0))
        param_ids = binding.get("param_ids", [])

        if mode == "direct":
            if name not in design_values:
                continue
            des_value = float(design_values[name]) * scale
        elif mode == "derived_tip_from_root_and_taper":
            if name not in design_values:
                continue
            deps = binding.get("depends_on", [])
            if len(deps) != 1:
                raise ValueError(f"Binding for '{name}' must define one depends_on variable")
            dep_name = deps[0]
            if dep_name not in design_values:
                raise KeyError(
                    f"Binding for '{name}' requires '{dep_name}' in provided design values"
                )
            taper = float(design_values[dep_name])
            des_value = (float(design_values[name]) * taper) * scale
        elif mode == "copy_from":
            deps = binding.get("depends_on", [])
            if len(deps) != 1:
                raise ValueError(f"Binding for '{name}' must define one depends_on variable")
            dep_name = deps[0]
            if dep_name not in design_values:
                raise KeyError(
                    f"Binding for '{name}' requires '{dep_name}' in provided design values"
                )
            des_value = float(design_values[dep_name]) * scale
        else:
            raise ValueError(f"Unsupported des_binding mode '{mode}' for variable '{name}'")

        for pid in param_ids:
            updates[pid] = des_value

    return updates


def write_output_des(
    output_des: Path,
    header: str,
    body_lines: list[str],
    parsed: dict[str, tuple[int, str, float]],
    updates: dict[str, float],
) -> None:
    new_body = list(body_lines)
    for pid, new_value in updates.items():
        if pid not in parsed:
            raise KeyError(f"DES parameter ID '{pid}' not found in source DES file")
        idx, left, _old = parsed[pid]
        new_body[idx] = f"{left}: {new_value:.6f}"

    output_des.parent.mkdir(parents=True, exist_ok=True)
    out_text = "\n".join([header, *new_body]) + "\n"
    output_des.write_text(out_text)


def main() -> None:
    cfg = parse_args()
    problem = read_json(cfg.problem_file)
    design_values = collect_design_values(cfg)
    if not design_values:
        raise ValueError("No design variable values provided. Use --design-json and/or --set.")

    validate_design_bounds(problem, design_values)
    header, body, parsed = parse_des_lines(cfg.base_des)
    updates = build_des_updates(problem, design_values)
    if not updates:
        raise RuntimeError("No mapped DES updates generated from provided design values.")

    write_output_des(cfg.output_des, header, body, parsed, updates)

    print(f"Wrote iteration DES: {cfg.output_des}")
    print(f"Source baseline DES preserved: {cfg.base_des}")
    print("Updated parameter IDs:")
    for pid in sorted(updates.keys()):
        print(f"  {pid} = {updates[pid]:.6f}")


if __name__ == "__main__":
    main()
