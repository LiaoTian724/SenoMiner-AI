# Goal
You will be given a paper about molecular glues. The paper is delimited by triple backticks (``` ... ```). Your goal is to extract measurements of molecular glue degradation assays, specifically focusing on DC50 and Dmax assay values. 

# Required Fields

Extract the following 13 fields:

- Compound_Name: Name of the molecular glue compound.
- IUPAC_Name: IUPAC chemical name of the compound.
- SMILES: SMILES string of the compound.
- Degradation_Target: The target protein to be degraded.
- Recruiter: E3 ligase (or E3 ligase-recruiting protein) involved in the degradation process.
- Assay: The assay method used to measure degradation
- Cell_Line: The specific cell line used for the assay; if a cell-free assay is used, denote this as 'cell-free'
- DC50: The compound concentration required to achieve 50% degradation of the target protein.
- DC50_units: Units for DC50 measurement.
- DC50_h: Timepoint for DC50 measurement.
- Dmax: The maximal degradation observed (out of 100%).
- Dmax_h: Timepoint for Dmax measurement.
- Dmax_concentration: Concentration at which Dmax was measured.

# Extraction Principles
Do not infer timepoints: only populate DC50_h (and Dmax_h) when the paper explicitly ties that time to the specific metric; otherwise leave blank; preserve reported qualifiers (~, <, >) exactly for DC50/Dmax and concentrations—do not coerce or round.
For Compound_Name, use the paper's exact compound identifier by stripping generic prefixes (e.g., "Compound"), preserving suffixes (e.g., a/b), and normalizing whitespace/case; when parsing tables, link each numeric value to its row's compound ID and cell line to avoid mislabeling or duplication.

# Output Format
- Output a single JSON array of objects, with no added commentary or explanation.
- Each object corresponds to a single experiment and only contains the fields listed under 'Required Fields'.
Example: [{"Compound_Name": "...", "IUPAC_Name": "...", ...}]