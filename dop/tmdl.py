"""TMDL (Tabular Model Definition Language) for the semantic model.

`write_model` turns the model dictionary that `dop.pbip.build_model` builds (tables, columns, measures, partitions,
hierarchies, relationships, expressions, functions, annotations) into the files of a `definition` folder, as Power
BI Desktop stores a project's semantic model since the TMDL format became the standard: `database.tmdl`,
`model.tmdl`, `relationships.tmdl`, `expressions.tmdl`, `functions.tmdl` and one `tables/<table>.tmdl` per table.
`read_model` parses such a folder back into the same dictionary shape, so the offline checks and the tests read
the committed project the way the generator built it.

Conventions (as Desktop writes them): tab indentation; an object is `<kind> <name>` with its properties one level
deeper; a boolean property that is true is the bare property name; a multi-line DAX or M expression sits in a
triple-backtick block; a description is a `///` line above its object.
"""
from __future__ import annotations

import json
import pathlib
import re

_BARE = re.compile(r"^[A-Za-z0-9_-]+$")
_BOOLS = {"isHidden", "isKey", "isNameInferred", "isDataTypeInferred", "isActive", "legacyRedirects",
          "returnErrorValuesAsNull"}
_REFS = {"sortByColumn"}
_COLUMN_ORDER = ["dataType", "isHidden", "isKey", "isNameInferred", "isDataTypeInferred", "formatString",
                 "lineageTag", "sourceColumn", "sortByColumn", "summarizeBy"]
_MEASURE_ORDER = ["formatString", "displayFolder", "lineageTag", "dataCategory"]
_TABLE_ORDER = ["dataCategory", "isHidden", "lineageTag"]


def tmdl_name(name: str) -> str:
    """A TMDL identifier: bare when it is only letters, digits, _ and -, otherwise in single quotes."""
    return name if _BARE.match(name) else "'" + name.replace("'", "''") + "'"


def _expression(expr, indent: int) -> str:
    """` = <expr>` for a one-line expression, or ` = ```` and the lines of the block for several."""
    if isinstance(expr, str):
        return f" = {expr}"
    tabs = "\t" * (indent + 2)
    return " = ```\n" + "".join(f"{tabs}{line}\n" if line else "\n" for line in expr) + f"{tabs}```"


def _props(obj: dict, order: list[str], indent: int) -> list[str]:
    tabs = "\t" * indent
    out = []
    for key in order:
        if key not in obj:
            continue
        value = obj[key]
        if key in _BOOLS:
            out.append(f"{tabs}{key}" if value else f"{tabs}{key}: false")
        elif key in _REFS:                        # a reference to another object: quoted like a name
            out.append(f"{tabs}{key}: {tmdl_name(value)}")
        else:
            out.append(f"{tabs}{key}: {value}")
    return out


def _annotations(obj: dict, indent: int) -> list[str]:
    tabs = "\t" * indent
    return [f"{tabs}annotation {a['name']} = {a['value']}" for a in obj.get("annotations", [])]


def _doc(obj: dict, indent: int) -> list[str]:
    description = obj.get("description")
    tabs = "\t" * indent
    return [f"{tabs}/// {description}"] if description else []


def _column(c: dict) -> list[str]:
    lines = _doc(c, 1) + [f"\tcolumn {tmdl_name(c['name'])}"] + _props(c, _COLUMN_ORDER, 2)
    details = c.get("relatedColumnDetails", {}).get("groupByColumns", [])
    if details:
        lines += ["", "\t\trelatedColumnDetails"] + [f"\t\t\tgroupByColumn: {tmdl_name(g['groupingColumn'])}"
                                                      for g in details]
    for prop in c.get("extendedProperties", []):
        value = json.dumps(prop["value"], indent=2)
        lines += ["", f"\t\textendedProperty {prop['name']} ="] + [f"\t\t\t\t{line}" for line in value.split("\n")]
    if c.get("annotations"):
        lines += [""] + _annotations(c, 2)
    return lines


def _measure(m: dict) -> list[str]:
    lines = _doc(m, 1) + [f"\tmeasure {tmdl_name(m['name'])}{_expression(m['expression'], 1)}"]
    return lines + _props(m, _MEASURE_ORDER, 2)


def _partition(p: dict) -> list[str]:
    source = p["source"]
    return [f"\tpartition {tmdl_name(p['name'])} = {source['type']}", f"\t\tmode: {p['mode']}",
            f"\t\tsource{_expression(source['expression'], 2)}"]


def _hierarchy(h: dict) -> list[str]:
    lines = [f"\thierarchy {tmdl_name(h['name'])}", f"\t\tlineageTag: {h['lineageTag']}"]
    for level in h["levels"]:
        lines += ["", f"\t\tlevel {tmdl_name(level['name'])}", f"\t\t\tlineageTag: {level['lineageTag']}",
                  f"\t\t\tcolumn: {tmdl_name(level['column'])}"]
    return lines


def _table(t: dict) -> str:
    blocks = [[f"table {tmdl_name(t['name'])}"] + _props(t, _TABLE_ORDER, 1)]
    blocks += [_measure(m) for m in t.get("measures", [])]
    blocks += [_column(c) for c in t.get("columns", [])]
    blocks += [_hierarchy(h) for h in t.get("hierarchies", [])]
    blocks += [_partition(p) for p in t.get("partitions", [])]
    if t.get("annotations"):
        blocks.append(_annotations(t, 1))
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"


def write_model(model: dict, database: str) -> dict[str, str]:
    """{path under the semantic model folder: text} for the TMDL definition of `model` (the build_model dict)."""
    m = model["model"]
    files = {}
    files["definition/database.tmdl"] = (f"database {tmdl_name(database)}\n"
                                         f"\tcompatibilityLevel: {model['compatibilityLevel']}\n")
    # properties first, nested objects after them: a property after a nested object is an indentation error
    lines = ["model Model", f"\tculture: {m['culture']}",
             f"\tdefaultPowerBIDataSourceVersion: {m['defaultPowerBIDataSourceVersion']}",
             f"\tsourceQueryCulture: {m['sourceQueryCulture']}"]
    if m.get("dataAccessOptions"):
        lines.append("\tdataAccessOptions")
        lines += _props(m["dataAccessOptions"], ["legacyRedirects", "returnErrorValuesAsNull"], 2)
    if m.get("annotations"):
        lines += [""] + _annotations(m, 1)
    lines += [""] + [f"ref table {tmdl_name(t['name'])}" for t in m["tables"]]
    files["definition/model.tmdl"] = "\n".join(lines) + "\n"

    rels = []
    for r in m.get("relationships", []):
        block = [f"relationship {tmdl_name(r['name'])}"]
        if r.get("isActive") is False:
            block.append("\tisActive: false")
        block += [f"\tfromColumn: {tmdl_name(r['fromTable'])}.{tmdl_name(r['fromColumn'])}",
                  f"\ttoColumn: {tmdl_name(r['toTable'])}.{tmdl_name(r['toColumn'])}"]
        rels.append("\n".join(block))
    files["definition/relationships.tmdl"] = "\n\n".join(rels) + "\n"

    exprs = []
    for e in m.get("expressions", []):
        block = [f"expression {tmdl_name(e['name'])}{_expression(e['expression'], 0)}",
                 f"\tlineageTag: {e['lineageTag']}"]
        if e.get("annotations"):
            block += [""] + _annotations(e, 1)
        exprs.append("\n".join(block))
    files["definition/expressions.tmdl"] = "\n\n".join(exprs) + "\n"

    if m.get("functions"):
        funcs = ["\n".join(_doc(f, 0) + [f"function {tmdl_name(f['name'])}{_expression(f['expression'], 0)}"])
                 for f in m["functions"]]
        files["definition/functions.tmdl"] = "\n\n".join(funcs) + "\n"

    for t in m["tables"]:
        files[f"definition/tables/{t['name']}.tmdl"] = _table(t)
    return files


# ----------------------------------------------------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------------------------------------------------

_DECL = re.compile(r"^(?P<kind>[A-Za-z]+)(?:\s+(?P<name>'(?:[^']|'')*'|[^\s=]+))?\s*(?:=\s*(?P<rest>.*))?$")


def _unquote(name: str) -> str:
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def _split_ref(ref: str) -> tuple[str, str]:
    """`table.column` with either part possibly quoted."""
    if ref.startswith("'"):
        end = ref.index("'.", 1)
        return _unquote(ref[:end + 1]), _unquote(ref[end + 2:])
    table, column = ref.split(".", 1)
    return table, _unquote(column)


def _parse_value(key: str, value: str):
    if value in ("true", "false"):
        return value == "true"
    if key == "compatibilityLevel":
        return int(value)
    if key in _REFS:
        return _unquote(value)
    return value


_PROPERTY = re.compile(r"^([A-Za-z]+):\s*(.*)$")


class _Lines:
    def __init__(self, text: str):
        self.lines = text.split("\n")
        self.i = 0

    def peek(self) -> str | None:
        return self.lines[self.i] if self.i < len(self.lines) else None

    def take(self) -> str:
        line = self.lines[self.i]
        self.i += 1
        return line


def _read_expression(rest: str, lines: _Lines, indent: int):
    """The expression after `=`: inline text, or the lines of a triple-backtick block (tabs of the block stripped)."""
    if rest.strip() != "```":
        return rest.strip()
    body = []
    while True:
        line = lines.take()
        if line.strip() == "```":
            break
        body.append(line[indent + 2:] if line.startswith("\t" * (indent + 2)) else line.lstrip("\t"))
    return body


def _read_objects(text: str) -> list[dict]:
    """Parse a TMDL document into nested objects: {kind, name, expression, props, children, doc}."""
    lines = _Lines(text)
    root: list[dict] = []
    stack: list[tuple[int, dict]] = []          # (indent, object)
    doc: list[str] = []
    while (raw := lines.peek()) is not None:
        lines.take()
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip("\t"))
        content = raw.strip()
        if content.startswith("///"):
            doc.append(content[3:].strip())
            continue
        if content.startswith("ref "):           # model.tmdl lists the files of the folder; the folder is read
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None
        prop = _PROPERTY.match(content)
        if prop and parent is not None:                      # `key: value`
            parent["props"][prop.group(1)] = _parse_value(prop.group(1), prop.group(2).strip())
            continue
        match = _DECL.match(content)
        if match is None:
            raise ValueError(f"TMDL: cannot read line {lines.i}: {content!r}")
        kind, name, rest = match.group("kind"), match.group("name"), match.group("rest")
        if kind in ("annotation", "extendedProperty") and rest is not None:
            value = rest.strip()
            if kind == "extendedProperty" and value == "":
                body = []
                while (nxt := lines.peek()) is not None and nxt.startswith("\t" * (indent + 2)):
                    body.append(lines.take()[indent + 2:])
                value = json.loads("\n".join(body))
            parent["props"].setdefault(kind, []).append((_unquote(name), value))
            continue
        if kind == "ref":
            continue
        obj = {"kind": kind, "name": _unquote(name) if name else None, "props": {}, "children": [],
               "expression": _read_expression(rest, lines, indent) if rest is not None else None,
               "doc": " ".join(doc)}
        doc = []
        if name is None and rest is None and kind not in ("dataAccessOptions", "relatedColumnDetails", "database"):
            # a bare boolean property of the parent
            if parent is not None:
                parent["props"][kind] = True
            continue
        (parent["children"] if parent is not None else root).append(obj)
        stack.append((indent, obj))
    return root


def _column_dict(o: dict) -> dict:
    c = {"name": o["name"]}
    props = o["props"]
    if props.get("sourceColumn", "").startswith("["):
        c["type"] = "calculatedTableColumn"
    for key in _COLUMN_ORDER:
        if key in props:
            c[key] = props[key]
    for child in o["children"]:
        if child["kind"] == "relatedColumnDetails":
            c["relatedColumnDetails"] = {"groupByColumns": [{"groupingColumn": _unquote(str(child["props"]["groupByColumn"]))}]}
    if "extendedProperty" in props:
        c["extendedProperties"] = [{"type": "json", "name": n, "value": v} for n, v in props["extendedProperty"]]
    if "annotation" in props:
        c["annotations"] = [{"name": n, "value": v} for n, v in props["annotation"]]
    if o["doc"]:
        c["description"] = o["doc"]
    return c


def _table_dict(o: dict) -> dict:
    t = {"name": o["name"]}
    for key in _TABLE_ORDER:
        if key in o["props"]:
            t[key] = o["props"][key]
    columns, measures, partitions, hierarchies = [], [], [], []
    for child in o["children"]:
        if child["kind"] == "column":
            columns.append(_column_dict(child))
        elif child["kind"] == "measure":
            m = {"name": child["name"], "expression": child["expression"]}
            for key in _MEASURE_ORDER:
                if key in child["props"]:
                    m[key] = child["props"][key]
            if child["doc"]:
                m["description"] = child["doc"]
            measures.append(m)
        elif child["kind"] == "partition":
            source_type = child["expression"]        # `partition X = m` : the type sits after the =
            source = next(s for s in child["children"] if s["kind"] == "source")
            partitions.append({"name": child["name"], "mode": child["props"]["mode"],
                               "source": {"type": source_type, "expression": source["expression"]}})
        elif child["kind"] == "hierarchy":
            levels = [{"name": lvl["name"], "ordinal": k, "column": _unquote(str(lvl["props"]["column"])),
                       "lineageTag": lvl["props"]["lineageTag"]}
                      for k, lvl in enumerate(c for c in child["children"] if c["kind"] == "level")]
            hierarchies.append({"name": child["name"], "lineageTag": child["props"]["lineageTag"], "levels": levels})
    t["columns"] = columns
    if measures:
        t["measures"] = measures
    t["partitions"] = partitions
    if hierarchies:
        t["hierarchies"] = hierarchies
    if "annotation" in o["props"]:
        t["annotations"] = [{"name": n, "value": v} for n, v in o["props"]["annotation"]]
    return t


def read_model(definition: pathlib.Path) -> dict:
    """The model dictionary (build_model's shape) of a TMDL `definition` folder."""
    database = _read_objects((definition / "database.tmdl").read_text(encoding="utf-8"))[0]
    model_obj = _read_objects((definition / "model.tmdl").read_text(encoding="utf-8"))[0]
    props = model_obj["props"]
    m: dict = {"culture": props.get("culture")}
    for child in model_obj["children"]:
        if child["kind"] == "dataAccessOptions":
            m["dataAccessOptions"] = dict(child["props"])
    m["defaultPowerBIDataSourceVersion"] = props.get("defaultPowerBIDataSourceVersion")
    m["sourceQueryCulture"] = props.get("sourceQueryCulture")
    by_name = {}
    for path in sorted((definition / "tables").glob("*.tmdl")):
        for o in _read_objects(path.read_text(encoding="utf-8")):
            if o["kind"] == "table":
                by_name[o["name"]] = _table_dict(o)
    # in the order of model.tmdl's `ref table` lines, which is the order the model was built in
    refs = [_unquote(line.strip()[len("ref table "):]) for line in
            (definition / "model.tmdl").read_text(encoding="utf-8").split("\n") if line.strip().startswith("ref table ")]
    m["tables"] = [by_name[n] for n in refs if n in by_name] + [t for n, t in by_name.items() if n not in refs]
    relationships = []
    rel_file = definition / "relationships.tmdl"
    if rel_file.exists():
        for o in _read_objects(rel_file.read_text(encoding="utf-8")):
            rel = {"name": o["name"]}
            if o["props"].get("isActive") is False:
                rel["isActive"] = False
            ft, fc = _split_ref(str(o["props"]["fromColumn"]))
            tt, tc = _split_ref(str(o["props"]["toColumn"]))
            rel.update({"fromTable": ft, "fromColumn": fc, "toTable": tt, "toColumn": tc})
            relationships.append(rel)
    m["relationships"] = relationships
    expressions = []
    expr_file = definition / "expressions.tmdl"
    if expr_file.exists():
        for o in _read_objects(expr_file.read_text(encoding="utf-8")):
            e = {"name": o["name"], "kind": "m", "expression": o["expression"], "lineageTag": o["props"].get("lineageTag")}
            if "annotation" in o["props"]:
                e["annotations"] = [{"name": n, "value": v} for n, v in o["props"]["annotation"]]
            expressions.append(e)
    m["expressions"] = expressions
    func_file = definition / "functions.tmdl"
    if func_file.exists():
        m["functions"] = [{"name": o["name"], "expression": o["expression"], **({"description": o["doc"]} if o["doc"] else {})}
                          for o in _read_objects(func_file.read_text(encoding="utf-8")) if o["kind"] == "function"]
    if "annotation" in props:
        m["annotations"] = [{"name": n, "value": v} for n, v in props["annotation"]]
    return {"compatibilityLevel": int(database["props"]["compatibilityLevel"]), "model": m}
