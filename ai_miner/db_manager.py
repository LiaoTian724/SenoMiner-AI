
import sqlite3
import os
import json
from backend.pipelines.identity_resolver import fetch_strict_external_ids

# 数据库文件直接生成在根目录下
DB_PATH = os.path.join(os.path.dirname(__file__), '../senolytics_data.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("[+] 检测到数据库重置，正在初始化全新、带动态扩展槽的数据表结构...")

    # 文献主表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            pmid TEXT PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            status INTEGER DEFAULT 0,
            reason TEXT,
            compound_count INTEGER DEFAULT 0,  -- 默认零计数
            pmc_id TEXT DEFAULT NULL,          -- 原生支持真实 PMC 映射
            is_open_access INTEGER DEFAULT 0,   -- 原生支持开源标识
            additional_metadata TEXT DEFAULT '{}' -- 文献层面的动态扩展槽
        )
    ''')
    print("articles 新主表创建成功")

    # 化合物表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS senolytic_compounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid TEXT, 
            compound_name TEXT, 
            common_names TEXT DEFAULT 'N/A',
            description TEXT DEFAULT '',
            cas_number TEXT DEFAULT 'N/A', 
            doi TEXT DEFAULT 'N/A', 
            indications TEXT DEFAULT '', 
            hypotheses_summary TEXT DEFAULT '', 
            in_vitro_data TEXT DEFAULT '', 
            in_vitro_anchor TEXT DEFAULT '',
            in_vivo_data TEXT DEFAULT '', 
            in_vivo_anchor TEXT DEFAULT '',
            pub_date TEXT DEFAULT 'N/A',
            pmc_id TEXT DEFAULT NULL,           
            is_open_access INTEGER DEFAULT 0,    
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            additional_metadata TEXT DEFAULT '{}', -- 化合物层面的动态扩展槽
            FOREIGN KEY (pmid) REFERENCES articles(pmid)
        )
    ''')
    print("[+] senolytic_compounds 全新子表创建成功")

    # 显式建立联合唯一性索引
    try:
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pmid_compound 
            ON senolytic_compounds (pmid, compound_name)
        ''')
        print("成功建立唯一性索引: idx_pmid_compound")
    except sqlite3.OperationalError as e:
        print(f"联合索引初始化跳过（或已存在）: {e}")

    conn.commit()
    conn.close()
    print("新数据库结构初始化完成")


def save_raw_article(pmid, title, abstract, pmc_id=None, is_open_access=0, additional_metadata='{}'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO articles (pmid, title, abstract, pmc_id, is_open_access, compound_count, additional_metadata) 
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (str(pmid), title, abstract, pmc_id, is_open_access, additional_metadata))
        
        if cursor.rowcount == 0:
            print(f"PMID {pmid} 数据库已存在或插入被忽略")
        else:
            print(f"PMID {pmid} 成功存入数据库 (PMC: {pmc_id}, OA: {is_open_access})")
            
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.OperationalError as e:
        print(f"数据库结构异常: {e}")
        return False
    except Exception as e:
        print(f"数据库未知错误: {e}")
        return False
    finally:
        conn.close()


def insert_custom_compound(data_dict: dict, db_path: str = None) -> bool:
    current_db_path = db_path if db_path else DB_PATH
    conn = sqlite3.connect(current_db_path, timeout=30)
    
    cursor = conn.cursor()
    try:
        pmid = data_dict.get("pmid")
        compound_name = data_dict.get("compound_name")
        is_open_access = data_dict.get("is_open_access")

        # 自动补 ID
        smiles = data_dict.get("smiles")
        chembl_id, drugbank_id = fetch_strict_external_ids(compound_name, smiles)
        data_dict["chembl_id"] = chembl_id
        data_dict["drugbank_id"] = drugbank_id

        if is_open_access is None and pmid:
            cursor.execute("SELECT is_open_access FROM articles WHERE pmid = ?", (str(pmid),))
            row = cursor.fetchone()
            is_open_access = row[0] if row else 0

        core_fields = {
            "pmid", "compound_name", "common_names", "description", "cas_number",
            "doi", "indications", "hypotheses_summary", "in_vitro_data", "in_vitro_anchor",
            "in_vivo_data", "in_vivo_anchor", "pub_date", "pmc_id", "is_open_access"
        }

        ext_data = {}
        for k, v in data_dict.items():
            if k not in core_fields:
                ext_data[k] = v
        metadata_json_str = json.dumps(ext_data, ensure_ascii=False)

        cursor.execute("""
            INSERT INTO senolytic_compounds (
                compound_name, common_names, description, cas_number, pmid, 
                doi, indications, hypotheses_summary, in_vitro_data, in_vitro_anchor,
                in_vivo_data, in_vivo_anchor, pub_date, pmc_id, is_open_access, 
                additional_metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(pmid, compound_name) DO UPDATE SET
                common_names = excluded.common_names,
                description = excluded.description,
                cas_number = excluded.cas_number,
                doi = excluded.doi,
                indications = excluded.indications,
                hypotheses_summary = excluded.hypotheses_summary,
                in_vitro_data = excluded.in_vitro_data,
                in_vitro_anchor = excluded.in_vitro_anchor,
                in_vivo_data = excluded.in_vivo_data,
                in_vivo_anchor = excluded.in_vivo_anchor,
                pub_date = excluded.pub_date,
                pmc_id = excluded.pmc_id,
                is_open_access = excluded.is_open_access,
                additional_metadata = excluded.additional_metadata,
                created_at = datetime('now', 'localtime')
        """, (
            compound_name, 
            data_dict.get("common_names") or "N/A", 
            data_dict.get("description") or "",
            data_dict.get("cas_number") or "N/A", 
            str(pmid), 
            data_dict.get("doi") or "N/A", 
            data_dict.get("indications") or "",
            data_dict.get("hypotheses_summary") or "", 
            data_dict.get("in_vitro_data") or "", 
            data_dict.get("in_vitro_anchor") or "",
            data_dict.get("in_vivo_data") or "", 
            data_dict.get("in_vivo_anchor") or "", 
            data_dict.get("pub_date") or "N/A",
            data_dict.get("pmc_id"),
            is_open_access,
            metadata_json_str
        ))
        
        cursor.execute("""
            UPDATE articles 
            SET compound_count = (SELECT COUNT(*) FROM senolytic_compounds WHERE pmid = ?) 
            WHERE pmid = ?
        """, (str(pmid), str(pmid)))

        conn.commit()
        print(f"化合物记录 [{compound_name}] 已成功入库")
        return True
    except Exception as e:
        conn.rollback()
        print(f"数据库记录录入失败: {e}")
        raise e
    finally:
        conn.close()




def bump_all_compounds_by_pmid(pmid: str):
    """
    不管新旧, 只要属于这篇文献(PMID)的化合物，一律将对应的 created_at 时间刷新到当前最新的一秒
    """
    if not pmid:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # 强刷该 PMID 对应的所有化合物的时间戳
        cursor.execute("""
            UPDATE senolytic_compounds 
            SET created_at = datetime('now', 'localtime') 
            WHERE pmid = ?
        """, (str(pmid),))
        conn.commit()
        print(f"已将 PMID {pmid} 的所有化合物捆绑置顶")
    except Exception as e:
        print(f"修改时间戳失败: {e}")
    finally:
        conn.close()