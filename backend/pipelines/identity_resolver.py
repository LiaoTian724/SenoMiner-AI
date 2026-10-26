import requests
import urllib.parse

def fetch_strict_external_ids(compound_name: str, smiles: str = None):
    chembl_id = "N/A"
    drugbank_id = "N/A"
    
    if not compound_name:
        print("\033[91m[错误] 化合物名称为空！\033[0m")
        return chembl_id, drugbank_id

    target_name = compound_name.strip()
    print(f"\n=== 开始查询外部ID: {target_name} ===")

    # 1. 查 ChEMBL
    try:
        url = f"https://www.ebi.ac.uk/chembl/api/data/molecule?pref_name__iexact={urllib.parse.quote(target_name)}&format=json"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        
        if res.status_code == 200:
            mols = res.json().get('molecules', [])
            if mols:
                chembl_id = mols[0].get('molecule_chembl_id', 'N/A')
                print(f"[ChEMBL] 成功: {chembl_id}")
                
                xrefs = mols[0].get('cross_references', [])
                for ref in xrefs:
                    if ref.get('xref_src') == 'DrugBank':
                        drugbank_id = ref.get('xref_id', 'N/A')
                        print(f"[DrugBank] 从ChEMBL关联: {drugbank_id}")
                        break
            else:
                print(f"[ChEMBL] 未找到: {target_name}")
        else:
            print(f"[ChEMBL] 请求失败，状态码: {res.status_code}")
    except Exception as e:
        print(f"[ChEMBL] 异常: {e}")

    # 2. SMILES 兜底
    if (chembl_id == "N/A" or drugbank_id == "N/A") and smiles:
        print(f"[SMILES] 启动兜底查询: {smiles[:30]}...")
        try:
            pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{urllib.parse.quote(smiles)}/property/Title/JSON"
            pc_res = requests.get(pubchem_url, timeout=8)
            if pc_res.status_code == 200:
                cid = pc_res.json().get('PropertyTable', {}).get('Properties', [{}])[0].get('CID')
                if cid:
                    unichem_url = f"https://www.ebi.ac.uk/unichem/rest/src_compound_id/{cid}/2"
                    uc_res = requests.get(unichem_url, timeout=8)
                    if uc_res.status_code == 200 and isinstance(uc_res.json(), list):
                        for mapping in uc_res.json():
                            src_id = str(mapping.get('src_id'))
                            comp_id = mapping.get('src_compound_id')
                            if src_id == '1' and chembl_id == "N/A":
                                chembl_id = comp_id
                                print(f"[SMILES] 查到 ChEMBL: {chembl_id}")
                            if src_id == '3' and drugbank_id == "N/A":
                                drugbank_id = comp_id
                                print(f"[SMILES] 查到 DrugBank: {drugbank_id}")
        except Exception as e:
            print(f"[SMILES] 异常: {e}")

    # 3. 同义词查 DrugBank
    if drugbank_id == "N/A":
        try:
            syn_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(target_name)}/synonyms/JSON"
            syn_res = requests.get(syn_url, timeout=8)
            if syn_res.status_code == 200:
                synonyms = syn_res.json().get('InformationList', {}).get('Information', [{}])[0].get('Synonym', [])
                for syn in synonyms:
                    if syn.startswith("DB") and len(syn) == 7 and syn[2:].isdigit():
                        drugbank_id = syn
                        print(f"[同义词] 查到 DrugBank: {drugbank_id}")
                        break
        except Exception:
            pass

    print(f"=== 查询结束 | ChEMBL: {chembl_id} | DrugBank: {drugbank_id} ===\n")
    return chembl_id, drugbank_id