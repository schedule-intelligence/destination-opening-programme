"""Fictional Destination Opening Programme (DOP): structure, activities and logic.

Everything here is invented. The programme contains four venue assets built from a common template
with asset-specific specialist systems, programme enabling works (utilities and transport) and a
programme-integration node that holds the readiness gates and the Day 1 Opening milestone.
"""
from __future__ import annotations

import datetime as dt

PROGRAMME = {"code": "DOP", "name": "Destination Opening Programme", "project": "DOP-IMS",
             "eps": "DOP", "eps_name": "Destination Opening Programme"}
DAY1_TARGET = dt.date(2027, 10, 14)
NTP_DATE = dt.date(2025, 3, 1)
DAY1_ID = "PRG-D1R-M999"

ASSETS = {
    "MTP": "Mesa Theme Park",
    "LWP": "Lagoon Water Park",
    "DAR": "Dune Arena",
    "PBR": "Palm Boulevard (Retail & Dining)",
    "PEW": "Programme Enabling Works",
    "PRG": "Programme Integration & Day 1",
}
VENUES = ["MTP", "LWP", "DAR", "PBR"]

WORKSTREAMS = {
    "CON": "Construction",
    "TNC": "Testing & Commissioning",
    "HOV": "Handover",
    "OPM": "Operator Mobilisation & Training",
    "OTE": "Operational Trials & Test Events",
    "D1R": "Day 1 Readiness",
}
PHASE_BY_WS = {"CON": "P1 Build", "TNC": "P2 Commission", "HOV": "P3 Handover",
               "OPM": "P4 Prepare to Operate", "OTE": "P4 Prepare to Operate", "D1R": "P5 Open"}
PHASES = {"P1 Build": "Build", "P2 Commission": "Commission", "P3 Handover": "Handover",
          "P4 Prepare to Operate": "Prepare to operate", "P5 Open": "Open"}

OWNERS = {
    "MWC": "Main Works Contractor",
    "MEP": "MEP & Systems Contractor",
    "ICA": "Independent Commissioning Authority",
    "OPR": "Destination Operator",
    "PMO": "Programme Management Office",
    "AAT": "Authority Approvals Team",
    "FMS": "Facilities Management",
    "SSY": "Security & Safety",
}
OWNER_LEADS = {  # accountable role per owner (no personal names)
    "MWC": "MWC Project Director", "MEP": "MEP Package Manager", "ICA": "Lead Commissioning Manager",
    "OPR": "Operator Readiness Lead", "PMO": "Programme Controls Manager", "AAT": "Approvals Manager",
    "FMS": "FM Mobilisation Manager", "SSY": "Head of Security & Safety",
}

PACKAGES = {
    "STR": "Structure & Envelope", "MEP": "MEP Installation", "FIT": "Fit-out & Finishes",
    "SYS": "Specialist Systems", "EXT": "External Works", "MGT": "Management & Supervision",
    "PRE": "Pre-commissioning", "COM": "Systems Commissioning", "IST": "Integrated Systems Testing",
    "SNG": "Snagging & Defects", "APR": "Authority Inspections & Approvals", "HND": "Completion & Handover",
    "RCT": "Recruitment & Onboarding", "TRN": "Training & Familiarisation", "TRL": "Operational Trials",
    "TEV": "Test Events", "GAT": "Readiness Gates",
    "PWR": "Power", "CLG": "District Cooling", "WAT": "Water & Drainage", "RDS": "Roads",
    "TRS": "Transit", "ICT": "Telecom & ICT",
}

GATES = {"RG1": "RG1 Construction complete", "RG2": "RG2 T&C complete", "RG3": "RG3 Ready to operate",
         "RG4": "RG4 Day 1 go/no-go"}

SITE, OFFICE, SEVEN = 1, 2, 3

# ----------------------------------------------------------------------------- venue template
# suffix: (name, ws, pkg, dur_days, cal, type, owner, gate)
T, M, F, L = "TT_Task", "TT_Mile", "TT_FinMile", "TT_LOE"
VENUE_TEMPLATE = {
    "CON-1010": ("Substructure & foundations", "CON", "STR", 40, SITE, T, "MWC", ""),
    "CON-1020": ("Superstructure frame", "CON", "STR", 44, SITE, T, "MWC", ""),
    "CON-1030": ("Roof structure & roofing", "CON", "STR", 40, SITE, T, "MWC", ""),
    "CON-1040": ("Building envelope & facade", "CON", "STR", 44, SITE, T, "MWC", ""),
    "CON-1050": ("Internal partitions & ceilings", "CON", "FIT", 35, SITE, T, "MWC", ""),
    "CON-1105": ("Long-lead MEP plant procurement & delivery", "CON", "MEP", 44, SITE, T, "MEP", ""),
    "CON-1110": ("MEP first fix - lower levels", "CON", "MEP", 44, SITE, T, "MEP", ""),
    "CON-1112": ("MEP first fix - upper levels & roof plant", "CON", "MEP", 40, SITE, T, "MEP", ""),
    "CON-1120": ("Main plant installation (chillers, switchgear, AHUs)", "CON", "MEP", 35, SITE, T, "MEP", ""),
    "CON-1131": ("MEP second fix - Zone A", "CON", "MEP", 40, SITE, T, "MEP", ""),
    "CON-1132": ("MEP second fix - Zone B", "CON", "MEP", 40, SITE, T, "MEP", ""),
    "CON-1135": ("MEP second fix - Zone C (BOH & plant rooms)", "CON", "MEP", 35, SITE, T, "MEP", ""),
    "CON-1140": ("BMS & ELV installation", "CON", "MEP", 35, SITE, T, "MEP", ""),
    "CON-1150": ("Vertical transportation installation", "CON", "MEP", 35, SITE, T, "MEP", ""),
    "CON-1210": ("Back-of-house fit-out", "CON", "FIT", 40, SITE, T, "MWC", ""),
    "CON-1220": ("Front-of-house fit-out & finishes", "CON", "FIT", 44, SITE, T, "MWC", ""),
    "CON-1225": ("FOH final finishes & joinery", "CON", "FIT", 40, SITE, T, "MWC", ""),
    "CON-1230": ("Signage & wayfinding", "CON", "FIT", 20, SITE, T, "MWC", ""),
    "CON-1310": ("{sys1}", "CON", "SYS", 44, SITE, T, "MEP", ""),
    "CON-1320": ("{sys2}", "CON", "SYS", 40, SITE, T, "MEP", ""),
    "CON-1330": ("{sys3}", "CON", "SYS", 40, SITE, T, "MWC", ""),
    "CON-1340": ("{sys4}", "CON", "SYS", 30, SITE, T, "MEP", ""),
    "CON-1410": ("External works & landscaping", "CON", "EXT", 40, SITE, T, "MWC", ""),
    "CON-1430": ("Car parks & drop-off", "CON", "EXT", 30, SITE, T, "MWC", ""),
    "CON-M142": ("Ready for commissioning (construction complete)", "CON", "EXT", 0, SITE, F, "MWC", "RG1"),
    "CON-9010": ("Construction supervision & site management (LOE)", "CON", "MGT", 0, SITE, L, "PMO", ""),
    "TNC-2010": ("Pre-commissioning checks (electrical & mechanical)", "TNC", "PRE", 20, SEVEN, T, "MEP", ""),
    "TNC-2110": ("HVAC & chilled water commissioning", "TNC", "COM", 25, SEVEN, T, "MEP", ""),
    "TNC-2120": ("Electrical systems commissioning", "TNC", "COM", 20, SEVEN, T, "MEP", ""),
    "TNC-2130": ("Fire & life safety systems commissioning", "TNC", "COM", 25, SEVEN, T, "MEP", ""),
    "TNC-2140": ("{com1}", "TNC", "COM", 35, SEVEN, T, "MEP", ""),
    "TNC-2145": ("{com2}", "TNC", "COM", 20, SEVEN, T, "ICA", ""),
    "TNC-2150": ("BMS & ELV commissioning", "TNC", "COM", 20, SEVEN, T, "MEP", ""),
    "TNC-2160": ("Vertical transportation testing & certification", "TNC", "COM", 10, SEVEN, T, "MEP", ""),
    "TNC-2170": ("Security systems (CCTV, access control) commissioning", "TNC", "COM", 15, SEVEN, T, "SSY", ""),
    "TNC-2210": ("Integrated systems test (IST)", "TNC", "IST", 15, SEVEN, T, "ICA", ""),
    "TNC-M220": ("T&C complete (ICA certificate)", "TNC", "IST", 0, SEVEN, F, "ICA", "RG2"),
    "HOV-3010": ("Snagging & defects rectification", "HOV", "SNG", 30, SITE, T, "MWC", ""),
    "HOV-3110": ("Civil defence & fire authority inspection", "HOV", "APR", 15, OFFICE, T, "AAT", ""),
    "HOV-3120": ("Completion certificate application & review", "HOV", "APR", 20, OFFICE, T, "AAT", ""),
    "HOV-M130": ("Occupancy certificate issued", "HOV", "APR", 0, OFFICE, F, "AAT", ""),
    "HOV-3210": ("Handover documentation (O&M, as-builts, warranties)", "HOV", "HND", 25, OFFICE, T, "MWC", ""),
    "HOV-3220": ("Defects walkdown with operator", "HOV", "HND", 5, SITE, T, "OPR", ""),
    "HOV-M230": ("Handover to operator", "HOV", "HND", 0, SITE, F, "PMO", "RG3"),
    "OPM-4010": ("Recruitment wave 1 (leadership & technical)", "OPM", "RCT", 40, OFFICE, T, "OPR", ""),
    "OPM-4015": ("Recruitment wave 2 (front-line staff)", "OPM", "RCT", 40, OFFICE, T, "OPR", ""),
    "OPM-4020": ("Onboarding & induction", "OPM", "RCT", 20, OFFICE, T, "OPR", ""),
    "OPM-4030": ("Uniforms, IT & systems provisioning", "OPM", "RCT", 30, OFFICE, T, "FMS", ""),
    "OPM-4110": ("Classroom & simulator training", "OPM", "TRN", 30, OFFICE, T, "OPR", ""),
    "OPM-M120": ("Operator site access granted", "OPM", "TRN", 0, SITE, M, "SSY", ""),
    "OPM-4130": ("On-site familiarisation & equipment training", "OPM", "TRN", 30, SEVEN, T, "OPR", ""),
    "OPM-4140": ("SOPs & emergency procedures validated", "OPM", "TRN", 20, OFFICE, T, "SSY", ""),
    "OPM-M150": ("Operator trained & certified", "OPM", "TRN", 0, OFFICE, F, "OPR", "RG3"),
    "OTE-5010": ("Operational trials (technical rehearsals)", "OTE", "TRL", 20, SEVEN, T, "OPR", ""),
    "OTE-5020": ("Emergency drills with civil defence", "OTE", "TRL", 5, SEVEN, T, "SSY", ""),
    "OTE-5030": ("Ticketing & POS systems trial", "OTE", "TRL", 7, SEVEN, T, "OPR", ""),
    "OTE-5110": ("Test events (invited guests)", "OTE", "TEV", 14, SEVEN, T, "OPR", ""),
    "D1R-6010": ("Operational readiness assessment", "D1R", "GAT", 7, OFFICE, T, "PMO", ""),
    "D1R-M020": ("Asset Day 1 ready", "D1R", "GAT", 0, SEVEN, F, "PMO", "RG4"),
}

# suffix pred -> suffix succ, type, lag_days
VENUE_LOGIC = [
    ("CON-1010", "CON-1020", "FS", 0), ("CON-1020", "CON-1030", "FS", 0), ("CON-1020", "CON-1040", "FS", 0),
    ("CON-1030", "CON-1050", "FS", 0), ("CON-1040", "CON-1050", "FS", 0),
    ("CON-1020", "CON-1110", "FS", 0), ("CON-1105", "CON-1120", "FS", 0), ("CON-1030", "CON-1120", "FS", 0),
    ("CON-1110", "CON-1112", "FS", 0), ("CON-1112", "CON-1131", "FS", 0), ("CON-1120", "CON-1131", "FS", 0), ("CON-1050", "CON-1131", "FS", 0),
    ("CON-1131", "CON-1132", "FS", 0), ("CON-1132", "CON-1135", "SS", 15), ("CON-1135", "CON-M142", "FS", 0),
    ("CON-1131", "CON-1140", "FS", 0), ("CON-1120", "CON-1140", "FS", 0),
    ("CON-1132", "CON-1150", "FS", 0),
    ("CON-1132", "CON-1210", "FS", 0), ("CON-1132", "CON-1220", "FS", 0), ("CON-1220", "CON-1225", "FS", 0), ("CON-1225", "CON-1230", "FS", 0),
    ("SYS_PRED", "CON-1310", "FS", 0), ("CON-1310", "CON-1320", "FS", 0), ("CON-1320", "CON-1330", "FS", 0),
    ("CON-1040", "CON-1410", "FS", 0), ("CON-1220", "CON-1410", "FS", 0), ("CON-1010", "CON-1430", "FS", 0), ("CON-1410", "CON-1430", "FF", 0),
    ("CON-1140", "CON-M142", "FS", 0), ("CON-1150", "CON-M142", "FS", 0), ("CON-1210", "CON-M142", "FS", 0),
    ("CON-1230", "CON-M142", "FS", 0), ("CON-1330", "CON-1340", "FS", 0), ("CON-1340", "CON-M142", "FS", 0), ("CON-1430", "CON-M142", "FS", 0),
    ("CON-1010", "CON-9010", "SS", 0), ("CON-M142", "CON-9010", "FF", 0),
    # T&C
    ("CON-1132", "TNC-2010", "FS", 0), ("CON-1135", "TNC-2010", "FS", 0), ("CON-1140", "TNC-2010", "FS", 0),
    ("CON-1220", "TNC-2010", "FS", 0), ("CON-1210", "TNC-2010", "FS", 0), ("CON-1150", "CON-1225", "FS", 0),
    ("TNC-2010", "TNC-2110", "FS", 0), ("TNC-2010", "TNC-2120", "FS", 0), ("TNC-2120", "TNC-2130", "FS", 0),
    ("CON-1340", "TNC-2140", "FS", 0), ("TNC-2120", "TNC-2140", "FS", 0), ("TNC-2140", "TNC-2145", "FS", 0),
    ("TNC-2110", "TNC-2150", "FS", 0), ("CON-1150", "TNC-2160", "FS", 0), ("TNC-2120", "TNC-2160", "FS", 0),
    ("TNC-2150", "TNC-2170", "FS", 0),
    ("TNC-2130", "TNC-2210", "FS", 0), ("TNC-2145", "TNC-2210", "FS", 0), ("TNC-2150", "TNC-2210", "FS", 0),
    ("TNC-2160", "TNC-2210", "FS", 0), ("TNC-2170", "TNC-2210", "FS", 0), ("CON-M142", "TNC-2210", "FS", 0),
    ("TNC-2210", "TNC-M220", "FS", 0),
    # Handover
    ("CON-M142", "HOV-3010", "FS", 0), ("TNC-M220", "HOV-3110", "FS", 0), ("HOV-3110", "HOV-3120", "FS", 0),
    ("HOV-3010", "HOV-3120", "FS", 0), ("HOV-3120", "HOV-M130", "FS", 0), ("TNC-M220", "HOV-3210", "FS", 0),
    ("HOV-3010", "HOV-3220", "FS", 0), ("HOV-M130", "HOV-M230", "FS", 0), ("HOV-3210", "HOV-M230", "FS", 0),
    ("HOV-3220", "HOV-M230", "FS", 0),
    # Operator mobilisation
    ("OPM-4010", "OPM-4015", "FS", 0), ("OPM-4015", "OPM-4020", "FS", 0), ("OPM-4020", "OPM-4030", "FS", 0),
    ("OPM-4020", "OPM-4110", "FS", 0), ("TNC-M220", "OPM-M120", "FS", 0), ("OPM-4030", "OPM-4130", "FS", 0),
    ("OPM-M120", "OPM-4130", "FS", 0), ("OPM-4110", "OPM-4130", "FS", 0), ("HOV-M130", "OPM-4130", "FS", 0),
    ("OPM-4130", "OPM-4140", "FS", 0), ("OPM-4140", "OPM-M150", "FS", 0),
    # Trials
    ("HOV-M230", "OTE-5010", "FS", 0), ("OPM-M150", "OTE-5010", "FS", 0), ("OTE-5010", "OTE-5020", "FS", 0),
    ("OPM-4030", "OTE-5030", "FS", 0), ("OTE-5010", "OTE-5030", "SS", 3),
    ("OTE-5020", "OTE-5110", "FS", 0), ("OTE-5030", "OTE-5110", "FS", 0), ("HOV-M130", "OTE-5110", "FS", 0),
    ("OTE-5110", "D1R-6010", "FS", 0), ("D1R-6010", "D1R-M020", "FS", 0),
]

VENUE_PARAMS = {
    "MTP": dict(start=dt.date(2025, 10, 11), plant=dt.date(2026, 4, 4), sys_pred="CON-1030",
                sys1="Ride systems installation (all rides)", sys2="Ride control systems & ride enclosures",
                sys3="Theming & show elements", sys4="Ride & show control integration", com1="Ride testing & commissioning (static & dynamic)",
                com2="Ride cycle testing & third-party certification",
                dur={"CON-1310": 110, "TNC-2140": 40, "TNC-2145": 30, "CON-1330": 44}),
    "LWP": dict(start=dt.date(2026, 1, 31), plant=dt.date(2026, 5, 2), sys_pred="CON-1112",
                sys1="Slide towers & flumes installation", sys2="Water treatment & filtration plant installation",
                sys3="Pool finishes & water features", sys4="Slide & attraction control integration", com1="Water treatment & filtration commissioning",
                com2="Water quality stabilisation & slide testing",
                dur={"CON-1310": 44, "CON-1320": 40, "CON-1330": 35, "TNC-2140": 25}),
    "DAR": dict(start=dt.date(2026, 1, 17), plant=dt.date(2026, 4, 4), sys_pred="CON-1112",
                sys1="Seating bowl & retractable seating", sys2="Show systems (AV, rigging, LED) installation",
                sys3="Premium suites & hospitality fit-out", sys4="Venue technology integration (ticketing, broadcast, IPTV)", com1="Show systems commissioning (AV, rigging, LED)",
                com2="Acoustic & broadcast performance testing",
                dur={"TNC-2140": 25, "TNC-2145": 15}),
    "PBR": dict(start=dt.date(2026, 1, 10), plant=dt.date(2026, 5, 2), sys_pred="CON-1112",
                sys1="Shell & core handover to tenants", sys2="Tenant fit-out - wave 1",
                sys3="Tenant fit-out - wave 2", sys4="Tenant fit-out - wave 3 & public realm", com1="Tenant systems integration testing",
                com2="Kitchen extract & fire suppression testing",
                dur={"CON-1310": 30, "CON-1320": 44, "CON-1330": 44, "TNC-2140": 20, "TNC-2145": 15,
                     "CON-1020": 40, "CON-1110": 40}),
}

# ----------------------------------------------------------------------------- enabling works
PEW_ACTS = {
    "PEW-CON-1010": ("Main substation civil works", "CON", "PWR", 40, SITE, T, "MWC", ""),
    "PEW-CON-1020": ("Main substation building & equipment installation", "CON", "PWR", 44, SITE, T, "MEP", ""),
    "PEW-CON-1030": ("HV cabling - South loop (Theme Park, Water Park)", "CON", "PWR", 40, SITE, T, "MEP", ""),
    "PEW-CON-1040": ("HV cabling - North loop (Arena, Boulevard)", "CON", "PWR", 44, SITE, T, "MEP", ""),
    "PEW-CON-1050": ("District cooling plant - civil & structure", "CON", "CLG", 44, SITE, T, "MWC", ""),
    "PEW-CON-1060": ("District cooling plant - chillers & pumps installation", "CON", "CLG", 44, SITE, T, "MEP", ""),
    "PEW-CON-1070": ("Chilled water distribution network", "CON", "CLG", 40, SITE, T, "MWC", ""),
    "PEW-CON-1080": ("Potable & irrigation water network", "CON", "WAT", 40, SITE, T, "MWC", ""),
    "PEW-CON-1090": ("Sewer & stormwater network", "CON", "WAT", 35, SITE, T, "MWC", ""),
    "PEW-CON-1110": ("Primary access road & junctions", "CON", "RDS", 44, SITE, T, "MWC", ""),
    "PEW-CON-1120": ("Internal roads, lighting & signage", "CON", "RDS", 35, SITE, T, "MWC", ""),
    "PEW-CON-1130": ("Transit link guideway & stations", "CON", "TRS", 100, SITE, T, "MWC", ""),
    "PEW-CON-1150": ("Transit systems installation (track, power, signalling)", "CON", "TRS", 44, SITE, T, "MEP", ""),
    "PEW-CON-1160": ("Transport hub & car park structure", "CON", "RDS", 40, SITE, T, "MWC", ""),
    "PEW-CON-1170": ("Telecom & ICT backbone", "CON", "ICT", 35, SITE, T, "MEP", ""),
    "PEW-CON-9010": ("Enabling works supervision (LOE)", "CON", "MGT", 0, SITE, L, "PMO", ""),
    "PEW-TNC-2010": ("Main substation energisation", "TNC", "PWR", 10, SEVEN, T, "MEP", ""),
    "PEW-TNC-2020": ("South loop HV commissioning & energisation", "TNC", "PWR", 10, SEVEN, T, "MEP", ""),
    "PEW-TNC-M021": ("Permanent power available - South loop", "TNC", "PWR", 0, SEVEN, F, "MEP", ""),
    "PEW-TNC-2030": ("North loop HV commissioning & energisation", "TNC", "PWR", 10, SEVEN, T, "MEP", ""),
    "PEW-TNC-M031": ("Permanent power available - North loop", "TNC", "PWR", 0, SEVEN, F, "MEP", ""),
    "PEW-TNC-2040": ("District cooling commissioning", "TNC", "CLG", 20, SEVEN, T, "MEP", ""),
    "PEW-TNC-M041": ("District cooling available", "TNC", "CLG", 0, SEVEN, F, "MEP", ""),
    "PEW-TNC-2050": ("Water network testing & disinfection", "TNC", "WAT", 10, SEVEN, T, "MWC", ""),
    "PEW-TNC-2060": ("Telecom backbone commissioning", "TNC", "ICT", 10, SEVEN, T, "MEP", ""),
    "PEW-TNC-2070": ("Transit system dynamic testing", "TNC", "TRS", 30, SEVEN, T, "ICA", ""),
    "PEW-TNC-M071": ("Transit ready for trial running", "TNC", "TRS", 0, SEVEN, F, "ICA", ""),
    "PEW-HOV-3010": ("Utility authority acceptance & handover", "HOV", "APR", 15, OFFICE, T, "AAT", ""),
    "PEW-HOV-3020": ("Road authority inspection & handover", "HOV", "APR", 10, OFFICE, T, "AAT", ""),
    "PEW-HOV-3030": ("Transit operating certificate", "HOV", "APR", 20, OFFICE, T, "AAT", ""),
    "PEW-HOV-M040": ("Enabling works handover complete", "HOV", "APR", 0, OFFICE, F, "PMO", "RG3"),
    "PEW-OPM-4010": ("Transit operator recruitment & training", "OPM", "RCT", 40, OFFICE, T, "OPR", ""),
    "PEW-OTE-5010": ("Transit trial running (shadow operation)", "OTE", "TRL", 30, SEVEN, T, "OPR", ""),
    "PEW-OTE-5020": ("Traffic management & wayfinding trials", "OTE", "TRL", 10, SEVEN, T, "SSY", ""),
}
PEW_LOGIC = [
    ("PEW-CON-1010", "PEW-CON-1020", "FS", 0), ("PEW-CON-1010", "PEW-CON-1030", "FS", 0),
    ("PEW-CON-1010", "PEW-CON-1040", "FS", 0), ("PEW-CON-1050", "PEW-CON-1060", "FS", 0),
    ("PEW-CON-1060", "PEW-CON-1070", "SS", 10), ("PEW-CON-1080", "PEW-CON-1090", "FS", 0),
    ("PEW-CON-1110", "PEW-CON-1120", "FS", 0), ("PEW-CON-1130", "PEW-CON-1150", "FS", 0),
    ("PEW-CON-1110", "PEW-CON-1160", "FS", 0), ("PEW-CON-1080", "PEW-CON-1170", "FS", 0),
    ("PEW-CON-1010", "PEW-CON-9010", "SS", 0), ("PEW-CON-1150", "PEW-CON-9010", "FF", 0),
    ("PEW-CON-1020", "PEW-TNC-2010", "FS", 0), ("PEW-TNC-2010", "PEW-TNC-2020", "FS", 0),
    ("PEW-CON-1030", "PEW-TNC-2020", "FS", 0), ("PEW-TNC-2020", "PEW-TNC-M021", "FS", 0),
    ("PEW-TNC-2010", "PEW-TNC-2030", "FS", 0), ("PEW-CON-1040", "PEW-TNC-2030", "FS", 0),
    ("PEW-TNC-2030", "PEW-TNC-M031", "FS", 0),
    ("PEW-CON-1060", "PEW-TNC-2040", "FS", 0), ("PEW-CON-1070", "PEW-TNC-2040", "FS", 0),
    ("PEW-TNC-2020", "PEW-TNC-2040", "FS", 0), ("PEW-TNC-2040", "PEW-TNC-M041", "FS", 0),
    ("PEW-CON-1080", "PEW-TNC-2050", "FS", 0), ("PEW-CON-1170", "PEW-TNC-2060", "FS", 0),
    ("PEW-CON-1150", "PEW-TNC-2070", "FS", 0), ("PEW-TNC-2030", "PEW-TNC-2070", "FS", 0),
    ("PEW-TNC-2070", "PEW-TNC-M071", "FS", 0),
    ("PEW-TNC-2020", "PEW-HOV-3010", "FS", 0), ("PEW-TNC-2030", "PEW-HOV-3010", "FS", 0),
    ("PEW-TNC-2040", "PEW-HOV-3010", "FS", 0), ("PEW-TNC-2060", "PEW-HOV-3010", "FS", 0),
    ("PEW-CON-1120", "PEW-HOV-3020", "FS", 0), ("PEW-TNC-M071", "PEW-HOV-3030", "FS", 0),
    ("PEW-HOV-3010", "PEW-HOV-M040", "FS", 0), ("PEW-HOV-3030", "PEW-HOV-M040", "FS", 0),
    ("PEW-CON-1090", "PEW-HOV-M040", "FS", 0), ("PEW-CON-1160", "PEW-HOV-M040", "FS", 0),
    ("PEW-TNC-M071", "PEW-OTE-5010", "FS", 0), ("PEW-OPM-4010", "PEW-OTE-5010", "FS", 0),
    ("PEW-CON-1120", "PEW-OTE-5020", "FS", 0), ("PEW-OTE-5010", "PEW-OTE-5020", "SS", 10),
]
PEW_STARTS = {"PEW-CON-1010": dt.date(2026, 8, 1), "PEW-CON-1050": dt.date(2026, 9, 5),
              "PEW-CON-1080": dt.date(2026, 10, 3), "PEW-CON-1110": dt.date(2026, 7, 4),
              "PEW-CON-1130": dt.date(2027, 1, 2), "PEW-OPM-4010": dt.date(2027, 1, 3)}
OPM_STARTS = {"MTP": dt.date(2026, 10, 18), "LWP": dt.date(2026, 11, 1), "DAR": dt.date(2026, 11, 1),
              "PBR": dt.date(2026, 11, 1)}

# ----------------------------------------------------------------------------- programme integration
PRG_ACTS = {
    "PRG-D1R-M000": ("Programme notice to proceed", "D1R", "GAT", 0, OFFICE, M, "PMO", ""),
    "PRG-D1R-9010": ("Programme management & controls (LOE)", "D1R", "MGT", 0, OFFICE, L, "PMO", ""),
    "PRG-OPM-4005": ("Operator executive team mobilisation", "OPM", "RCT", 20, OFFICE, T, "OPR", ""),
    "PRG-OPM-4010": ("Destination-wide recruitment campaign", "OPM", "RCT", 100, OFFICE, T, "OPR", ""),
    "PRG-OPM-4020": ("Service culture & guest-experience training", "OPM", "TRN", 30, OFFICE, T, "OPR", ""),
    "PRG-OPM-4030": ("FM mobilisation & maintenance contracts live", "OPM", "RCT", 40, OFFICE, T, "FMS", ""),
    "PRG-OPM-4040": ("Security & safety operational readiness accreditation", "OPM", "TRN", 30, OFFICE, T, "SSY", ""),
    "PRG-OPM-4050": ("Destination operating permits & licences", "OPM", "RCT", 25, OFFICE, T, "AAT", ""),
    "PRG-OPM-4060": ("Guest services & contact centre readiness", "OPM", "TRN", 20, OFFICE, T, "OPR", ""),
    "PRG-OTE-5010": ("Destination ticketing, CRM & IT go-live", "OTE", "TRL", 30, OFFICE, T, "OPR", ""),
    "PRG-OTE-5020": ("Integrated destination test event (all assets)", "OTE", "TEV", 5, SEVEN, T, "OPR", ""),
    "PRG-OTE-5030": ("Opening ceremony operational rehearsal", "OTE", "TEV", 3, SEVEN, T, "SSY", ""),
    "PRG-D1R-M010": ("RG1 Construction complete gate", "D1R", "GAT", 0, SEVEN, F, "PMO", "RG1"),
    "PRG-D1R-M020": ("RG2 T&C complete gate", "D1R", "GAT", 0, SEVEN, F, "PMO", "RG2"),
    "PRG-D1R-M030": ("RG3 Ready to operate gate", "D1R", "GAT", 0, SEVEN, F, "PMO", "RG3"),
    "PRG-D1R-6010": ("Day 1 go/no-go readiness review", "D1R", "GAT", 5, OFFICE, T, "PMO", "RG4"),
    "PRG-D1R-6020": ("Day 1 command centre & hypercare set-up", "D1R", "GAT", 15, SEVEN, T, "PMO", ""),
    "PRG-D1R-M040": ("RG4 Day 1 go/no-go gate", "D1R", "GAT", 0, SEVEN, F, "PMO", "RG4"),
    "PRG-D1R-M999": ("Day 1 Opening", "D1R", "GAT", 0, SEVEN, F, "PMO", "RG4"),
}
PRG_LOGIC = [
    ("PRG-D1R-M000", "PRG-OPM-4005", "FS", 0), ("PRG-OPM-4005", "PRG-OPM-4010", "FS", 0),
    ("PRG-OPM-4010", "PRG-OPM-4020", "FS", 0), ("PRG-OPM-4020", "PRG-OPM-4060", "FS", 0),
    ("PRG-OPM-4005", "PRG-OPM-4050", "FS", 0),
    ("PRG-D1R-M000", "PRG-D1R-9010", "SS", 0), ("PRG-D1R-M999", "PRG-D1R-9010", "FF", 0),
    ("PRG-D1R-M010", "PRG-OPM-4030", "SS", 0), ("PRG-D1R-M020", "PRG-OPM-4040", "FS", 0),
    ("PRG-OPM-4060", "PRG-OTE-5010", "FS", 0),
    ("PRG-OTE-5010", "PRG-OTE-5020", "FS", 0), ("PRG-OPM-4030", "PRG-OTE-5020", "FS", 0),
    ("PEW-OTE-5010", "PRG-OTE-5020", "FS", 0), ("PRG-OTE-5020", "PRG-OTE-5030", "FS", 0),
    ("PRG-D1R-M030", "PRG-D1R-6020", "FS", 0),
    ("PRG-OTE-5030", "PRG-D1R-6010", "FS", 0), ("PRG-OPM-4040", "PRG-D1R-6010", "FS", 0),
    ("PRG-OPM-4050", "PRG-D1R-6010", "FS", 0), ("PRG-D1R-6020", "PRG-D1R-6010", "FS", 0),
    ("PEW-HOV-M040", "PRG-D1R-M030", "FS", 0),
    ("PRG-D1R-6010", "PRG-D1R-M040", "FS", 0), ("PRG-D1R-M040", "PRG-D1R-M999", "FS", 0),
    ("PEW-OTE-5020", "PRG-D1R-6010", "FS", 0),
]
CROSS_LOGIC = []  # filled in build_template()

# interfaces: (giver suffix-or-id, receiver, description)
def interface_list() -> list[dict]:
    out = []
    n = 0

    def add(giver, receiver, desc):
        nonlocal n
        n += 1
        out.append({"interface_id": f"IF-{n:02d}", "giver": giver, "receiver": receiver, "description": desc})

    for a in VENUES:
        loop = "PEW-TNC-M021" if a in ("MTP", "LWP") else "PEW-TNC-M031"
        add(loop, f"{a}-TNC-2010", f"Permanent power to {ASSETS[a]} for pre-commissioning")
    for a in VENUES:
        add("PEW-TNC-M041", f"{a}-TNC-2110", f"District cooling to {ASSETS[a]} for HVAC commissioning")
    for a in VENUES:
        add(f"{a}-CON-M142", f"{a}-TNC-2210", f"{ASSETS[a]} construction complete to IST (construction > T&C)")
    for a in VENUES:
        add(f"{a}-TNC-M220", f"{a}-OPM-M120", f"{ASSETS[a]} T&C complete to operator site access (T&C > operator)")
    for a in VENUES:
        add(f"{a}-TNC-M220", f"{a}-HOV-3110", f"{ASSETS[a]} T&C complete to authority inspection (T&C > handover)")
    for a in VENUES:
        add(f"{a}-HOV-M130", f"{a}-OPM-4130", f"{ASSETS[a]} occupancy certificate to operator familiarisation")
    for a in VENUES:
        add(f"{a}-HOV-M230", f"{a}-OTE-5010", f"{ASSETS[a]} handover to operator to operational trials")
    for a in VENUES:
        add(f"{a}-D1R-M020", "PRG-D1R-6010", f"{ASSETS[a]} Day 1 ready to programme go/no-go review")
    add("PEW-TNC-M071", "PEW-OTE-5010", "Transit ready to transit trial running")
    add("PEW-OTE-5010", "PRG-OTE-5020", "Transit trial running to integrated destination test event")
    return out


def build_template() -> tuple[dict[str, dict], list[tuple]]:
    """Return (activities, relationships) for the BL0 programme (before storyline deltas)."""
    acts: dict[str, dict] = {}
    rels: list[tuple] = []

    def add_act(aid, spec, asset, **extra):
        name, ws, pkg, dur, cal, typ, owner, gate = spec
        acts[aid] = dict(id=aid, name=name, asset=asset, ws=ws, pkg=pkg, dur=dur, cal=cal, type=typ,
                         owner=owner, gate=gate, phase=PHASE_BY_WS[ws], cstr_type="", cstr_date=None, **extra)

    for a in VENUES:
        p = VENUE_PARAMS[a]
        for sfx, spec in VENUE_TEMPLATE.items():
            name = spec[0].format(**p)
            dur = p["dur"].get(sfx, spec[3])
            add_act(f"{a}-{sfx}", (name,) + spec[1:3] + (dur,) + spec[4:], a)
        for pr, su, ty, lag in VENUE_LOGIC:
            pr = p["sys_pred"] if pr == "SYS_PRED" else pr
            rels.append((f"{a}-{pr}", f"{a}-{su}", ty, lag))
        acts[f"{a}-CON-1010"].update(cstr_type="CS_MSOA", cstr_date=p["start"])
        acts[f"{a}-CON-1105"].update(cstr_type="CS_MSOA", cstr_date=p["plant"])
        acts[f"{a}-OPM-4010"].update(cstr_type="CS_MSOA", cstr_date=OPM_STARTS[a])
        rels.append(("PRG-D1R-M000", f"{a}-CON-1010", "FS", 0))
        rels.append(("PRG-D1R-M000", f"{a}-CON-1105", "FS", 0))
        # cross-asset / programme logic
        loop = "PEW-TNC-M021" if a in ("MTP", "LWP") else "PEW-TNC-M031"
        rels += [(loop, f"{a}-TNC-2010", "FS", 0), ("PEW-TNC-M041", f"{a}-TNC-2110", "FS", 0),
                 ("PRG-OPM-4005", f"{a}-OPM-4010", "FS", 0),
                 (f"{a}-CON-M142", "PRG-D1R-M010", "FS", 0), (f"{a}-TNC-M220", "PRG-D1R-M020", "FS", 0),
                 (f"{a}-HOV-M230", "PRG-D1R-M030", "FS", 0), (f"{a}-OPM-M150", "PRG-D1R-M030", "FS", 0),
                 (f"{a}-D1R-M020", "PRG-D1R-6010", "FS", 0), (f"{a}-OTE-5110", "PRG-OTE-5020", "FS", 0),
                 ("PRG-OTE-5010", f"{a}-OTE-5030", "FS", 0)]
    rels.append(("MTP-CON-1320", "MTP-CON-1220", "FS", 0))  # queue-line finishes need ride enclosures
    for aid, spec in PEW_ACTS.items():
        add_act(aid, spec, "PEW")
    rels += PEW_LOGIC
    for aid, d in PEW_STARTS.items():
        acts[aid].update(cstr_type="CS_MSOA", cstr_date=d)
        rels.append(("PRG-D1R-M000", aid, "FS", 0))
    rels += [("PEW-TNC-M071", "PRG-D1R-M020", "FS", 0), ("PEW-CON-1090", "PRG-D1R-M010", "FS", 0),
             ("PEW-CON-1120", "PRG-D1R-M010", "FS", 0)]
    for aid, spec in PRG_ACTS.items():
        add_act(aid, spec, "PRG")
    rels += PRG_LOGIC
    acts["PRG-D1R-M999"].update(cstr_type="CS_MEOB", cstr_date=DAY1_TARGET)
    acts["PRG-OPM-4005"].update(cstr_type="CS_MSOA", cstr_date=dt.date(2026, 3, 1))
    acts["PRG-OTE-5010"].update(cstr_type="CS_MSOA", cstr_date=dt.date(2027, 4, 4))
    acts["PRG-OPM-4050"].update(cstr_type="CS_MSOA", cstr_date=dt.date(2027, 6, 6))
    # venue operator recruitment starts after the destination campaign has started
    for a in VENUES:
        rels.append(("PRG-OPM-4010", f"{a}-OPM-4010", "SS", 20))
    rels = [r for r in rels if not (r[0] == "PRG-OPM-4005" and r[1].endswith("-OPM-4010") and r[1] != "PRG-OPM-4010")]
    return acts, rels
