"""Paginated report (RDL) on the published semantic model: the reconciliation certificate.

`build_rdl` returns the text of `powerbi/DOP_reconciliation_certificate.rdl`, a print-ready A4 landscape report
for Power BI paginated reports (Report Builder format, RDL 2016). It reads the published DOP semantic model with
DAX: a data-date parameter (every update, the latest by default), the headline measures of that update and the
forty reconciliation controls with their source, model and dashboard values. It is the document a controls
manager signs: one page per update, the same every time, exportable to PDF, Word or Excel and deliverable by
subscription.

The data source names the model by its workspace and dataset ids in the Power BI service (`SERVICE` below); to
point the report at another copy of the model, change those two ids and regenerate.
"""
from __future__ import annotations

import uuid
from xml.sax.saxutils import escape

SERVICE = {
    "tenant_id": "cecdb5e6-c0f4-4323-9c08-e9b2d442dd15",
    "workspace": "DOP Schedule Intelligence",
    "dataset": "DOP",
    "dataset_id": "bfce9993-96be-4e91-9bf8-ea8eb16695cc",
}
RDL_NAME = "DOP_reconciliation_certificate.rdl"

NAVY, TEAL, TEXT, MUTED, RULE, TINT = "#1F3A5F", "#2B7A78", "#1A202C", "#4A5568", "#E2E8F0", "#F2F4F7"
GREEN, RED = "#1A6E3C", "#A93226"
FONT = "Segoe UI"
PAGE_W, PAGE_H, MARGIN = 29.7, 21.0, 1.5
BODY_W = PAGE_W - 2 * MARGIN

# (field, header, width cm, align, font)
COLUMNS = [
    ("control_id", "ID", 3.4, "Left", FONT),
    ("control", "Control", 6.8, "Left", FONT),
    ("source_value", "Source XER", 5.0, "Left", "Consolas"),
    ("model_value", "Model", 5.0, "Left", "Consolas"),
    ("dashboard_value", "Dashboard", 5.0, "Left", "Consolas"),
    ("result", "Result", 1.5, "Center", FONT),
]
assert abs(sum(c[2] for c in COLUMNS) - BODY_W) < 1e-6

DAX_UPDATES = """EVALUATE
SELECTCOLUMNS (
    dim_snapshot,
    "snapshot_id", dim_snapshot[snapshot_id],
    "label", FORMAT ( dim_snapshot[data_date], "dd-MMM-yyyy" ) & "  (" & dim_snapshot[label] & ")"
)
ORDER BY [snapshot_id] DESC"""

DAX_LATEST = """EVALUATE
ROW ( "snapshot_id", MAXX ( ALL ( dim_snapshot ), dim_snapshot[snapshot_id] ) )"""

DAX_HEADER = """EVALUATE
CALCULATETABLE (
    ROW (
        "data_date", FORMAT ( [Data date], "dd-MMM-yyyy" ),
        "baseline", [Baseline in force],
        "source_file", [Source file],
        "day1_forecast", FORMAT ( [Day 1 forecast], "dd-MMM-yyyy" ),
        "day1_float", [Day 1 total float],
        "dq_score", [DQ score],
        "controls_passed", [Controls passed],
        "controls_total", [Controls total]
    ),
    dim_snapshot[snapshot_id] = VALUE ( @Snapshot )
)"""

DAX_CONTROLS = """EVALUATE
SELECTCOLUMNS (
    FILTER ( fact_reconciliation, fact_reconciliation[snapshot_id] = VALUE ( @Snapshot ) ),
    "control_id", fact_reconciliation[control_id],
    "control", fact_reconciliation[control],
    "source_value", fact_reconciliation[source_value],
    "model_value", fact_reconciliation[model_value],
    "dashboard_value", fact_reconciliation[dashboard_value],
    "result", IF ( fact_reconciliation[passed], "Pass", "Fail" )
)
ORDER BY [control_id]"""

HEADER_FIELDS = ["data_date", "baseline", "source_file", "day1_forecast", "day1_float", "dq_score",
                 "controls_passed", "controls_total"]


def _cm(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") + "cm"


def _textbox(name: str, value: str, *, size: float = 8, colour: str = TEXT, bold: bool = False,
             align: str = "Left", font: str = FONT, background: str | None = None, bottom_rule: str | None = None,
             box: tuple[float, float, float, float] | None = None, valign: str = "Middle", pad: float = 4) -> str:
    """A text box; `value` is literal text or an expression starting with `=`. `box` = (top, left, height, width)
    in cm for a free-standing box, None inside a tablix cell."""
    style = [f"<Border><Style>None</Style></Border>"]
    if bottom_rule:
        style.append(f"<BottomBorder><Color>{bottom_rule}</Color><Style>Solid</Style><Width>0.75pt</Width></BottomBorder>")
    if background:
        style.append(f"<BackgroundColor>{background}</BackgroundColor>")
    style.append(f"<VerticalAlign>{valign}</VerticalAlign>")
    style += [f"<Padding{side}>{pad}pt</Padding{side}>" for side in ("Left", "Right")]
    style += [f"<Padding{side}>2pt</Padding{side}>" for side in ("Top", "Bottom")]
    place = ""
    if box:
        top, left, height, width = box
        place = f"<Top>{_cm(top)}</Top><Left>{_cm(left)}</Left><Height>{_cm(height)}</Height><Width>{_cm(width)}</Width>"
    weight = "<FontWeight>SemiBold</FontWeight>" if bold else ""
    return (f'<Textbox Name="{name}"><CanGrow>true</CanGrow><KeepTogether>true</KeepTogether><Paragraphs><Paragraph>'
            f"<TextRuns><TextRun><Value>{escape(value)}</Value><Style><FontFamily>{font}</FontFamily>"
            f"<FontSize>{size:g}pt</FontSize>{weight}<Color>{colour}</Color></Style></TextRun></TextRuns>"
            f"<Style><TextAlign>{align}</TextAlign></Style></Paragraph></Paragraphs>"
            f"<rd:DefaultName>{name}</rd:DefaultName>{place}<Style>{''.join(style)}</Style></Textbox>")


def _dataset(name: str, dax: str, fields: list[str], parameter: bool) -> str:
    params = ('<QueryParameters><QueryParameter Name="Snapshot"><Value>=Parameters!Snapshot.Value</Value>'
              "</QueryParameter></QueryParameters>") if parameter else ""
    field_xml = "".join(f'<Field Name="{f}"><DataField>[{f}]</DataField></Field>' for f in fields)
    return (f'<DataSet Name="{name}"><Query><DataSourceName>DOP</DataSourceName>{params}'
            f"<CommandText>{escape(dax)}</CommandText></Query><Fields>{field_xml}</Fields></DataSet>")


def _tablix(top: float) -> str:
    header_cells, detail_cells = [], []
    for field, header, _, align, font in COLUMNS:
        header_cells.append("<TablixCell><CellContents>" + _textbox(
            f"h_{field}", header, size=8, colour="#FFFFFF", bold=True, align=align, background=NAVY) +
            "</CellContents></TablixCell>")
        if field == "result":
            value, colour, bold = "=Fields!result.Value", f'=IIF(Fields!result.Value = "Pass", "{GREEN}", "{RED}")', True
        else:
            value, colour, bold = f"=Fields!{field}.Value", TEXT, False
        size = 7 if font == "Consolas" else 8
        detail_cells.append("<TablixCell><CellContents>" + _textbox(
            f"d_{field}", value, size=size, colour=colour, bold=bold, align=align, font=font, bottom_rule=RULE,
            background=f'=IIF(RowNumber(Nothing) Mod 2 = 0, "{TINT}", "#FFFFFF")', valign="Top") +
            "</CellContents></TablixCell>")
    columns = "".join(f"<TablixColumn><Width>{_cm(c[2])}</Width></TablixColumn>" for c in COLUMNS)
    members = "<TablixMember />" * len(COLUMNS)
    return (f'<Tablix Name="ControlsTable"><TablixBody><TablixColumns>{columns}</TablixColumns><TablixRows>'
            f"<TablixRow><Height>0.65cm</Height><TablixCells>{''.join(header_cells)}</TablixCells></TablixRow>"
            f"<TablixRow><Height>0.55cm</Height><TablixCells>{''.join(detail_cells)}</TablixCells></TablixRow>"
            f"</TablixRows></TablixBody><TablixColumnHierarchy><TablixMembers>{members}</TablixMembers>"
            "</TablixColumnHierarchy><TablixRowHierarchy><TablixMembers>"
            "<TablixMember><KeepWithGroup>After</KeepWithGroup><RepeatOnNewPage>true</RepeatOnNewPage></TablixMember>"
            '<TablixMember><Group Name="Details" /></TablixMember></TablixMembers></TablixRowHierarchy>'
            "<RepeatColumnHeaders>true</RepeatColumnHeaders><DataSetName>Controls</DataSetName>"
            f"<Top>{_cm(top)}</Top><Left>0cm</Left><Height>1.2cm</Height><Width>{_cm(BODY_W)}</Width>"
            "<Style><Border><Style>None</Style></Border></Style></Tablix>")


def build_rdl() -> str:
    first = lambda f: f'First(Fields!{f}.Value, "Header")'
    all_pass = f"{first('controls_passed')} = {first('controls_total')}"
    kpis = [
        ("Data date", f"={first('data_date')}", f'="Baseline in force " & {first("baseline")}'),
        ("Day 1 forecast", f"={first('day1_forecast')}",
         f'="Total float " & Format({first("day1_float")}, "+0;-0;0") & " working days"'),
        ("Schedule quality", f'=Format({first("dq_score")}, "0.0") & " / 100"', "DCMA 14-point and update discipline"),
        ("Controls passed", f'={first("controls_passed")} & " of " & {first("controls_total")}',
         f'=IIF({all_pass}, "Reconciled: publication allowed", "Not reconciled: publication blocked")'),
    ]
    items = [
        _textbox("Eyebrow", "RECONCILIATION CERTIFICATE", size=8, colour=TEAL, bold=True, box=(0, 0, 0.5, BODY_W), pad=0),
        _textbox("Statement",
                 f'=IIF({all_pass}, "Every published number reconciles to the source P6 schedule at " & '
                 f'{first("data_date")} & ".", "The outputs do not reconcile to the source P6 schedule at " & '
                 f'{first("data_date")} & ".")',
                 size=14, colour=NAVY, bold=True, box=(0.5, 0, 0.9, BODY_W), pad=0),
        _textbox("Scope", f'="Dashboard, Power BI report and packs. Source file " & {first("source_file")} & ". Each control compares the value read from '
                 'the XER export, the value in the star-schema model and the value the dashboard shows; a control '
                 'passes only when all three agree."', size=8.5, colour=MUTED, box=(1.4, 0, 0.6, BODY_W), pad=0),
    ]
    tile_w, gap, top = (BODY_W - 3 * 0.4) / 4, 0.4, 2.3
    for k, (label, value, caption) in enumerate(kpis):
        left = k * (tile_w + gap)
        colour = f'=IIF({all_pass}, "{GREEN}", "{RED}")' if label == "Controls passed" else NAVY
        items += [
            _textbox(f"Kpi{k}Label", label.upper(), size=7, colour=MUTED, bold=True, background=TINT,
                     box=(top, left, 0.5, tile_w), pad=8),
            _textbox(f"Kpi{k}Value", value, size=15, colour=colour, bold=True, background=TINT,
                     box=(top + 0.5, left, 0.9, tile_w), pad=8),
            _textbox(f"Kpi{k}Caption", caption, size=7.5, colour=MUTED, background=TINT,
                     box=(top + 1.4, left, 0.55, tile_w), pad=8),
        ]
    table_top = top + 2.35
    items.append(_tablix(table_top))

    header = (f"<PageHeader><Height>1cm</Height><PrintOnFirstPage>true</PrintOnFirstPage>"
              f"<PrintOnLastPage>true</PrintOnLastPage><ReportItems>"
              + _textbox("HeaderLeft", "Destination Opening Programme  |  Schedule intelligence", size=8, colour=NAVY,
                         bold=True, bottom_rule=NAVY, box=(0, 0, 0.7, BODY_W / 2), pad=0)
              + _textbox("HeaderRight", "Fictional programme, fictional data", size=8, colour=MUTED, align="Right",
                         bottom_rule=NAVY, box=(0, BODY_W / 2, 0.7, BODY_W / 2), pad=0)
              + "</ReportItems></PageHeader>")
    footer = (f"<PageFooter><Height>0.8cm</Height><PrintOnFirstPage>true</PrintOnFirstPage>"
              f"<PrintOnLastPage>true</PrintOnLastPage><ReportItems>"
              + _textbox("FooterLeft", '="Generated " & Format(Globals!ExecutionTime, "dd-MMM-yyyy HH:mm") & '
                         '" from the published DOP semantic model"', size=7, colour=MUTED,
                         box=(0.2, 0, 0.5, BODY_W * 0.7), pad=0)
              + _textbox("FooterRight", '="Page " & Globals!PageNumber & " of " & Globals!TotalPages', size=7,
                         colour=MUTED, align="Right", box=(0.2, BODY_W * 0.7, 0.5, BODY_W * 0.3), pad=0)
              + "</ReportItems></PageFooter>")

    connect = (f'Data Source=pbiazure://api.powerbi.com/;Identity Provider="https://login.microsoftonline.com/'
               f'organizations, https://analysis.windows.net/powerbi/api, {SERVICE["tenant_id"]}";'
               f'Initial Catalog=sobe_wowvirtualserver-{SERVICE["dataset_id"]};Integrated Security=ClaimsToken')
    report_id = uuid.uuid5(uuid.NAMESPACE_URL, "dop/rdl/reconciliation-certificate")
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" '
        'xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">',
        "<AutoRefresh>0</AutoRefresh>",
        "<Description>Reconciliation certificate: the forty controls of a data date, source XER against model "
        "against dashboard.</Description>",
        '<DataSources><DataSource Name="DOP"><rd:SecurityType>None</rd:SecurityType><ConnectionProperties>'
        f"<DataProvider>PBIDATASET</DataProvider><ConnectString>{escape(connect)}</ConnectString>"
        "</ConnectionProperties><rd:DataSourceID>" + str(uuid.uuid5(uuid.NAMESPACE_URL, "dop/rdl/datasource")) +
        f"</rd:DataSourceID><rd:PowerBIWorkspaceName>{escape(SERVICE['workspace'])}</rd:PowerBIWorkspaceName>"
        f"<rd:PowerBIDatasetName>{escape(SERVICE['dataset'])}</rd:PowerBIDatasetName></DataSource></DataSources>",
        "<DataSets>",
        _dataset("Updates", DAX_UPDATES, ["snapshot_id", "label"], False),
        _dataset("Latest", DAX_LATEST, ["snapshot_id"], False),
        _dataset("Header", DAX_HEADER, HEADER_FIELDS, True),
        _dataset("Controls", DAX_CONTROLS, [c[0] for c in COLUMNS], True),
        "</DataSets>",
        '<ReportParameters><ReportParameter Name="Snapshot"><DataType>Integer</DataType><DefaultValue>'
        "<DataSetReference><DataSetName>Latest</DataSetName><ValueField>snapshot_id</ValueField></DataSetReference>"
        "</DefaultValue><Prompt>Data date</Prompt><ValidValues><DataSetReference><DataSetName>Updates</DataSetName>"
        "<ValueField>snapshot_id</ValueField><LabelField>label</LabelField></DataSetReference></ValidValues>"
        "</ReportParameter></ReportParameters>",
        "<ReportParametersLayout><GridLayoutDefinition><NumberOfColumns>4</NumberOfColumns><NumberOfRows>1"
        "</NumberOfRows><CellDefinitions><CellDefinition><ColumnIndex>0</ColumnIndex><RowIndex>0</RowIndex>"
        "<ParameterName>Snapshot</ParameterName></CellDefinition></CellDefinitions></GridLayoutDefinition>"
        "</ReportParametersLayout>",
        f"<ReportSections><ReportSection><Body><ReportItems>{''.join(items)}</ReportItems>"
        f"<Height>{_cm(table_top + 1.2)}</Height><Style /></Body><Width>{_cm(BODY_W)}</Width><Page>{header}{footer}"
        f"<PageHeight>{_cm(PAGE_H)}</PageHeight><PageWidth>{_cm(PAGE_W)}</PageWidth>"
        + "".join(f"<{side}Margin>{_cm(MARGIN)}</{side}Margin>" for side in ("Left", "Right", "Top", "Bottom"))
        + "<ColumnSpacing>0.13cm</ColumnSpacing><Style /></Page></ReportSection></ReportSections>",
        "<Language>en-GB</Language><rd:ReportUnitType>Cm</rd:ReportUnitType>"
        f"<rd:ReportID>{report_id}</rd:ReportID>",
        "</Report>",
    ]
    return "\n".join(parts) + "\n"
