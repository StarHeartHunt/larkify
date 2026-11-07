"""Write the IR out as Python modules."""

from collections import defaultdict
from collections.abc import Iterable
import json
import keyword
from pathlib import Path
import shutil
import subprocess
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .ir import (
    Endpoint,
    EventDef,
    Model,
    ModelField,
    Param,
    Project,
    Resource,
    Version,
    argument_hint,
    model_hint,
    models_in,
    typed_dict_hint,
)
from .parser import sorted_models

PACKAGE_DIR = Path(__file__).parent.parent / "feishukit"
REST_DIR = PACKAGE_DIR / "rest"
MODELS_DIR = PACKAGE_DIR / "models"
EVENTS_DIR = PACKAGE_DIR / "webhooks" / "events"

# Hand-written modules living next to the generated ones.
REST_KEEP = {"_base.py", "paginator.py"}


def docstring(text: str) -> str:
    """Escape a value for use inside a triple quoted string."""
    text = text.replace("\\", "\\\\").replace('"""', "'''")
    return f"{text} " if text.endswith('"') else text


def python_tuple(values: Iterable[str]) -> str:
    items = [repr(v) for v in values]
    if len(items) == 1:
        return f"({items[0]},)"
    return "(" + ", ".join(items) + ")"


def field_annotation(field: ModelField, model: Model) -> str:
    hint = model_hint(field.type)
    if model.variant == "request" and field.required:
        return hint
    return f"{hint} | None"


def field_default(field: ModelField, model: Model) -> str:
    required = model.variant == "request" and field.required
    if field.py_name == field.wire_name:
        return "" if required else " = None"
    alias = f"alias={field.wire_name!r}"
    return f" = Field({alias})" if required else f" = Field(default=None, {alias})"


def typed_dict_annotation(field: ModelField) -> str:
    hint = typed_dict_hint(field.type)
    return f"Required[{hint}]" if field.required else hint


def needs_functional_typed_dict(model: Model) -> bool:
    return not all(
        f.wire_name.isidentifier() and not keyword.iskeyword(f.wire_name)
        for f in model.fields
    ) or any(f.wire_name.startswith("__") for f in model.fields)


def _argument(param: Param) -> str:
    hint = argument_hint(param.type)
    if param.required:
        return f"{param.py_name}: {hint},"
    return f"{param.py_name}: Missing[{hint}] = UNSET,"


def leading_arguments(endpoint: Endpoint) -> str:
    path = "".join(f"{p.py_name}: str, " for p in endpoint.path_params)
    query = " ".join(_argument(p) for p in endpoint.query_params)
    return f"{path}*, {query}"


def keyword_arguments(endpoint: Endpoint) -> str:
    return " ".join(_argument(p) for p in endpoint.kwargs)


def has_overloads(endpoint: Endpoint) -> bool:
    """Whether keyword arguments can express the whole body."""
    if endpoint.body is None or not endpoint.kwargs:
        return False
    passed = {p.wire_name for p in endpoint.kwargs}
    return all(f.wire_name in passed for f in endpoint.body.fields if f.required)


def return_type(endpoint: Endpoint) -> str:
    return f"Response[{endpoint.response_model}]"


def wire_path(endpoint: Endpoint) -> str:
    """The path as documented, recovered from the URL expression."""
    url = endpoint.url
    url = url[1:] if url.startswith("f") else url
    path = url[1:-1]
    for param in endpoint.path_params:
        path = path.replace(
            "{path_param(" + param.py_name + ")}", "{" + param.py_name + "}"
        )
    return path


def build_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    environment.filters.update(
        docstring=docstring,
        python_tuple=python_tuple,
        field_annotation=field_annotation,
        field_default=field_default,
        typed_dict_annotation=typed_dict_annotation,
        model_hint=model_hint,
        leading_arguments=leading_arguments,
        keyword_arguments=keyword_arguments,
        return_type=return_type,
        wire_path=wire_path,
    )
    environment.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)
    environment.tests.update(
        needs_functional_typed_dict=needs_functional_typed_dict,
        has_overloads=has_overloads,
    )
    return environment


ENVIRONMENT = build_environment()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render(template: str, path: Path, **context: Any) -> None:
    write(path, ENVIRONMENT.get_template(template).render(**context))


def clean_output() -> None:
    for generated in (MODELS_DIR, EVENTS_DIR):
        if generated.exists():
            shutil.rmtree(generated)
    if REST_DIR.exists():
        for child in REST_DIR.iterdir():
            if child.name in REST_KEEP:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def model_home(model: Model) -> str:
    """Module holding a model: its resource, or `_shared` when several use it."""
    return "_shared" if len(model.users) != 1 else next(iter(model.users))


def render_models(project: Project, version: Version) -> None:
    root = MODELS_DIR / project.py_name / version.version
    write(MODELS_DIR / "__init__.py", "")
    write(root.parent / "__init__.py", "")
    grouped: defaultdict[str, list[Model]] = defaultdict(list)
    for model in version.models:
        grouped[model_home(model)].append(model)

    write(root / "__init__.py", "")
    for module, models in grouped.items():
        shared_imports: set[str] = set()
        exports: list[str] = []
        for model in models:
            exports.append(model.name)
            if model.variant == "request":
                exports.append(model.typed_name)
            for dependency in model.dependencies:
                if module != "_shared" and model_home(dependency) == "_shared":
                    shared_imports.add(dependency.name)
                    if dependency.variant == "request":
                        shared_imports.add(dependency.typed_name)
        render(
            "models.py.jinja",
            root / f"{module}.py",
            models=sorted_models(models),
            shared_imports=sorted(shared_imports),
            exports=exports,
        )


def _imports(
    version: Version, resource: Resource
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    package = f"feishukit.models.{version.project_module}.{version.version}"
    runtime: defaultdict[str, set[str]] = defaultdict(set)
    typing: defaultdict[str, set[str]] = defaultdict(set)

    for endpoint in resource.endpoints:
        if endpoint.body is not None:
            module = f"{package}.{model_home(endpoint.body)}"
            runtime[module].add(endpoint.body.name)
            typing[module].add(endpoint.body.typed_name)
        if endpoint.response_model not in ("Any", "bytes"):
            runtime[f"{package}.{resource.py_name}"].add(endpoint.response_model)
        for param in endpoint.kwargs:
            for model in models_in(param.type):
                module = f"{package}.{model_home(model)}"
                typing[module].update((model.name, model.typed_name))

    return (
        [(m, sorted(n)) for m, n in sorted(runtime.items())],
        [(m, sorted(n)) for m, n in sorted(typing.items())],
    )


def render_project(project: Project) -> None:
    project_module = f"feishukit.rest.{project.py_name}"
    project_dir = REST_DIR / project.py_name
    children = []

    for version in project.versions:
        version.project_module = project.py_name
        version_module = f"{project_module}.{version.version}"
        children.append(
            {
                "attribute": version.version,
                "module": version_module,
                "class_name": f"{version.class_name}Client",
            }
        )

        if version.legacy:
            resource = version.resources[0]
            render(
                "client.py.jinja",
                project_dir / "legacy.py",
                class_name=f"{version.class_name}Client",
                endpoints=resource.endpoints,
                runtime_imports=[],
                type_imports=[],
            )
            continue

        render_models(project, version)
        version_children = []
        for resource in version.resources:
            runtime_imports, type_imports = _imports(version, resource)
            render(
                "client.py.jinja",
                project_dir / version.version / f"{resource.py_name}.py",
                class_name=resource.class_name,
                endpoints=resource.endpoints,
                runtime_imports=runtime_imports,
                type_imports=type_imports,
            )
            version_children.append(
                {
                    "attribute": resource.py_name,
                    "module": f"{version_module}.{resource.py_name}",
                    "class_name": resource.class_name,
                }
            )
        render(
            "namespace.py.jinja",
            project_dir / version.version / "__init__.py",
            base_module="feishukit.rest._base",
            base_class="BaseClient",
            class_name=f"{version.class_name}Client",
            docstring=f"{project.py_name} {version.version}",
            children=version_children,
        )

    render(
        "namespace.py.jinja",
        project_dir / "__init__.py",
        base_module="feishukit.rest._base",
        base_class="BaseClient",
        class_name=f"{project.class_name}Client",
        docstring=project.py_name,
        children=children,
    )


def render_rest_namespace(projects: list[Project]) -> None:
    render(
        "namespace.py.jinja",
        REST_DIR / "__init__.py",
        base_module="feishukit.rest._base",
        base_class="BaseRestNamespace",
        class_name="RestNamespace",
        docstring="Every server-side API, by project, version and resource.",
        children=[
            {
                "attribute": project.py_name,
                "module": f"feishukit.rest.{project.py_name}",
                "class_name": f"{project.class_name}Client",
            }
            for project in projects
        ],
    )


def render_events(models: dict[str, list[Model]], events: list[EventDef]) -> None:
    grouped: defaultdict[str, list[EventDef]] = defaultdict(list)
    for event in events:
        grouped[event.project].append(event)

    render("event_index.py.jinja", EVENTS_DIR / "__init__.py", events=events)
    for project, project_events in grouped.items():
        render(
            "event_models.py.jinja",
            EVENTS_DIR / f"{project}.py",
            models=models.get(project, []),
            events=project_events,
        )


def format_output(paths: Iterable[Path]) -> None:
    # Isolated: the project configuration excludes generated code from linting,
    # and excluded files would be skipped here without notice.
    targets = [str(p) for p in paths]
    fix = ["ruff", "check", "--isolated", "--fix", "--quiet", "--select", "F401,I"]
    subprocess.run([*fix, *targets], check=True)
    subprocess.run(["ruff", "format", "--isolated", "--quiet", *targets], check=True)
