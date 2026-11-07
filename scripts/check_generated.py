"""Import every generated module and force-build every model.

Models use `defer_build`, so a bad annotation stays hidden until the model is
first used. This walks all of them.
"""

import importlib
import pkgutil
import sys
import time
import warnings

from larkify.model import FeishuModel
import larkify.models
import larkify.rest
import larkify.webhooks.events

warnings.simplefilter("error")


def modules(package):
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        yield info.name


def main() -> None:
    start = time.perf_counter()
    count = built = 0
    failures = []
    for package in (larkify.models, larkify.rest, larkify.webhooks.events):
        for name in modules(package):
            count += 1
            try:
                module = importlib.import_module(name)
            except Exception as e:
                failures.append((name, repr(e)))
                continue
            for value in vars(module).values():
                if (
                    isinstance(value, type)
                    and issubclass(value, FeishuModel)
                    and value.__module__ == name
                ):
                    built += 1
                    try:
                        value.model_rebuild(force=True)
                        value.model_json_schema()
                    except Exception as e:
                        failures.append((f"{name}.{value.__name__}", repr(e)[:300]))

    print(f"{count} modules, {built} models, {time.perf_counter() - start:.1f}s")
    for failure in failures[:40]:
        print("FAILED", *failure)
    print(f"{len(failures)} failures")
    sys.exit(1 if failures or not built else 0)


if __name__ == "__main__":
    main()
