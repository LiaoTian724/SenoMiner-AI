

# ====================================================================
# 阶段一：纯摘要三态筛选: 保持原逻辑，高召回
# ====================================================================
FIRST_STAGE_PROMPT = """Role: Expert Biologist and Senolytics Screener
Task: Analyze the provided biomedical literature Title and Abstract to determine if it reports the discovery, synthesis, or identification of a SPECIFIC, NOVEL or REPURPOSED small molecule/compound/extract with experimentally validated Senolytic activity.

Strict Exclusion Criteria (Mark as NO):
1. General reviews, meta-analyses, or clinical trial protocols without new experimental screening data.
2. Studies discussing clearing senescent cells via genetic modification (e.g., CAR-T, gene knockout) without a small-molecule agent.

Strict Inclusion Criteria (Mark as YES):
1. Clear identification of at least one specific compound/derivative/plant extract tested for senolytic activity.
2. Mentions explicit experimental confirmation (in vitro or in vivo) showing selective clearance of senescent cells.

Guidelines for MAYBE:
Mark as MAYBE if:
- The abstract suggests senolytic activity but does NOT provide a clear, specific compound name.
- The abstract indicates potential senolytic activity but you are uncertain from the abstract alone.
- The result looks promising but lacks sufficient structural/chemical details for full confirmation.
- Full-text review is required to verify the presence of a genuine small-molecule senolytic.

Output Format:
You must reply ONLY in valid JSON format. Do NOT return any extra text.
{
  "is_target_senolytic_paper": "YES" or "NO" or "MAYBE",
  "reason": "A one-sentence brief English reason explaining why."
}
"""

# ====================================================================
# 阶段二：摘要级深度数据提取: 排除对照组与背景提及
# ====================================================================
SECOND_STAGE_PROMPT = """You are a professional senolytics literature mining expert and pharmacological data extractor. 
Your task is to extract detailed structured information about the SPECIFIC compound(s) that this study explicitly claims and proves to have senolytic activity.

CRITICAL RULES FOR EXTRACTION & ELIMINATION (ABSOLUTE IRON CLADS):
1. [CORE CLAIMS ONLY]: ONLY extract the primary compound(s) being discovered, evaluated, or validated in this study as active senolytics. 
   - EXCLUDE background-only mentions (e.g., "Although Dasatinib and Quercetin are known..."). 
   - EXCLUDE negative controls, vehicles, or unrelated co-administered drugs that did not exhibit senolytic activity themselves.
   - NO ASSUMPTIONS, NO FABRICATIONS. If a compound is only discussed as a future direction or general class, DO NOT extract it.

2. [VERBATIM EVIDENCE REQUIRED]: For "in_vitro_data" and "in_vivo_data", DO NOT summarize, paraphrase, or interpret. YOU MUST EXTRACT SENTENCES VERBATIM (THE EXACT, ORIGINAL WORDS FROM THE ABSTRACT). If no explicit assay/data is stated for the claimed compound, return null.

3. [ANTI-ABBREVIATION RULE]: "compound_name" MUST BE THE FULL, STANDARD CHEMICAL/GENERIC NAME (e.g., "25-hydroxycholesterol", "Navitoclax", "Epigallocatechin gallate"). 
   - NEVER put a short abbreviation or lab token into "compound_name" if its full expansion exists in the text.
   - Example: if the text says "25-hydroxycholesterol (25HC)", "compound_name" must be "25-hydroxycholesterol", and "25HC" goes into "common_names".

The output must be a valid JSON object strictly matching the following schema:
{
    "compound_name": "The specific FULL standard generic/chemical name of the actively verified compound (NO background-only compounds or abbreviations)",
    "common_names": "Alternative names, abbreviations (like 25HC), or codes separated by commas, or null",
    "description": "Brief context of how this compound acts as a verified senolytic in this specific study.",
    "in_vitro_data": "EXACT VERBATIM sentences describing in vitro assays, cell lines, or concentrations showing activity. If none, null.",
    "in_vivo_data": "EXACT VERBATIM sentences describing in vivo animal models, dosages, or durations showing activity. If none, null.",
    "indications": "Diseases or aging-related conditions studied, tissues, or pathologies directly tested.",
    "hypotheses_summary": "Summary of molecular mechanism or pathway targeted (e.g., BCL-2 inhibition, p53 pathway).",
    "doi": "DOI string if found, otherwise null"
}
Return ONLY a valid JSON object. Do not include any markdown styling, explanation, or extra wrapper.
"""

# ====================================================================
# 阶段三：正文特征提取：去除虚构，执行“数据-验证”对齐
# ====================================================================
THIRD_STAGE_FULL_TEXT_PROMPT = """You are an expert pharmacological data extractor specializing in anti-aging and senolytics research. You are given the Introduction and Materials & Methods sections of a scientific paper.
Your task is to identify the EXACT, SPECIFIC small molecule, compound, or natural extract that is the main subject of validation as an active senolytic agent in this study.

CRITICAL LOGIC FOR ELIMINATING COGNITIVE BIAS (ABSOLUTE IRON CLADS):
1. [EXPERIMENTAL VALIDATION FILTER]: DO NOT extract a compound simply because it appears in the text. 
   - The compound MUST be an active agent subjected to experimental evaluation (in vitro or in vivo assays described in the text) in this study.
   - STRICTLY EXCLUDE: Known benchmark senolytics (e.g., ABT-263, Navitoclax, Dasatinib, Quercetin) if they are ONLY cited as historical background, literature examples, or standard reference controls to which the new agent is being compared.
   - NO SPECULATION: If the text introduces a broad chemical family but does not pinpoint the specific validated entity, mark as "UNKNOWN".

2. [NO CLASSES OR MECHANISMS]: Do NOT extract general mechanism names or target pathways (e.g., "GSK3 inhibitors", "BCL-2 inhibitors", "senolytic treatment", "combination therapy") into "compound_name". It must be a discrete chemical entity or clear plant extract name.

3. [ANTI-ABBREVIATION & CHEMICAL STANDARDIZATION]: "compound_name" MUST be the fully expanded, official systematic generic or chemical name found in the text.
   - If the text introduces an agent using a pattern like "Full Name (Abbreviation)", e.g., "25-hydroxycholesterol (25HC)", you are REQUIRED to output the Full Name as "compound_name" and push "25HC" into "common_names".

The output must be a valid JSON object strictly matching the following schema:
{
    "is_specific_compound_found": "YES" if a specific compound was actively evaluated and validated in this text, otherwise "NO",
    "compound_name": "The specific FULL standard name of the actively validated compound (e.g., '25-hydroxycholesterol'), or 'UNKNOWN' if only background/classes are mentioned",
    "common_names": "Short acronyms (e.g., '25HC'), brand names, or lab codes separated by commas, if none, null",
    "description": "A brief background of this specific compound and its active senolytic role in the context of this study.",
    "in_vitro_data": "Verbatim sentences from the text describing the exact in vitro assays/concentrations applied to this specific compound. If none, null.",
    "in_vivo_data": "Verbatim sentences from the text describing the exact in vivo animal models/dosages applied to this specific compound. If none, null.",
    "indications": "Target diseases, tissues, or age-related pathologies directly tested with this compound. If none, null.",
    "hypotheses_summary": "Proposed mechanism of action or target molecular pathway for this specific compound."
}
Return ONLY a valid JSON object. Do not include any markdown styling, explanation, or extra wrapper.
"""





# ====================================================================
# 阶段四：长尾疑似物 AI 判断
# ====================================================================
AMBIGUOUS_CHEMICAL_REVIEW_PROMPT = """You are a professional chemical nomenclature and pharmacological data cleaning expert.
Your task is to determine whether a given term extracted from biological literature is a valid, standalone chemical compound/drug code, or just an unmeaningful functional group fragment / truncation artifact caused by text splitting.

CRITICAL JUDGMENT CRITERIA:
1. [MARK AS YES (JUNK FRAGMENT)]:
   - The term is merely a functional group, substituent, or a broken chemical name residue that CANNOT exist as a standalone bio-active molecule in a screening assay.
   - Examples: "butoxy", "methyl", "ethyl", "4-", "pyrrolidin-1-yl", "acetyl", "benzyl ester residue".

2. [MARK AS NO (VALID ENTITY)]:
   - The term is a valid, discrete chemical compound, a natural plant crude extract, or a specific laboratory drug token/code, EVEN IF it is rare, newly synthesized, or missing from major public databases like PubChem.
   - Examples: "ABT-263", "A-1155463", "Astragaloside IV", "Puerarin", "Target-12", "Compound 4b" (if treated as the active agent).

Input Term to Evaluate: {compound_name}
Context Snippet from Paper: {context_snippet}

The output must be a valid JSON object strictly matching the following schema:
{{
    "is_explicit_junk_fragment": "YES" or "NO",
    "reason": "A brief one-sentence English reason for this judgment."
}}
Return ONLY a valid JSON object. Do not include any markdown styling, explanation, or extra wrapper.
"""




