import {shapeMarkup} from '/shapes.js';
import {fontFamily} from '/fonts.js';
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const types = {ads:'광고판',menu:'메뉴판',notice:'안내판'};
export const icons = {
 grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 screen:'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>',
 ads:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="15" cy="8" r="1.5"/>',
 menu:'<path d="M5 3h14v18H5zM8 7h8M8 11h8M8 15h5"/>',
 bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
 settings:'<path d="m9 3-1 3-3 1 1 4-2 3 3 3 4-1 3 2 3-3-1-4 2-3-3-3-4 1z"/><circle cx="11" cy="11" r="3"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4 2c-1 .7-1.5 1-1.5 3M12 17h.01"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
 external:'<path d="M14 3h7v7m-1-6L10 14M10 3H4v17h16v-6"/>',
 edit:'<path d="m16 3 5 5-12 12-6 1 1-6zM13 6l5 5"/>',
 play:'<path d="m8 4 12 8-12 8z"/>',pause:'<path d="M8 4v16M16 4v16"/>',
 image:'<rect x="2" y="3" width="20" height="18" rx="2"/><circle cx="8" cy="9" r="2"/><path d="m2 18 6-5 4 3 4-5 6 7"/>',
 video:'<rect x="2" y="5" width="14" height="14" rx="2"/><path d="m16 9 6-4v14l-6-4"/>',
 text:'<path d="M4 4h16M12 4v16M8 20h8"/>',shape:'<rect x="3" y="3" width="18" height="18" rx="2"/>',
 trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
 copy:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
 undo:'<path d="m8 4-5 5 5 5M3 9h11a6 6 0 0 1 0 12"/>',redo:'<path d="m16 4 5 5-5 5m5-5H10a6 6 0 0 0 0 12"/>',
 up:'<path d="m5 15 7-7 7 7"/>',down:'<path d="m5 9 7 7 7-7"/>',
 search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
 save:'<path d="M4 3h13l4 4v14H3V3h1M7 3v6h10V3M7 21v-8h10v8"/>',
 check:'<path d="m4 12 5 5L20 6"/>',refresh:'<path d="M20 8a9 9 0 1 0 0 8M20 3v5h-5"/>',
 mail:'<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 5 10 8L22 5"/>',
 phone:'<path d="M5 3h4l2 5-3 2a15 15 0 0 0 6 6l2-3 5 2v4c-10 4-21-7-16-16z"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 server:'<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6h.01M7 17h.01M11 6h6M11 17h6"/>',
 layers:'<path d="m12 3 10 6-10 6L2 9zM2 13l10 6 10-6M2 17l10 6 10-6"/>',
 close:'<path d="m6 6 12 12M18 6 6 18"/>',hamburger:'<path d="M3 6h18M3 12h18M3 18h18"/>'
};
export function icon(name){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.screen}</svg>`}
export function newContent(mode='slides') {return {mode, fontFamily:'pretendard', background:'#142039',aspect:'landscape',playbackRate:1,slides:[],menuItems:[]}}
export function uid(){return 's-'+(crypto.randomUUID ? crypto.randomUUID() : Date.now()+'-'+Math.random().toString(36).slice(2))}
export function newElement(kind, extra={}){return {id:uid(),kind,x:10,y:12,w:70,h:20,text:kind==='text'?'새 텍스트':'',color:'#ffffff',fontSize:64,bold:true,align:'left',fit:'cover',...extra}}
export function newSlide(){return {id:uid(),duration:8,transition:'fade',elements:[]}}
const stageObservers=new WeakMap();
export function releaseStage(host){stageObservers.get(host)?.disconnect();stageObservers.delete(host)}
export function releaseStages(root){if(!root)return;root.querySelectorAll('.stage').forEach(releaseStage)}
function surfaceFor(host,screen){releaseStage(host);const surface=document.createElement('div');surface.className='design-surface';const portrait=screen.content?.aspect==='portrait',width=portrait?900:1600,height=portrait?1600:900;surface.style.width=width+'px';surface.style.height=height+'px';host.append(surface);const fit=()=>{surface.style.transform=`scale(${host.getBoundingClientRect().width/width})`};fit();const observer=new ResizeObserver(fit);observer.observe(host);stageObservers.set(host,observer);return surface}
export function elementNode(element, media, screen, animate=false){
 const node=document.createElement('div');node.className='scene-element';node.dataset.element=element.id;
 Object.assign(node.style,{left:element.x+'%',top:element.y+'%',width:element.w+'%',height:element.h+'%',color:element.color||'#ffffff',fontSize:(element.fontSize||48)+'px',fontWeight:element.bold?700:400,fontStyle:element.italic?'italic':'normal',textDecoration:element.underline?'underline':'none',transform:`rotate(${element.rotation||0}deg)`,filter:element.shadow?'drop-shadow(0px 8px 12px #00000055)':'none',textAlign:element.align||'left',lineHeight:String(element.lineHeight||1.25),letterSpacing:(element.letterSpacing||0)+'px',fontFamily:fontFamily(element.fontFamily||screen.content?.fontFamily),opacity:element.opacity??1,borderRadius:(element.radius||0)+'px'});
 const content=document.createElement('div');content.className='layer-content';content.style.justifyContent=({left:'flex-start',center:'center',right:'flex-end'})[element.align||'left'];node.append(content);
 if(element.kind==='text'){const t=document.createElement('div');t.textContent=element.text;content.append(t)}
 else if(element.kind==='shape'){const portrait=screen.content?.aspect==='portrait';content.innerHTML=shapeMarkup(element.shape||'rect',(portrait?900:1600)*element.w/100,(portrait?1600:900)*element.h/100,element)}
 else {const item=media.find(m=>m.id===element.mediaId);if(item){const child=document.createElement(element.kind==='video'?'video':'img');child.src=item.url;child.style.objectFit=element.fit||'cover';child.style.transform=`scale(${element.flipX?-1:1},${element.flipY?-1:1})`;if(element.kind==='video'){child.muted=true;child.playsInline=true;child.preload='metadata';child.playbackRate=element.playbackRate||screen.content?.playbackRate||1}else child.alt=item.name;child.addEventListener('error',()=>{content.textContent='미디어를 재생할 수 없습니다';content.style.fontSize='24px'},{once:true});content.append(child)}else content.textContent='미디어 없음'}
 const a=element.animation;if(animate&&a&&a.preset!=='none'){content.classList.add('layer-'+a.preset);Object.assign(content.style,{animationDuration:(a.duration||.8)+'s',animationDelay:(a.delay||0)+'s',animationIterationCount:a.repeat?'infinite':'1',animationFillMode:'both',animationTimingFunction:'ease-out'})}
 return node;
}
export function drawStage(host, screen, media=[], slideIndex=0, options={}){
 host.replaceChildren();host.classList.add('stage');host.classList.toggle('portrait',screen.content?.aspect==='portrait');
 const activeSlide=screen.content?.slides?.[slideIndex % (screen.content.slides.length||1)];host.style.background=activeSlide?.background||screen.content?.background||'#142039';
 const surface=surfaceFor(host,screen);const scene=document.createElement('div');scene.className='scene';surface.append(scene);
 const c=screen.content;
 if(screen.status==='paused'&&!options.editor){scene.innerHTML='<div class="screensaver"><div class="screensaver-mark">N<span></span></div><strong>Nuvistage</strong><span>화면을 잠시 쉬고 있습니다</span></div>';host.style.background='#080e1b';return scene}
 if(c?.mode==='menu'){
  const wrapper=document.createElement('div');wrapper.className='menu-scene';wrapper.classList.toggle('compact-menu',c.menuItems.length>10);
  wrapper.innerHTML=`<div class="menu-heading" style="color:${escapeHtml(screen.accent)}">${escapeHtml(screen.title)}</div><div class="menu-subtitle">${escapeHtml(screen.subtitle)}</div><div class="menu-items">${c.menuItems.map(item=>`<div class="menu-item ${item.soldOut?'sold':''}"><div class="menu-top"><span>${item.featured?'<b class="recommend">BEST</b>':''}${escapeHtml(item.name)}</span><span>${item.soldOut?'품절':escapeHtml(item.price)}</span></div><div class="menu-desc">${escapeHtml(item.description)}</div></div>`).join('')}</div>`;scene.append(wrapper);
 }else if(c && ['slides','images','videos'].includes(c.mode) && c.slides.length){
  const slide=c.slides[slideIndex % c.slides.length];
  slide.elements.filter(e=>!e.hidden).forEach(e=>scene.append(elementNode({...e,fontFamily:e.fontFamily||slide.fontFamily||c.fontFamily},media,screen,options.animate)));
  if(options.animate)scene.classList.add('transition-'+slide.transition);
 }else if(c&&['slides','images','videos'].includes(c.mode)){const empty=document.createElement('div');empty.className='media-placeholder';empty.textContent=['images','videos'].includes(c.mode)?'미디어를 추가해 주세요':'텍스트 · 이미지 · 영상을 자유롭게 추가해 주세요';scene.append(empty)}else basic(scene,screen);

 return scene;
}
function basic(scene,s){const wrapper=document.createElement('div');wrapper.className='basic-scene';wrapper.innerHTML=`<div class="scene-eyebrow">${escapeHtml(s.name)}</div><h2 style="color:${escapeHtml(s.accent)}">${escapeHtml(s.title)}</h2><p>${escapeHtml(s.subtitle)}</p>`;scene.append(wrapper)}
export async function exitLayers(host,slide){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 const promises=[];
 for(const element of slide.elements){const config=element.animation||{},preset=config.exit||'none';if(preset==='none')continue;const outer=[...host.querySelectorAll('.scene-element')].find(n=>n.dataset.element===element.id),node=outer?.querySelector('.layer-content');if(!node)continue;
  const current=getComputedStyle(node),start={opacity:current.opacity,transform:current.transform==='none'?'translate(0,0)':current.transform};let target='translate(0,0)';
  const effect=preset==='reverse'?({rise:'drop','slide-left':'slide-left',zoom:'zoom-out'})[config.preset]||'fade':preset;
  if(effect==='drop')target=preset==='reverse'?'translateY(28px)':'translateY(40px)';if(effect==='slide-left')target='translateX(-60px)';if(effect==='slide-right')target='translateX(60px)';if(effect==='zoom-out')target='scale(.8)';
  node.style.animation='none';const animation=node.animate([start,{opacity:0,transform:target}],{duration:(config.exitDuration||.6)*1000,delay:(config.exitDelay||0)*1000,fill:'both',easing:'ease-in'});promises.push(animation.finished.catch(()=>{}));
 }
 await Promise.all(promises);
}
export class Playback {
 constructor(host,screen,media,options={}){this.host=host;this.screen=screen;this.media=media;this.index=options.startIndex||0;this.options=options;this.dead=false;this.exiting=false;this.show()}
 show(){if(this.dead)return;clearTimeout(this.timer);this.exiting=false;const s=this.screen,c=s.content;drawStage(this.host,s,this.media,this.index,{animate:true});this.host.dataset.playbackPhase='display';this.host.dataset.slideIndex=String(this.index);
 if(s.status==='paused')return;const slides=c?.slides||[],playable=['slides','images','videos'].includes(c?.mode)&&slides.length;const current=slides[this.index];let pending=this.host.querySelectorAll('video').length;
 for(const video of this.host.querySelectorAll('video')){video.loop=!(playable&&current.duration===0);video.addEventListener('ended',()=>{if(playable&&current.duration===0&&--pending===0)this.advance()},{once:true});video.addEventListener('error',()=>{if(playable&&current.duration===0){clearTimeout(this.timer);this.timer=setTimeout(()=>this.advance(),5000)}},{once:true});video.play().catch(()=>{if(this.dead||this.exiting)return;const n=document.createElement('div');n.className='media-error';n.textContent='영상 재생을 시작하려면 화면을 눌러 주세요.';this.host.append(n);video.style.pointerEvents='auto';video.onclick=()=>video.play().then(()=>n.remove()).catch(()=>{});if(playable&&current.duration===0){clearTimeout(this.timer);this.timer=setTimeout(()=>this.advance(),15000)}})}
 if(playable&&current.duration>0)this.timer=setTimeout(()=>this.advance(),current.duration*1000);
 }
 async advance(){if(this.dead||this.exiting)return;this.exiting=true;clearTimeout(this.timer);this.host.dataset.playbackPhase='exit';this.host.querySelectorAll('video').forEach(v=>v.pause());const slide=this.screen.content.slides[this.index];await exitLayers(this.host,slide);if(this.dead)return;this.index=(this.index+1)%this.screen.content.slides.length;this.show()}
 destroy(){this.dead=true;releaseStage(this.host);clearTimeout(this.timer);for(const animation of this.host.getAnimations?.({subtree:true})||[])animation.cancel();this.host.querySelectorAll('video').forEach(v=>{v.pause();v.removeAttribute('src');v.load()});delete this.host.dataset.playbackPhase}
}
