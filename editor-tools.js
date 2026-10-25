import {newContent,uid} from '/canvas.js';
const copy=value=>JSON.parse(JSON.stringify(value));
export function switchContentMode(content,mode){
 if(!['slides','images','videos','menu'].includes(mode))throw Error('지원하지 않는 편집 모드입니다.');
 if(content.mode===mode)return copy(content);
 const archives=copy(content.modeDrafts||{}),previous=copy(content);delete previous.modeDrafts;
 if(previous.mode!=='basic')archives[previous.mode]=previous;
 const target=archives[mode]?copy(archives[mode]):newContent(mode);delete archives[mode];
 target.aspect=content.aspect;target.modeDrafts=archives;return target;
}
export function selectionBounds(elements){if(!elements.length)return null;const x=Math.min(...elements.map(e=>e.x)),y=Math.min(...elements.map(e=>e.y));return {x,y,w:Math.max(...elements.map(e=>e.x+e.w))-x,h:Math.max(...elements.map(e=>e.y+e.h))-y}}
export function alignSelection(elements,alignment){const active=elements.filter(e=>!e.locked);if(!active.length)return;const b=active.length===1?{x:0,y:0,w:100,h:100}:selectionBounds(active);for(const e of active){if(alignment==='left')e.x=b.x;if(alignment==='center')e.x=b.x+(b.w-e.w)/2;if(alignment==='right')e.x=b.x+b.w-e.w;if(alignment==='top')e.y=b.y;if(alignment==='middle')e.y=b.y+(b.h-e.h)/2;if(alignment==='bottom')e.y=b.y+b.h-e.h}}
export function distributeSelection(elements,axis){const active=elements.filter(e=>!e.locked).sort((a,b)=>a[axis]-b[axis]);if(active.length<3)return;const size=axis==='x'?'w':'h',first=active[0][axis],last=active.at(-1)[axis]+active.at(-1)[size],gap=(last-first-active.reduce((n,e)=>n+e[size],0))/(active.length-1);if(gap<0)return;let cursor=first;for(const e of active){e[axis]=cursor;cursor+=e[size]+gap}}
export function duplicateSelection(elements,offset=2){const b=selectionBounds(elements),dx=Math.min(offset,100-b.x-b.w),dy=Math.min(offset,100-b.y-b.h);return elements.map(e=>({...copy(e),id:uid(),x:e.x+dx,y:e.y+dy,locked:false}))}
export function moveSelection(elements,dx,dy){const b=selectionBounds(elements);if(!b)return;dx=Math.max(-b.x,Math.min(100-b.x-b.w,dx));dy=Math.max(-b.y,Math.min(100-b.y-b.h,dy));for(const e of elements){e.x=Math.round((e.x+dx)*100)/100;e.y=Math.round((e.y+dy)*100)/100}}
export function snapBox(box,threshold=.7){const guides=[];const result={...box};for(const [pos,size,axis]of [['x','w','vertical'],['y','h','horizontal']]){const points=[box[pos],box[pos]+box[size]/2,box[pos]+box[size]],targets=[0,50,100];let best=null;for(const point of points)for(const target of targets){const delta=target-point;if(Math.abs(delta)<=threshold&&(!best||Math.abs(delta)<Math.abs(best.delta)))best={delta,target}}if(best){result[pos]+=best.delta;guides.push({axis,at:best.target})}}return {box:result,guides}}
