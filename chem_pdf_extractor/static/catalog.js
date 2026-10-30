'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let state = {compounds:[],papers:[],local_pdfs:[],summary:{}};
let selected = null, selectedPart = 0, structureSdf = '', renderMode = 'auto', molecularStyle = 'ballstick', initialMoleculeView = null, stopAnimation = null, webglViewer = null, moleculeLoad = 0;
let catalogPage = 1, pageSize = 5;
let catalogRenderKey = '', previewGeneration = 0, previewStops = [];
const structureCache = new Map();
let actionPending=false, refreshedAt=Date.now();

async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'X-Chem-PDF-Extractor-Token':window.LOCAL_TOKEN,...(options.headers||{})}});
  const body = await response.json();
  if(response.status===403)throw Error("页面连接已过期，请刷新页面后继续。");
  if (!response.ok || body.ok === false) throw Error(body.error || '请求失败');
  return body;
}
function message(value, error=false) { $('message').textContent=value; $('message').classList.toggle('error',error); }
function clip(value,n=110) { const s=String(value||'').replace(/\s+/g,' ').trim(); return s.length>n?s.slice(0,n-1)+'…':s; }
function paperLabel(p) { return p?.title||p?.source_name||'文献名称待核对'; }
function dateLabel(value) { const date=new Date(value); return Number.isNaN(date.getTime())?'':date.toLocaleString('zh-CN',{hour12:false}); }
function sourceLink(p) { const url=/^https?:\/\//.test(p.url||'')?p.url:(/^\d+$/.test(p.pmid)?`https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/`:(/^10\./.test(p.doi||'')?`https://doi.org/${encodeURI(p.doi)}`:'')); return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(paperLabel(p))}</a>`:esc(paperLabel(p)); }
function compoundParts(item) { const id=item.identity||{}; return id.components?.length?id.components:[id]; }
function structureData(cid) {
  const key=String(cid);
  if(!structureCache.has(key)) {
    const promise=api(`/api/catalog/structure?cid=${encodeURIComponent(key)}`).catch(error=>{structureCache.delete(key);throw error});
    structureCache.set(key,promise);
    if(structureCache.size>64)structureCache.delete(structureCache.keys().next().value);
  }
  return structureCache.get(key);
}
function previewHtml(item,index) {
  const parts=compoundParts(item);
  return `<div class="molecule-previews ${parts.length>1?'combination-previews':''}">${parts.map((part,i)=>`<div class="molecule-preview"><div class="preview-frame" id="preview-${index}-${i}" data-molecule="${esc(part.name||item.name)}"><span class="preview-loading">${part.cid?'加载结构…':'暂无结构'}</span></div>${parts.length>1?`<small>${esc(part.name)}</small>`:''}<small id="preview-source-${index}-${i}" class="preview-source"></small></div>`).join('')}</div>`;
}
async function renderPreviews(items,generation) {
  await Promise.all(items.flatMap(item=>compoundParts(item).map(async(part,i)=>{
    const index=state.compounds.indexOf(item),box=$(`preview-${index}-${i}`);
    if(!box||!/^\d+$/.test(String(part.cid||'')))return;
    try {
      const data=await structureData(part.cid);
      if(generation!==previewGeneration||!box.isConnected)return;
      previewStops.push(preview3D(data.sdf,box));
      const caption=$(`preview-source-${index}-${i}`);
      caption.textContent=data.origin==='rdkit_etkdg'?'计算构象':'PubChem';
      caption.title=(data.label||'')+'；拖动分子可旋转';
    } catch(error) {
      if(generation!==previewGeneration||!box.isConnected)return;
      box.innerHTML=`<span class="preview-loading">暂无法显示<br><button data-retry-preview="1">重试</button></span>`;
      box.title=error.message;
    }
  })));
}
function recordMatches(record,q,study,effect) {
  if(study&&record.study_type!==study||effect&&record.effect_type!==effect)return false;
  const source=record.source||{};
  const text=[record.compound_name,record.result,record.study_label,record.effect_label,record.model,record.induction,record.induction_agent,record.induction_conditions,record.recovery,record.dose,record.duration,record.route,record.control,record.sample_size,record.assay,source.title,source.pmid,source.doi].join(' ').normalize('NFKC').toLocaleLowerCase();
  return q.normalize('NFKC').toLocaleLowerCase().split(/\s+/).filter(Boolean).every(word=>text.includes(word));
}
function recordQuery() { return {q:$('catalogSearch').value.trim().toLocaleLowerCase().slice(0,200),study:$('studyFilter').value,effect:$('effectFilter').value}; }
function renderCatalog() {
  const {q,study,effect}=recordQuery();
  const items=state.compounds.filter(c=>c.papers.some(p=>(p.experiment_records||[]).some(r=>recordMatches(r,q,study,effect))));
  const totalPages=Math.max(1,Math.ceil(items.length/pageSize)); catalogPage=Math.max(1,Math.min(catalogPage,totalPages));
  const pageItems=items.slice((catalogPage-1)*pageSize,catalogPage*pageSize);
  $('catalogCount').textContent=`${state.summary.compounds||0} 个化合物/组合 · ${state.summary.papers||0} 篇文献`;
  const pending=state.papers.filter(p=>p.review_status!=='complete'||p.card_status!=='complete').length;
  $('statusLine').textContent=`按文献读取时间从新到旧排列。${pending?` ${pending} 篇尚待完成核对。`:''}`;
  const key=JSON.stringify([q,study,effect,catalogPage,pageSize,pageItems.map(c=>[c.id,c.name,c.identity,c.papers.map(p=>[p.title,p.read_at])])]);
  if(key!==catalogRenderKey) {
    catalogRenderKey=key;const generation=++previewGeneration;
    previewStops.forEach(stop=>stop());previewStops=[];
    $('catalogRows').innerHTML=pageItems.length?pageItems.map(c=>{
      const index=state.compounds.indexOf(c);
      return `<tr><td><strong>${esc(c.name)}</strong></td><td class="structure-cell">${previewHtml(c,index)}</td><td class="source-title">${c.papers.map(p=>`<div>${sourceLink(p)}<br><small class="muted">读取：${esc(dateLabel(p.read_at))}</small></div>`).join('')}</td><td><button data-open="${index}">查看详情</button></td></tr>`;
    }).join(''):'<tr><td colspan="4" class="empty">没有符合条件的化合物。</td></tr>';
    renderPreviews(pageItems,generation);
  }
  $('pageSelect').innerHTML=Array.from({length:totalPages},(_,i)=>`<option value="${i+1}" ${catalogPage===i+1?'selected':''}>${i+1}</option>`).join('');
  $('pageInfo').textContent=`共 ${items.length} 条 · 第 ${catalogPage} / ${totalPages} 页`;
  $('prevPage').disabled=catalogPage===1; $('nextPage').disabled=catalogPage===totalPages;
  const waiting=state.local_pdfs.filter(p=>!p.processed&&!(state.running&&state.task?.kind==='pdf'&&state.task.source===p.name)),done=state.local_pdfs.filter(p=>p.processed);
  $('localPdfRows').innerHTML=waiting.length?`<p class="muted small">待提取文件</p>${waiting.map(p=>`<div class="local-item">${esc(p.name)}<button data-pdf="${esc(p.name)}" ${state.running||actionPending?'disabled':''}>${state.running&&state.task?.source===p.name?'正在提取…':'提取这篇 PDF'}</button></div>`).join('')}`:'';
  $('completedPdfLabel').textContent=`已完成文件（${done.length}）`;
  $('completedPdfRows').innerHTML=done.map(p=>`<div class="completed-file">${esc(p.name)}</div>`).join('');
  $('uploadBtn').disabled=state.running||actionPending;
  $('importIdentifier').disabled=state.running||actionPending;
  for(const b of $('searchResultRows').querySelectorAll('[data-import]'))b.disabled=state.running||actionPending;
  renderProgress();
}
function elapsedLabel(seconds) { const n=Math.max(0,Math.floor(seconds));return n<60?`${n} 秒`:`${Math.floor(n/60)} 分 ${n%60} 秒`; }
function updateElapsed() { const t=state.task,box=$('taskElapsed');if(t&&box)box.textContent=elapsedLabel(t.elapsed_seconds+(state.running?(Date.now()-refreshedAt)/1000:0)); }
function renderProgress() {
  const t=state.task;
  if(!t){$('taskProgress').innerHTML='<p class="muted small">上传 PDF，或输入 DOI / PMID 开始提取。</p>';return}
  const stages=[['loading','读取'],['extracting','提取'],['reviewing','核对'],['linking','关联实验'],['enriching','查库'],['saving','保存']];
  const activity=t.events?.length?t.events[t.events.length-1].message:'';
  const active=stages.findIndex(([id])=>id===t.stage),finished=t.status==='complete';
  $('taskProgress').innerHTML=`<p class="task-source">${esc(t.source)}</p><strong class="task-status ${t.status==='failed'?'error':''}">${state.running?'正在运行 · ':''}${esc(t.stage_label)}</strong>
    <ol class="task-stages">${stages.map(([id,label],i)=>`<li class="${finished||i<active?'done':i===active?'current':''}">${esc(label)}</li>`).join('')}</ol>
    ${state.running?`<progress aria-label="${esc(t.stage_label)}" ${t.total?`value="${t.completed}" max="${t.total}"`:''}></progress>`:''}
    <p class="task-message ${t.error?'error':''}">${esc(t.message)}</p>
    ${state.running&&/重试|拆分/.test(activity)?`<p class="small muted">${esc(activity)}</p>`:''}
    <p class="muted small">${state.running?'已运行':'耗时'} <span id="taskElapsed"></span>${state.running?' · 自动更新；等待模型时耗时仍会增加':''}</p>
    ${t.status==='failed'?'<button data-retry-task="1">重试并继续</button><p class="muted small">复用已完成分段，无需从头提取。</p>':''}
    ${t.events?.length?`<details class="task-log"><summary>运行记录</summary><ol>${t.events.slice(-12).map(e=>`<li>${esc(new Date(e.time*1000).toLocaleTimeString('zh-CN',{hour12:false}))} ${esc(e.message)}</li>`).join('')}</ol></details>`:''}`;
  updateElapsed();
}
let refreshing=false;
async function refresh() { if(refreshing)return;refreshing=true;try { const data=await api('/api/catalog');if(!actionPending){state=data;refreshedAt=Date.now();renderCatalog()} } catch(e) { message(`无法更新进展：${e.message}`,true); }finally{refreshing=false} }
async function beginExtraction(kind,source) {
  if(actionPending||state.running){message('已有文献正在处理，请查看右侧提取进展。',true);return}
  actionPending=true;
  $('taskProgress').innerHTML=`<p class="task-source">${esc(source)}</p><strong>正在启动提取…</strong><progress aria-label="正在启动"></progress>`;
  $('uploadBtn').disabled=true;$('importIdentifier').disabled=true;
  try {
    const data=await api(kind==='pdf'?'/api/catalog/process-pdf':'/api/catalog/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(kind==='pdf'?{name:source}:{identifier:source})});
    state={...state,...data};refreshedAt=Date.now();message('已开始提取，请查看右侧进展。');
  }catch(e){message(e.message,true)}finally{actionPending=false;renderCatalog();await refresh()}
}
function studyLabel(type) { return ({clinical:'人体给药研究',ex_vivo:'离体组织实验',in_vitro:'细胞实验',in_vivo:'动物实验'})[type]||'实验类型待核对'; }
function outcomeHtml(o) {
  return `<details class="outcome"><summary>${esc(o.assay||o.endpoint||'检测结果')}</summary>
  <p><b>结果：</b>${esc(o.result)}</p><p><b>检测方法：</b>${esc(o.assay||'原文未报告')}　<b>样本数：</b>${esc(o.sample_size||'原文未报告')}</p>
  <p><b>对照：</b>${esc(o.control||'原文未报告')}　<b>统计：</b>${esc(o.statistics||'原文未报告')}</p>
  <p class="quote"><b>原文结果引文：</b> ${esc(o.quote)}</p><p class="muted">来源 ${esc(o.location)}</p></details>`;
}
function technicalHtml(g) {
  const evidence=Object.entries(g.protocol_evidence||{}).filter(([,v])=>v?.quote);
  const labels={model:'研究对象',dose:'活性药物剂量',duration:'处理时间',route:'给药',control:'对照',sample_size:'样本量',assay:'检测方法',induction:'造模 / 预处理',induction_agent:'衰老诱导剂',induction_conditions:'诱导条件',recovery:'恢复培养'};
  return `<details class="technical"><summary>原文参数与更多检测结果</summary>${evidence.length?`<details class="outcome"><summary>实验参数的原文</summary>${evidence.map(([k,v])=>`<p><b>${esc(labels[k]||k)}：</b>${esc(v.quote)}</p>`).join('')}</details>`:''}${g.outcomes.map(outcomeHtml).join('')}
  <details class="outcome"><summary>原文实验步骤（${g.steps.length}）</summary>${g.steps.length?`<ol class="steps">${g.steps.map(s=>`<li>${esc(s.action)}<div class="quote">${esc(s.quote)}</div></li>`).join('')}</ol>`:'<p class="small muted">原文未提供可核对的连续步骤，请查 Methods 与补充材料。</p>'}</details></details>`;
}
function protocolHtml(story) {
  const steps=story.reading_steps?.length?story.reading_steps:[
    story.model?`实验对象：${story.model}`:'实验对象：原文未报告',
    story.induction?`造模 / 预处理：${story.induction}`:'',
    [story.dose,story.route,story.duration].filter(Boolean).length?`药物处理：${[story.dose,story.route,story.duration].filter(Boolean).join('；')}`:'剂量与处理时间：原文未报告',
    story.assay?`检测方法：${story.assay}`:'检测方法：原文未报告'
  ].filter(Boolean);
  return `<ol class="experiment-steps">${steps.map(step=>`<li>${esc(step)}</li>`).join('')}</ol>`;
}
function experimentTable(record) {
  const rows=[['实验类型',record.study_label],['论文报告作用类型',record.effect_label],['研究对象',record.model]];
  if(record.induction_agent)rows.push(['衰老诱导剂',record.induction_agent]);
  if(record.induction_conditions)rows.push(['诱导条件',record.induction_conditions]);
  else if(record.induction)rows.push(['造模 / 预处理',record.induction]);
  if(record.recovery)rows.push(['恢复培养',record.recovery]);
  rows.push(['活性药物浓度 / 剂量',record.dose],['处理时间',record.duration]);
  if(record.route)rows.push(['给药方式 / 频率',record.route]);
  rows.push(['对照',record.control]);
  if(record.sample_size)rows.push(['样本量',record.sample_size]);
  rows.push(['检测方法',record.assay],['实验结果',record.result]);
  return `<table class="experiment-table"><caption>实验条件与结果</caption><thead><tr><th scope="col">字段</th><th scope="col">论文中的实验数据</th></tr></thead><tbody>${rows.map(([label,value])=>`<tr><th scope="row">${esc(label)}</th><td>${value?esc(value):'<span class="unreported">未提取</span>'}</td></tr>`).join('')}</tbody></table>`;
}
function experimentRecordHtml(record,group,story) {
  return `<section class="experiment-record">${experimentTable(record)}
    <section class="record-evidence"><h4>原文证据</h4><p class="citation">${esc(record.evidence_location)}</p><blockquote>${esc(String(record.evidence_quote||'').replace(/\s+/g,' '))}</blockquote></section>
    <p class="record-conclusion"><b>实验结论：</b>${esc(record.conclusion||'未提取')}</p>
    <details class="protocol-details"><summary>详细实验操作与原文参数</summary>${protocolHtml(story)}${technicalHtml(group)}</details>
  </section>`;
}
function paperHtml(p) {
  const query=recordQuery(),all=p.experiment_records||[];
  const records=all.filter(r=>recordMatches(r,query.q,query.study,query.effect));
  if(!records.length)return '';
  const links=[/^\d+$/.test(p.pmid)?`<a href="https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/" target="_blank" rel="noopener noreferrer">PMID ${p.pmid}</a>`:'',p.doi?`<a href="https://doi.org/${encodeURI(p.doi)}" target="_blank" rel="noopener noreferrer">DOI ${esc(p.doi)}</a>`:''].filter(Boolean).join(' · ');
  const render=record=>{const group=p.groups.find(g=>g.id===record.group_id);const story=record.primary?p.lead_claim:group?.story;return group?experimentRecordHtml(record,group,story||{}):''};
  const [primary,...others]=records;
  return `<article class="paper-story"><h3 class="record-heading">实验记录</h3>${records.length<all.length?'<p class="small muted">显示符合当前筛选条件的实验。</p>':''}${render(primary)}
    <section class="literature-source"><h4>文献来源</h4><p>${sourceLink(p)}</p><p class="citation">${links}${p.year?' · '+esc(p.year):''}</p><p class="citation">${esc(p.source_name)}</p></section>
    ${others.length?`<details class="other-experiments"><summary>同篇其他独立实验（${others.length}）</summary>${others.map((record,i)=>`<details class="extra-experiment"><summary>实验 ${i+2} · ${esc(record.title)} · ${esc(record.study_label)}</summary>${render(record)}</details>`).join('')}</details>`:''}</article>`;
}
function identityHtml(id) {
  const parts=id.components?.length?id.components:[id];
  const links=parts.flatMap(p=>{
    const a=[];
    if(/^\d+$/.test(String(p.cid||''))) a.push(`<a href="https://pubchem.ncbi.nlm.nih.gov/compound/${p.cid}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · PubChem ${p.cid}</a>`);
    if(/^CHEMBL\d+$/.test(String(p.chembl_id||''))) a.push(`<a href="https://www.ebi.ac.uk/chembl/explore/compound/${p.chembl_id}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · ${esc(p.chembl_id)}</a>`);
    return a;
  });
  return `<section class="compound-overview" aria-label="化合物信息与分子结构"><div class="identity-grid"><div class="viewer-panel"><strong>3D 分子结构</strong><div class="component-tabs" id="componentTabs">${parts.map((p,i)=>`<button data-part="${i}" class="${i===0?'active':''}">${esc(p.name||id.name)}</button>`).join('')}</div><div id="moleculeView" class="molecule-view"><div class="viewer-message">正在读取 3D 结构…</div></div><div class="viewer-actions"><button data-style="ballstick" aria-pressed="true">球棍</button><button data-style="spacefill" aria-pressed="false">空间填充</button><button data-reset="1">重置视角</button><button data-mode="canvas" title="浏览器无法正常显示立体模型时使用">兼容显示</button></div><p class="viewer-note" id="viewerStatus" role="status"></p><p class="viewer-note" id="structureOrigin">PubChem 构象或 RDKit 计算构象，可拖动旋转。</p></div><div><h3 id="componentName">${esc(parts[0]?.name||id.name)}</h3><div class="properties" id="componentProps"></div><div class="external-links">${links.join('')}</div><details class="related-literature"><summary>拓展：PubMed 相关文献</summary><div id="relatedLiterature"></div></details></div></div></section>`;
}
function openDetail(index) {
  selected=state.compounds[index]; selectedPart=0; renderMode='auto'; molecularStyle='ballstick'; if(!selected)return;
  $('detailTitle').textContent=selected.name;
  $('detailBody').innerHTML=`<section class="chemistry-section" aria-label="分子结构与数据库信息"><h3>分子结构与数据库信息</h3>${identityHtml(selected.identity||{})}</section>${selected.papers.map(paperHtml).join('')}`;
  $('detailDialog').showModal(); $('detailDialog').scrollTop=0;
  showMolecule();
}
function setComponentInfo(part) {
  $('componentName').textContent=part.name||selected.name;
  const property=(label,value)=>`<div class="property"><small>${esc(label)}</small>${esc(value||'数据库未返回')}</div>`;
  $('componentProps').innerHTML=property('PubChem CID',part.cid)+property('ChEMBL ID',part.chembl_id)+property('分子式',part.formula)+property('分子量',part.mass)+`<details class="extra-identifiers"><summary>更多名称与结构标识</summary>${property('InChIKey',part.inchikey)}${property('IUPAC 名称',part.iupac_name)}${property('其他名称',(part.synonyms||[]).slice(0,4).join('；'))}</details>`;
  const literature=(part.literature||[]).filter(p=>/^\d+$/.test(String(p.pmid||'')));
  $('relatedLiterature').innerHTML=literature.length?`<h4>PubMed 相关文献</h4><ul class="related-papers">${literature.slice(0,3).map(p=>`<li><a href="https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/" target="_blank" rel="noopener noreferrer">${esc(p.title||'PMID '+p.pmid)}</a></li>`).join('')}</ul><p class="muted small">相关文献单独展示，不用来补当前论文的实验结果。</p>`:'';
  for(const b of $('componentTabs').querySelectorAll('button')) b.classList.toggle('active',Number(b.dataset.part)===selectedPart);
}
function parseSdf(sdf) {
  const lines=sdf.split(/\r?\n/), atoms=[], bonds=[];
  if(sdf.includes('V3000')) {
    let section='';
    for(const line of lines) {
      if(line.includes('BEGIN ATOM')){section='atom';continue} if(line.includes('END ATOM')){section='';continue}
      if(line.includes('BEGIN BOND')){section='bond';continue} if(line.includes('END BOND')){section='';continue}
      const p=line.replace(/^M\s+V30\s+/,'').trim().split(/\s+/);
      if(section==='atom'&&p.length>=5) atoms.push({el:p[1],x:+p[2],y:+p[3],z:+p[4]});
      if(section==='bond'&&p.length>=4) bonds.push([+p[2]-1,+p[3]-1]);
    }
  } else {
    const header=lines.findIndex(l=>/V2000/.test(l)); if(header<0)throw Error('PubChem SDF 格式不受支持');
    const n=parseInt(lines[header].slice(0,3),10),m=parseInt(lines[header].slice(3,6),10);
    if(!n||n>500||!Number.isFinite(m))throw Error('PubChem SDF 原子数无效');
    for(let i=0;i<n;i++){const l=lines[header+1+i]||'';atoms.push({x:+l.slice(0,10),y:+l.slice(10,20),z:+l.slice(20,30),el:l.slice(31,34).trim()});}
    for(let i=0;i<m;i++){const l=lines[header+1+n+i]||'';bonds.push([parseInt(l.slice(0,3),10)-1,parseInt(l.slice(3,6),10)-1]);}
  }
  if(!atoms.length||atoms.some(a=>![a.x,a.y,a.z].every(Number.isFinite)))throw Error('PubChem 3D 坐标无效');
  return {atoms,bonds:bonds.filter(([a,b])=>a>=0&&b>=0&&a<atoms.length&&b<atoms.length)};
}
// Three reusable contexts at most: thumbnail snapshots, hovered thumbnail, detail.
// Moving a stable host preserves 3Dmol's listeners; setContainer would rebind them.
let thumbnailGpu=null, previewGpu=null, detailGpu=null, activePreview=null;
function moleculeStyle(style='ballstick') {
  return style==='spacefill'?{sphere:{colorscheme:'Jmol'}}:{stick:{radius:.16,colorscheme:'Jmol'},sphere:{scale:.32,colorscheme:'Jmol'}};
}
function gpuSlot(interactive=true) {
  const lib=window.$3Dmol||window['3Dmol'];if(!lib)throw Error('立体显示组件尚未加载');
  const parking=document.createElement('div'),host=document.createElement('div');
  parking.className='molecule-render-buffer';host.className='molecule-gpu-host';parking.append(host);document.body.append(parking);
  let viewer;
  try{viewer=lib.createViewer(host,{backgroundColor:'#ffffff',antialias:true,nomouse:!interactive});}
  catch(error){parking.remove();throw error}
  viewer.getCanvas().setAttribute('role','img');viewer.getCanvas().setAttribute('aria-label','分子三维结构，可拖动旋转及滚轮缩放');
  const slot={parking,host,viewer,lost:false,onLost:null,baseView:viewer.getView()};
  viewer.getCanvas().addEventListener('webglcontextlost',e=>{e.preventDefault();slot.lost=true;slot.onLost?.()});
  viewer.getCanvas().addEventListener('webglcontextrestored',()=>{slot.lost=false});
  return slot;
}
function loadGpu(slot,sdf,style='ballstick',view=null) {
  if(slot.lost)throw Error('浏览器立体显示暂不可用');
  const v=slot.viewer;v.removeAllModels();v.addModel(sdf,'sdf');v.setStyle({},moleculeStyle(style));v.resize();v.setView(slot.baseView);
  v.zoomTo();v.rotate(20,'y');v.rotate(-15,'x');if(view)v.setView(view);v.render();
  return v.getView();
}
function parkGpu(slot) {
  slot.onLost=null;slot.parking.append(slot.host);
  if(!slot.lost)slot.viewer.clear();
}
function webglPreview(sdf,box) {
  thumbnailGpu=thumbnailGpu||gpuSlot(false);
  const rect=box.getBoundingClientRect();thumbnailGpu.parking.style.width=`${Math.max(rect.width,80)}px`;thumbnailGpu.parking.style.height=`${Math.max(rect.height,80)}px`;
  const initial=loadGpu(thumbnailGpu,sdf);
  const image=document.createElement('img');image.src=thumbnailGpu.viewer.pngURI();image.alt=`${box.dataset.molecule||'分子'}的立体球棍模型`;image.draggable=false;
  box.replaceChildren(image);box.dataset.renderer='webgl';
  let view=initial,disposed=false,dragging=false,hover=false,fallbackStop=null;
  function deactivate() {
    if(activePreview?.box!==box)return;
    if(!previewGpu.lost){view=previewGpu.viewer.getView();image.src=previewGpu.viewer.pngURI()}
    parkGpu(previewGpu);box.classList.remove('preview-interactive');activePreview=null;
  }
  function fallback(){deactivate();box.dataset.renderer='canvas';fallbackStop=canvas3D(sdf,box,{preview:true,animate:false})}
  function activate() {
    if(disposed||fallbackStop||activePreview?.box===box)return;
    activePreview?.deactivate();
    try {
      previewGpu=previewGpu||gpuSlot();box.append(previewGpu.host);loadGpu(previewGpu,sdf,'ballstick',view);
      box.classList.add('preview-interactive');activePreview={box,deactivate};previewGpu.onLost=fallback;
    } catch(error){if(previewGpu)parkGpu(previewGpu);fallback()}
  }
  function enter(){hover=true;activate()}
  function leave(){hover=false;if(!dragging)deactivate()}
  function down(){dragging=true}
  function up(){dragging=false;if(!hover)deactivate()}
  box.addEventListener('mouseenter',enter);box.addEventListener('mouseleave',leave);box.addEventListener('mousedown',down);window.addEventListener('mouseup',up);
  const resize=new ResizeObserver(()=>{if(activePreview?.box===box&&!previewGpu.lost){previewGpu.viewer.resize();previewGpu.viewer.render()}});resize.observe(box);
  return ()=>{disposed=true;deactivate();fallbackStop?.();resize.disconnect();box.removeEventListener('mouseenter',enter);box.removeEventListener('mouseleave',leave);box.removeEventListener('mousedown',down);window.removeEventListener('mouseup',up)};
}
function preview3D(sdf,box) {
  try{return webglPreview(sdf,box)}
  catch(error){box.dataset.renderer='canvas';return canvas3D(sdf,box,{preview:true,animate:false})}
}
function webgl3D(sdf,box,style) {
  detailGpu=detailGpu||gpuSlot();
  if(detailGpu.lost)throw Error('浏览器立体显示暂不可用');
  box.replaceChildren(detailGpu.host);const initial=loadGpu(detailGpu,sdf,style);webglViewer=detailGpu.viewer;
  detailGpu.onLost=()=>{renderMode='canvas';renderStructure()};box.dataset.renderer='webgl';
  const resize=new ResizeObserver(()=>{if(!detailGpu.lost){webglViewer?.resize();webglViewer?.render()}});resize.observe(box);
  return {initial,stop:()=>{resize.disconnect();parkGpu(detailGpu);webglViewer=null}};
}

function canvas3D(sdf,box,{preview=false,animate=false,style='ballstick'}={}) {
  const {atoms,bonds}=parseSdf(sdf),canvas=document.createElement('canvas'); box.replaceChildren(canvas);
  canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`${box.dataset.molecule||'分子'}的 3D 结构，可拖动旋转`);
  const ctx=canvas.getContext('2d'); if(!ctx)throw Error('浏览器无法创建 Canvas');
  const min=[Math.min(...atoms.map(a=>a.x)),Math.min(...atoms.map(a=>a.y)),Math.min(...atoms.map(a=>a.z))];
  const max=[Math.max(...atoms.map(a=>a.x)),Math.max(...atoms.map(a=>a.y)),Math.max(...atoms.map(a=>a.z))];
  const mid=min.map((v,i)=>(v+max[i])/2);
  const radius=Math.max(...atoms.map(a=>Math.hypot(a.x-mid[0],a.y-mid[1],a.z-mid[2])),1);
  let rx=-0.25,ry=0.5,drag=null,active=true,frame=0,zoom=1;
  const colors={C:'#727b81',H:'#e3e7e9',O:'#c83b35',N:'#365fba',S:'#c29c19',Cl:'#4f9b54',F:'#56a65c',P:'#dd9044'};
  function draw(){if(!active)return;const rect=box.getBoundingClientRect(),dpr=window.devicePixelRatio||1,w=rect.width,h=rect.height;
    if(!w||!h)return;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr)}
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);
    const scale=Math.max(1,Math.min(w,h)-28)/(radius*(style==='spacefill'?3.3:2.7))*zoom;
    const pts=atoms.map(a=>{let x=(a.x-mid[0])*scale,y=(a.y-mid[1])*scale,z=(a.z-mid[2])*scale;
      const xx=x*Math.cos(ry)+z*Math.sin(ry),zz=z*Math.cos(ry)-x*Math.sin(ry);
      const yy=y*Math.cos(rx)-zz*Math.sin(rx),depth=y*Math.sin(rx)+zz*Math.cos(rx);
      const perspective=600/(600-depth);return {x:w/2+xx*perspective,y:h/2-yy*perspective,z:depth,r:({H:1.2,C:1.7,N:1.55,O:1.52,S:1.8,P:1.8,F:1.47,Cl:1.75,Br:1.85,I:1.98}[a.el]||1.7)*scale*(style==='spacefill'?1:.32)*perspective,el:a.el};});
    // Sort atoms and short bond segments together for depth occlusion.
    const pieces=pts.map(p=>({z:p.z,atom:p}));
    if(style!=='spacefill')for(const [a,b] of bonds){const u=pts[a],v=pts[b];for(let j=0;j<12;j++){const t=j/12,k=(j+1)/12;pieces.push({z:u.z+(v.z-u.z)*(t+k)/2,bond:{x:u.x+(v.x-u.x)*t,y:u.y+(v.y-u.y)*t,xx:u.x+(v.x-u.x)*k,yy:u.y+(v.y-u.y)*k,color:colors[t<.5?u.el:v.el]||'#866ea0'}})}}
    for(const piece of pieces.sort((a,b)=>a.z-b.z)) {
      if(piece.bond){const b=piece.bond;ctx.beginPath();ctx.moveTo(b.x,b.y);ctx.lineTo(b.xx,b.yy);ctx.strokeStyle=b.color;ctx.lineWidth=Math.max(1,scale*.25);ctx.lineCap='round';ctx.stroke();continue}
      const p=piece.atom,r=Math.max(1,p.r),base=colors[p.el]||'#866ea0';
      const shade=ctx.createRadialGradient(p.x-r*.32,p.y-r*.38,r*.05,p.x,p.y,r);
      shade.addColorStop(0,'#ffffff');shade.addColorStop(.24,base);shade.addColorStop(.78,base);shade.addColorStop(1,'#394550');
      ctx.beginPath();ctx.arc(p.x,p.y,r,0,Math.PI*2);ctx.fillStyle=shade;ctx.fill();
    }
    if(animate){if(!drag)ry+=0.003;frame=requestAnimationFrame(draw)}}
  function down(e){drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)}
  function move(e){if(!drag)return;ry+=(e.clientX-drag[0])*.012;rx+=(e.clientY-drag[1])*.012;drag=[e.clientX,e.clientY];draw()}
  function up(){drag=null}
  function wheel(e){e.preventDefault();zoom=Math.max(.5,Math.min(2.5,zoom*Math.exp(-e.deltaY*.001)));draw()}
  canvas.addEventListener('wheel',wheel,{passive:false});
  canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);
  canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);canvas.addEventListener('lostpointercapture',up);
  const resize=new ResizeObserver(()=>{if(!animate)draw()});resize.observe(box);
  draw();return ()=>{active=false;cancelAnimationFrame(frame);resize.disconnect();canvas.removeEventListener('wheel',wheel);canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',up);canvas.removeEventListener('lostpointercapture',up)};
}
function renderStructure() {
  if(stopAnimation){stopAnimation();stopAnimation=null} webglViewer=null;initialMoleculeView=null;
  const box=$('moleculeView'); if(!structureSdf){box.innerHTML='<div class="viewer-message">暂无 3D 结构</div>';return}
  let fallback=renderMode==='canvas';
  if(!fallback)try {
    const gpu=webgl3D(structureSdf,box,molecularStyle);stopAnimation=gpu.stop;initialMoleculeView=gpu.initial;
  } catch(error){if(detailGpu)parkGpu(detailGpu);fallback=true}
  if(fallback)try{box.dataset.renderer='canvas';stopAnimation=canvas3D(structureSdf,box,{style:molecularStyle})}
  catch(error){box.innerHTML=`<div class="viewer-message">${esc(error.message)}</div>`}
  $('viewerStatus').textContent=fallback?'当前为兼容显示。可拖动旋转、滚轮缩放。':'立体显示 · 拖动旋转，滚轮缩放。';
  for(const b of $('detailBody').querySelectorAll('[data-style]'))b.setAttribute('aria-pressed',String(b.dataset.style===molecularStyle));
  const toggle=$('detailBody').querySelector('[data-mode]');if(toggle){toggle.dataset.mode=fallback?'auto':'canvas';toggle.textContent=fallback?'尝试立体显示':'兼容显示'}
}
async function showMolecule() {
  const load = ++moleculeLoad;
  const part=compoundParts(selected)[selectedPart]||{};
  setComponentInfo(part);structureSdf='';webglViewer=null;if(stopAnimation){stopAnimation();stopAnimation=null}
  const box=$('moleculeView');box.innerHTML='<div class="viewer-message">正在读取 PubChem 3D 结构…</div>';
  if(!/^\d+$/.test(String(part.cid||''))){box.innerHTML='<div class="viewer-message">此成分没有经过确认的 PubChem CID，无法显示 3D 结构。</div>';return}
  try{const data=await structureData(part.cid);if(load!==moleculeLoad||!$('detailDialog').open)return;structureSdf=data.sdf;$('structureOrigin').textContent=data.label+(data.origin==='rdkit_etkdg'?'（计算生成，非实验测定）。':'。')+' 可拖动旋转。';renderStructure()}
  catch(e){if(load!==moleculeLoad||!$('detailDialog').open)return;box.innerHTML=`<div class="viewer-message">${esc(e.message)}<br><a href="https://pubchem.ncbi.nlm.nih.gov/compound/${part.cid}" target="_blank" rel="noopener noreferrer">查看 PubChem 原站</a></div>`}
}
$('catalogRows').addEventListener('click',e=>{if(e.target.closest('[data-retry-preview]')){catalogRenderKey='';renderCatalog();return}const b=e.target.closest('[data-open]');if(b)openDetail(Number(b.dataset.open))});
$('closeDetail').addEventListener('click',()=>$('detailDialog').close());
$('detailDialog').addEventListener('close',()=>{moleculeLoad++;webglViewer=null;if(stopAnimation){stopAnimation();stopAnimation=null}});
$('detailBody').addEventListener('click',e=>{
  const part=e.target.closest('[data-part]');if(part){selectedPart=Number(part.dataset.part);showMolecule()}
  const style=e.target.closest('[data-style]');if(style&&structureSdf){molecularStyle=style.dataset.style;if(webglViewer){webglViewer.setStyle({},moleculeStyle(molecularStyle));webglViewer.render();for(const b of $('detailBody').querySelectorAll('[data-style]'))b.setAttribute('aria-pressed',String(b.dataset.style===molecularStyle))}else renderStructure()}
  const mode=e.target.closest('[data-mode]');if(mode&&structureSdf){renderMode=mode.dataset.mode;renderStructure()}
  if(e.target.closest('[data-reset]')){if(webglViewer){webglViewer.setView(initialMoleculeView);webglViewer.render()}else if(structureSdf)renderStructure()}
});
$('catalogSearch').addEventListener('input',()=>{catalogPage=1;renderCatalog()});
for(const id of ['studyFilter','effectFilter'])$(id).addEventListener('change',()=>{catalogPage=1;renderCatalog()});
$('exportRecords').addEventListener('click',async()=>{
  const b=$('exportRecords');b.disabled=true;
  try {
    const {q,study,effect}=recordQuery();
    const params=new URLSearchParams({format:'csv',q,study_type:study,effect_type:effect});
    const response=await fetch('/api/catalog/records?'+params,{headers:{'X-Chem-PDF-Extractor-Token':window.LOCAL_TOKEN}});
    if(!response.ok)throw Error('实验表导出失败，请刷新页面后重试');
    const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
    link.href=url;link.download='experiment-records.csv';document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),30000);message('已导出符合当前筛选条件的实验记录。');
  }catch(e){message(e.message,true)}finally{b.disabled=false}
});
$('prevPage').addEventListener('click',()=>{catalogPage--;renderCatalog()});
$('nextPage').addEventListener('click',()=>{catalogPage++;renderCatalog()});
$('pageSelect').addEventListener('change',()=>{catalogPage=Number($('pageSelect').value);renderCatalog()});
$('pageSize').addEventListener('change',()=>{pageSize=Number($('pageSize').value);catalogPage=1;renderCatalog()});
$('searchPubmed').addEventListener('click',async()=>{const q=$('pubmedQuery').value.trim();if(q.length<3){message('请输入关键词、完整 DOI 或 PMID',true);return}const b=$('searchPubmed');b.disabled=true;message('正在查找文献…');try{const data=await api(`/api/catalog/search?q=${encodeURIComponent(q)}`);$('searchResults').hidden=false;$('searchResultRows').innerHTML=data.papers.length?data.papers.map(p=>`<div class="search-hit"><div><b>${esc(p.title)}</b><br><small>PMID ${esc(p.pmid)} · ${esc(p.doi)}</small><p>${esc(p.abstract)}</p></div><button data-import="${esc(p.pmid)}" ${state.running?'disabled':''}>提取公开全文</button></div>`).join(''):'<p>没有匹配的文献，可上传 PDF 提取。</p>';message(`找到 ${data.papers.length} 篇文献；点击“提取公开全文”开始。`)}catch(e){message(e.message,true)}finally{b.disabled=false}});
$('pubmedQuery').addEventListener('keydown',e=>{if(e.key==='Enter')$('searchPubmed').click()});
$('importIdentifier').addEventListener('click',()=>{const id=$('pubmedQuery').value.trim();if(!id){message('请输入 DOI、PMID 或 PMC 编号',true);return}beginExtraction('identifier',id)});
$('searchResultRows').addEventListener('click',e=>{const b=e.target.closest('[data-import]');if(b&&!b.disabled)beginExtraction('identifier',b.dataset.import)});
$('taskProgress').addEventListener('click',e=>{if(e.target.closest('[data-retry-task]')&&state.task)beginExtraction(state.task.kind,state.task.source)});
$('uploadBtn').addEventListener('click',async()=>{
  const file=$('pdfUpload').files?.[0];if(!file){message('请先选择 PDF',true);return}if(file.size>30000000){message('PDF 不能超过 30 MB',true);return}
  if(state.running||actionPending)return;
  actionPending=true;$('uploadBtn').disabled=true;$('uploadBtn').textContent='正在上传…';message(`正在上传 ${file.name}…`);
  try{await api(`/api/catalog/upload-pdf?name=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':'application/pdf'},body:file});$('pdfUpload').value='';actionPending=false;await beginExtraction('pdf',file.name)}catch(e){message(e.message,true)}finally{actionPending=false;$('uploadBtn').textContent='上传并提取';renderCatalog()}
});
$('localPdfRows').addEventListener('click',e=>{const b=e.target.closest('[data-pdf]');if(b&&!b.disabled)beginExtraction('pdf',b.dataset.pdf)});
refresh();setInterval(refresh,3000);setInterval(updateElapsed,1000);
