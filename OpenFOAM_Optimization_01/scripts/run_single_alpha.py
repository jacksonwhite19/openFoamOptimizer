#!/usr/bin/env python3
"""
Single-angle pipeline runner (incremental build).

Phase 1:
- Parse CLI arguments
- Print resolved run configuration

Phase 2:
- Create a fresh case from template
- Ensure triSurface directory exists
- Copy baseline_m STL into case
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunConfig:
    alpha_deg: float
    uinf: float
    case_name: str
    template_dir: Path
    cases_root: Path
    outputs_dir: Path
    stl_name: str
    run_vsp_export: bool
    vsp_exe: str
    vsp3_file: Path
    des_file: Path
    export_geom_script: Path
    export_frontal_script: Path
    wsl_windows_drive: str
    convert_stl_units: bool
    raw_stl_name: str
    inject_refs: bool
    max_skewness: float
    max_non_orthogonality: float
    require_mesh_ok: bool
    allow_mesh_warnings: bool
    end_time: int | None
    averaging_window: int
    results_filename: str
    skip_solver: bool
    skip_mesh: bool
    mesh_source_case: Path | None
    no_mesh: bool
    dry_run: bool

    @property
    def case_dir(self) -> Path:
        return self.cases_root / self.case_name

    @property
    def source_stl(self) -> Path:
        return self.outputs_dir / self.stl_name

    @property
    def case_stl(self) -> Path:
        return self.case_dir / "constant" / "triSurface" / self.stl_name


def log_step(message: str) -> None:
    print(f"[run_single_alpha] {message}")


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Run single-angle OpenFOAM workflow (incremental implementation)."
    )
    parser.add_argument("--alpha", type=float, required=True, help="Angle of attack in degrees.")
    parser.add_argument("--uinf", type=float, default=25.0, help="Freestream velocity magnitude [m/s].")
    parser.add_argument(
        "--case-name",
        type=str,
        default="alpha_8_auto",
        help="Case directory name under cases/test_runs.",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path("templates/drone_template"),
        help="Template case directory.",
    )
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=Path("cases/test_runs"),
        help="Root directory for generated test run cases.",
    )
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=Path("geometry/outputs"),
        help="Directory containing geometry export outputs.",
    )
    parser.add_argument(
        "--stl-name",
        type=str,
        default="baseline_m.stl",
        help="STL filename expected in outputs and copied into case.",
    )
    parser.add_argument(
        "--skip-vsp-export",
        action="store_true",
        help="Skip VSP export stage (debug only). Default is to run exports each invocation.",
    )
    parser.add_argument(
        "--vsp-exe",
        type=str,
        default=r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe",
        help="VSP executable path/name.",
    )
    parser.add_argument(
        "--vsp3-file",
        type=Path,
        default=Path("geometry/source/baseline.vsp3"),
        help="Path to .vsp3 geometry file.",
    )
    parser.add_argument(
        "--des-file",
        type=Path,
        default=Path("geometry/source/baseline.des"),
        help="Path to .des file.",
    )
    parser.add_argument(
        "--export-geom-script",
        type=Path,
        default=Path("scripts/vsp_utils/export_geom.vspscript"),
        help="VSP script for geometry/mass export.",
    )
    parser.add_argument(
        "--export-frontal-script",
        type=Path,
        default=Path("scripts/vsp_utils/export_frontal_area.vspscript"),
        help="VSP script for frontal area export.",
    )
    parser.add_argument(
        "--wsl-windows-drive",
        type=str,
        default="Z:",
        help="Windows drive mapping used for WSL paths (e.g. Z: for Z:\\home\\...).",
    )
    parser.add_argument(
        "--skip-convert-stl-units",
        action="store_true",
        help="Skip STL unit conversion stage (debug only). Default converts mm->m each invocation.",
    )
    parser.add_argument(
        "--raw-stl-name",
        type=str,
        default="baseline.stl",
        help="Raw STL filename in outputs_dir (typically mm units).",
    )
    parser.add_argument(
        "--skip-inject-refs",
        action="store_true",
        help="Skip VSP ref parsing/injection stage (debug only). Default injects each invocation.",
    )
    parser.add_argument(
        "--max-skewness",
        type=float,
        default=8.0,
        help="Maximum allowed mesh skewness from checkMesh.",
    )
    parser.add_argument(
        "--max-non-orthogonality",
        type=float,
        default=70.0,
        help="Maximum allowed mesh non-orthogonality from checkMesh.",
    )
    parser.add_argument(
        "--require-mesh-ok",
        action="store_true",
        help="Require literal 'Mesh OK.' in checkMesh output in addition to numeric thresholds.",
    )
    parser.add_argument(
        "--allow-mesh-warnings",
        action="store_true",
        help="Continue to solver even if checkMesh gate fails. Intended for debugging only.",
    )
    parser.add_argument(
        "--end-time",
        type=int,
        default=None,
        help="Optional override for system/controlDict endTime.",
    )
    parser.add_argument(
        "--averaging-window",
        type=int,
        default=50,
        help="Number of trailing force-coefficient rows for mean/std (default: 50).",
    )
    parser.add_argument(
        "--results-filename",
        type=str,
        default="results.json",
        help="Output JSON filename written inside case directory.",
    )
    parser.add_argument(
        "--skip-solver",
        action="store_true",
        help="Run setup + meshing only; skip simpleFoam.",
    )
    parser.add_argument(
        "--skip-mesh",
        action="store_true",
        help="Skip meshing and run solver using mesh copied from --mesh-source-case.",
    )
    parser.add_argument(
        "--mesh-source-case",
        type=Path,
        default=None,
        help="Case directory to copy constant/polyMesh from when using --skip-mesh.",
    )
    parser.add_argument(
        "--no-mesh",
        action="store_true",
        help="Skip all meshing/solver steps (export + setup stages only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without mutating files.",
    )
    args = parser.parse_args()

    return RunConfig(
        alpha_deg=args.alpha,
        uinf=args.uinf,
        case_name=args.case_name,
        template_dir=args.template_dir,
        cases_root=args.cases_root,
        outputs_dir=args.outputs_dir,
        stl_name=args.stl_name,
        run_vsp_export=(not args.skip_vsp_export),
        vsp_exe=args.vsp_exe,
        vsp3_file=args.vsp3_file,
        des_file=args.des_file,
        export_geom_script=args.export_geom_script,
        export_frontal_script=args.export_frontal_script,
        wsl_windows_drive=args.wsl_windows_drive,
        convert_stl_units=(not args.skip_convert_stl_units),
        raw_stl_name=args.raw_stl_name,
        inject_refs=(not args.skip_inject_refs),
        max_skewness=args.max_skewness,
        max_non_orthogonality=args.max_non_orthogonality,
        require_mesh_ok=args.require_mesh_ok,
        allow_mesh_warnings=args.allow_mesh_warnings,
        end_time=args.end_time,
        averaging_window=args.averaging_window,
        results_filename=args.results_filename,
        skip_solver=args.skip_solver,
        skip_mesh=args.skip_mesh,
        mesh_source_case=args.mesh_source_case,
        no_mesh=args.no_mesh,
        dry_run=args.dry_run,
    )


def validate_phase_2_inputs(cfg: RunConfig) -> None:
    missing = []
    if not cfg.template_dir.exists():
        missing.append(f"template_dir missing: {cfg.template_dir}")
    if not cfg.source_stl.exists():
        missing.append(f"source STL missing: {cfg.source_stl}")
    if missing:
        raise FileNotFoundError(" | ".join(missing))


def run_external_command(
    cfg: RunConfig,
    cmd: list[str],
    log_path: Path,
    cwd: Path | None = None,
    allow_nonzero: bool = False,
) -> int:
    cmd_str = " ".join(cmd)
    if cfg.dry_run:
        log_step(f"[dry-run] would run: {cmd_str} (log: {log_path}, cwd={cwd or Path.cwd()})")
        return 0

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_step(f"Running: {cmd_str}")
    with log_path.open("w") as log_file:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if proc.returncode != 0:
        if allow_nonzero:
            log_step(
                f"WARNING: command returned {proc.returncode} but continuing: {cmd_str}"
            )
            return proc.returncode
        raise RuntimeError(f"Command failed ({proc.returncode}): {cmd_str}. See {log_path}")
    return proc.returncode


def to_windows_path(path: Path, wsl_windows_drive: str = "Z:") -> str:
    raw = str(path)

    # Already a Windows path (e.g., Z:\foo or Z:/foo) -> keep as-is.
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return raw

    # Normalize relative paths against current working directory first.
    p = Path(raw)
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
        raw = str(p)

    # Fallback for non-WSL execution contexts.
    if raw.startswith("/mnt/") and len(raw) > 6:
        drive = raw[5].upper()
        rest = raw[6:].replace("/", "\\")
        return f"{drive}:{rest}"
    if raw.startswith("/home/"):
        rest = raw[1:].replace("/", "\\")
        return f"{wsl_windows_drive}\\{rest}"
    # Handle UNC form emitted in some Windows-hosted Python executions.
    unc_marker = "\\\\wsl.localhost\\Ubuntu-22.04\\home\\"
    if raw.startswith(unc_marker):
        rest = raw[len("\\\\wsl.localhost\\Ubuntu-22.04\\"):].replace("/", "\\")
        return f"{wsl_windows_drive}\\{rest}"
    wslpath = shutil.which("wslpath")
    if wslpath:
        proc = subprocess.run(
            [wslpath, "-w", raw],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
        raise RuntimeError(f"Failed to convert path to Windows format: {path}\n{proc.stderr}")
    return raw


def run_vsp_export_and_prepare_geometry(cfg: RunConfig) -> None:
    if not cfg.run_vsp_export:
        return

    log_step("Phase 1.5: running VSP exports and geometry preparation")
    root = Path(".")
    vsp_exe_path = Path(cfg.vsp_exe)
    if not vsp_exe_path.exists():
        wslpath = shutil.which("wslpath")
        if wslpath:
            proc = subprocess.run(
                [wslpath, "-u", cfg.vsp_exe],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                vsp_exe_path = Path(proc.stdout.strip())
    if not vsp_exe_path.exists():
        raise FileNotFoundError(f"Could not resolve vsp.exe path: {cfg.vsp_exe}")
    vsp_cwd = vsp_exe_path.parent
    vsp3_win = to_windows_path(cfg.vsp3_file, cfg.wsl_windows_drive)
    des_win = to_windows_path(cfg.des_file, cfg.wsl_windows_drive)
    geom_script_win = to_windows_path(cfg.export_geom_script, cfg.wsl_windows_drive)
    frontal_script_win = to_windows_path(cfg.export_frontal_script, cfg.wsl_windows_drive)
    geom_rc = run_external_command(
        cfg,
        [
            str(vsp_exe_path),
            "-batch",
            vsp3_win,
            "-des",
            des_win,
            "-script",
            geom_script_win,
        ],
        cfg.outputs_dir / "log.vsp_export_geom.auto",
        cwd=vsp_cwd,
        allow_nonzero=True,
    )
    frontal_rc = run_external_command(
        cfg,
        [
            str(vsp_exe_path),
            "-batch",
            vsp3_win,
            "-des",
            des_win,
            "-script",
            frontal_script_win,
        ],
        cfg.outputs_dir / "log.vsp_export_frontal.auto",
        cwd=vsp_cwd,
        allow_nonzero=True,
    )

    if not cfg.dry_run:
        raw_stl = cfg.outputs_dir / cfg.raw_stl_name
        if not raw_stl.exists():
            raise FileNotFoundError(
                f"Expected raw STL missing after VSP export: {raw_stl}"
            )
        massprops = cfg.outputs_dir / "baseline_massprops.csv"
        frontal = cfg.outputs_dir / "baseline_frontal_area.csv"
        if not massprops.exists():
            raise FileNotFoundError(
                f"Expected massprops CSV missing after VSP export: {massprops}"
            )
        if not frontal.exists():
            raise FileNotFoundError(
                f"Expected frontal area CSV missing after VSP export: {frontal}"
            )
        if geom_rc != 0:
            log_step(
                f"WARNING: geometry export returned code {geom_rc}, "
                "but expected STL/massprops files were present."
            )
        if frontal_rc != 0:
            log_step(
                f"WARNING: frontal export returned code {frontal_rc}, "
                "but expected frontal-area file was present."
            )
    run_external_command(
        cfg,
        ["python3", "scripts/compute_openfoam_refs.py"],
        cfg.outputs_dir / "log.compute_openfoam_refs.auto",
        cwd=root,
    )

    if cfg.convert_stl_units:
        raw_stl = cfg.outputs_dir / cfg.raw_stl_name
        converted_stl = cfg.outputs_dir / cfg.stl_name
        run_external_command(
            cfg,
            [
                "surfaceTransformPoints",
                "scale=(0.001 0.001 0.001)",
                str(raw_stl),
                str(converted_stl),
            ],
            cfg.outputs_dir / "log.surfaceTransformPoints.auto",
            cwd=root,
        )


def setup_case_from_template(cfg: RunConfig) -> None:
    log_step("Phase 2: creating case from template and copying STL")
    validate_phase_2_inputs(cfg)

    if cfg.dry_run:
        log_step(f"[dry-run] would remove existing case dir if present: {cfg.case_dir}")
        log_step(f"[dry-run] would copy template: {cfg.template_dir} -> {cfg.case_dir}")
        log_step(f"[dry-run] would ensure directory exists: {cfg.case_stl.parent}")
        log_step(f"[dry-run] would copy STL: {cfg.source_stl} -> {cfg.case_stl}")
        return

    if cfg.case_dir.exists():
        shutil.rmtree(cfg.case_dir)
        log_step(f"Removed existing case directory: {cfg.case_dir}")

    cfg.cases_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cfg.template_dir, cfg.case_dir)
    log_step(f"Copied template to case: {cfg.case_dir}")

    # Remove Windows metadata/shortcut artifacts that can crash OpenFOAM utilities.
    removed = 0
    for path in cfg.case_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name.lower().endswith(".lnk") or name.endswith(":Zone.Identifier"):
            path.unlink()
            removed += 1
    if removed:
        log_step(f"Removed {removed} Windows artifact file(s) from case directory")

    cfg.case_stl.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cfg.source_stl, cfg.case_stl)
    log_step(f"Copied STL into case: {cfg.case_stl}")


def _replace_or_fail(content: str, pattern: str, replacement: str, label: str) -> str:
    updated, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    if n == 0:
        raise ValueError(f"Could not find pattern for {label}")
    return updated


def apply_alpha_to_case(cfg: RunConfig) -> None:
    """Phase 3: apply angle-dependent velocity and force directions."""
    log_step("Phase 3: applying AoA settings to initialConditions and forceCoeffs")

    angle_rad = math.radians(cfg.alpha_deg)
    ux = cfg.uinf * math.cos(angle_rad)
    uz = cfg.uinf * math.sin(angle_rad)
    drag_x = math.cos(angle_rad)
    drag_z = math.sin(angle_rad)
    lift_x = -math.sin(angle_rad)
    lift_z = math.cos(angle_rad)

    init_file = cfg.case_dir / "0" / "include" / "initialConditions"
    force_file = cfg.case_dir / "system" / "forceCoeffs"

    if cfg.dry_run:
        log_step(
            f"[dry-run] would set flowVelocity=({ux:.6f} 0 {uz:.6f}) in {init_file}"
        )
        log_step(
            f"[dry-run] would set dragDir=({drag_x:.6f} 0 {drag_z:.6f}) and "
            f"liftDir=({lift_x:.6f} 0 {lift_z:.6f}) in {force_file}"
        )
        return

    if not init_file.exists():
        raise FileNotFoundError(f"Missing initialConditions file: {init_file}")
    if not force_file.exists():
        raise FileNotFoundError(f"Missing forceCoeffs file: {force_file}")

    init_content = init_file.read_text()
    init_content = _replace_or_fail(
        init_content,
        r"flowVelocity\s+\([^)]+\);",
        f"flowVelocity    ({ux:.6f} 0 {uz:.6f});",
        "flowVelocity",
    )
    init_file.write_text(init_content)
    log_step(f"Updated flowVelocity in {init_file}")

    force_content = force_file.read_text()
    force_content = _replace_or_fail(
        force_content,
        r"dragDir\s+\([^)]+\);",
        f"dragDir         ({drag_x:.6f} 0 {drag_z:.6f});",
        "dragDir",
    )
    force_content = _replace_or_fail(
        force_content,
        r"liftDir\s+\([^)]+\);",
        f"liftDir         ({lift_x:.6f} 0 {lift_z:.6f});",
        "liftDir",
    )
    force_file.write_text(force_content)
    log_step(f"Updated liftDir/dragDir in {force_file}")


def inject_reference_data(cfg: RunConfig) -> None:
    if not cfg.inject_refs:
        return

    log_step("Phase 2.5: parsing VSP outputs and injecting OpenFOAM refs")
    from parse_vsp_outputs import parse_all_vsp_outputs
    from inject_openfoam_dicts import inject_all_openfoam_dicts

    massprops = cfg.outputs_dir / "baseline_massprops.csv"
    frontal = cfg.outputs_dir / "baseline_frontal_area.csv"
    wing_refs = cfg.outputs_dir / "wing_refs.csv"

    if cfg.dry_run:
        log_step(
            "[dry-run] would parse VSP outputs from "
            f"{massprops}, {frontal}, {wing_refs} and inject into {cfg.case_dir}"
        )
        return

    vsp_data = parse_all_vsp_outputs(massprops, frontal, wing_refs)
    inject_all_openfoam_dicts(cfg.case_dir, vsp_data, stl_name=cfg.stl_name)
    log_step("Injected references into forceCoeffs/snappyHexMeshDict")


def apply_solver_controls(cfg: RunConfig) -> None:
    """Optional controlDict patching for run controls."""
    if cfg.end_time is None:
        return

    control_file = cfg.case_dir / "system" / "controlDict"
    if cfg.dry_run:
        log_step(f"[dry-run] would set endTime={cfg.end_time} in {control_file}")
        return
    if not control_file.exists():
        raise FileNotFoundError(f"Missing controlDict file: {control_file}")

    content = control_file.read_text()
    content = _replace_or_fail(
        content,
        r"endTime\s+[0-9.eE+\-]+;",
        f"endTime         {cfg.end_time};",
        "controlDict endTime",
    )
    control_file.write_text(content)
    log_step(f"Updated endTime={cfg.end_time} in {control_file}")


def run_command(cfg: RunConfig, cmd: list[str], log_path: Path) -> None:
    run_external_command(cfg, cmd, log_path, cwd=cfg.case_dir)


def copy_mesh_from_source_case(cfg: RunConfig) -> None:
    if cfg.mesh_source_case is None:
        raise ValueError("--skip-mesh requires --mesh-source-case")

    src_poly = cfg.mesh_source_case / "constant" / "polyMesh"
    dst_poly = cfg.case_dir / "constant" / "polyMesh"

    if not src_poly.exists():
        raise FileNotFoundError(f"Source mesh missing: {src_poly}")

    if cfg.dry_run:
        log_step(f"[dry-run] would copy mesh: {src_poly} -> {dst_poly}")
        return

    if dst_poly.exists():
        shutil.rmtree(dst_poly)
    shutil.copytree(src_poly, dst_poly)
    log_step(f"Copied mesh from source case: {src_poly} -> {dst_poly}")


def parse_check_mesh_metrics(check_mesh_log: Path) -> dict[str, float | bool | int]:
    text = check_mesh_log.read_text()
    non_ortho_match = re.search(
        r"Mesh non-orthogonality Max:\s*([0-9.eE+\-]+)",
        text,
    )
    skew_match = re.search(
        r"Max skewness\s*=\s*([0-9.eE+\-]+)",
        text,
    )
    mesh_ok = "Mesh OK." in text
    failed_checks_match = re.search(r"Failed\s+([0-9]+)\s+mesh checks\.", text)
    failed_checks = int(failed_checks_match.group(1)) if failed_checks_match else 0

    if non_ortho_match is None or skew_match is None:
        raise RuntimeError(f"Failed to parse checkMesh metrics from {check_mesh_log}")

    return {
        "mesh_ok": mesh_ok,
        "max_non_orthogonality": float(non_ortho_match.group(1)),
        "max_skewness": float(skew_match.group(1)),
        "failed_checks": failed_checks,
    }


def run_mesh_and_solver(cfg: RunConfig) -> dict[str, float | bool | int] | None:
    """Phase 4/5: mesh pipeline + solver execution."""
    log_step("Phase 4: running mesh pipeline")

    run_command(cfg, ["blockMesh"], cfg.case_dir / "log.blockMesh.auto")
    run_command(cfg, ["surfaceFeatures"], cfg.case_dir / "log.surfaceFeatures.auto")
    run_command(cfg, ["snappyHexMesh", "-overwrite"], cfg.case_dir / "log.snappyHexMesh.auto")
    run_command(cfg, ["checkMesh"], cfg.case_dir / "log.checkMesh.auto")

    mesh_metrics: dict[str, float | bool | int] | None = None
    if not cfg.dry_run:
        mesh_metrics = parse_check_mesh_metrics(cfg.case_dir / "log.checkMesh.auto")
        log_step(
            "checkMesh metrics: "
            f"mesh_ok={mesh_metrics['mesh_ok']}, "
            f"max_non_orthogonality={mesh_metrics['max_non_orthogonality']:.6f}, "
            f"max_skewness={mesh_metrics['max_skewness']:.6f}, "
            f"failed_checks={mesh_metrics['failed_checks']}"
        )

        if cfg.require_mesh_ok and not mesh_metrics["mesh_ok"]:
            if cfg.allow_mesh_warnings:
                log_step(
                    "WARNING: checkMesh did not report 'Mesh OK.'; "
                    "continuing due to --allow-mesh-warnings"
                )
            else:
                raise RuntimeError(
                    "Mesh quality gate failed: checkMesh did not report 'Mesh OK.' "
                    "(use --require-mesh-ok only when this is mandatory)."
                )
        if float(mesh_metrics["max_non_orthogonality"]) > cfg.max_non_orthogonality:
            if cfg.allow_mesh_warnings:
                log_step(
                    "WARNING: non-orthogonality gate failed "
                    f"({mesh_metrics['max_non_orthogonality']} > {cfg.max_non_orthogonality}); "
                    "continuing due to --allow-mesh-warnings"
                )
            else:
                raise RuntimeError(
                    f"Mesh gate failed: non-orthogonality {mesh_metrics['max_non_orthogonality']} "
                    f"> limit {cfg.max_non_orthogonality}"
                )
        if float(mesh_metrics["max_skewness"]) > cfg.max_skewness:
            if cfg.allow_mesh_warnings:
                log_step(
                    "WARNING: skewness gate failed "
                    f"({mesh_metrics['max_skewness']} > {cfg.max_skewness}); "
                    "continuing due to --allow-mesh-warnings"
                )
            else:
                raise RuntimeError(
                    f"Mesh gate failed: skewness {mesh_metrics['max_skewness']} "
                    f"> limit {cfg.max_skewness}"
                )

    if cfg.skip_solver:
        log_step("Phase 5 skipped (--skip-solver)")
        return mesh_metrics

    log_step("Phase 5: running solver")
    run_command(cfg, ["simpleFoam"], cfg.case_dir / "log.simpleFoam.auto")
    return mesh_metrics


def find_force_coeffs_file(case_dir: Path) -> Path:
    candidates = sorted(case_dir.glob("postProcessing/forceCoeffs*/0/forceCoeffs.dat"))
    if not candidates:
        raise FileNotFoundError(
            f"No force coefficients file found under {case_dir / 'postProcessing'}"
        )
    return candidates[-1]


def compute_force_stats(force_file: Path, window: int) -> dict[str, float | int]:
    rows: list[tuple[float, float, float, float]] = []
    for line in force_file.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 4:
            continue
        rows.append((float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])))

    if not rows:
        raise RuntimeError(f"No numeric rows found in {force_file}")

    tail = rows[-window:] if len(rows) >= window else rows

    def mean(vals: list[float]) -> float:
        return sum(vals) / len(vals)

    def std(vals: list[float], m: float) -> float:
        return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))

    cm_vals = [r[1] for r in tail]
    cd_vals = [r[2] for r in tail]
    cl_vals = [r[3] for r in tail]
    cm_mean = mean(cm_vals)
    cd_mean = mean(cd_vals)
    cl_mean = mean(cl_vals)

    return {
        "rows": len(tail),
        "start_time": int(tail[0][0]),
        "end_time": int(tail[-1][0]),
        "iterations": int(rows[-1][0]),
        "CM_mean": cm_mean,
        "CM_std": std(cm_vals, cm_mean),
        "CD_mean": cd_mean,
        "CD_std": std(cd_vals, cd_mean),
        "CL_mean": cl_mean,
        "CL_std": std(cl_vals, cl_mean),
        "L_D_mean": cl_mean / cd_mean if cd_mean != 0 else float("nan"),
    }


def classify_convergence(stats: dict[str, float | int]) -> str:
    cl_mean = float(stats["CL_mean"])
    cd_mean = float(stats["CD_mean"])
    cl_std = float(stats["CL_std"])
    cd_std = float(stats["CD_std"])

    cl_rel = abs(cl_std / cl_mean) if cl_mean != 0 else float("inf")
    cd_rel = abs(cd_std / cd_mean) if cd_mean != 0 else float("inf")
    if cl_rel < 0.01 and cd_rel < 0.005:
        return "converged"
    return "quasi_steady"


def write_results_json(cfg: RunConfig, mesh_metrics: dict[str, float | bool] | None) -> None:
    if cfg.dry_run:
        log_step("[dry-run] would parse force coefficients and write results JSON")
        return
    if cfg.skip_solver:
        log_step("Skipping results output because solver was skipped")
        return

    force_file = find_force_coeffs_file(cfg.case_dir)
    stats = compute_force_stats(force_file, cfg.averaging_window)
    status = classify_convergence(stats)

    mesh_warning = False
    if mesh_metrics is not None:
        mesh_warning = (not bool(mesh_metrics["mesh_ok"])) or int(mesh_metrics["failed_checks"]) > 0

    payload = {
        "geometry_id": cfg.stl_name.replace(".stl", ""),
        "alpha_deg": cfg.alpha_deg,
        "convergence_status": status,
        "iterations": stats["iterations"],
        "averaging_window": {
            "rows": stats["rows"],
            "start_time": stats["start_time"],
            "end_time": stats["end_time"],
        },
        "force_coefficients": {
            "CL_mean": round(float(stats["CL_mean"]), 6),
            "CL_std": round(float(stats["CL_std"]), 6),
            "CD_mean": round(float(stats["CD_mean"]), 6),
            "CD_std": round(float(stats["CD_std"]), 6),
            "CM_mean": round(float(stats["CM_mean"]), 6),
            "CM_std": round(float(stats["CM_std"]), 6),
            "L_D_mean": round(float(stats["L_D_mean"]), 6),
        },
        "mesh_quality": {
            "mesh_ok": bool(mesh_metrics["mesh_ok"]) if mesh_metrics is not None else None,
            "mesh_warning": mesh_warning if mesh_metrics is not None else None,
            "failed_checks": int(mesh_metrics["failed_checks"]) if mesh_metrics is not None else None,
            "max_non_orthogonality": (
                round(float(mesh_metrics["max_non_orthogonality"]), 6)
                if mesh_metrics is not None
                else None
            ),
            "max_skewness": (
                round(float(mesh_metrics["max_skewness"]), 6) if mesh_metrics is not None else None
            ),
        },
        "artifacts": {
            "case_dir": str(cfg.case_dir),
            "solver_log": str(cfg.case_dir / "log.simpleFoam.auto"),
            "mesh_log": str(cfg.case_dir / "log.checkMesh.auto"),
            "force_coeffs_file": str(force_file),
        },
        "notes": [
            "Generated by scripts/run_single_alpha.py",
            f"Statistics computed from last {cfg.averaging_window} samples.",
            f"run_vsp_export={cfg.run_vsp_export}",
            f"convert_stl_units={cfg.convert_stl_units}",
            f"inject_refs={cfg.inject_refs}",
        ],
    }

    output = cfg.case_dir / cfg.results_filename
    output.write_text(json.dumps(payload, indent=2))
    log_step(f"Wrote results: {output}")


def print_config(cfg: RunConfig) -> None:
    log_step("Resolved configuration")
    print(f"  alpha_deg    : {cfg.alpha_deg}")
    print(f"  uinf         : {cfg.uinf}")
    print(f"  case_name    : {cfg.case_name}")
    print(f"  template_dir : {cfg.template_dir}")
    print(f"  cases_root   : {cfg.cases_root}")
    print(f"  case_dir     : {cfg.case_dir}")
    print(f"  outputs_dir  : {cfg.outputs_dir}")
    print(f"  source_stl   : {cfg.source_stl}")
    print(f"  case_stl     : {cfg.case_stl}")
    print(f"  run_vsp_export: {cfg.run_vsp_export}")
    print(f"  vsp_exe      : {cfg.vsp_exe}")
    print(f"  vsp3_file    : {cfg.vsp3_file}")
    print(f"  des_file     : {cfg.des_file}")
    print(f"  export_geom  : {cfg.export_geom_script}")
    print(f"  export_front : {cfg.export_frontal_script}")
    print(f"  convert_stl  : {cfg.convert_stl_units}")
    print(f"  raw_stl_name : {cfg.raw_stl_name}")
    print(f"  inject_refs  : {cfg.inject_refs}")
    print(f"  max_skewness : {cfg.max_skewness}")
    print(f"  max_non_ortho: {cfg.max_non_orthogonality}")
    print(f"  require_mesh_ok: {cfg.require_mesh_ok}")
    print(f"  allow_mesh_w : {cfg.allow_mesh_warnings}")
    print(f"  end_time     : {cfg.end_time}")
    print(f"  avg_window   : {cfg.averaging_window}")
    print(f"  results_file : {cfg.results_filename}")
    print(f"  skip_solver  : {cfg.skip_solver}")
    print(f"  skip_mesh    : {cfg.skip_mesh}")
    print(f"  mesh_source  : {cfg.mesh_source_case}")
    print(f"  no_mesh      : {cfg.no_mesh}")
    print(f"  dry_run      : {cfg.dry_run}")


def main() -> None:
    cfg = parse_args()
    print_config(cfg)
    run_vsp_export_and_prepare_geometry(cfg)
    setup_case_from_template(cfg)
    inject_reference_data(cfg)
    apply_alpha_to_case(cfg)
    apply_solver_controls(cfg)
    if cfg.no_mesh:
        log_step("Phase 4+5 skipped (--no-mesh)")
        log_step("Phase 1.5+2+2.5+3 complete")
        return
    if cfg.skip_mesh:
        log_step("Phase 4 skipped (--skip-mesh)")
        copy_mesh_from_source_case(cfg)
        if cfg.skip_solver:
            log_step("Phase 5 skipped (--skip-solver)")
            return
        log_step("Phase 5: running solver")
        run_command(cfg, ["simpleFoam"], cfg.case_dir / "log.simpleFoam.auto")
        write_results_json(cfg, mesh_metrics=None)
        log_step("Phase 1.5+2+2.5+3+5 complete (mesh reused)")
        return
    mesh_metrics = run_mesh_and_solver(cfg)
    write_results_json(cfg, mesh_metrics)
    log_step("Phase 1+2+3+4+5+6 complete")


if __name__ == "__main__":
    main()
