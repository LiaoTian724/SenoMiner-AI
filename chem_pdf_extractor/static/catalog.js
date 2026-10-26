'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let state = {compounds:[],papers:[],local_pdfs:[],summary:{}};
let selected = null, selectedPart = 0, structureSdf = '', renderMode = 'canvas', stopAnimation = null, webglViewer = null, moleculeLoad = 0;
let catalogPage = 1, pageSize = 5;

async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'X-Chem-PDF-Extractor-Token':window.LOCAL_TOKEN,...(options.headers||{})}});
  const body = await response.json();
  if (!response.ok || body.ok === false) throw Error(body.error || '请求失败');
  return body;
}
function message(value, error=false) { $('message').textContent=value; $('message').classList.toggle('error',error); }
function groupCount(item) { return item.papers.reduce((n,p)=>n+(p.experiment_groups||0),0); }
function clip(value,n=110) { const s=String(value||'').replace(/\s+/g,' ').trim(); return s.length>n?s.slice(0,n-1)+'…':s; }
function paperLabel(p) { return p?.title||p?.source_name||'文献名称待核对'; }
function dateLabel(value) { const date=new Date(value); return Number.isNaN(date.getTime())?'':date.toLocaleString('zh-CN',{hour12:false}); }
function sourceLink(p) { const url=/^https?:\/\//.test(p.url||'')?p.url:(/^\d+$/.test(p.pmid)?`https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/`:(/^10\./.test(p.doi||'')?`https://doi.org/${encodeURI(p.doi)}`:'')); return url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(paperLabel(p))}</a>`:esc(paperLabel(p)); }
function claimPreview(c,lead) {
  let text=String(lead.result||lead.quote||'').replace(/\s+/g,' ').trim();
  if(/[\u4e00-\u9fff]/.test(text))return clip(text,85);
  const name=c.name.toLocaleLowerCase();
  if(!text.toLocaleLowerCase().includes(name)&&String(lead.quote||'').toLocaleLowerCase().includes(name))text=String(lead.quote).replace(/\s+/g,' ');
  const position=text.toLocaleLowerCase().indexOf(name);
  const start=position>35?Math.max(0,position-20):0;
  return (start?'…':'')+clip(text.slice(start),85);
}
function renderCatalog() {
  const q=$('catalogSearch').value.trim().toLocaleLowerCase();
  const items=state.compounds.filter(c => (c.name+' '+c.papers.map(p=>p.title).join(' ')).toLocaleLowerCase().includes(q));
  const totalPages=Math.max(1,Math.ceil(items.length/pageSize)); catalogPage=Math.max(1,Math.min(catalogPage,totalPages));
  const pageItems=items.slice((catalogPage-1)*pageSize,catalogPage*pageSize);
  $('catalogCount').textContent=`${state.summary.compounds||0} 个化合物/组合 · ${state.summary.papers||0} 篇文献 · ${state.summary.experiment_groups||0} 个实验组`;
  const pending=state.papers.filter(p=>p.review_status!=='complete'||p.card_status!=='complete').length;
  $('statusLine').textContent=`按最新读取文献排序；仅展示通过独立全文复核的本篇实验。${pending?` ${pending} 篇等待完成复核。`:''}`;
  $('catalogRows').innerHTML=pageItems.length?pageItems.map(c=>{
    const index=state.compounds.indexOf(c),id=c.identity||{};
    const first=c.papers[0],lead=first?.lead_claim||{};
    return `<tr><td><strong>${esc(c.name)}</strong><br><span class="tag">有本篇实验支持</span></td><td class="claim-preview">${esc(claimPreview(c,lead))}</td><td class="source-title">${c.papers.map(p=>`<div>${sourceLink(p)}<br><small class="muted">读取：${esc(dateLabel(p.read_at))}</small></div>`).join('')}</td><td>${groupCount(c)}</td><td><button data-open="${index}">阅读证据</button></td></tr>`;
  }).join(''):'<tr><td colspan="5" class="empty">没有符合条件的化合物。</td></tr>';
  $('pageSelect').innerHTML=Array.from({length:totalPages},(_,i)=>`<option value="${i+1}" ${catalogPage===i+1?'selected':''}>${i+1}</option>`).join('');
  $('pageInfo').textContent=`共 ${items.length} 条 · 第 ${catalogPage} / ${totalPages} 页`;
  $('prevPage').disabled=catalogPage===1; $('nextPage').disabled=catalogPage===totalPages;
  $('paperReviewRows').innerHTML=state.papers.map(p=>`<div class="review-paper"><p>${sourceLink(p)}</p><p class="muted small">${p.review_status==='complete'&&p.card_status==='complete'?`${p.catalog_records} 条结果进入目录`:'全文复核或实验关联尚未完成，暂不收录'}</p>${p.review_decisions?.length?`<ul>${p.review_decisions.map(d=>`<li><b>${esc(d.canonical_name||d.input_name)}</b>：${d.verdict==='accepted'?'通过角色复核':'排除或待核对'} · ${esc(d.reason)}</li>`).join('')}</ul>`:''}</div>`).join('');
  $('localPdfRows').innerHTML=state.local_pdfs.map(p=>`<div class="local-item">${esc(p.name)}<button data-pdf="${esc(p.name)}" ${p.processed||state.running?'disabled':''}>${p.processed?'已处理':'提取这篇 PDF'}</button></div>`).join('');
  if(state.running) message(state.message||'正在处理论文…');
  else if(state.error) message(state.error,true);
}
async function refresh() { try { state=await api('/api/catalog'); renderCatalog(); } catch(e) { message(e.message,true); } }
function prop(label,value) { return `<div class="property"><small>${esc(label)}</small>${esc(value||'原文未报告')}</div>`; }
function studyLabel(type) { return ({clinical:'人体临床给药',ex_vivo:'离体组织实验',in_vitro:'细胞体外实验',in_vivo:'动物体内实验'})[type]||'模型类型待核对'; }
function outcomeHtml(o) {
  return `<details class="outcome"><summary>${esc(o.endpoint||o.assay||'检测终点')} <span class="muted">· ${esc(o.outcome_kind)}</span></summary>
  <p><b>结果：</b>${esc(o.result)}</p><p><b>检测方法：</b>${esc(o.assay||'原文未报告')}　<b>样本数：</b>${esc(o.sample_size||'原文未报告')}</p>
  <p><b>对照：</b>${esc(o.control||'原文未报告')}　<b>统计：</b>${esc(o.statistics||'原文未报告')}</p>
  <p class="quote"><b>原文结果引文：</b> ${esc(o.quote)}</p><p class="muted">来源 ${esc(o.location)} · 证据记录 ${esc((o.source_record_ids||[o.id]).join(', '))}</p></details>`;
}
function technicalHtml(g) {
  return `<details class="technical"><summary>查看全部检测结果与原文步骤</summary><p class="muted small">同一实验的不同指标归于一组；每条保留原文引文与样本量。</p>${g.outcomes.map(outcomeHtml).join('')}
  <details class="outcome"><summary>原文实验步骤（${g.steps.length}）</summary>${g.steps.length?`<ol class="steps">${g.steps.map(s=>`<li>${esc(s.action)}<div class="quote">${esc(s.quote)}</div></li>`).join('')}</ol>`:'<p class="small muted">原文未提供可核对的连续步骤，请查 Methods 与补充材料。</p>'}</details></details>`;
}
function protocolHtml(story,g) {
  return `${story.induction?`<p class="induction"><b>造模 / 预处理：</b>${esc(story.induction)}（不作为活性药物剂量）</p>`:''}<dl class="protocol"><div><dt>对象</dt><dd>${esc(story.model||'原文未报告')}</dd></div><div><dt>药物与剂量</dt><dd>${esc(story.dose||'原文未报告')}</dd></div>
  <div><dt>给药</dt><dd>${esc(story.route||'原文未报告')}</dd></div><div><dt>流程</dt><dd>${esc(story.duration||'原文未报告')}</dd></div><div><dt>检测</dt><dd>${esc(story.assay||'原文未报告')}</dd></div></dl>
  ${story.steps?.length?`<p class="brief-steps">关键操作：${story.steps.map(s=>esc(clip(s,85))).join(' → ')}</p>`:''}${g?.dose_basis&&!g.dose_basis.startsWith('原文单位')?`<p class="muted small">剂量口径：${esc(g.dose_basis)}</p>`:''}`;
}
function experimentHtml(g) {
  const s=g.story||{},quote=s.quote||g.outcomes[0]?.quote||'';
  return `<details class="extra-experiment"><summary>${esc(g.title)} <span class="tag">${studyLabel(g.study_type)}</span></summary><div class="extra-content">
  <p><b>原文结果：</b><span class="quote-inline">${esc(clip(quote,450))}</span></p>${protocolHtml(s,g)}
  <p><b>观察结果：</b>${esc(s.result||'原文未报告')}</p><p><b>证据边界：</b>${esc(s.scope||'待核对')}</p>${technicalHtml(g)}</div></details>`;
}
function paperHtml(p) {
  const links=[/^\d+$/.test(p.pmid)?`<a href="https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/" target="_blank" rel="noopener noreferrer">PubMed PMID ${p.pmid}</a>`:'',p.doi?`<a href="https://doi.org/${encodeURI(p.doi)}" target="_blank" rel="noopener noreferrer">DOI ${esc(p.doi)}</a>`:''].filter(Boolean).join(' · ');
  const claim=p.lead_claim||{},lead=p.groups.find(g=>g.id===claim.group_id)||p.groups[0],others=p.groups.filter(g=>g!==lead);
  return `<article class="paper-story"><p class="paper-source">${esc(p.title)}${links?' · '+links:''}</p>
  <section class="story-section"><h3>1. 论文哪里报告有效？</h3><blockquote>${esc(String(claim.quote||'原文结果引文待核对').replace(/\s+/g,' '))}</blockquote><p class="citation">${esc(claim.location||'Results')} · ${esc(p.source_name)}</p></section>
  <section class="story-section"><h3>2. 支持这句话的实验</h3><p class="muted small">${esc(lead.title)} · ${studyLabel(lead.study_type)}</p>${protocolHtml(claim,lead)}</section>
  <section class="story-section"><h3>3. 实验结果</h3><p>${esc(claim.result||'请查看原文结果引文')}</p>${lead.outcomes.length>1?`<p class="muted small">同一实验另有 ${lead.outcomes.length-1} 个检测指标，详见下方技术明细。</p>`:''}</section>
  <section class="story-section"><h3>4. 能证明什么？</h3><p>${esc(claim.scope||'证据范围待核对')}</p></section>
  <p class="citation">实验来源：${esc(claim.location||'Results')}；${esc(p.source_name)}</p>${technicalHtml(lead)}
  ${others.length?`<details class="other-experiments"><summary>另外 ${others.length} 个独立实验（展开查看）</summary>${others.map(experimentHtml).join('')}</details>`:''}</article>`;
}
function identityHtml(id) {
  const parts=id.components?.length?id.components:[id];
  const links=parts.flatMap(p=>{
    const a=[];
    if(/^\d+$/.test(String(p.cid||''))) a.push(`<a href="https://pubchem.ncbi.nlm.nih.gov/compound/${p.cid}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · PubChem ${p.cid}</a>`);
    if(/^CHEMBL\d+$/.test(String(p.chembl_id||''))) a.push(`<a href="https://www.ebi.ac.uk/chembl/explore/compound/${p.chembl_id}" target="_blank" rel="noopener noreferrer">${esc(p.name)} · ${esc(p.chembl_id)}</a>`);
    return a;
  });
  return `<section class="compound-overview" aria-label="化合物信息与分子结构"><div class="identity-grid"><div class="viewer-panel"><strong>3D 分子结构</strong><div class="component-tabs" id="componentTabs">${parts.map((p,i)=>`<button data-part="${i}" class="${i===0?'active':''}">${esc(p.name||id.name)}</button>`).join('')}</div><div id="moleculeView" class="molecule-view"><div class="viewer-message">正在读取 3D 结构…</div></div><div class="viewer-actions"><button data-mode="canvas">兼容 3D</button><button data-mode="webgl">WebGL 3D</button><button data-reset="1">重置视角</button></div><p class="viewer-note" id="structureOrigin">优先读取 PubChem 3D；缺失时使用 RDKit 生成构象。可拖动旋转。</p></div><div><h3 id="componentName">${esc(parts[0]?.name||id.name)}</h3><div class="properties" id="componentProps"></div><div class="external-links">${links.join('')}</div><div id="relatedLiterature"></div><p class="muted small">名称和化学属性来自 PubChem / ChEMBL；文献来自 PubMed。生成构象只供结构展示。</p></div></div></section>`;
}
function openDetail(index) {
  selected=state.compounds[index]; selectedPart=0; renderMode='canvas'; if(!selected)return;
  $('detailTitle').textContent=selected.name;
  $('detailBody').innerHTML=`${identityHtml(selected.identity)}<p class="evidence-status">有本篇实验支持 · 结论范围以论文中的模型和终点为准</p>${selected.papers.map(paperHtml).join('')}`;
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
function canvas3D(sdf,box) {
  const {atoms,bonds}=parseSdf(sdf),canvas=document.createElement('canvas'); box.replaceChildren(canvas);
  const ctx=canvas.getContext('2d'); if(!ctx)throw Error('浏览器无法创建 Canvas');
  const min=[Math.min(...atoms.map(a=>a.x)),Math.min(...atoms.map(a=>a.y)),Math.min(...atoms.map(a=>a.z))];
  const max=[Math.max(...atoms.map(a=>a.x)),Math.max(...atoms.map(a=>a.y)),Math.max(...atoms.map(a=>a.z))];
  const mid=min.map((v,i)=>(v+max[i])/2),scale=225/Math.max(...max.map((v,i)=>v-min[i]),1);
  let rx=-0.25,ry=0.5,drag=null,active=true,frame=0;
  const colors={C:'#727b81',H:'#e3e7e9',O:'#c83b35',N:'#365fba',S:'#c29c19',Cl:'#4f9b54',F:'#56a65c',P:'#dd9044'};
  function draw(){if(!active)return;const rect=box.getBoundingClientRect(),dpr=window.devicePixelRatio||1,w=rect.width,h=rect.height;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr)}
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);ctx.fillStyle='#fbfcfd';ctx.fillRect(0,0,w,h);
    const pts=atoms.map(a=>{let x=(a.x-mid[0])*scale,y=(a.y-mid[1])*scale,z=(a.z-mid[2])*scale;
      const xx=x*Math.cos(ry)+z*Math.sin(ry),zz=z*Math.cos(ry)-x*Math.sin(ry);
      const yy=y*Math.cos(rx)-zz*Math.sin(rx),depth=y*Math.sin(rx)+zz*Math.cos(rx);
      const perspective=420/(420-depth);return {x:w/2+xx*perspective,y:h/2-yy*perspective,z:depth,r:(a.el==='H'?3.4:6.4)*perspective,el:a.el};});
    for(const [a,b] of bonds){const u=pts[a],v=pts[b];ctx.beginPath();ctx.moveTo(u.x,u.y);ctx.lineTo(v.x,v.y);ctx.strokeStyle='#98a1a7';ctx.lineWidth=3;ctx.stroke()}
    for(const p of [...pts].sort((a,b)=>a.z-b.z)){ctx.beginPath();ctx.arc(p.x,p.y,Math.max(2,p.r),0,Math.PI*2);ctx.fillStyle=colors[p.el]||'#866ea0';ctx.fill();ctx.strokeStyle='#455058';ctx.lineWidth=.6;ctx.stroke()}
    if(!drag)ry+=0.003;frame=requestAnimationFrame(draw)}
  canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;ry+=(e.clientX-drag[0])*.012;rx+=(e.clientY-drag[1])*.012;drag=[e.clientX,e.clientY]});
  canvas.addEventListener('pointerup',()=>{drag=null});
  draw(); return ()=>{active=false;cancelAnimationFrame(frame)};
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
  const parts=selected.identity.components?.length?selected.identity.components:[selected.identity],part=parts[selectedPart]||{};
  setComponentInfo(part);structureSdf='';if(stopAnimation){stopAnimation();stopAnimation=null}
  const box=$('moleculeView');box.innerHTML='<div class="viewer-message">正在读取 PubChem 3D 结构…</div>';
  if(!/^\d+$/.test(String(part.cid||''))){box.innerHTML='<div class="viewer-message">此成分没有经过确认的 PubChem CID，无法显示 3D 结构。</div>';return}
  try{const data=await api(`/api/catalog/structure?cid=${encodeURIComponent(part.cid)}`);if(load!==moleculeLoad||!$('detailDialog').open)return;structureSdf=data.sdf;$('structureOrigin').textContent=data.label+(data.origin==='rdkit_etkdg'?'（计算生成，非实验测定）。':'。')+' 可拖动旋转。';renderStructure()}
  catch(e){if(load!==moleculeLoad||!$('detailDialog').open)return;box.innerHTML=`<div class="viewer-message">${esc(e.message)}<br><a href="https://pubchem.ncbi.nlm.nih.gov/compound/${part.cid}" target="_blank" rel="noopener noreferrer">查看 PubChem 原站</a></div>`}
}
$('catalogRows').addEventListener('click',e=>{const b=e.target.closest('[data-open]');if(b)openDetail(Number(b.dataset.open))});
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
$('searchPubmed').addEventListener('click',async()=>{const q=$('pubmedQuery').value.trim();if(q.length<3){message('请输入至少 3 个字符的检索词',true);return}const b=$('searchPubmed');b.disabled=true;message('正在检索 PubMed…');try{const data=await api(`/api/catalog/search?q=${encodeURIComponent(q)}`);$('searchResults').hidden=false;$('searchResultRows').innerHTML=data.papers.length?data.papers.map(p=>`<div class="search-hit"><div><b>${esc(p.title)}</b><br><small>PMID ${esc(p.pmid)} · ${esc(p.doi)}</small><p>${esc(p.abstract)}</p></div><button data-import="${esc(p.pmid)}">提取公开全文</button></div>`).join(''):'<p>没有匹配的文献。</p>';message(`找到 ${data.papers.length} 篇候选文献。`)}catch(e){message(e.message,true)}finally{b.disabled=false}});
$('pubmedQuery').addEventListener('keydown',e=>{if(e.key==='Enter')$('searchPubmed').click()});
$('searchResultRows').addEventListener('click',async e=>{const b=e.target.closest('[data-import]');if(!b)return;const pmid=b.dataset.import;if(!/^\d+$/.test(pmid))return;if(!confirm(`将获取 PMID ${pmid} 的公开全文并发送到已配置的云端模型。继续吗？`))return;b.disabled=true;try{await api('/api/catalog/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pmid})});message(`PMID ${pmid} 正在处理。`)}catch(err){message(err.message,true);b.disabled=false}});
$('uploadBtn').addEventListener('click',async()=>{const file=$('pdfUpload').files?.[0];if(!file){message('请先选择 PDF',true);return}if(file.size>30000000){message('PDF 不能超过 30 MB',true);return}const b=$('uploadBtn');b.disabled=true;try{await api(`/api/catalog/upload-pdf?name=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':'application/pdf'},body:file});message(`${file.name} 已加入输入目录。`);$('pdfUpload').value='';await refresh()}catch(e){message(e.message,true)}finally{b.disabled=false}});
$('localPdfRows').addEventListener('click',async e=>{const b=e.target.closest('[data-pdf]');if(!b||b.disabled)return;const name=b.dataset.pdf;if(!confirm(`将解析 ${name} 并把论文文字发送到已配置的云端模型。开始吗？`))return;b.disabled=true;try{await api('/api/catalog/process-pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});message(`${name} 正在处理。`)}catch(err){message(err.message,true);b.disabled=false}});
refresh();setInterval(refresh,5000);
