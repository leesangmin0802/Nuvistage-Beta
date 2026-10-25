import {Playback} from '/canvas.js';
import {preloadFonts,fontsFor,installCustomFonts} from '/fonts.js';
await preloadFonts();
const id=new URLSearchParams(location.search).get('id'),host=document.getElementById('player'),status=document.getElementById('connection');
const token=new URLSearchParams(location.hash.slice(1)).get('token');
window.addEventListener('hashchange',()=>location.reload());
let clientId;try{clientId=localStorage.getItem('pisignage-player-id');if(!clientId){clientId='player-'+(crypto.randomUUID?.()||Date.now()+'-'+Math.random().toString(36).slice(2));localStorage.setItem('pisignage-player-id',clientId)}}catch{clientId='player-'+Math.random().toString(36).slice(2)}
let player,last='';
function clear(message){player?.destroy();player=null;last='';host.className='player-message';host.textContent=message;status.textContent=''}
async function update(){try{
 if(!id){clear('출력 URL에 화면 ID가 없습니다.');return}
 const response=await fetch(token?'/api/player/'+encodeURIComponent(id):'/api/screens/'+encodeURIComponent(id),{cache:'no-store',headers:token?{Authorization:'Bearer '+token,'X-Player-ID':clientId}:{}});
 if(response.status===410){clear('이 화면 유형은 더 이상 제공하지 않습니다. 관리자에서 광고판이나 메뉴판을 연결해 주세요.');return}
 if(response.status===404){clear('삭제되었거나 존재하지 않는 화면입니다.');return}
 if(response.status===401){clear('연결 권한이 없습니다. 관리자에서 이 화면의 플레이어 연결 링크를 확인해 주세요.');return}
 if(!response.ok)throw Error('서버 오류');
 let screen,media=[];if(token){const data=await response.json();screen=data.screen;media=data.media;installCustomFonts(data.customFonts)}else{screen=await response.json();const r=await fetch('/api/media');if(!r.ok)throw Error('미디어 오류');media=(await r.json()).media;const fonts=await fetch('/api/fonts');if(fonts.ok)installCustomFonts((await fonts.json()).fonts)}
 await preloadFonts(screen.status==='paused'?['pretendard']:fontsFor(screen));status.textContent='';const signature=JSON.stringify(screen);
 if(signature!==last){player?.destroy();host.className='stage';player=new Playback(host,screen,media);document.title=screen.name+' · Nuvistage';last=signature}else if(player){player.media=media}

 }catch(error){status.textContent='연결 재시도 중 · 마지막 화면을 유지합니다.'}finally{setTimeout(update,1000)}}
update();
