// Frontend behavior without a browser: rendering, immediate feedback and API wiring.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,files:[],listeners:{},classList:{toggle(){}},addEventListener(name,fn){this.listeners[name]=fn},querySelectorAll(){return []},showModal(){this.open=true}});return nodes.get(id)}
let requests=[],pendingStart;
const initial={compounds:[],papers:[],local_pdfs:[{name:'waiting.pdf',processed:false},{name:'done.pdf',processed:true}],summary:{}};
const ctx=vm.createContext({document:{getElementById:node},window:{LOCAL_TOKEN:'local'},Date,JSON,Math,Number,String,Map,Error,Promise,encodeURIComponent,setInterval(){},fetch:async(path,options={})=>{
 requests.push([path,options]);
 if(path.startsWith('/api/catalog/structure'))return new Promise(()=>{});
 if(path==='/api/catalog/process-pdf')return new Promise(resolve=>{pendingStart=()=>resolve({ok:true,json:async()=>({ok:true,running:true,task:{source:'waiting.pdf',kind:'pdf',status:'running',stage:'extracting',stage_label:'分段提取',completed:1,total:4,elapsed_seconds:2,message:'已完成 1/4 段',events:[]}})})});
 return {ok:true,json:async()=>initial};
}});
vm.runInContext(fs.readFileSync('chem_pdf_extractor/static/catalog.js','utf8'),ctx);
(async()=>{
 await new Promise(setImmediate);
 assert.match(node('localPdfRows').innerHTML,/waiting.pdf/);
 assert.doesNotMatch(node('localPdfRows').innerHTML,/done.pdf/);
 assert.match(node('completedPdfRows').innerHTML,/done.pdf/);
 const started=vm.runInContext("beginExtraction('pdf','waiting.pdf')",ctx);
 assert.match(node('taskProgress').innerHTML,/正在启动/);
 assert.equal(node('uploadBtn').disabled,true);
 pendingStart();
 // Stop the next polling response from hiding the mocked running state.
 initial.running=true;initial.task={source:'waiting.pdf',kind:'pdf',status:'running',stage:'extracting',stage_label:'分段提取',completed:1,total:4,elapsed_seconds:2,message:'已完成 1/4 段',events:[]};
 await started;
 assert.match(node('taskProgress').innerHTML,/value="1" max="4"/);
 assert.match(node('taskProgress').innerHTML,/已完成 1\/4 段/);
 assert.equal(JSON.parse(requests.find(([p])=>p==='/api/catalog/process-pdf')[1].body).name,'waiting.pdf');
 vm.runInContext("state.running=false;state.task.status='failed';state.task.stage='failed';state.task.stage_label='提取失败';state.task.error='network';renderProgress()",ctx);
 assert.match(node('taskProgress').innerHTML,/重试并继续/);
 assert.doesNotMatch(node('taskProgress').innerHTML,/<progress/);
 vm.runInContext(`state.compounds=[{name:'17-DMAG',identity:{name:'17-DMAG',cid:'5288674',formula:'C32H48N4O8'},papers:[{title:'Source paper',source_name:'paper.pdf',groups:[{id:'g',study_type:'in_vitro',outcomes:[],steps:[]}],lead_claim:{group_id:'g',quote:'Source claim'}}]}];openDetail(0)`,ctx);
 const detail=node('detailBody').innerHTML;
 assert.ok(detail.indexOf('class="chemistry-section"')<detail.indexOf('class="paper-story"'));
 assert.doesNotMatch(detail,/<details[^>]*id="chemistryDetails"/);
 assert.match(node('componentProps').innerHTML,/5288674/);
 assert.ok(requests.some(([url])=>url==='/api/catalog/structure?cid=5288674'));
 assert.equal(node('detailDialog').open,true);
 console.log('Frontend progress, retry, and molecular information first with immediate loading: OK');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1});
