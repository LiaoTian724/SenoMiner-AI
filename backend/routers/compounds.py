import sqlite3
import json
from fastapi import APIRouter, HTTPException
from ai_miner.db_manager import DB_PATH
\
router = APIRouter(tags=["数据网关"])

@router.get("/api/v1/compounds/list")
def get_compounds_list():
    """ 
    读取化合物列表
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM senolytic_compounds 
        ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    cleaned_list = []
    for row in rows:
        item = dict(row)
        
        try:
            ext_meta = json.loads(item.get("additional_metadata") or "{}")
        except:
            ext_meta = {}
            
        for k, v in ext_meta.items():
            if k not in item:
                item[k] = v
                
        cleaned_list.append(item)
        
    return {"status": "success", "data": cleaned_list}


# ------------------------------
# 删除接口
# ------------------------------
@router.delete("/api/v1/compounds/{compound_id}")
def delete_compound(compound_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM senolytic_compounds WHERE id = ?", (compound_id,))
        exists = cursor.fetchone()
        
        if not exists:
            conn.close()
            raise HTTPException(status_code=404, detail="化合物不存在")
        
        # 执行删除
        cursor.execute("DELETE FROM senolytic_compounds WHERE id = ?", (compound_id,))
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": "删除成功"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")