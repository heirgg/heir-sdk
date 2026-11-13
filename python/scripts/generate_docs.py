"""Generate the public Python SDK reference from source ASTs, without importing the SDK.

Run from any directory. --check compares bytes and exits nonzero without writing. The source hash includes all
Python implementation files and the package manifest so behavioral changes also invalidate the reference.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "python/src/heir"
OUTPUT = ROOT / "docs/reference/python.mdx"
PROTOCOLS = {"__enter__", "__exit__", "__aenter__", "__aexit__", "__iter__", "__aiter__", "__str__", "__repr__"}
Function = ast.FunctionDef | ast.AsyncFunctionDef
Definition = ast.ClassDef | Function | ast.Assign | ast.AnnAssign


@dataclass(frozen=True)
class Source:
    path: Path
    text: str
    tree: ast.Module

    def expression(self, node: ast.AST | None) -> str:
        if node is None:
            return "Any"
        text = ast.get_source_segment(self.text, node)
        if text is None:
            raise ValueError(f"Missing source expression in {self.path}")
        return " ".join(text.strip().split())


def sources() -> dict[str, Source]:
    result = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        result[path.relative_to(PACKAGE).as_posix()] = Source(path, text, ast.parse(text))
    return result


def exported(source: Source, model_names: list[str] | None = None) -> list[str]:
    for node in source.tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                raise ValueError("__all__ must be a literal sequence")
            result: list[str] = []
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    result.append(item.value)
                elif (
                    isinstance(item, ast.Starred)
                    and source.expression(item.value) == "models.__all__"
                    and model_names is not None
                ):
                    result.extend(model_names)
                else:
                    raise ValueError(f"Unsupported public export: {source.expression(item)}")
            if len(set(result)) != len(result):
                raise ValueError("Duplicate public exports")
            return result
    raise ValueError(f"No __all__ in {source.path}")


def definitions(all_sources: dict[str, Source]) -> dict[str, tuple[Source, Definition]]:
    result: dict[str, tuple[Source, Definition]] = {}
    for name, source in all_sources.items():
        if name.endswith("__init__.py"):
            continue
        for node in source.tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                result[node.name] = (source, node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        result[target.id] = (source, node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                result[node.target.id] = (source, node)
    return result


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(
        [*PACKAGE.rglob("*.py"), PACKAGE / "py.typed", ROOT / "python/pyproject.toml", *(ROOT / "spec").glob("*.json")]
    ):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def package_version() -> str:
    project = (ROOT / "python/pyproject.toml").read_text(encoding="utf-8").split("[project]", 1)[1].split("\n[", 1)[0]
    match = re.search(r'^version\s*=\s*"([^"]+)"', project, re.MULTILINE)
    if match is None:
        raise ValueError("Expected a literal project version in pyproject.toml")
    return match.group(1)


def code(value: str, *, table: bool = False) -> str:
    if table:
        value = value.replace("|", "\\|")
    return "`" + value.replace("`", "&#96;") + "`"


def prose(value: str) -> str:
    def escape(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("{", "&#123;")
            .replace("}", "&#125;")
        )

    result: list[str] = []
    offset = 0
    for span in re.finditer(r"(`+)(.*?)\1", value):
        result.extend((escape(value[offset : span.start()]), span.group(0)))
        offset = span.end()
    result.append(escape(value[offset:]))
    return "".join(result)


def summary(node: ast.ClassDef | Function) -> str:
    doc = ast.get_docstring(node)
    return prose(" ".join(doc.split("\n\n", 1)[0].split())) if doc else ""


def parameters(fn: Function, source: Source) -> list[tuple[str, str, str, str]]:
    rows = []
    positional = [*fn.args.posonlyargs, *fn.args.args]
    defaults = [None] * (len(positional) - len(fn.args.defaults)) + list(fn.args.defaults)
    for index, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        if arg.arg in {"self", "cls"}:
            continue
        kind = "positional only" if index < len(fn.args.posonlyargs) else "positional or keyword"
        rows.append(
            (
                arg.arg,
                source.expression(arg.annotation),
                "required" if default is None else source.expression(default),
                kind,
            )
        )
    if fn.args.vararg:
        arg = fn.args.vararg
        rows.append(("*" + arg.arg, source.expression(arg.annotation), "()", "variadic"))
    for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True):
        rows.append(
            (
                arg.arg,
                source.expression(arg.annotation),
                "required" if default is None else source.expression(default),
                "keyword only",
            )
        )
    if fn.args.kwarg:
        arg = fn.args.kwarg
        rows.append(("**" + arg.arg, source.expression(arg.annotation), "{}", "variadic keywords"))
    return rows


def signature(name: str, fn: Function, source: Source, *, constructor: bool = False) -> str:
    args: list[str] = []
    previous = ""
    for arg, annotation, default, kind in parameters(fn, source):
        if previous == "positional only" and kind != "positional only":
            args.append("/")
        if kind == "keyword only" and previous not in {"keyword only", "variadic"}:
            args.append("*")
        item = f"{arg}: {annotation}"
        if default != "required":
            item += f" = {default}"
        args.append(item)
        previous = kind
    if previous == "positional only":
        args.append("/")
    prefix = "async def " if isinstance(fn, ast.AsyncFunctionDef) else "def "
    if constructor:
        prefix = ""
    suffix = "" if constructor else " -> " + source.expression(fn.returns)
    return f"{prefix}{name}({', '.join(args)}){suffix}"


def parameter_table(fn: Function, source: Source) -> list[str]:
    rows = parameters(fn, source)
    if not rows:
        return ["No arguments.", ""]
    result = ["| Parameter | Type | Default | Passing style |", "| --- | --- | --- | --- |"]
    result += [
        f"| {code(name, table=True)} | {code(kind, table=True)} | {code(default, table=True)} | {style} |"
        for name, kind, default, style in rows
    ]
    return [*result, ""]


def nullable(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return nullable(node.left) or nullable(node.right)
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Optional"


def field_info(node: ast.AnnAssign, source: Source) -> tuple[str, str, str, str, str]:
    if not isinstance(node.target, ast.Name):
        raise ValueError("Expected a named model field")
    name = node.target.id
    alias = name
    value = node.value
    if isinstance(value, ast.Call) and source.expression(value.func) == "Field":
        keyword_args = {keyword.arg: keyword.value for keyword in value.keywords}
        alias_value = keyword_args.get("alias")
        if isinstance(alias_value, ast.Constant) and isinstance(alias_value.value, str):
            alias = alias_value.value
        value = value.args[0] if value.args else keyword_args.get("default")
    required = value is None or (isinstance(value, ast.Constant) and value.value is Ellipsis)
    default = "required" if required else source.expression(value)
    return name, alias, source.expression(node.annotation), default, "yes" if nullable(node.annotation) else "no"


def fields(cls: ast.ClassDef) -> list[ast.AnnAssign]:
    return [
        node
        for node in cls.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and not node.target.id.startswith("_")
        and node.target.id != "model_config"
    ]


def model_reference(name: str, cls: ast.ClassDef, source: Source) -> list[str]:
    result = [
        f"### {name}",
        "",
        f"Import: {code('from heir import ' + name)} or {code('from heir.models import ' + name)}.",
        "",
    ]
    if text := summary(cls):
        result += [text, ""]
    config = next(
        (
            node.value
            for node in cls.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "model_config" for t in node.targets)
        ),
        None,
    )
    extra = "ignore"
    if isinstance(config, ast.Call):
        for keyword in config.keywords:
            if keyword.arg == "extra" and isinstance(keyword.value, ast.Constant):
                extra = str(keyword.value.value)
    result += [f"Unknown fields: {code(extra)}. Field names and JSON aliases are accepted during construction.", ""]
    result += [
        "| Python field | JSON field | Python type | Default at construction | Accepts None |",
        "| --- | --- | --- | --- | --- |",
    ]
    for field_node in fields(cls):
        field, alias, annotation, default, accepts_none = field_info(field_node, source)
        result.append(
            f"| {code(field, table=True)} | {code(alias, table=True)} | {code(annotation, table=True)} "
            f"| {code(default, table=True)} | {accepts_none} |"
        )
    result.append("")
    for node in cls.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__annotations__" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "__pydantic_extra__":
                    result += [
                        f"Additional fields are retained as {code(source.expression(value))}; "
                        "their names stay unchanged in JSON.",
                        "",
                    ]
    return result


def public_attributes(cls: ast.ClassDef, source: Source, index: dict[str, tuple[Source, Definition]]) -> dict[str, str]:
    result = {}
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id in index:
            base_source, base_node = index[base.id]
            if isinstance(base_node, ast.ClassDef):
                result.update(public_attributes(base_node, base_source, index))
    for field in fields(cls):
        if isinstance(field.target, ast.Name):
            result[field.target.id] = source.expression(field.annotation)
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name != "__init__":
            continue
        argument_types = {name: annotation for name, annotation, _, _ in parameters(fn, source)}
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and not target.attr.startswith("_")
                ):
                    continue
                if isinstance(node, ast.AnnAssign):
                    annotation = source.expression(node.annotation)
                elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                    annotation = node.value.func.id
                else:
                    annotation = argument_types.get(target.attr, "Any")
                    if isinstance(node.value, (ast.BoolOp, ast.IfExp)):
                        annotation = annotation.replace(" | None", "")
                result[target.attr] = annotation
    return result


def class_reference(
    name: str, cls: ast.ClassDef, source: Source, index: dict[str, tuple[Source, Definition]]
) -> list[str]:
    bases = [
        source.expression(base) for base in cls.bases if not (isinstance(base, ast.Name) and base.id.startswith("_"))
    ]
    result = [f"### {name}", ""]
    if bases:
        result += [f"Public bases: {code(', '.join(bases))}.", ""]
    if text := summary(cls):
        result += [text, ""]
    constructor = next(
        (node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"), None
    )
    if constructor:
        result += ["```text", signature(name, constructor, source, constructor=True), "```", ""]
        result += parameter_table(constructor, source)
    elif any(source.expression(d).startswith("dataclass") for d in cls.decorator_list):
        args = []
        for node in fields(cls):
            field, _, annotation, default, _ = field_info(node, source)
            args.append(f"{field}: {annotation}" + ("" if default == "required" else f" = {default}"))
        result += ["```text", f"{name}({', '.join(args)})", "```", ""]
        if any("frozen=True" in source.expression(d) for d in cls.decorator_list):
            result += ["Frozen dataclass: fields cannot be reassigned.", ""]
    attributes = public_attributes(cls, source, index)
    if attributes:
        result += ["| Public attribute | Type |", "| --- | --- |"]
        result += [
            f"| {code(field, table=True)} | {code(annotation, table=True)} |"
            for field, annotation in sorted(attributes.items())
        ]
        result.append("")
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name == "__init__" or (fn.name.startswith("_") and fn.name not in PROTOCOLS):
            continue
        result += [f"#### {name} {fn.name}", ""]
        if any(isinstance(d, ast.Name) and d.id == "property" for d in fn.decorator_list):
            result += [f"Read-only property: {code(fn.name + ': ' + source.expression(fn.returns))}.", ""]
        else:
            result += ["```text", signature(name + "." + fn.name, fn, source), "```", ""]
            result += parameter_table(fn, source)
            result += [f"Returns: {code(source.expression(fn.returns))}.", ""]
        if text := summary(fn):
            result += [text, ""]
        if name in {"League", "AsyncLeague"} and not fn.name.startswith("_"):
            result += [
                "See [League operations](/sdk/python/league) for behavior, examples, errors, and the HTTP route.",
                "",
            ]
        if name in {"Stats", "AsyncStats"} and not fn.name.startswith("_"):
            result += [
                "See [stat submission](/sdk/python/stats) for behavior, examples, idempotency, and the HTTP route.",
                "",
            ]
    return result


def render() -> str:
    all_sources = sources()
    model_names = exported(all_sources["models/__init__.py"])
    names = exported(all_sources["__init__.py"], model_names)
    index = definitions(all_sources)
    missing = set(names) - set(index) - {"models"}
    if missing:
        raise ValueError(f"Undocumented public exports: {sorted(missing)}")
    result = [
        "---",
        "title: Python SDK reference",
        "description: Complete source-generated exports, signatures, attributes, and model fields.",
        f"sdkSourceHash: {json.dumps(source_hash())}",
        "---",
        "",
        "This reference is generated from Python source without importing Pydantic or the SDK. It "
        "describes the current source checkout. See [installation](/sdk/python) for package "
        "availability.",
        "",
        f"Package version declared in `pyproject.toml`: {code(package_version())}.",
        "",
        "Regenerate with `python python/scripts/generate_docs.py` from the SDK repository. `--check` "
        "performs no writes. The source hash covers every Python implementation file, `py.typed`, "
        "`pyproject.toml`, and `spec/*.json`, including transport and protocol behavior.",
        "",
        "## Public exports",
        "",
        "All names below are exported by `heir`. Generated model classes are also exported by `heir.models`.",
        "",
        "```python",
        "from heir import (",
        *[f"    {name}," for name in names],
        ")",
        "```",
        "",
        "## Clients, resources, pages, options, and errors",
        "",
        "Signatures omit bound `self` and `cls`. Keyword-only parameters follow `*`. `ItemT` is a page's"
        " row type; `BodyT` is its complete response model. A returned page is not a plain list. An "
        "`async def` result is obtained by awaiting the call.",
        "",
    ]
    for name in names:
        if name in model_names or name == "models":
            continue
        source, node = index[name]
        if isinstance(node, ast.ClassDef):
            result += class_reference(name, node, source, index)
    result += ["## Functions, constants, and literal types", ""]
    for name in names:
        if name in model_names or name == "models":
            continue
        source, node = index[name]
        if isinstance(node, ast.ClassDef):
            continue
        result += [f"### {name}", ""]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result += ["```text", signature(name, node, source), "```", "", *parameter_table(node, source)]
            if text := summary(node):
                result += [text, ""]
        else:
            result += ["```python", f"{name} = {source.expression(node.value)}", "```", ""]
    result += [
        "## Generated models",
        "",
        "Every field is listed below. `required` means that construction needs a value, even when `None`"
        " is accepted. Other cells show the Python default. Accepting `None` in Python does not "
        "guarantee that the API accepts JSON null for that field; consult the linked HTTP API contracts "
        "before sending it.",
        "",
        "The SDK sends explicitly set fields and changed mutable defaults, preserving explicit nulls and"
        " current allowed extra fields. Raw Pydantic dumping has its own omission flags. See [model "
        "behavior](/sdk/python/models) for validation, aliases, datetime conversion, and mutation "
        "details.",
        "",
        "Standard inherited Pydantic methods are documented in the [BaseModel "
        "API](https://docs.pydantic.dev/latest/api/base_model/). SDK operations convert request "
        "validation failures to `HeirInputError` and response validation failures to "
        "`HeirProtocolError`; direct model construction can raise Pydantic `ValidationError`.",
        "",
    ]
    for name in sorted(model_names):
        source, node = index[name]
        if not isinstance(node, ast.ClassDef):
            raise ValueError(f"Expected model class for {name}")
        result += model_reference(name, node, source)
    result += [
        "## Models namespace",
        "",
        "`heir.models.__all__` lists exactly the generated model classes above. Clients, options, "
        "errors, page helpers, and literal query aliases are top-level `heir` exports instead.",
        "",
    ]
    return "\n".join(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"Out of date: {OUTPUT.relative_to(ROOT)}. Run python python/scripts/generate_docs.py.")
            return 1
        print("Python SDK reference is up to date.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
