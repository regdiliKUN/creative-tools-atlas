/* 自动化引擎 · 前端作业单编译验证 */
const fs=require('fs'),vm=require('vm');const store={};
function mkEl(id){return{id,value:'',textContent:'',innerHTML:'',tagName:'DIV',selectedIndex:0,open:false,
 style:{display:''},dataset:{},disabled:false,classList:{toggle(){},remove(){},add(){},contains(){return false}},
 addEventListener(){},querySelectorAll(){return[]},querySelector(){return mkEl('s')},appendChild(){},removeChild(){},
 select(){},click(){},focus(){},setAttribute(){},getAttribute(){return null}};}
global.document={getElementById:id=>(store[id]=store[id]||mkEl(id)),querySelectorAll:()=>[],
 createElement:()=>mkEl('x'),body:{appendChild(){},removeChild(){}},execCommand:()=>true,activeElement:null};
global.localStorage={getItem:()=>null,setItem(){}};global.navigator={};global.window={print(){}};
global.Blob=function(){};global.URL={createObjectURL:()=>'',revokeObjectURL(){}};
global.AbortSignal={timeout:()=>({})};global.fetch=()=>Promise.reject(new Error('x'));
global.CSS={escape:s=>s};global.setTimeout=f=>{f();return 0};global.clearTimeout=()=>{};
let code=fs.readFileSync(require('path').join(__dirname,'v10_script.js'),'utf8');
code+='\n;globalThis.__api={buildJobSpec,stepKind,profile,promptPack,get selectedWf(){return selectedWf},set selectedWf(v){selectedWf=v}};';
vm.runInThisContext(code);const A=globalThis.__api;
['proj','subject','style','vram','usage','comm','extra'].forEach(id=>document.getElementById(id));
store.proj.value='测试角色';store.subject.value='森林守卫';store.style.value='干净赛璐璐平涂';
store.vram.value='24';store.usage.value='个人练习';store.comm.value='no';

console.log('='.repeat(70));
console.log('自动化引擎 · 作业单编译验证');
console.log('='.repeat(70));
console.log('\n[步骤类型识别]');
for(const t of ['起稿与设定基底','AI 辅助生成与局部重绘','抠图与净化','图生 3D 模型','精修与交付','切片设置','VRM 导出']){
  console.log('  %-24s -> %s',t,A.stepKind(t));
}
console.log('\n[角色工作流作业单]');
A.selectedWf=new Set(['character']);
const spec=A.buildJobSpec(A.profile());
console.log('  名称:',spec.name);
console.log('  总步骤:',spec.steps_total,' 可自动:',spec.auto_count,' 需人工:',spec.steps_total-spec.auto_count);
console.log('  正面提示词长度:',spec.prompt_pos.length,' 负面:',spec.prompt_neg.length);
spec.steps.forEach(s=>console.log('    -',s.kind,'|',s.label));

console.log('\n[图生3D工作流作业单]');
A.selectedWf=new Set(['to3d']);
const spec2=A.buildJobSpec(A.profile());
console.log('  总步骤:',spec2.steps_total,' 可自动:',spec2.auto_count);
spec2.steps.forEach(s=>console.log('    -',s.kind,'|',s.label));

const ok = spec.steps_total>0 && spec.auto_count>0 && spec.prompt_pos.length>20
  && spec2.auto_count>0 && A.stepKind('起稿与设定基底')==='hand_draw'
  && A.stepKind('AI 辅助生成与局部重绘')==='text_to_image';
console.log('\n'+(ok?'JOB_SPEC_OK':'JOB_SPEC_FAIL'));
