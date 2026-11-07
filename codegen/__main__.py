import argparse
import asyncio
import shutil
import sys

from . import fetch


def build() -> None:
    from . import render
    from .events import parse_events
    from .parser import parse_projects

    projects = parse_projects()
    event_models, events = parse_events()
    render.clean_output()
    for project in projects:
        render.render_project(project)
    render.render_rest_namespace(projects)
    render.render_events(event_models, events)
    render.format_output([render.REST_DIR, render.MODELS_DIR, render.EVENTS_DIR])

    endpoints = sum(
        len(r.endpoints) for p in projects for v in p.versions for r in v.resources
    )
    models = sum(len(v.models) for p in projects for v in p.versions)
    print(f"generated {endpoints} endpoints, {models} models, {len(events)} events")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m codegen")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_parser = commands.add_parser("fetch", help="snapshot the platform metadata")
    fetch_parser.add_argument("--refresh", action="store_true")
    commands.add_parser("build", help="generate code from the snapshot")
    args = parser.parse_args()

    if args.command == "fetch":
        asyncio.run(fetch.run(args.refresh))
    else:
        if shutil.which("ruff") is None:
            sys.exit("ruff is required, run from the project environment")
        build()


if __name__ == "__main__":
    main()
