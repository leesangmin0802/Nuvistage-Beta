import {Playback} from '/canvas.js';
import {preloadFonts,fontsFor} from '/fonts.js';
export function ruleActive(rule,timezone,instant=new Date()){
 const fields=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(instant).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));
 const day=new Date(Date.UTC(+fields.year,+fields.month-1,+fields.day)),minutes=+fields.hour*60+(+fields.minute),time=value=>+value.slice(0,2)*60+(+value.slice(3)),start=time(rule.start),end=time(rule.end);
 if(start<end){if(minutes<start||minutes>=end)return false}else if(start>end){if(minutes<end)day.setUTCDate(day.getUTCDate()-1);else if(minutes<start)return false}
 const date=day.toISOString().slice(0,10),weekday=(day.getUTCDay()+6)%7;
 return rule.days.includes(weekday)&&(!rule.date_from||date>=rule.date_from)&&(!rule.date_to||date<=rule.date_to)
}
export function scheduledScreen(program,instant=new Date()){
 if(program.override&&program.override.until>instant.getTime()/1000)return program.override.screen;
 const rule=[...program.rules].sort((a,b)=>b.priority-a.priority||(a.id<b.id?-1:a.id>b.id?1:0)).find(r=>ruleActive(r,program.timezone,instant));
 if(rule?.paused)return {...Object.values(program.playlists)[0],status:'paused'};
 return program.playlists[rule?.playlist_id||program.default_playlist_id];
}
export class ScheduledPlayback{
 constructor(host,screen,media,{program=null,...options}={}){this.host=host;this.media=media;this.program=program;this.screen=screen;this.options=options;this.update();if(program)this.timer=setInterval(()=>this.update(),1000)}
 async update(){if(this.dead)return;const screen=this.program?scheduledScreen(this.program):this.screen;if(!screen)return;const signature=screen.id+':'+screen.revision+':'+screen.status+':'+(this.program?.override?.until>Date.now()/1000?'override':'normal');if(signature!==this.signature){this.signature=signature;const epoch=this.epoch=(this.epoch||0)+1;await preloadFonts([...fontsFor(screen),...Object.values(this.program?.playlists||{}).flatMap(fontsFor)]);if(this.dead||epoch!==this.epoch)return;this.playback?.destroy();this.zonePlayers?.forEach(p=>p.destroy());this.host.replaceChildren();const zones=this.program?.zones||[];if(zones.length>1&&screen.status!=='paused'&&!(this.program.override?.until>Date.now()/1000)){this.host.classList.toggle('portrait',screen.content?.aspect==='portrait');this.host.classList.add('stage');this.zonePlayers=zones.map((zone,i)=>{const container=document.createElement('div');container.className='program-zone';Object.assign(container.style,{left:zone.x+'%',top:zone.y+'%',width:zone.w+'%',height:zone.h+'%'});const region=document.createElement('div');region.className='stage program-region';container.append(region);this.host.append(container);return new Playback(region,i?this.program.playlists[zone.playlist_id]:screen,this.media,this.options)})}else{this.zonePlayers=[];this.playback=new Playback(this.host,screen,this.media,this.options)}}this.overlay(screen)}
 overlay(screen){if(!this.program||screen.status==='paused')return;let layer=this.host.querySelector('.program-overlay');if(!layer){layer=document.createElement('div');layer.className='program-overlay';this.host.append(layer)}let ticker=layer.querySelector('.program-ticker'),clock=layer.querySelector('.program-clock');if(this.program.ticker&&!ticker){ticker=document.createElement('div');ticker.className='program-ticker';const text=document.createElement('span');text.textContent=this.program.ticker;ticker.append(text);layer.append(ticker)}if(this.program.clock){if(!clock){clock=document.createElement('time');clock.className='program-clock';layer.append(clock)}clock.textContent=new Intl.DateTimeFormat('ko-KR',{timeZone:this.program.timezone,hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date())}}
 destroy(){this.dead=true;clearInterval(this.timer);this.playback?.destroy();this.zonePlayers?.forEach(p=>p.destroy());this.host.querySelector('.program-overlay')?.remove()}
}
