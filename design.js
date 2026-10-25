import {newSlide,uid} from '/canvas.js';
const copy=value=>JSON.parse(JSON.stringify(value));
export function cloneSlideDesign(slide,background){const result=slide?copy(slide):newSlide();result.id=uid();result.background ||= background||'#142039';result.elements.forEach(e=>e.id=uid());return result}
export function applyDesign(screen,template,{index=0,scope='slide'}={}){
 const expected=screen.type==='notice'?'ads':screen.type;if(template.type!==expected)throw Error('현재 화면 종류에 맞는 템플릿을 선택해 주세요.');const next=copy(screen),content=copy(template.content);
 if(scope==='slide'&&content.mode!=='slides')throw Error('이 템플릿은 전체 구성으로 불러와 주세요.');
 if(scope==='all'){content.slides=content.slides.map(s=>cloneSlideDesign(s,content.background));next.content=content;next.title=template.title;next.subtitle=template.subtitle;next.accent=template.accent;return {screen:next,index:0}}
 if(content.aspect!==next.content.aspect)throw Error('화면 방향이 다릅니다. 기본 설정에서 방향을 바꾸거나 전체 구성으로 불러와 주세요.');
 const source=content.slides[0];if(!source)throw Error('적용할 슬라이드가 없습니다.');const slide=cloneSlideDesign(source,content.background);slide.templateId=template.id;slide.templateName=template.name;slide.fontFamily=source.fontFamily||content.fontFamily||'nanum-gothic';
 if(next.content.mode!=='slides'){next.content.mode='slides';next.content.slides=[]}
 index=Math.min(index,next.content.slides.length);next.content.slides[index]=slide;return {screen:next,index};
}
