"""Validate the generated models against the examples in the documentation.

Without credentials, the worked examples Feishu publishes are the closest thing
to real traffic. Failures point at either a wrong model or a wrong example, so
they are reported rather than asserted to be zero.
"""

from collections import Counter
import importlib
import re
import sys

from pydantic import ValidationError

from codegen.parser import iter_documents, load_example, parse_projects
from codegen.render import model_home, wire_path


def media_example(section):
    for media in (section or {}).values():
        return media.get("example")
    return None


def main() -> None:
    documents = {}
    for document in iter_documents():
        definition = document["definition"]
        if definition:
            key = (
                definition["httpMethod"],
                re.sub(r":\w+", "{}", definition["apiPath"]),
            )
            documents[key] = document

    def check(kind, package, endpoint, model, payload):
        module = importlib.import_module(f"{package}.{model_home(model)}")
        try:
            getattr(module, model.name).model_validate(payload)
            stats[f"{kind} ok"] += 1
        except ValidationError as e:
            stats[f"{kind} failed"] += 1
            first = e.errors()[0]
            kinds[(kind, first["type"])] += 1
            failures.append(
                f"{kind} {endpoint.project}.{endpoint.version}."
                f"{endpoint.resource}.{endpoint.method}: "
                f"{'.'.join(map(str, first['loc']))}: "
                f"{first['type']}: {str(first['input'])[:60]}"
            )

    stats: Counter[str] = Counter()
    failures: list[str] = []
    kinds: Counter[tuple[str, str]] = Counter()

    for project in parse_projects():
        for version in project.versions:
            if version.legacy:
                continue
            models = {m.name: m for m in version.models}
            for resource in version.resources:
                for endpoint in resource.endpoints:
                    document = documents.get(
                        (
                            endpoint.http_method,
                            re.sub(r"\{\w+\}", "{}", wire_path(endpoint)),
                        )
                    )
                    if document is None:
                        stats["no document"] += 1
                        continue
                    api = document["detail"].get("apiSchema") or {}
                    package = f"larkify.models.{project.py_name}.{version.version}"

                    if endpoint.body is not None:
                        example = media_example(
                            (api.get("requestBody") or {}).get("content")
                        )
                        payload = load_example(example)
                        if isinstance(payload, dict):
                            check("request", package, endpoint, endpoint.body, payload)
                        else:
                            stats["request no example"] += 1

                    model = models.get(endpoint.response_model)
                    if model is not None:
                        example = media_example(
                            ((api.get("responses") or {}).get("200") or {}).get(
                                "content"
                            )
                        )
                        payload = load_example(example)
                        if isinstance(payload, dict):
                            data = (
                                payload.get("data")
                                if endpoint.data_key == "data"
                                else payload
                            )
                            check(
                                "response",
                                package,
                                endpoint,
                                model,
                                data if data is not None else {},
                            )
                        else:
                            stats["response no example"] += 1

    for key, value in sorted(stats.items()):
        print(f"{key}: {value}")
    print(kinds.most_common())
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    for failure in failures[:limit]:
        print(failure)


if __name__ == "__main__":
    main()
