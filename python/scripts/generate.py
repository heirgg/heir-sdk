"""Write src/heir/models/*.py from ../spec with datamodel-code-generator.

Before generating, each document is reshaped so the Python models read well; nothing about the wire format changes,
only its Python spelling:

- each request and response body named in ../spec/type-names.json (`<operationId> request`, `<operationId> <status>`)
  becomes the component of that name, whether the document writes it inline or under another component name;
- every inline object becomes a named component, so a caller can name the type (the names in ../spec/type-names.json,
  shared with the other SDKs' generators, otherwise <Parent><Field>); a named type's own fields are listed under its
  name (`Player.mmr`), wherever the type appears;
- a union of numeric literals (0 | 1) or of a string with a literal collapses to one primitive; a boolean literal
  becomes a plain boolean; a nullable primitive is written in the form the generator reads as `X | None`;
- objects are left open, so a field the API adds later is ignored rather than refused;
- a `number` is `int | float`, so a whole number in an answer stays an `int` (`10`, not `10.0`) and a fraction stays a
  `float`; an `integer` is `int`;
- `uri` and `uuid` strings are plain strings, and no length, range or pattern constraint is kept: like the other SDKs,
  the models do not validate, the API does.

`--check` fails instead of writing when the committed files are out of date.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SPEC = HERE.parent.parent / "spec"
MODELS = HERE.parent / "src" / "heir" / "models"
DOCUMENTS = [
    # The error envelopes are written by hand (HeirAPIError), so both documents' `Error` schemas are left out.
    ("public-openapi.json", "public", ["Error", "LeagueError"]),
    ("stat-submission-openapi.json", "stats", ["Error"]),
]
PRIMITIVES = {"string", "number", "integer", "boolean"}
CONSTRAINTS = (
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
)
Schema = dict[str, Any]


def main() -> int:
    check = "--check" in sys.argv
    names: dict[str, str] = json.loads((SPEC / "type-names.json").read_text())
    stale: list[str] = []
    classes: dict[str, list[str]] = {}
    for file, module, exclude in DOCUMENTS:
        code = generate(SPEC / file, exclude, names)
        classes[module] = re.findall(r"^class (\w+)\(", code, re.MULTILINE)
        target = MODELS / f"{module}.py"
        if check:
            if not target.exists() or target.read_text() != code:
                stale.append(target.name)
        else:
            target.write_text(code)
            print(f"Wrote {target}")
    init = init_module(classes)
    if check:
        if (MODELS / "__init__.py").read_text() != init:
            stale.append("__init__.py")
        if stale:
            print(
                f"Out of date: {', '.join(stale)}. Run `python scripts/generate.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("Generated models are up to date.")
    else:
        (MODELS / "__init__.py").write_text(init)
    return 0


def generate(path: Path, exclude: list[str], names: dict[str, str]) -> str:
    doc = json.loads(path.read_text())
    schemas: Schema = doc["components"]["schemas"]
    name_operations(doc, names)
    for name in exclude:
        schemas.pop(name, None)
    reshape(schemas, names)
    keep_whole_numbers(schemas)
    doc.pop("paths", None)
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / path.name
        source.write_text(json.dumps(doc))
        output = Path(folder) / "models.py"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "datamodel_code_generator",
                "--input",
                str(source),
                "--input-file-type",
                "openapi",
                "--output",
                str(output),
                "--output-model-type",
                "pydantic_v2.BaseModel",
                "--target-python-version",
                "3.10",
                "--snake-case-field",
                "--allow-population-by-field-name",
                "--use-standard-collections",
                "--use-union-operator",
                "--use-schema-description",
                "--field-constraints",
                "--collapse-root-models",
                "--enum-field-as-literal",
                "all",
                "--use-double-quotes",
                "--disable-timestamp",
                "--base-class",
                "heir.models._base.HeirModel",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        code = output.read_text()
    header = f"# Generated by scripts/generate.py from ../../../spec/{path.name}; do not edit by hand.\n"
    return header + code.split("\n", 2)[2].lstrip("\n") if code.startswith("# generated by") else header + code


def init_module(classes: dict[str, list[str]]) -> str:
    lines = ["# Generated by scripts/generate.py; do not edit by hand.", ""]
    names: list[str] = []
    for module, found in classes.items():
        lines.append(f"from .{module} import (")
        lines.extend(f"    {name}," for name in sorted(found, key=str.lower))
        lines.append(")")
        names.extend(found)
    lines += ["", "__all__ = ["] + [f'    "{name}",' for name in sorted(names)] + ["]", ""]
    return "\n".join(lines)


def name_operations(doc: Schema, names: dict[str, str]) -> None:
    """Make each request and response body named in `names` the component of that name.

    The backend writes most bodies inline, and some under names of its own; the SDKs name them the same way in every
    language. A body with no documented fields cannot become a model and is refused, so the gap is fixed in the backend
    document rather than shipped as an empty type.
    """
    schemas: Schema = doc["components"]["schemas"]
    for path, methods in sorted(doc.get("paths", {}).items()):
        for method, operation in sorted(methods.items()):
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            slots = [("request", operation.get("requestBody", {}))]
            slots += sorted(operation.get("responses", {}).items())
            for slot, body in slots:
                key = f"{operation['operationId']} {slot}"
                media = body.get("content", {}).get("application/json")
                if key not in names or media is None:
                    continue
                name, schema = names[key], media["schema"]
                if "$ref" in schema:
                    rename(doc, schema["$ref"].rsplit("/", 1)[-1], name)
                    continue
                if "properties" not in schema:
                    raise SystemExit(f"{key} ({method.upper()} {path}) documents no fields, so {name} would be empty")
                copied = {k: v for k, v in schema.items() if k not in {"description", "example", "examples"}}
                if name in schemas and schemas[name] != copied:
                    raise SystemExit(f"two different shapes are both named {name}: reshaping needs a second name")
                schemas[name] = copied
                media["schema"] = {"$ref": f"#/components/schemas/{name}"}


def rename(doc: Schema, old: str, new: str) -> None:
    """Rename the component `old` to `new`, and every reference to it."""
    if old == new:
        return
    schemas: Schema = doc["components"]["schemas"]
    if new in schemas:
        raise SystemExit(f"cannot rename {old}: a component is already named {new}")
    schemas[new] = schemas.pop(old)
    target, replacement = f"#/components/schemas/{old}", f"#/components/schemas/{new}"

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("$ref") == target:
                node["$ref"] = replacement
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(doc)


# The components reshaped so far. A document's own component can be reached as a field's type before its turn comes as a
# root; it is reshaped then, so it is compared with a newcomer in the same form.
reshaped: set[str] = set()


def reshape(schemas: Schema, names: dict[str, str]) -> None:
    reshaped.clear()
    for root in sorted(schemas):
        if root not in reshaped:
            reshaped.add(root)
            walk(schemas, names, root, root, schemas[root])


def walk(schemas: Schema, names: dict[str, str], path: str, type_name: str, node: Schema) -> None:
    """Reshape one object schema's properties. `path` is its place in the document and `type_name` its class."""
    collapse(node)
    for field, slot in sorted(node.get("properties", {}).items()):
        place(schemas, names, f"{path}.{field}", type_name + field[:1].upper() + field[1:], slot)


def place(schemas: Schema, names: dict[str, str], path: str, auto_name: str, slot: Schema) -> None:
    """Reshape the schema at `path` (a field, an array's items or a map's values), hoisting an inline object."""
    inner, set_ref = unwrap_nullable(slot)
    collapse(inner)
    if "$ref" in inner:
        return
    # A nullable array has been rewritten as `type: ["array", "null"]`; its items are reshaped all the same.
    kind = inner.get("type")
    if (kind == "array" or (isinstance(kind, list) and "array" in kind)) and isinstance(inner.get("items"), dict):
        unconstrain(inner["items"])
        place(schemas, names, f"{path}[]", auto_name + "Item", inner["items"])
    values = inner.get("additionalProperties")
    if isinstance(values, dict):
        unconstrain(values)
        if "properties" in values:
            place(schemas, names, f"{path}{{}}", auto_name + "Value", values)
    inner.pop("propertyNames", None)
    if "properties" in inner:
        name = names.get(path, auto_name)
        # A named type's fields are listed under its name, so it is spelled the same wherever it appears.
        within = name if path in names else path
        known = name in schemas
        hoisted = hoist(schemas, names, within, name, inner)
        set_ref(name)
        if not known:
            walk(schemas, names, within, name, hoisted)


def unconstrain(node: Schema) -> None:
    """Drop the constraints of a primitive used as an array's items or a map's values: the generator would otherwise
    wrap it in a class of its own."""
    if node.get("type") in PRIMITIVES:
        for key in CONSTRAINTS:
            node.pop(key, None)
        if node.get("format") in {"uri", "uuid"}:
            del node["format"]


def hoist(schemas: Schema, names: dict[str, str], path: str, name: str, node: Schema) -> Schema:
    """Store `node` as the component `name`, or check it agrees with the one already there; return the stored copy."""
    copied = deepcopy(node)
    copied.pop("description", None)
    if name in schemas:
        stored: Schema = schemas[name]
        if name not in reshaped:
            reshaped.add(name)
            walk(schemas, names, name, name, stored)
        # The stored one has been reshaped all the way down; reshape the newcomer the same way before comparing.
        walk(schemas, names, path, name, copied)
        if {key: value for key, value in stored.items() if key != "description"} != copied:
            raise SystemExit(f"two different shapes are both named {name}: reshaping needs a second name")
        return stored
    reshaped.add(name)
    schemas[name] = copied
    return copied


def unwrap_nullable(slot: Schema) -> tuple[Schema, Any]:
    """Find the schema inside a nullable wrapper (`anyOf: [X, null]`), and how to replace it with a reference.

    A nullable primitive is rewritten as `type: [X, "null"]`, which the generator reads as `X | None` without inventing
    a wrapper class for the constrained inner type.
    """
    members = slot.get("anyOf")
    if isinstance(members, list) and len(members) == 2:
        for index, member in enumerate(members):
            if isinstance(member, dict) and member.get("type") == "null":
                other = members[1 - index]
                if isinstance(other, dict) and other.get("type") in PRIMITIVES | {"array"}:
                    kind = other["type"]
                    description = slot.get("description")
                    slot.clear()
                    slot.update(other)
                    slot["type"] = [kind, "null"]
                    if description:
                        slot["description"] = description
                    return slot, lambda name: None

                def set_ref(name: str, members: list[Any] = members, index: int = 1 - index) -> None:
                    members[index] = {"$ref": f"#/components/schemas/{name}"}

                return other, set_ref

    def replace(name: str) -> None:
        description = slot.get("description")
        slot.clear()
        slot["$ref"] = f"#/components/schemas/{name}"
        if description:
            slot["description"] = description

    return slot, replace


def keep_whole_numbers(node: Any) -> None:
    """Spell every `number` as `integer | number`, which the models read as `int | float`.

    A stat or a rating may be a fraction, so the API documents a number; most are whole. Pydantic keeps the type the
    JSON value has, so `10` stays `10` when it is read and when it is sent again, where `float` would make it `10.0`.
    """
    if isinstance(node, list):
        for value in node:
            keep_whole_numbers(value)
        return
    if not isinstance(node, dict):
        return
    for value in node.values():
        keep_whole_numbers(value)
    kind = node.get("type")
    if "const" in node or "enum" in node:
        return
    if kind == "number":
        del node["type"]
        node["anyOf"] = [{"type": "integer"}, {"type": "number"}]
    elif isinstance(kind, list) and "number" in kind:
        del node["type"]
        others = [{"type": other} for other in kind if other != "number"]
        node["anyOf"] = [{"type": "integer"}, {"type": "number"}, *others]


def collapse(node: Schema) -> None:
    """Rewrite unions a model cannot express well into one primitive, a boolean literal into a boolean, leave the
    object open, and drop the string formats the other SDKs also read as plain strings."""
    if node.get("additionalProperties") is False:
        del node["additionalProperties"]
    members = node.get("anyOf")
    if isinstance(members, list) and members:
        kinds = {("number" if m.get("type") == "integer" else m.get("type")) for m in members if isinstance(m, dict)}
        if len(kinds) == 1 and (kind := kinds.pop()) in PRIMITIVES:
            literals = [m["const"] for m in members if "const" in m]
            all_literal = len(literals) == len(members)
            del node["anyOf"]
            if kind == "number" and all_literal and all(float(v).is_integer() for v in literals):
                node["type"] = "integer"
            elif kind == "string" and all_literal:
                node["type"], node["enum"] = "string", literals
            else:
                node["type"] = kind
    if node.get("type") == "boolean":
        node.pop("const", None)
    if node.get("format") in {"uri", "uuid"}:
        del node["format"]
    # Like the other SDKs, the models carry no validation of their own: the API checks a request and says what is
    # wrong, and an answer is never refused for a detail the API may change.
    for key in CONSTRAINTS:
        node.pop(key, None)


if __name__ == "__main__":
    raise SystemExit(main())
