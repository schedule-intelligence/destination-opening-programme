"""The paginated report (dop/rdl.py): well-formed RDL that asks the model only for things the model has."""
import pathlib
import re
import xml.etree.ElementTree as ET

from dop import rdl, tmdl

ROOT = pathlib.Path(__file__).resolve().parents[1]
NS = {"r": "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"}


def _root():
    return ET.fromstring(rdl.build_rdl())


def test_committed_rdl_is_the_generated_one():
    committed = (ROOT / "powerbi" / rdl.RDL_NAME).read_text(encoding="utf-8")
    assert committed == rdl.build_rdl()


def test_names_are_unique_across_datasets_regions_and_items():
    root = _root()
    names = [e.get("Name") for e in root.iter() if e.get("Name") and not e.tag.endswith(("Field", "QueryParameter",
                                                                                         "ReportParameter"))]
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)


def test_every_dataset_field_is_returned_by_its_query_and_used_fields_exist():
    root = _root()
    fields = {}
    for ds in root.findall(".//r:DataSet", NS):
        dax = ds.find("r:Query/r:CommandText", NS).text
        names = [f.get("Name") for f in ds.findall("r:Fields/r:Field", NS)]
        for name in names:
            assert f'"{name}"' in dax, (ds.get("Name"), name)
        fields[ds.get("Name")] = set(names)
    text = rdl.build_rdl()
    for field in re.findall(r"Fields!(\w+)\.Value", text):
        assert any(field in f for f in fields.values()), field
    assert set(re.findall(r'First\(Fields!\w+\.Value, &quot;(\w+)&quot;\)', text)) <= set(fields)


def test_queries_use_only_measures_and_columns_of_the_model():
    model = tmdl.read_model(ROOT / "powerbi" / "DOP.SemanticModel" / "definition")["model"]
    columns = {(t["name"], c["name"]) for t in model["tables"] for c in t["columns"]}
    measures = {m["name"] for t in model["tables"] for m in t.get("measures", [])}
    for dax in (rdl.DAX_UPDATES, rdl.DAX_LATEST, rdl.DAX_HEADER, rdl.DAX_CONTROLS):
        for table, column in re.findall(r"\b(dim_\w+|fact_\w+)\[([^\]]+)\]", dax):
            assert (table, column) in columns, (table, column)
        aliases = set(re.findall(r'"(\w+)",', dax))
        for name in re.findall(r"(?<![\w'])\[([^\]]+)\]", dax):
            assert name in measures or name in aliases, name


def test_table_fills_the_page_width_and_the_page_is_a4_landscape():
    root = _root()
    widths = [float(w.text[:-2]) for w in root.findall(".//r:TablixColumn/r:Width", NS)]
    assert abs(sum(widths) - rdl.BODY_W) < 1e-6
    page = root.find(".//r:Page", NS)
    assert page.find("r:PageWidth", NS).text == "29.7cm" and page.find("r:PageHeight", NS).text == "21cm"
