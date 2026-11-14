"""Checks for the training YAML builder (training_config.py). Needs no MolCraftDiffusion install.

    python test_training_config.py

Each assertion below pins a bug that made `MolCraftDiff train` fail at start-up with the YAML this
builder produced (found by running every family for one epoch against MolCraftDiffusion 1.13.0).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    import training_config as tc

    def build(**overrides) -> dict:
        payload = {
            "task_family": "diffusion",
            "name": "t",
            "dataset_name": "d",
            "data_root": "/tmp/d",
            "csv_path": "/tmp/d/m.csv",
            "xyz_dir": "/tmp/d/xyz",
            "diffusion_steps": 50,
            "num_epochs": 1,
            "output_path": "/tmp/out",
            "max_atom": 30,
        }
        payload.update(overrides)
        tc.validate_payload(payload)
        return yaml.safe_load(tc.build_yaml_text(payload, "/tmp/out"))

    # --- registry sanity -------------------------------------------------------------------
    assert tc.PUBLIC_TASK_FAMILIES <= set(tc.TASK_FAMILIES), "PUBLIC_TASK_FAMILIES names unknown families"
    for name, meta in tc.TASK_FAMILIES.items():
        for key in ("label", "tasks_config", "trainer_config", "category"):
            assert key in meta, f"{name} lacks {key!r}"

    # --- TABASCO: the shipped configs leave these three as `???` and `train` does not fill them
    for family, backbone in [("diffusion_tabasco", "transformer_config"), ("diffusion_tabasco_egnn", "egnn_config")]:
        tasks = build(task_family=family)["tasks"]
        assert tasks["num_atom_types"] == 15, (family, tasks.get("num_atom_types"))  # default vocabulary
        assert tasks[backbone]["atom_dim"] == 15, (family, tasks.get(backbone))
        assert tasks["dataset_stats"]["max_atoms"] == 30, (family, tasks.get("dataset_stats"))
        # allow_unknown appends one extra "unknown" type to the vocabulary at training time
        tasks = build(task_family=family, atom_vocab="H C N O", allow_unknown=True)["tasks"]
        assert tasks["num_atom_types"] == 5 and tasks[backbone]["atom_dim"] == 5, family
    assert "num_atom_types" not in build(task_family="diffusion")["tasks"], "only TABASCO families carry it"

    # --- scheduler: regression's trainer group ships ReduceLROnPlateau kwargs ------------------
    trainer = build(task_family="regression", task_learn=["prop"], condition_names="prop")["trainer"]
    assert "scheduler" not in trainer and "scheduler_kwargs" not in trainer, (
        "default cosine would merge onto the plateau kwargs and crash CosineAnnealingLR(mode=...)"
    )
    trainer = build(task_family="regression", task_learn=["prop"], scheduler="reducelronplateau")["trainer"]
    assert trainer["scheduler"] == "reducelronplateau" and "scheduler_kwargs" not in trainer
    trainer = build(task_family="regression", task_learn=["prop"], scheduler="cosineannealing",
                    scheduler_kwargs={"T_max": 7, "eta_min": 0.0})["trainer"]
    assert trainer["scheduler"] == "cosineannealing" and trainer["scheduler_kwargs"]["T_max"] == 7
    trainer = build(task_family="diffusion", num_epochs=9)["trainer"]
    assert trainer["scheduler"] == "cosineannealing" and trainer["scheduler_kwargs"]["T_max"] == 9

    # --- guidance keeps its targets (guidance.yaml hard-codes task_learn: [S1_exc, T1_exc]) -----
    assert build(task_family="guidance", task_learn="a, b")["tasks"]["task_learn"] == ["a", "b"]
    assert build(task_family="guidance", task_learn=["a"])["tasks"]["task_learn"] == ["a"]
    assert "task_learn" not in build(task_family="guidance")["tasks"]

    # --- families whose tasks read batch["graph"] need a pyg batch -------------------------------
    for family in ("ssl3d_egcl", "ssl3d_equiformer", "guidance", "guidance_esen"):
        assert build(task_family=family)["data"]["data_type"] == "pyg", family
    assert build(task_family="regression", task_learn=["prop"])["data"]["data_type"] == "pyg"
    for family in ("diffusion", "diffusion_tabasco", "diffusion_transformer", "vae_equiformer"):
        assert build(task_family=family, latent_dim=8)["data"]["data_type"] == "pointcloud", family

    print(f"OK: training YAML builder ({len(tc.TASK_FAMILIES)} families)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
