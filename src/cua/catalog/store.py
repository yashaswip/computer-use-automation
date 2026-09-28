from __future__ import annotations

import json
from pathlib import Path

from cua.models.artifact import CapabilityArtifact


class Catalog:
    def __init__(self, root: str | Path = "capabilities"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, slug: str) -> Path:
        return self.root / f"{slug}.json"

    def save(self, artifact: CapabilityArtifact) -> Path:
        path = self.path_for(artifact.slug)
        path.write_text(artifact.model_dump_json(indent=2))
        return path

    def save_draft(self, artifact: CapabilityArtifact) -> Path:
        """Keep a reviewed catalog entry intact. Discovery writes a sibling draft."""
        approved = self.path_for(artifact.slug)
        path = self.root / f"{artifact.slug}.draft.json" if approved.exists() else approved
        path.write_text(artifact.model_dump_json(indent=2))
        return path

    def load(self, slug_or_path: str) -> CapabilityArtifact:
        p = Path(slug_or_path)
        if not p.exists():
            p = self.path_for(slug_or_path)
        return CapabilityArtifact.model_validate_json(p.read_text())

    def list(self) -> list[dict]:
        items = []
        for f in sorted(self.root.glob("*.json")):
            data = json.loads(f.read_text())
            items.append(
                {
                    "slug": data.get("slug"),
                    "title": data.get("title"),
                    "parameters": [p["name"] for p in data.get("parameters", [])],
                    "outputs": [o["name"] for o in data.get("outputs", [])],
                    "path": str(f),
                }
            )
        return items
