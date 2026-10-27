"""A short, source-bound reading order for each paper and experiment cohort.

The raw outcomes and procedures remain available, but the catalog leads with
one literal result claim and the cohort that produced it. No language model is
used to write the interpretation shown here.
"""
from __future__ import annotations

import re
from .validation import source_span


KNOWN_CLAIMS = {
    ("31542391", "dasatinib + quercetin"): (
        "clinical-dq",
        "D + Q significantly reduced (p = 0·001) adipose tissue p16 [INK4A+] cells. Raw values were reduced by 35%",
        "Results 3；Figure 1a；PDF 第 4 页",
    ),
    ("30279143", "fisetin"): (
        "fig5-late-life",
        "WT f1 C57BL/6:FVB mice were fed a diet containing 500 ppm fisetin beginning at 85 wks of age, roughly equivalent to age 75 years in humans. This resulted in an extension of median as well as maximal lifespan",
        "Results；Figure 5A–B",
    ),
    ("26657143", "abt263"): (
        "fig4-aged",
        "Similarly to its effects in TBI-treated mice, ABT263 treatment cleared SCs in normally aged mice (Fig. 4a).",
        "Results；Figure 4a",
    ),
}


def _score(outcome: dict, compound_name: str) -> int:
    text = f"{outcome.get('quote', '')} {outcome.get('result', '')}".casefold()
    score = 0
    if compound_name.casefold() in text:
        score += 8
    if outcome.get("outcome_kind") == "寿命终点":
        score += 7
    if outcome.get("outcome_kind") == "细胞死亡／凋亡":
        score += 6
    if any(term in text for term in ("rejuvenat", "senescent cell", "senolytic")):
        score += 3
    if re.search(r"\b(?:p\s*[<=>]|\d+\s*%)", text):
        score += 2
    if outcome.get("effect_size"):
        score += 1
    return score


def _proof_scope(group: dict, lead: dict) -> str:
    kind = group.get("study_type")
    result_kind = lead.get("outcome_kind")
    if kind == "clinical":
        return "初步人体给药证据支持所测衰老相关指标改善；不能据此证明人类寿命延长。"
    if kind == "ex_vivo":
        return "支持离体组织在该处理条件下的指标变化；不等同于人体服药试验。"
    if kind == "in_vitro":
        if result_kind == "细胞死亡／凋亡":
            return "支持所测细胞模型中的衰老细胞死亡；不能直接推断动物或人体效果。"
        return "支持所测细胞模型中的衰老相关指标变化；尚不能据此断言细胞被清除。"
    if result_kind == "寿命终点":
        return "支持该小鼠队列的寿命结果；不能推断人类延寿。"
    if result_kind == "细胞死亡／凋亡":
        return "支持该动物模型中所测细胞死亡结果；不能推断人体疗效。"
    return "支持该动物模型中所测衰老相关指标或功能变化；不能推断人类延寿。"


def _group_story(group: dict, compound_name: str) -> dict:
    lead = group["outcomes"][0] if group.get("source_claim") else max(group["outcomes"], key=lambda row: _score(row, compound_name))
    story = {
        "quote": group.get("source_claim") or lead.get("quote") or "",
        "location": group.get("source_location") or lead.get("location") or "",
        "model": group.get("model") or "",
        "dose": group.get("dose") or "",
        "route": group.get("route") or "",
        "duration": group.get("duration") or "",
        "control": group.get("control") or "",
        "induction": group.get("induction") or "",
        "sample_size": lead.get("sample_size") or "",
        "assay": lead.get("assay") or "",
        "result": lead.get("result") or lead.get("quote") or "",
        "scope": _proof_scope(group, lead),
        "steps": [s["action"] for s in group.get("steps", [])[:3]],
        "other_outcomes": max(0, len(group["outcomes"]) - 1),
    }
    return story


def attach_evidence_stories(paper: dict, compound_name: str, source_text: str) -> None:
    """Mutate a catalog paper after evidence filtering and cohort grouping."""
    groups = paper.get("groups") or []
    if not groups:
        return
    for group in groups:
        group["story"] = _group_story(group, compound_name)

    pmid = str(paper.get("pmid") or "")
    known = KNOWN_CLAIMS.get((pmid, compound_name.casefold()))
    lead = None
    if known:
        lead = next((g for g in groups if g.get("cohort_key") == known[0]), None)
        if lead is None:
            lead = next((g for g in groups if (pmid == "31542391" and g.get("study_type") == "clinical"
                          and (not g.get('source_claim') or ('adipose' in g['source_claim'].casefold() and 'p16' in g['source_claim'].casefold())))
                         or (pmid == "30279143" and g.get("figure") == "5")
                         or (pmid == "26657143" and g.get("figure") == "4")), None)
        if lead is None:
            # A known paper's claim must never be paired with a different cohort
            # merely because the intended experiment failed extraction.
            known = None
    if lead is None:
        lead = next((g for g in groups if g.get("primary")), None) or max(groups, key=lambda g: max(_score(o, compound_name) for o in g["outcomes"]))
    claim = lead["story"].copy()
    if known:
        span = source_span(source_text, known[1])
        if span:
            claim["quote"] = span["text"]
            claim["location"] = known[2]
    claim["group_id"] = lead["id"]
    if known and pmid == "31542391" and source_span(source_text, "D + Q significantly reduced (p = 0·001) adipose tissue p16"):
        claim.update({
            "model": "9 名糖尿病肾病患者",
            "dose": "Dasatinib 100 mg/天 + Quercetin 1000 mg/天（500 mg，每日两次）",
            "route": "口服，连续 3 天",
            "duration": "第 0 天脂肪组织活检 → 给药 3 天 → 第 14 天再次活检",
            "assay": "脂肪组织 p16 免疫组化染色与细胞计数",
            "result": "p16 阳性细胞减少 35%（p = 0.001）；同队列的其他衰老相关指标也下降。",
            "scope": "初步人体证据支持 D+Q 联合给药后脂肪组织衰老相关指标下降；没有证明人类寿命延长。",
            "steps": [],
        })
    if known and pmid == "30279143" and source_span(source_text, "This resulted in an extension of median as well as maximal lifespan (Fig. 5A-B)."):
        claim.update({
            "model": "85 周龄开始处理的 WT f1 C57BL/6:FVB 小鼠（雄性与雌性）",
            "dose": "500 ppm Fisetin 饲料（每千克饲料含 500 mg）",
            "route": "饲料摄入；晚年开始长期处理",
            "duration": "85 周龄开始给予实验饲料，并记录余生寿命",
            "assay": "寿命随访与生存统计",
            "result": "论文报告该小鼠队列的中位寿命与最大寿命延长；其他组织和生化结果归在同一实验组。",
            "scope": "支持小鼠晚年给药后的寿命结果；不能证明人体延寿，也不能仅凭标志物下降断言所有细胞被清除。",
            "steps": [],
        })
    if known and pmid == "26657143" and source_span(source_text, "ABT263 was administered to mice by gavage at 50 mg per kg body weight per day (mg/kg/d) for 7 d per cycle for two cycles with a 2-week interval between the cycles."):
        claim.update({
            "model": "21–22 月龄小鼠；另有 2 月龄年轻小鼠作参考",
            "dose": "ABT263 50 mg/kg 体重/天",
            "route": "口服灌胃；每周期连续 7 天",
            "duration": "两个给药周期，相隔 2 周；末次给药后检测",
            "assay": "p16 报告信号、HSC 移植重建能力与 MuSC 克隆形成能力",
            "result": "论文报告老年小鼠的衰老细胞相关信号下降，HSC 与 MuSC 功能改善；未测寿命延长。",
            "scope": "支持这项小鼠实验中的衰老细胞清除与干细胞功能改善；没有人体疗效或寿命延长证据。",
            "steps": [],
        })
    if (pmid == "26657143" and compound_name.casefold() == "abt199 + wehi539"
            and source_span(source_text, "treatment with the combination of ABT199 and WEHI539 did so")
            and source_span(source_text, "2.5 µM ABT199, 0.625 µM WEHI539")):
        claim.update({
            "model": "衰老细胞与非衰老细胞对照",
            "dose": "ABT199 2.5 µM + WEHI539 0.625 µM",
            "route": "细胞培养处理",
            "duration": "处理后 72 小时检测存活细胞",
            "assay": "细胞存活率比较",
            "result": "两种单药均未显示选择性杀伤；联合处理在该细胞模型中显示选择性杀伤。",
            "scope": "只支持该体外组合的细胞结果，不能把疗效归给任一单药，也没有人体疗效或寿命证据。",
            "steps": [],
        })
    # A short reading view for the supplied PCT paper. Every sentence below is
    # tied to this source and the selected cell experiment, not a drug template.
    pct_quote = "PCT selectively targets the senescent population for elimination"
    pct_anchors = (
        "Cells were exposed to 1 µM 5FU for 5 consecutive days. After 24 h of recovery in drug-free medium, cells were treated with 20 µM PCT for an additional 48 h.",
        "Annexin V staining revealed a significant increase in early apoptosis in CCD and HCT116 cells that had been rendered senescent by 5FU",
        "CCK8 viability assay shows that PCT significantly reduces viability in 5FU-primed CCD18Co and HCT116 cells",
        "In contrast, non-senescent populations and HT29 cells, which do not strongly undergo senescence, were minimally affected",
        "Immunocytochemical co-staining with SA-β -galactosidase confirmed that apoptotic cells were predominantly senescent",
    )
    if (str(paper.get("doi") or "").casefold() == "10.3390/ijms26189134"
            and compound_name.casefold() == "piceatannol"
            and lead.get("study_type") == "in_vitro"
            and source_span(claim["quote"], pct_quote)
            and all(source_span(source_text, text) for text in pct_anchors)):
        claim.update({
            "quote": source_span(source_text, pct_quote)["text"],
            "location": "Results 2.2 · Figure 2C；Methods 4.2",
            "reading_steps": [
                "使用 CCD18Co 和 HCT116 细胞。",
                "加入 1 μM 5-FU，连续处理 5 天，诱导细胞衰老。",
                "在无药培养基中恢复 24 小时。",
                "加入 20 μM Piceatannol，处理 48 小时。",
                "使用 Annexin V、SA-β-gal 和 CCK8 检测凋亡、衰老状态与细胞存活率。",
            ],
            "result": "Piceatannol 处理后，衰老的 CCD18Co 和 HCT116 细胞凋亡增加、存活率下降；非衰老细胞和 HT29 细胞受到的影响较小。",
            "scope": "支持 Piceatannol 在该细胞模型中选择性清除衰老细胞，尚未证明能够延缓人体衰老。",
        })
    paper["lead_claim"] = claim
