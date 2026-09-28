from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich import print

from cua.agent.loop import DiscoveryRunner
from cua.catalog.store import Catalog
from cua.config import Settings
from cua.replay.executor import ReplayExecutor

app = typer.Typer(help="Computer-use automation: discover once, replay many.")
catalog_app = typer.Typer()
app.add_typer(catalog_app, name="catalog")


@app.command("serve-target")
def serve_target(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the Fieldbook demo console (legacy-style stand-in)."""
    uvicorn.run("target_app.app:app", host=host, port=port, reload=False)


@app.command("serve-operator")
def serve_operator(host: str = "127.0.0.1", port: int = 8766) -> None:
    """Minimal operator console for live-session handoff."""
    uvicorn.run("cua.hitl.operator_app:app", host=host, port=port, reload=False)


@app.command()
def discover(
    goal: str = typer.Option(..., help="Natural-language goal"),
    url: Optional[str] = typer.Option(None, help="Entry URL"),
    save: bool = typer.Option(True, help="Write artifact to capabilities/"),
) -> None:
    """LLM-driven observe → decide → act. Records a capability artifact."""

    async def _run() -> None:
        runner = DiscoveryRunner()
        artifact, result = await runner.run(goal, url)
        print(result.model_dump())
        if save and result.status == "success":
            path = Catalog().save_draft(artifact)
            print(f"[green]saved draft[/green] {path}")
            print("Review it, then copy the approved contract into capabilities/.")

    asyncio.run(_run())


@app.command()
def replay(
    artifact: str = typer.Option(..., help="Path or catalog slug"),
    param: list[str] = typer.Option([], help="key=value (repeatable)"),
    approve_irreversible: bool = typer.Option(False, help="Skip HITL confirm on irreversible steps"),
    variant: Optional[str] = typer.Option(None, help="Tenant build overlay, e.g. lakeshore"),
    url: Optional[str] = typer.Option(None, help="Override the artifact entry URL"),
) -> None:
    """Deterministic replay. No model in the decision loop."""
    params = _parse_params(param)
    art = Catalog().load(artifact)

    async def _run() -> None:
        result = await ReplayExecutor().run(
            art,
            params,
            require_confirm_irreversible=not approve_irreversible,
            variant_id=variant,
            entry_url=url,
        )
        print(result.model_dump())
        if result.status == "failed":
            raise typer.Exit(code=2)
        if result.status in {"escalated", "aborted"}:
            raise typer.Exit(code=3)

    asyncio.run(_run())


@catalog_app.command("list")
def catalog_list() -> None:
    print(json.dumps(Catalog().list(), indent=2))


@catalog_app.command("invoke")
def catalog_invoke(
    slug: str = typer.Argument(...),
    param: list[str] = typer.Option([]),
    approve_irreversible: bool = typer.Option(False),
    variant: Optional[str] = typer.Option(None, help="Tenant build overlay, e.g. lakeshore"),
) -> None:
    """Agent-facing: invoke a saved capability by name with typed args."""
    replay(artifact=slug, param=param, approve_irreversible=approve_irreversible, variant=variant)


def _parse_params(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"expected key=value, got {item}")
        k, v = item.split("=", 1)
        out[k] = v
    return out


@app.command("package-info")
def package_info() -> None:
    s = Settings()
    print({"target": s.target_base_url, "model": s.openai_model, "headless": s.headless})


if __name__ == "__main__":
    app()
