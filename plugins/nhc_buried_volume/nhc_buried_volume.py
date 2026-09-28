"""Compute NHC ligand buried volumes from XYZ files with Morfeus.

Input convention:
    atom 1 = N
    atom 2 = carbene C
    atom 3 = N

The Morfeus buried-volume center is represented as a dummy metal atom placed
2.0 A from the carbene carbon along the N-C-N angle bisector. By default this
uses the external bisector, i.e. opposite to the internal N-C-N ring direction.
"""
from __future__ import annotations

import argparse
import csv
import glob
import logging
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

# Morfeus imports matplotlib in this environment. Point its caches at /tmp so
# batch runs do not fail or spend time warning about unwritable home caches.
_cache_root = Path(tempfile.gettempdir()) / "nhc_buried_volume_cache"
_cache_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))

from morfeus import BuriedVolume, Sterimol  # noqa: E402

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Xyz:
    elements: list[str]
    coordinates: np.ndarray


def read_xyz(path: str | Path) -> Xyz:
    """Read a plain XYZ file."""
    path = Path(path)
    with path.open() as handle:
        lines = handle.read().splitlines()

    if not lines:
        raise ValueError("empty XYZ file")

    try:
        n_atoms = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("first XYZ line must be the atom count") from exc

    atom_lines = lines[2 : 2 + n_atoms]
    if len(atom_lines) != n_atoms:
        raise ValueError(f"expected {n_atoms} atoms, found {len(atom_lines)}")

    elements: list[str] = []
    coordinates: list[list[float]] = []
    for i, line in enumerate(atom_lines, start=1):
        fields = line.strip().split()
        if len(fields) < 4:
            raise ValueError(f"atom line {i} has fewer than 4 fields")
        elements.append(fields[0])
        try:
            coordinates.append([float(fields[1]), float(fields[2]), float(fields[3])])
        except ValueError as exc:
            raise ValueError(f"atom line {i} has non-numeric coordinates") from exc

    return Xyz(elements=elements, coordinates=np.array(coordinates, dtype=float))


def unit(vector: np.ndarray, label: str) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm < 1e-12:
        raise ValueError(f"cannot normalize near-zero {label} vector")
    return vector / norm


def ncn_bisector(
    coordinates: np.ndarray,
    *,
    bisector: str = "external",
) -> tuple[np.ndarray, np.ndarray]:
    """Return (dummy_center, direction) for atoms N-C-N at positions 0, 1, 2."""
    n1 = coordinates[0]
    carbene = coordinates[1]
    n2 = coordinates[2]

    c_to_n1 = unit(n1 - carbene, "C-to-N1")
    c_to_n2 = unit(n2 - carbene, "C-to-N2")
    internal = unit(c_to_n1 + c_to_n2, "N-C-N bisector")

    if bisector == "internal":
        direction = internal
    elif bisector == "external":
        direction = -internal
    else:
        raise ValueError(f"unknown bisector mode: {bisector}")

    return carbene, direction


def ncn_angle_degrees(coordinates: np.ndarray) -> float:
    n1 = coordinates[0]
    carbene = coordinates[1]
    n2 = coordinates[2]
    c_to_n1 = unit(n1 - carbene, "C-to-N1")
    c_to_n2 = unit(n2 - carbene, "C-to-N2")
    cosine = float(np.clip(np.dot(c_to_n1, c_to_n2), -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def validate_first_three(elements: list[str]) -> None:
    if len(elements) < 3:
        raise ValueError("XYZ must contain at least three atoms")
    expected = ["N", "C", "N"]
    actual = elements[:3]
    if actual != expected:
        raise ValueError(f"first three atoms must be N-C-N, found {'-'.join(actual)}")


def compute_buried_volume(
    xyz_path: str | Path,
    *,
    distance: float = 2.0,
    sphere_radius: float = 3.5,
    bisector: str = "external",
    include_hs: bool = True,
    radii_type: str = "bondi",
    radii_scale: float = 1.17,
    density: float = 0.001,
) -> dict[str, object]:
    """Compute buried volume descriptors for one NHC XYZ file."""
    xyz = read_xyz(xyz_path)
    validate_first_three(xyz.elements)

    carbene, direction = ncn_bisector(xyz.coordinates, bisector=bisector)
    dummy_center = carbene + distance * direction

    elements = ["Pd", *xyz.elements]
    coordinates = np.vstack([dummy_center, xyz.coordinates])

    bv = BuriedVolume(
        elements,
        coordinates,
        1,
        include_hs=include_hs,
        radius=sphere_radius,
        radii_type=radii_type,
        radii_scale=radii_scale,
        density=density,
        z_axis_atoms=[3],    # carbene C (aug 1-indexed: Pd=1, N1=2, C=3, N2=4)
        xz_plane_atoms=[2],  # N1 in xz-plane → ring plane = xz, N1 at +x
    )
    bv.octant_analysis()

    # Sterimol: dummy Pd (1-indexed 1) → carbene C (1-indexed 2)
    st = Sterimol(elements, coordinates, 1, 2, radii_type=radii_type)

    record: dict[str, object] = {
        "filename": Path(xyz_path).name,
        "path": str(xyz_path),
        "n_atoms": len(xyz.elements),
        "ncn_angle_deg": ncn_angle_degrees(xyz.coordinates),
        "bisector": bisector,
        "center_distance_A": distance,
        "sphere_radius_A": sphere_radius,
        "radii_type": radii_type,
        "radii_scale": radii_scale,
        "include_hs": include_hs,
        "center_x": dummy_center[0],
        "center_y": dummy_center[1],
        "center_z": dummy_center[2],
        "direction_x": direction[0],
        "direction_y": direction[1],
        "direction_z": direction[2],
        "fraction_buried_volume": bv.fraction_buried_volume,
        "percent_buried_volume": 100.0 * bv.fraction_buried_volume,
        "buried_volume_A3": bv.buried_volume,
        "free_volume_A3": bv.free_volume,
    }
    for i in range(8):
        record[f"oct_{i}_pVbur"] = bv.octants["percent_buried_volume"][i]
    for i in range(1, 5):
        record[f"quad_{i}_pVbur"] = bv.quadrants["percent_buried_volume"][i]
    record.update({
        "sterimol_L": float(st.L_value),
        "sterimol_L_uncorr": float(st.L_value_uncorrected),
        "sterimol_B1": float(st.B_1_value),
        "sterimol_B5": float(st.B_5_value),
        "sterimol_bond_len": float(st.bond_length),
        "error": "",
    })
    return record


def iter_xyz_inputs(input_path: str | Path, *, include_opt: bool = False) -> list[Path]:
    path = Path(input_path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"input path does not exist: {path}")

    xyzs = sorted(Path(p) for p in glob.glob(str(path / "*.xyz")))
    if not include_opt:
        xyzs = [p for p in xyzs if "opt" not in p.name]
    return xyzs


def write_csv(records: Iterable[dict[str, object]], output: str | Path) -> None:
    records = list(records)
    if not records:
        raise ValueError("no records to write")

    fieldnames = list(records[0].keys())
    with Path(output).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compute NHC buried volumes with a 3.5 A Morfeus sphere centered "
            "2.0 A from the carbene along the N-C-N bisector."
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input XYZ file or directory containing XYZ files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output CSV path. Default: <input>/nhc_buried_volume.csv for directories.",
    )
    parser.add_argument(
        "--distance",
        type=float,
        default=2.0,
        help="Dummy center distance from carbene carbon in A (default: 2.0).",
    )
    parser.add_argument(
        "--sphere-radius",
        type=float,
        default=3.5,
        help="Buried-volume sphere radius in A (default: 3.5).",
    )
    parser.add_argument(
        "--bisector",
        choices=["external", "internal"],
        default="external",
        help=(
            "Use the external or internal N-C-N angle bisector. External is "
            "opposite the N-C-N ring direction and is the default."
        ),
    )
    parser.add_argument(
        "--radii-type",
        default="bondi",
        help="Morfeus radii type (default: bondi).",
    )
    parser.add_argument(
        "--radii-scale",
        type=float,
        default=1.17,
        help="Scale factor for vdW radii (default: 1.17).",
    )
    parser.add_argument(
        "--density",
        type=float,
        default=0.001,
        help="Morfeus point density in A^3 per point (default: 0.001).",
    )
    parser.add_argument(
        "--exclude-hs",
        action="store_true",
        help="Exclude hydrogen atoms from the buried-volume calculation.",
    )
    parser.add_argument(
        "--include-opt",
        action="store_true",
        help="Include XYZ files with 'opt' in the filename.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first file that cannot be processed.",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args()

    xyz_paths = iter_xyz_inputs(args.input, include_opt=args.include_opt)
    if not xyz_paths:
        raise SystemExit(f"No XYZ files found in {args.input}")

    records: list[dict[str, object]] = []
    for xyz_path in xyz_paths:
        try:
            record = compute_buried_volume(
                xyz_path,
                distance=args.distance,
                sphere_radius=args.sphere_radius,
                bisector=args.bisector,
                include_hs=not args.exclude_hs,
                radii_type=args.radii_type,
                radii_scale=args.radii_scale,
                density=args.density,
            )
        except Exception as exc:
            if args.fail_fast:
                raise
            LOGGER.warning("Failed %s: %s", xyz_path, exc)
            record = {
                "filename": xyz_path.name,
                "path": str(xyz_path),
                "n_atoms": "",
                "ncn_angle_deg": "",
                "bisector": args.bisector,
                "center_distance_A": args.distance,
                "sphere_radius_A": args.sphere_radius,
                "radii_type": args.radii_type,
                "radii_scale": args.radii_scale,
                "include_hs": not args.exclude_hs,
                "center_x": "",
                "center_y": "",
                "center_z": "",
                "direction_x": "",
                "direction_y": "",
                "direction_z": "",
                "fraction_buried_volume": "",
                "percent_buried_volume": "",
                "buried_volume_A3": "",
                "free_volume_A3": "",
                **{f"oct_{i}_pVbur": "" for i in range(8)},
                **{f"quad_{i}_pVbur": "" for i in range(1, 5)},
                "sterimol_L": "",
                "sterimol_L_uncorr": "",
                "sterimol_B1": "",
                "sterimol_B5": "",
                "sterimol_bond_len": "",
                "error": str(exc),
            }
        records.append(record)

    input_path = Path(args.input)
    output = args.output
    if output is None and input_path.is_dir():
        output = input_path / "nhc_buried_volume.csv"

    if output is None:
        record = records[0]
        if record["error"]:
            raise SystemExit(record["error"])
        print(
            f"{record['filename']}: "
            f"V_bur={record['percent_buried_volume']:.2f}% "
            f"({record['buried_volume_A3']:.3f} A^3)"
        )
    else:
        write_csv(records, output)
        n_ok = sum(1 for record in records if not record["error"])
        LOGGER.info("Wrote %d records (%d successful) to %s", len(records), n_ok, output)


if __name__ == "__main__":
    main()
