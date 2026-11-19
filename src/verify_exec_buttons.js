/* 执行台按钮渲染验证：桥未连 / 桥已连 两种状态下，按钮是否可见、可点 */
const fs=require('fs'),vm=require('vm');
const store={};
function mkEl(id){return{id,value:'',textContent:'',innerHTML:'',tagName:'DIV',selectedIndex:0,open:false,
 style:{display:''},dataset:{},disabled:false,_attr:{},
 classList:{toggle(){},remove(){},add(){},contains(){return false}},addEventListener(){},
 querySelectorAll(){return[]},querySelector(){return mkEl('s')},appendChild(){},removeChild(){},
 select(){},click(){},focus(){},setAttribute(k,v){this._attr[k]=v},getAttribute(){return null}};}
global.document={getElementById:id=>(store[id]=store[id]||mkEl(id)),querySelectorAll:()=>[],
 createElement:()=>mkEl('x'),body:{appendChild(){},removeChild(){}},execCommand:()=>true,activeElement:null};
global.localStorage={getItem:()=>null,setItem(){}};global.navigator={};global.window={print(){}};
global.Blob=function(){};global.URL={createObjectURL:()=>'',revokeObjectURL(){}};
global.AbortSignal={timeout:()=>({})};global.fetch=()=>Promise.reject(new Error('no net'));
global.CSS={escape:s=>s};global.setTimeout=f=>{f();return 0};global.clearTimeout=()=>{};
let code=fs.readFileSync(require('path').join(__dirname,'v10_script.js'),'utf8');
code+='\n;globalThis.__api={toolBtn,get bridgeOn(){return bridgeOn},set bridgeOn(v){bridgeOn=v},set toolStatus(v){toolStatus=v},get toolStatus(){return toolStatus}};';
vm.runInThisContext(code);
const A=globalThis.__api;
['proj','subject','style','vram','usage','comm','extra'].forEach(id=>document.getElementById(id));

const names=['Krita','Blender','Krita AI Diffusion','ComfyUI','Aseprite','excalidraw','trimesh'];
console.log('='.repeat(70));
console.log('执行台按钮渲染验证');
console.log('='.repeat(70));

// 场景1：桥未连，无状态
A.bridgeOn=false; A.toolStatus={};
console.log('\n[场景1] 工具桥未运行：');
let emptyCount=0;
for(const n of names){const h=A.toolBtn(n);if(!h){emptyCount++;}console.log('  %-20s %s',n,h.slice(0,90).replace(/\s+/g,' '));}
console.log('  空按钮数(应为0):',emptyCount);

// 场景2：桥已连 + 工具状态（模拟真实 status）
A.bridgeOn=true;
A.toolStatus={
 krita:{installed:true,kind:'desktop'}, blender:{installed:true,kind:'desktop'},
 comfyui:{installed:false,kind:'suite'}, aseprite:{installed:false,winget:'aseprite.aseprite'},
 excalidraw:{installed:true,kind:'web'}, trimesh:{installed:true,kind:'cli'}
};
console.log('\n[场景2] 工具桥已连接：');
for(const n of names){const h=A.toolBtn(n);console.log('  %-20s %s',n,h.slice(0,90).replace(/\s+/g,' '));}

// 断言
const off=A.toolBtn('Krita');             // 已装桌面软件，桥未连
A.bridgeOn=false;
const offKrita=A.toolBtn('Krita');
A.bridgeOn=true;
const onKrita=A.toolBtn('Krita');
console.log('\n'+'-'.repeat(70));
console.log('断言：');
console.log('  桥未连 Krita 有可见按钮:', !!offKrita && offKrita.includes('disabled'), offKrita);
console.log('  桥已连 Krita 可点启动:', onKrita.includes('data-launch') && !onKrita.includes('disabled'), onKrita);
console.log('  桥未连无任何空按钮:', emptyCount===0);
const ok = !!offKrita && offKrita.includes('disabled') && onKrita.includes('data-launch') && emptyCount===0;
console.log('\n'+(ok?'BUTTON_RENDER_OK':'BUTTON_RENDER_FAIL'));
