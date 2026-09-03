(()=>{"use strict";
const $=s=>document.querySelector(s);const viewport=$("#imageViewport");if(!viewport)return;
const isTouch=()=>window.matchMedia("(pointer: coarse)").matches||navigator.maxTouchPoints>0;
let panMode=isTouch(),panStart=null,pinchDistance=null,lastPinchStep=0,boundCanvas=null;

function addPanButton(){const bar=document.querySelector('.zoom-toolbar');if(!bar||$('#mobilePanBtn'))return;const btn=document.createElement('button');btn.id='mobilePanBtn';btn.className='btn secondary';btn.textContent='✋ 移動モード';btn.disabled=!viewport.querySelector('canvas');btn.onclick=()=>{panMode=!panMode;syncPanButton()};bar.appendChild(btn);syncPanButton();}
function syncPanButton(){const btn=$('#mobilePanBtn');if(!btn)return;btn.classList.toggle('active',panMode);btn.textContent=panMode?'✋ 移動モード ON':'✋ 移動モード';const canvas=viewport.querySelector('canvas');if(canvas)canvas.style.cursor=panMode?'grab':'crosshair';}
function setCropMode(){panMode=false;syncPanButton();}
['#selectTitleBtn','#selectArtistBtn'].forEach(id=>{const el=$(id);if(el)el.addEventListener('click',setCropMode,true)});

function dispatchMouse(type,touch,target=boundCanvas){if(!touch||!target)return;const ev=new MouseEvent(type,{bubbles:true,cancelable:true,clientX:touch.clientX,clientY:touch.clientY,screenX:touch.screenX,screenY:touch.screenY,button:0,buttons:type==='mouseup'?0:1});target.dispatchEvent(ev);}
function distance(t1,t2){return Math.hypot(t2.clientX-t1.clientX,t2.clientY-t1.clientY)}
function pinchCenter(t1,t2){return{x:(t1.clientX+t2.clientX)/2,y:(t1.clientY+t2.clientY)/2}}

function bindCanvas(canvas){if(!canvas||canvas===boundCanvas)return;boundCanvas=canvas;canvas.style.touchAction='none';canvas.addEventListener('touchstart',e=>{
  if(e.touches.length===2){e.preventDefault();pinchDistance=distance(e.touches[0],e.touches[1]);lastPinchStep=pinchDistance;return;}
  if(e.touches.length!==1)return;const t=e.touches[0];e.preventDefault();
  if(panMode){panStart={x:t.clientX,y:t.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};canvas.style.cursor='grabbing';}
  else dispatchMouse('mousedown',t,canvas);
},{passive:false});
canvas.addEventListener('touchmove',e=>{
  if(e.touches.length===2){e.preventDefault();const d=distance(e.touches[0],e.touches[1]);if(pinchDistance==null){pinchDistance=d;lastPinchStep=d;return;}if(Math.abs(d-lastPinchStep)>=18){const c=pinchCenter(e.touches[0],e.touches[1]);viewport.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:d>lastPinchStep?-120:120,clientX:c.x,clientY:c.y}));lastPinchStep=d;}return;}
  if(e.touches.length!==1)return;const t=e.touches[0];e.preventDefault();
  if(panMode&&panStart){viewport.scrollLeft=panStart.left-(t.clientX-panStart.x);viewport.scrollTop=panStart.top-(t.clientY-panStart.y);}
  else dispatchMouse('mousemove',t,window);
},{passive:false});
canvas.addEventListener('touchend',e=>{e.preventDefault();if(!panMode)window.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,cancelable:true,button:0,buttons:0}));panStart=null;pinchDistance=null;lastPinchStep=0;canvas.style.cursor=panMode?'grab':'crosshair';},{passive:false});
canvas.addEventListener('touchcancel',()=>{panStart=null;pinchDistance=null;lastPinchStep=0});
const btn=$('#mobilePanBtn');if(btn)btn.disabled=false;syncPanButton();}

function bindCurrentCanvas(){const canvas=viewport.querySelector('canvas');if(canvas)bindCanvas(canvas)}
const observer=new MutationObserver(()=>{bindCurrentCanvas();const btn=$('#mobilePanBtn');if(btn)btn.disabled=!viewport.querySelector('canvas')});observer.observe(viewport,{childList:true,subtree:true});

function addMobileHint(){if(!isTouch())return;const help=document.querySelector('.crop-help');if(!help||document.querySelector('.mobile-touch-hint'))return;const hint=document.createElement('div');hint.className='pill mobile-touch-hint';hint.style.marginTop='8px';hint.textContent='スマホ操作: ✋移動 / 1本指で範囲選択 / 2本指でピンチズーム';help.insertAdjacentElement('afterend',hint);}

addPanButton();addMobileHint();bindCurrentCanvas();
window.addEventListener('resize',()=>{if(window.innerWidth<=820)addMobileHint()});
})();
