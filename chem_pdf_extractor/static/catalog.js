'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let state = {compounds:[],papers:[],local_pdfs:[],summary:{}};
let selected = null, selectedPart = 0, structureSdf = '', renderMode = 'canvas', stopAnimation = null, webglViewer = null, moleculeLoad = 0;
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
      previewStops.push(canvas3D(data.sdf,box,{preview:true,animate:false}));
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
function renderCatalog() {
  const q=$('catalogSearch').value.trim().toLocaleLowerCase();
  const items=state.compounds.filter(c => (c.name+' '+c.papers.map(p=>p.title).join(' ')).toLocaleLowerCase().includes(q));
  const totalPages=Math.max(1,Math.ceil(items.length/pageSize)); catalogPage=Math.max(1,Math.min(catalogPage,totalPages));
  const pageItems=items.slice((catalogPage-1)*pageSize,catalogPage*pageSize);
  $('catalogCount').textContent=`${state.summary.compounds||0} 个化合物/组合 · ${state.summary.papers||0} 篇文献`;
  const pending=state.papers.filter(p=>p.review_status!=='complete'||p.card_status!=='complete').length;
  $('statusLine').textContent=`按文献读取时间从新到旧排列。${pending?` ${pending} 篇尚待完成核对。`:''}`;
  const key=JSON.stringify([q,catalogPage,pageSize,pageItems.map(c=>[c.id,c.name,c.identity,c.papers.map(p=>[p.title,p.read_at])])]);
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
  const labels={model:'实验对象',dose:'剂量',duration:'处理时间',route:'给药',control:'对照',sample_size:'样本数',assay:'检测方法'};
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
function experimentHtml(g) {
  const s=g.story||{},quote=s.quote||g.outcomes[0]?.quote||'';
  return `<details class="extra-experiment"><summary>${esc(g.title)} · ${studyLabel(g.study_type)}</summary><div class="extra-content">
  <p class="citation">${esc(s.location)}</p><p class="quote-inline">${esc(quote)}</p>${protocolHtml(s)}
  <p><b>实验结果：</b>${esc(s.result||'原文未报告')}</p><p><b>结论：</b>${esc(s.scope||'待核对')}</p>${technicalHtml(g)}</div></details>`;
}
function paperHtml(p) {
  const links=[/^\d+$/.test(p.pmid)?`<a href="https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/" target="_blank" rel="noopener noreferrer">PubMed PMID ${p.pmid}</a>`:'',p.doi?`<a href="https://doi.org/${encodeURI(p.doi)}" target="_blank" rel="noopener noreferrer">DOI ${esc(p.doi)}</a>`:''].filter(Boolean).join(' · ');
  const claim=p.lead_claim||{},lead=p.groups.find(g=>g.id===claim.group_id)||p.groups[0],others=p.groups.filter(g=>g!==lead);
  return `<article class="paper-story"><p class="paper-source">${esc(p.title)}${links?' · '+links:''}</p>
  <p class="study-context">${studyLabel(lead.study_type)}</p>
  <section class="story-section"><h3>1. 原文依据</h3><p class="citation">${esc(claim.location||'Results')} · ${esc(p.source_name)}</p><blockquote>${esc(String(claim.quote||'原文结果引文待核对').replace(/\s+/g,' '))}</blockquote></section>
  <section class="story-section"><h3>2. 实验步骤</h3>${protocolHtml(claim)}</section>
  <section class="story-section"><h3>3. 实验结果</h3><p>${esc(claim.result||'请查看原文结果引文')}</p></section>
  <section class="story-section"><h3>4. 结论</h3><p>${esc(claim.scope||'证据范围待核对')}</p></section>
  ${technicalHtml(lead)}${others.length?`<details class="other-experiments"><summary>其他实验（${others.length}）</summary>${others.map(experimentHtml).join('')}</details>`:''}</article>`;
}
function identityHtml(id) {
  const parts=id.components?.length?id.components:[id];
  const links=parts.flatMap(p=>{
    const a=[];
    if(/^\d+$/.test(String(p.cid||''))) a.push(`<a href="https://pubchem.ncbi.nlm.nih.gov/compound/${p.cid}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · PubChem ${p.cid}</a>`);
    if(/^CHEMBL\d+$/.test(String(p.chembl_id||''))) a.push(`<a href="https://www.ebi.ac.uk/chembl/explore/compound/${p.chembl_id}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · ${esc(p.chembl_id)}</a>`);
    return a;
  });
  return `<section class="compound-overview" aria-label="化合物信息与分子结构"><div class="identity-grid"><div class="viewer-panel"><strong>3D 分子结构</strong><div class="component-tabs" id="componentTabs">${parts.map((p,i)=>`<button data-part="${i}" class="${i===0?'active':''}">${esc(p.name||id.name)}</button>`).join('')}</div><div id="moleculeView" class="molecule-view"><div class="viewer-message">正在读取 3D 结构…</div></div><div class="viewer-actions"><button data-mode="canvas">兼容 3D</button><button data-mode="webgl">WebGL 3D</button><button data-reset="1">重置视角</button></div><p class="viewer-note" id="structureOrigin">PubChem 构象或 RDKit 计算构象，可拖动旋转。</p></div><div><h3 id="componentName">${esc(parts[0]?.name||id.name)}</h3><div class="properties" id="componentProps"></div><div class="external-links">${links.join('')}</div><details class="related-literature"><summary>拓展：PubMed 相关文献</summary><div id="relatedLiterature"></div></details></div></div></section>`;
}
function openDetail(index) {
  selected=state.compounds[index]; selectedPart=0; renderMode='canvas'; if(!selected)return;
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
function canvas3D(sdf,box,{preview=false,animate=true}={}) {
  const {atoms,bonds}=parseSdf(sdf),canvas=document.createElement('canvas'); box.replaceChildren(canvas);
  canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`${box.dataset.molecule||'分子'}的 3D 结构，可拖动旋转`);
  const ctx=canvas.getContext('2d'); if(!ctx)throw Error('浏览器无法创建 Canvas');
  const min=[Math.min(...atoms.map(a=>a.x)),Math.min(...atoms.map(a=>a.y)),Math.min(...atoms.map(a=>a.z))];
  const max=[Math.max(...atoms.map(a=>a.x)),Math.max(...atoms.map(a=>a.y)),Math.max(...atoms.map(a=>a.z))];
  const mid=min.map((v,i)=>(v+max[i])/2);
  const radius=Math.max(...atoms.map(a=>Math.hypot(a.x-mid[0],a.y-mid[1],a.z-mid[2])),1);
  let rx=-0.25,ry=0.5,drag=null,active=true,frame=0;
  const colors={C:'#727b81',H:'#e3e7e9',O:'#c83b35',N:'#365fba',S:'#c29c19',Cl:'#4f9b54',F:'#56a65c',P:'#dd9044'};
  function draw(){if(!active)return;const rect=box.getBoundingClientRect(),dpr=window.devicePixelRatio||1,w=rect.width,h=rect.height;
    if(!w||!h)return;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr)}
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);ctx.fillStyle='#fbfcfd';ctx.fillRect(0,0,w,h);
    const scale=Math.max(1,Math.min(w,h)-28)/(radius*2.5),size=preview?0.68:1;
    const pts=atoms.map(a=>{let x=(a.x-mid[0])*scale,y=(a.y-mid[1])*scale,z=(a.z-mid[2])*scale;
      const xx=x*Math.cos(ry)+z*Math.sin(ry),zz=z*Math.cos(ry)-x*Math.sin(ry);
      const yy=y*Math.cos(rx)-zz*Math.sin(rx),depth=y*Math.sin(rx)+zz*Math.cos(rx);
      const perspective=600/(600-depth);return {x:w/2+xx*perspective,y:h/2-yy*perspective,z:depth,r:(a.el==='H'?3.4:6.4)*perspective*size,el:a.el};});
    for(const [a,b] of bonds){const u=pts[a],v=pts[b];ctx.beginPath();ctx.moveTo(u.x,u.y);ctx.lineTo(v.x,v.y);ctx.strokeStyle='#98a1a7';ctx.lineWidth=preview?1.8:3;ctx.stroke()}
    for(const p of [...pts].sort((a,b)=>a.z-b.z)){ctx.beginPath();ctx.arc(p.x,p.y,Math.max(1.5,p.r),0,Math.PI*2);ctx.fillStyle=colors[p.el]||'#866ea0';ctx.fill();ctx.strokeStyle='#455058';ctx.lineWidth=.5;ctx.stroke()}
    if(animate){if(!drag)ry+=0.003;frame=requestAnimationFrame(draw)}}
  function down(e){drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)}
  function move(e){if(!drag)return;ry+=(e.clientX-drag[0])*.012;rx+=(e.clientY-drag[1])*.012;drag=[e.clientX,e.clientY];if(!animate)draw()}
  function up(){drag=null}
  canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);
  canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);canvas.addEventListener('lostpointercapture',up);
  const resize=new ResizeObserver(()=>{if(!animate)draw()});resize.observe(box);
  draw();return ()=>{active=false;cancelAnimationFrame(frame);resize.disconnect();canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',up);canvas.removeEventListener('lostpointercapture',up)};
}
function renderStructure() {
  if(stopAnimation){stopAnimation();stopAnimation=null} webglViewer=null;
  const box=$('moleculeView'); if(!structureSdf){box.innerHTML='<div class="viewer-message">暂无 3D 结构</div>';return}
  try {
    if(renderMode==='webgl'&&window.$3Dmol&&document.createElement('canvas').getContext('webgl')) {
      box.replaceChildren(); webglViewer=$3Dmol.createViewer(box,{backgroundColor:'#fbfcfd'});
      webglViewer.addModel(structureSdf,'sdf');webglViewer.setStyle({},{stick:{radius:.14},sphere:{scale:.3}});webglViewer.zoomTo();webglViewer.render();webglViewer.resize();
      const canvas=box.querySelector('canvas');if(canvas)canvas.addEventListener('webglcontextlost',()=>{renderMode='canvas';renderStructure()},{once:true});
    } else {renderMode='canvas';stopAnimation=canvas3D(structureSdf,box)}
  } catch(e) {renderMode='canvas';try{stopAnimation=canvas3D(structureSdf,box)}catch(inner){box.innerHTML=`<div class="viewer-message">${esc(inner.message)}</div>`}}
}
async function showMolecule() {
  const load = ++moleculeLoad;
  const part=compoundParts(selected)[selectedPart]||{};
  setComponentInfo(part);structureSdf='';if(stopAnimation){stopAnimation();stopAnimation=null}
  const box=$('moleculeView');box.innerHTML='<div class="viewer-message">正在读取 PubChem 3D 结构…</div>';
  if(!/^\d+$/.test(String(part.cid||''))){box.innerHTML='<div class="viewer-message">此成分没有经过确认的 PubChem CID，无法显示 3D 结构。</div>';return}
  try{const data=await structureData(part.cid);if(load!==moleculeLoad||!$('detailDialog').open)return;structureSdf=data.sdf;$('structureOrigin').textContent=data.label+(data.origin==='rdkit_etkdg'?'（计算生成，非实验测定）。':'。')+' 可拖动旋转。';renderStructure()}
  catch(e){if(load!==moleculeLoad||!$('detailDialog').open)return;box.innerHTML=`<div class="viewer-message">${esc(e.message)}<br><a href="https://pubchem.ncbi.nlm.nih.gov/compound/${part.cid}" target="_blank" rel="noopener noreferrer">查看 PubChem 原站</a></div>`}
}
$('catalogRows').addEventListener('click',e=>{if(e.target.closest('[data-retry-preview]')){catalogRenderKey='';renderCatalog();return}const b=e.target.closest('[data-open]');if(b)openDetail(Number(b.dataset.open))});
$('closeDetail').addEventListener('click',()=>$('detailDialog').close());
$('detailDialog').addEventListener('close',()=>{moleculeLoad++;if(stopAnimation){stopAnimation();stopAnimation=null}});
$('detailBody').addEventListener('click',e=>{
  const part=e.target.closest('[data-part]');if(part){selectedPart=Number(part.dataset.part);showMolecule()}
  const mode=e.target.closest('[data-mode]');if(mode&&structureSdf){renderMode=mode.dataset.mode;renderStructure()}
  if(e.target.closest('[data-reset]')){if(webglViewer){webglViewer.zoomTo();webglViewer.render()}else if(structureSdf)renderStructure()}
});
$('catalogSearch').addEventListener('input',()=>{catalogPage=1;renderCatalog()});
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
