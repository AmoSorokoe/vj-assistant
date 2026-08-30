(()=>{"use strict";
const STORAGE_KEY="vj-youtube-video-map-v1";
const $=s=>document.querySelector(s);
let videoMap=loadMap();
let scanQueued=false;

function loadMap(){try{return JSON.parse(localStorage.getItem(STORAGE_KEY))||{}}catch{return {}}}
function saveMap(){localStorage.setItem(STORAGE_KEY,JSON.stringify(videoMap))}
function norm(s){return String(s||"").normalize("NFKC").toLowerCase().replace(/[\s\u3000]+/g,"").trim()}
function trackKey(row){const title=row.querySelector(".title")?.value||"";const artist=row.querySelector(".artist")?.value||"";return `${norm(title)}::${norm(artist)}`}
function extractVideoId(value){
  const raw=String(value||"").trim();
  if(!raw)return "";
  if(/^[A-Za-z0-9_-]{11}$/.test(raw))return raw;
  try{
    const url=new URL(raw);
    const host=url.hostname.replace(/^www\./,"");
    if(host==="youtu.be")return validId(url.pathname.split("/").filter(Boolean)[0]);
    if(host.endsWith("youtube.com")){
      const q=validId(url.searchParams.get("v"));if(q)return q;
      const parts=url.pathname.split("/").filter(Boolean);
      if(["shorts","embed","live"].includes(parts[0]))return validId(parts[1]);
    }
  }catch{}
  const m=raw.match(/(?:v=|youtu\.be\/|shorts\/|embed\/|live\/)([A-Za-z0-9_-]{11})/);return m?m[1]:"";
}
function validId(v){return /^[A-Za-z0-9_-]{11}$/.test(String(v||""))?String(v):""}
function canonical(id){return id?`https://www.youtube.com/watch?v=${id}`:""}
function escapeHtml(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}

function ensureHeaderControls(){
  const area=$(".result-head-actions");if(!area)return;
  if(!$("#youtubeVideoBadge")){
    const badge=document.createElement("div");badge.className="badge youtube-video-badge";badge.id="youtubeVideoBadge";badge.textContent="動画 0/0";area.insertBefore(badge,$("#addBlankBtn")||null);
  }
  if(!$("#openYoutubePlaylistBtn")){
    const btn=document.createElement("button");btn.id="openYoutubePlaylistBtn";btn.className="btn youtube-playlist-btn";btn.textContent="▶ 一括プレイリストを開く";btn.disabled=true;btn.addEventListener("click",openBatchPlaylist);area.appendChild(btn);
  }
}

function enhanceRows(){
  ensureHeaderControls();
  document.querySelectorAll("#tracks .row-group").forEach(enhanceRow);
  updateSummary();
}

function enhanceRow(row){
  if(row.dataset.youtubeEnhanced==="1")return;
  const edit=row.querySelector(".edit");if(!edit)return;
  row.dataset.youtubeEnhanced="1";
  const wrap=document.createElement("div");wrap.className="youtube-url-row";
  wrap.innerHTML=`<input class="youtube-url-input" type="text" spellcheck="false" placeholder="YouTube動画URLを貼り付け"><button class="youtube-paste-btn" type="button">貼付</button><span class="youtube-url-state">未登録</span>`;
  edit.appendChild(wrap);
  const input=wrap.querySelector(".youtube-url-input"),paste=wrap.querySelector(".youtube-paste-btn"),state=wrap.querySelector(".youtube-url-state");
  const key=trackKey(row),saved=videoMap[key];
  if(saved?.videoId)input.value=saved.url||canonical(saved.videoId);
  function commit(){
    const id=extractVideoId(input.value),keyNow=trackKey(row);
    if(!input.value.trim()){
      delete videoMap[keyNow];saveMap();setState(state,input,"empty");updateSummary();return;
    }
    if(!id){setState(state,input,"bad");updateSummary();return;}
    const url=canonical(id);input.value=url;videoMap[keyNow]={videoId:id,url,updatedAt:Date.now()};saveMap();setState(state,input,"ok");updateSummary();
  }
  input.addEventListener("change",commit);
  input.addEventListener("paste",()=>setTimeout(commit,0));
  input.addEventListener("input",()=>{const id=extractVideoId(input.value);setState(state,input,id?"ok":input.value.trim()?"bad":"empty");updateSummary(false)});
  paste.addEventListener("click",async()=>{
    try{const text=await navigator.clipboard.readText();if(!text)throw new Error();input.value=text;commit()}catch{input.focus();state.textContent="Ctrl+Vで貼付";state.className="youtube-url-state warn"}
  });
  row.querySelectorAll(".title,.artist").forEach(el=>el.addEventListener("change",()=>{
    const id=extractVideoId(input.value);if(id){const k=trackKey(row);videoMap[k]={videoId:id,url:canonical(id),updatedAt:Date.now()};saveMap()}
  }));
  setState(state,input,extractVideoId(input.value)?"ok":"empty");
}

function setState(state,input,type){
  state.className="youtube-url-state";
  input.classList.remove("valid","invalid");
  if(type==="ok"){state.textContent="✓ 登録済";state.classList.add("ok");input.classList.add("valid")}
  else if(type==="bad"){state.textContent="URLを確認";state.classList.add("bad");input.classList.add("invalid")}
  else{state.textContent="未登録"}
}

function currentVideoIds(){
  const ids=[];
  document.querySelectorAll("#tracks .row-group").forEach(row=>{
    const input=row.querySelector(".youtube-url-input");if(!input)return;
    const id=extractVideoId(input.value);if(id&&!ids.includes(id))ids.push(id);
  });
  return ids;
}
function updateSummary(rescan=true){
  if(rescan)document.querySelectorAll("#tracks .row-group:not([data-youtube-enhanced='1'])").forEach(enhanceRow);
  const total=document.querySelectorAll("#tracks .row-group").length,ids=currentVideoIds();
  const badge=$("#youtubeVideoBadge"),btn=$("#openYoutubePlaylistBtn");
  if(badge)badge.textContent=`動画 ${ids.length}/${total}`;
  if(btn){btn.disabled=ids.length===0;btn.title=ids.length?`${ids.length}曲をセトリ順で開きます`:"YouTube動画URLを1曲以上登録してください"}
}
function openBatchPlaylist(){
  const ids=currentVideoIds();
  if(!ids.length){alert("YouTube動画URLがまだ登録されていません。");return}
  const url=`https://www.youtube.com/watch_videos?video_ids=${ids.join(",")}`;
  window.open(url,"_blank","noopener,noreferrer");
}

const observer=new MutationObserver(()=>{
  if(scanQueued)return;scanQueued=true;requestAnimationFrame(()=>{scanQueued=false;enhanceRows()});
});
const tracks=$("#tracks");if(tracks)observer.observe(tracks,{childList:true,subtree:true});
ensureHeaderControls();enhanceRows();
window.addEventListener("storage",e=>{if(e.key===STORAGE_KEY){videoMap=loadMap();enhanceRows()}});
})();