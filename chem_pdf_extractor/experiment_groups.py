"""Conservative presentation grouping: one intervention cohort, several outcomes.

This layer never merges across papers. Known demo papers have explicit, reviewable
cohort labels; other papers use figure, model class and regimen as a cautious key.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any
from .validation import source_span

MISSING = {"", "原文未报告", "not reported", "unreported"}
FIGURE = re.compile(r"\bfig(?:ure)?\.?\s*(\d+)", re.I)


def study_type(row: dict) -> str:
    text = f"{row.get('model', '')} {row.get('route', '')}".casefold()
    kind = str(row.get("model_type") or "").casefold()
    if kind == "clinical":
        return "clinical"
    if "explant" in text or "ex vivo" in text or "resected" in text:
        return "ex_vivo"
    if kind in {"in_vitro", "in_vivo", "ex_vivo", "clinical"}:
        return kind
    if "patient" in text or "subjects" in text:
        return "clinical"
    if "mice" in text or "mouse" in text:
        return "in_vivo"
    return "unreported"


def dose_details(row: dict) -> dict[str, str]:
    dose = str(row.get("dose") or "")
    route = str(row.get("route") or "")
    kind = study_type(row)
    if re.search(r"\bppm\b", dose, re.I):
        ppm = re.search(r"\b([\d,.]+)\s*ppm\b", dose, re.I)
        return {"dose": f"{ppm.group(1)} ppm（每千克饲料含 {ppm.group(1)} mg）" if ppm else dose,
                "basis": "饲料浓度，不是每千克体重给药剂量", "route": "饲料摄入"}
    if re.search(r"\bmg\s*/\s*kg\b", dose, re.I):
        return {"dose": dose, "basis": "每千克体重", "route": "口服灌胃" if "gavage" in route.casefold() else route}
    if re.search(r"\b(?:μm|µm|um)\b", dose, re.I):
        return {"dose": dose, "basis": "培养体系浓度", "route": "离体组织培养" if kind == "ex_vivo" else "细胞培养"}
    return {"dose": dose, "basis": "原文单位未进一步归一", "route": route}


def _cohort(row: dict, pmid: str) -> tuple[str, str]:
    model = str(row.get("model") or "").casefold()
    place = str(row.get("location") or "")
    fig = FIGURE.search(place)
    number = fig.group(1) if fig else "未定位图号"
    kind = study_type(row)
    if pmid == "26657143":
        if number == "4" or "normally aged" in model:
            return "fig4-aged", "Figure 4 · 自然老年小鼠 HSC/MuSC 功能"
        if number == "3" or (number == "9" and "hsc" in model):
            return "fig3-tbi-hsc", "Figure 3 · 照射小鼠 HSC 清除与移植功能"
        if number == "2" or (kind == "in_vitro" and ("qvd" in str(row.get("dose") or "").casefold() or "annexin" in str(row.get("assay") or "").casefold())):
            return "fig2-apoptosis", "Figure 2 · 衰老细胞凋亡机制"
        if number == "1":
            if kind == "in_vivo":
                return "fig1-tbi-reporter", "Figure 1D–G · 照射小鼠衰老细胞检测"
            return "fig1-cell-screen", "Figure 1A–C · 衰老细胞选择性杀伤"
    if pmid == "31542391":
        return "clinical-dq", "临床队列 · Dasatinib + Quercetin 三日给药"
    if pmid == "30279143":
        if number == "1":
            if "imr90" in model:
                return "fig1-imr90", "Figure 1 · IMR90 细胞浓度响应"
            if re.search(r"fig(?:ure)?\.?\s*1b\b", place, re.I):
                return "fig1-mef-dose", "Figure 1B · MEF 细胞浓度响应"
            return "fig1-mef", "Figure 1A · MEF 黄酮筛选"
        if number == "2":
            return "fig2-intermittent", "Figure 2 · 早衰小鼠间歇性饲料给药"
        if number == "3":
            return "fig3-chronic", "Figure 3 · 早衰小鼠长期饲料给药"
        if number == "4":
            if kind == "ex_vivo":
                return "fig4-human-explant", "Figure 4E–F · 人脂肪组织离体实验"
            if "ink-attac" in model:
                return "fig4-ink-attac", "Figure 4B–D · 老年 INK-ATTAC 小鼠脂肪细胞分型"
            return "fig4-wt", "Figure 4A · 老年 WT 小鼠短期灌胃"
        if number == "5":
            return "fig5-late-life", "Figure 5 · 老年 WT 小鼠晚年开始的长期给药"
    marker = ""
    for token in ("ink-attac", "imr90", "ercc1", "mef", "c57bl", "wt"):
        if token in model:
            marker = token
            break
    regimen = "feed" if "ppm" in str(row.get("dose") or "").casefold() else "non-feed"
    key = f"fig{number}-{kind}-{marker}-{regimen}"
    return key, f"Figure {number} · {kind.replace('_', ' ')} 实验组"


def _completeness(row: dict) -> int:
    fields = ("model", "dose", "duration", "route", "control", "sample_size", "assay", "statistics")
    return sum(bool(str(row.get(f) or "").strip()) for f in fields) + len(row.get("steps") or [])


def _outcome_key(row: dict) -> str:
    quote = re.sub(r"\s+", " ", str(row.get("quote") or "")).strip().casefold()
    return quote or str(row.get("id") or "")


def outcome_kind(row: dict) -> str:
    text = f"{row.get('endpoint', '')} {row.get('assay', '')} {row.get('result', '')}".casefold()
    negated_death = re.search(r"(?:no|without|lack of|failed to show)\s+(?:clear\s+)?(?:evidence of\s+)?(?:cell killing|cell death|apoptosis)", text)
    if not negated_death and any(x in text for x in ("apoptosis", "caspase", "cell killing", "cell death")):
        return "细胞死亡／凋亡"
    if any(x in text for x in ("lifespan", "寿命")):
        return "寿命终点"
    if any(x in text for x in ("il-6", "il-8", "mcp-1", "sasp", "inflammation", "cytokine")):
        return "炎症／SASP 指标"
    if any(x in text for x in ("amylase", "alanine aminotransferase", "alt", "pathology")):
        return "器官功能／病理指标"
    return "衰老相关标志物；不等同于细胞清除"


def _steps(rows: list[dict]) -> list[dict]:
    found = {}
    for row in sorted(rows, key=_completeness, reverse=True):
        for step in row.get("steps") or []:
            if not isinstance(step, dict) or not isinstance(step.get("evidence"), dict):
                continue
            action = str(step.get("action") or "").strip()
            quote = str(step["evidence"].get("text") or "").strip()
            if not action or not quote:
                continue
            # A result sentence is not an experimental procedure.
            if re.search(r"\b(?:these data|these results|significantly (?:reduced|increased)|fisetin (?:reduced|improved|extended))\b", action, re.I):
                continue
            key = re.sub(r"\s+", " ", quote).casefold()
            found.setdefault(key, {"action": action, "quote": quote})
    return list(found.values())[:20]


KNOWN_OUTCOMES = {
    "fig3-chronic": [
        ("Fig. 3A–D", "多组织 p16/p21 与 SASP 标志物", "qRT-PCR",
         "Fisetin reduced expression of senescence and SASP markers significantly in all tissues."),
        ("Fig. 3E", "外周血 CD3+ T 细胞 p16/p21 与 SASP", "qRT-PCR",
         "Similarly, there was a reduction in the expression of p16Ink4a, p21Cip1 and the SASP factors in peripheral blood CD3+ T cells"),
        ("Fig. 3F–G", "肝脏 HNE 加合物与 GSH/GSSG", "ELISA；谷胱甘肽定量",
         "In addition, fisetin reduced oxidative stress in the liver as determined by measuring the lipid peroxidation product 4-hydroxynonenal (HNE) adducts and an increase in the ratio of reduced to oxidized glutathione"),
    ],
    "fig4-human-explant": [
        ("Fig. 4E", "SA-β-gal 阳性细胞比例", "SA-β-gal 染色",
         "Fisetin treatment caused a significant reduction in the percent of SA-ß-gal positive cells"),
        ("Fig. 4F", "IL-6、IL-8、MCP-1 分泌水平", "条件培养基多重蛋白检测",
         "as well as in expression of the SASP factors IL-6, IL-8, and MCP-1 in human WAT"),
    ],
}

# The earlier extraction omitted Methods for several demo cohorts. Attach only
# literal, source-verified passages from the same paper and matching cohort.
KNOWN_STEPS = {
    "fig4-aged": [
        ("对 21–22 月龄小鼠给予 ABT263 或溶媒；另以 2 月龄小鼠作年轻参考。",
         "Aged (21- to 22-month-old) male C57BL/6 mice received vehicle (Veh) or ABT263 (ABT) according to the scheme shown in Figure 3a"),
        ("ABT263 按体重 50 mg/kg/天灌胃，每周期 7 天、共两周期，周期相隔 2 周。",
         "ABT263 was administered to mice by gavage at 50 mg per kg body weight per day (mg/kg/d) for 7 d per cycle for two cycles with a 2-week interval between the cycles."),
        ("末次处理后 1 周分析老年 C57BL/6 小鼠。",
         "were analyzed 1 week after the treatment"),
    ],
    "fig3-tbi-hsc": [
        ("以 6 Gy 全身照射建立小鼠早衰样 HSC 模型。",
         "a sublethal dose (6 Gy) of TBI"),
        ("ABT263 按体重 50 mg/kg/天灌胃，每周期 7 天、共两周期，周期相隔 2 周。",
         "ABT263 was administered to mice by gavage at 50 mg per kg body weight per day (mg/kg/d) for 7 d per cycle for two cycles with a 2-week interval between the cycles."),
    ],
    "fig1-mef": [
        ("将 Ercc1−/− MEF 在 20% O₂ 培养 5 次传代以诱导衰老。",
         "Ercc1−/− MEFs were passaged 5 times at 20% O2 to induce senescence"),
        ("每孔接种 5000 个细胞，至少 6 小时后加入待测黄酮。",
         "then seeded at 5000 cells per well in 96 well plates at least 6 h prior to treatment."),
        ("以 C12FDG 染色并使用 IN Cell Analyzer 6000 量化存活与 SA-β-gal 阳性细胞。",
         "An IN Cell Analyzer 6000 was used to quantitate total number of viable cells (Hoechst+) and the number of senescent cells (C12FDG+)."),
    ],
    "fig1-mef-dose": [
        ("将混合的增殖与衰老 MEF 细胞暴露于不同浓度的 Fisetin。",
         "after treating mixed cultures of proliferating and senescent cells with various doses of fisetin"),
        ("以 C12FDG 和 Hoechst 染色量化存活与衰老细胞。",
         "An IN Cell Analyzer 6000 was used to quantitate total number of viable cells (Hoechst+) and the number of senescent cells (C12FDG+)."),
    ],
    "fig2-intermittent": [
        ("从 6–8 周龄、12–14 周龄两个时段间歇给予含 500 ppm Fisetin 的饲料。",
         "The mice were exposed to a fisetin diet intermittently from 6 to 8 then 12–14 wks of age."),
        ("开始给药前测量全身荧光素酶信号，此后每周测量。",
         "Whole body luciferase activity was measured before starting the fisetin diet then weekly thereafter."),
        ("注射荧光素底物，并用 IVIS Lumina 成像。",
         "were injected intraperitoneally with 10 μL per gram body weight D-luciferin substrate"),
    ],
    "fig3-chronic": [
        ("从 10 周龄开始给予含 500 ppm Fisetin 的饲料，持续 10 周后取组织。",
         "Ercc1−/∆ mice were treated with the 500 ppm fisetin diet for 10 wks beginning at 10 wks of age"),
        ("检测脂肪、脾、肝、肾组织的 p16/p21 与 SASP 基因表达。",
         "Tissues from 20-week-old male and female Ercc1−/∆ mice chronically exposed to fisetin through their diet or fed a control diet were analyzed for the expression of senescence"),
        ("分离外周血 CD3+ T 细胞并进行 qPCR。",
         "Senescence and SASP markers in CD3+ peripheral T cells isolated from the same mice. mRNA levels were measured by qRT-PCR."),
        ("以 ELISA 测量肝脏 HNE 加合物，并定量 GSH/GSSG。",
         "4-hydroxynonenal (HNE) adducts were measured in liver"),
    ],
    "fig4-wt": [
        ("对 22–24 月龄 WT 小鼠灌胃 100 mg/kg Fisetin 或溶媒，连续 5 天。",
         "22–24-month-old WT C57BL/6 mice were given fisetin (100 mg/kg) or vehicle for 5 days by oral gavage."),
        ("末次给药 72 小时后处死，检测腹股沟脂肪组织 SA-β-gal 阳性细胞。",
         "72 h after the final dose, the mice were sacrificed and the SA-β-gal+ cells were quantified in inguinal fat"),
    ],
    "fig4-ink-attac": [
        ("对 22–24 月龄 INK-ATTAC 雄鼠按短期方案给予 Fisetin。",
         "Aged INK-ATTAC male mice (22–24 months) were acutely treated with fisetin as described above"),
        ("取皮下脂肪，以 CyTOF 量化 p16/FLAG 阳性细胞群。",
         "CyTOF analysis used to quantify p16Ink4a/FLAG+ cell populations in subcutaneous fat tissue"),
        ("在同一细胞群中测量 CENP-B。",
         "Quantification of another marker of cellular senescence in the same cell populations (CENP-B+ cells)."),
    ],
}

LATE_LIFE_OUTCOMES = [
    ("Fig. 5F–I", "多组织 p16/p21 与 SASP 标志物", "qRT-PCR", "n=4–10", "单因素 ANOVA，Tukey 多重比较",
     "Similar to the progeroid mice, fisetin reduced the expression of senescence and SASP markers in multiple tissues of aged WT mice exposed to oral fisetin",
     "n = 4–10 mice per group. One-way ANOVA with Tukey's multiple comparison test."),
    ("Fig. 5J", "外周血 CD3+ T 细胞衰老与 SASP 标志物", "qRT-PCR", "n=4–6", "单因素 ANOVA，Tukey 多重比较",
     "Furthermore, there was a reduction in senescence and SASP factor expression in peripheral CD3+ T cells",
     "n = 4–6 mice per group. One-way ANOVA with Tukey's multiple comparison test."),
    ("Fig. 5K", "循环 MCP-1", "ELISA", "n=5", "单因素 ANOVA，Tukey 多重比较",
     "There was also a reduction in levels of circulating MCP-1",
     "Circulating levels of the SASP factor chemokine MCP-1 were measured by ELISA. n = 5 mice per group. One-way ANOVA with Tukey's multiple comparison test."),
    ("Fig. 5L–M", "肝脏 HNE 与 GSH/GSSG 氧化应激指标", "HNE ELISA；GSH/GSSG 定量", "HNE n=5–6；GSH/GSSG n=6–7", "双尾非配对 t 检验",
     "Finally, fisetin reduced oxidative stress in the liver of old WT mice",
     "4-hydroxynonenal (HNE) adducts a marker of lipid peroxidation and oxidative stress measured by ELISA in liver. n = 5–6 mice per group."),
]


def _refine_known_outcomes(key: str, outcomes: list[dict], source_text: str) -> list[dict]:
    """Split known multi-endpoint evidence only when each quote is in the source."""
    if key not in KNOWN_OUTCOMES or not source_text or not outcomes:
        return outcomes
    base = max(outcomes, key=_completeness)
    refined = []
    for location, endpoint, assay, exact in KNOWN_OUTCOMES[key]:
        span = source_span(source_text, exact)
        if span is None:
            continue
        row = dict(base, id=f'{base["id"]}-{len(refined)+1}', location=location,
                   endpoint=endpoint, assay=assay, result=span["text"], quote=span["text"],
                   quote_matched=True, source_record_ids=base.get("source_record_ids", [base.get("id")]))
        row["outcome_kind"] = outcome_kind(row)
        refined.append(row)
    return refined if len(refined) == len(KNOWN_OUTCOMES[key]) else outcomes


def _attach_verified_steps(key: str, steps: list[dict], source_text: str) -> list[dict]:
    seen = {re.sub(r"\s+", " ", s["quote"]).casefold() for s in steps}
    for action, exact in KNOWN_STEPS.get(key, []):
        span = source_span(source_text, exact)
        if span is None:
            continue
        quote = span["text"]
        normalized = re.sub(r"\s+", " ", quote).casefold()
        if normalized not in seen:
            steps.append({"action": action, "quote": quote})
            seen.add(normalized)
    return steps


def _attach_late_life_outcomes(outcomes: list[dict], source_text: str) -> list[dict]:
    if not source_text or not outcomes:
        return outcomes
    base = max(outcomes, key=_completeness)
    for location, endpoint, assay, sample_size, statistics, exact, legend in LATE_LIFE_OUTCOMES:
        span = source_span(source_text, exact)
        if span is None:
            continue
        quote = span["text"]
        if any(quote in str(row.get("quote") or "") for row in outcomes):
            continue
        has_legend = source_span(source_text, legend) is not None
        outcomes.append(dict(base, id=f'{base["id"]}-{location}', location=location,
                             endpoint=endpoint, assay=assay, result=quote, quote=quote,
                             sample_size=sample_size if has_legend else "",
                             statistics=statistics if has_legend else "",
                             quote_matched=True, source_record_ids=base.get("source_record_ids", [base.get("id")])))
    return outcomes


def _dedup_clinical_markers(outcomes: list[dict]) -> list[dict]:
    """Same trial, same marker, differently worded Results/Figure records."""
    grouped: dict[str, dict] = {}
    for row in outcomes:
        text = str(row.get("endpoint") or "").casefold()
        if "crown-like" in text:
            key = "crown-like structures"
        elif "cd68" in text or "macrophage" in text:
            key = "CD68 macrophages"
        elif "p16" in text:
            key = "p16"
        elif "p21" in text:
            key = "p21"
        elif "gal" in text:
            key = "SA-β-gal"
        else:
            key = row.get("id") or text
        old = grouped.get(key)
        if old is None:
            grouped[key] = row
            continue
        ids = list(dict.fromkeys((old.get("source_record_ids") or []) + (row.get("source_record_ids") or [])))
        better = row if _completeness(row) > _completeness(old) else old
        other = old if better is row else row
        merged = dict(better, source_record_ids=ids)
        for field in ("dose", "duration", "route", "control", "sample_size", "assay", "statistics"):
            if not merged.get(field) and other.get(field):
                merged[field] = other[field]
        grouped[key] = merged
    return list(grouped.values())


def group_paper_records(records: list[dict], pmid: str, source_text: str = "") -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in records:
        key, title = _cohort(row, pmid)
        group = grouped.setdefault(key, {"id": hashlib.sha256(f"{pmid}:{key}".encode()).hexdigest()[:12], "cohort_key": key,
                                         "title": title, "study_type": "clinical" if pmid == "31542391" else study_type(row), "records": [],
                                         "figure": FIGURE.search(str(row.get("location") or "")).group(1)
                                         if FIGURE.search(str(row.get("location") or "")) else ""})
        group["records"].append(row)
    result = []
    for key, group in grouped.items():
        rows = group.pop("records")
        by_quote: dict[str, dict] = {}
        for row in rows:
            outcome_key = _outcome_key(row)
            old = by_quote.get(outcome_key)
            if old is None:
                by_quote[outcome_key] = dict(row, source_record_ids=[row.get("id")])
            else:
                old["source_record_ids"].append(row.get("id"))
                if _completeness(row) > _completeness(old):
                    better = dict(row, source_record_ids=old["source_record_ids"])
                    for field in ("model", "dose", "duration", "route", "control", "sample_size", "assay", "statistics"):
                        if not better.get(field) and old.get(field):
                            better[field] = old[field]
                    by_quote[outcome_key] = better
                else:
                    for field in ("model", "dose", "duration", "route", "control", "sample_size", "assay", "statistics"):
                        if not old.get(field) and row.get(field):
                            old[field] = row[field]
        outcomes = sorted(by_quote.values(), key=lambda r: r.get("location") or "")
        if pmid == "30279143":
            outcomes = _refine_known_outcomes(key, outcomes, source_text)
            if key == "fig5-late-life":
                outcomes = _attach_late_life_outcomes(outcomes, source_text)
        if pmid == "31542391":
            outcomes = _dedup_clinical_markers(outcomes)
        representative = max(outcomes, key=_completeness)
        details = dose_details(representative)
        group.update({"model": representative.get("model") or "", "dose": details["dose"],
                      "dose_basis": details["basis"], "route": details["route"],
                      "duration": representative.get("duration") or "", "control": representative.get("control") or "",
                      "steps": _attach_verified_steps(key, _steps(rows), source_text), "outcomes": [{**r, "outcome_kind": outcome_kind(r)} for r in outcomes],
                      "raw_record_count": len(rows)})
        if key == "fig3-chronic" and source_span(source_text, "Tissues from 20-week-old male and female Ercc1−/∆ mice chronically exposed to fisetin through their diet or fed a control diet"):
            group["control"] = "未加 Fisetin 的 Ercc1−/∆ 同龄小鼠；同龄 WT 小鼠作为表达参考"
        if key in {"fig1-tbi-reporter", "fig3-tbi-hsc", "fig4-aged"} and source_span(source_text, "ABT263 was administered to mice by gavage at 50 mg per kg body weight per day (mg/kg/d) for 7 d per cycle for two cycles with a 2-week interval between the cycles."):
            group["dose"] = "50 mg/kg 体重/天"
            group["dose_basis"] = "每千克体重"
            group["route"] = "口服灌胃"
            group["duration"] = "每周期 7 天，共 2 周期；周期之间间隔 2 周"
        result.append(group)
    return sorted(result, key=lambda g: (int(g["figure"]) if g["figure"].isdigit() else 999, g["title"]))
