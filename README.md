# SenoMiner-AI: Senolytics Knowledge Discovery and Mining Pipeline via LLM Agents

本项目基于 metapub 项目进行二次开发和修改
原项目: https://github.com/metapub/metapub




# 配置环境
确保你已安装 Anaconda 或 Miniconda: 
conda env create -f environment.yml
conda activate SenolyticsRepository


# 启动后端:
cd backend
python -m uvicorn main:app --reload

# 启动前端(换新终端):
cd frontend
npm install
npm run dev

