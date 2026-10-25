export const SHAPES=[['rect','사각형'],['rounded','둥근 사각형'],['ellipse','타원'],['triangle','삼각형'],['diamond','마름모'],['pentagon','오각형'],['hexagon','육각형'],['star','별'],['heart','하트'],['arrow-right','오른쪽 화살표'],['arrow-left','왼쪽 화살표'],['chevron','꺾은 화살표'],['speech','말풍선'],['line','직선']];
export function shapeMarkup(shape='rect',w=100,h=100,settings={}){
 const color=settings.color||'#6685ff',stroke=settings.stroke||color,sw=settings.strokeWidth||0,p=(x,y)=>`${x*w/100},${y*h/100}`;let geometry='';
 const polygon=points=>`<polygon points="${points.map(([x,y])=>p(x,y)).join(' ')}"/>`;
 if(shape==='ellipse')geometry=`<ellipse cx="${w/2}" cy="${h/2}" rx="${Math.max(.1,(w-sw)/2)}" ry="${Math.max(.1,(h-sw)/2)}"/>`;
 else if(shape==='triangle')geometry=polygon([[50,2],[98,98],[2,98]]);
 else if(shape==='diamond')geometry=polygon([[50,2],[98,50],[50,98],[2,50]]);
 else if(['pentagon','hexagon','star'].includes(shape)){const count=shape==='star'?10:shape==='hexagon'?6:5;geometry=polygon(Array.from({length:count},(_,i)=>{const a=-Math.PI/2+i*Math.PI*2/count,r=shape==='star'&&i%2?.43:1;return [50+47*Math.cos(a)*r,50+47*Math.sin(a)*r]}))}
 else if(shape==='heart')geometry=`<path d="M ${p(50,94)} C ${p(-15,50)} ${p(0,-5)} ${p(30,8)} Q ${p(44,12)} ${p(50,27)} Q ${p(56,12)} ${p(70,8)} C ${p(100,-5)} ${p(115,50)} ${p(50,94)} Z"/>`;
 else if(shape==='arrow-right')geometry=polygon([[2,30],[62,30],[62,4],[98,50],[62,96],[62,70],[2,70]]);
 else if(shape==='arrow-left')geometry=polygon([[98,30],[38,30],[38,4],[2,50],[38,96],[38,70],[98,70]]);
 else if(shape==='chevron')geometry=polygon([[3,4],[65,4],[98,50],[65,96],[3,96],[35,50]]);
 else if(shape==='speech')geometry=polygon([[3,3],[97,3],[97,73],[43,73],[20,97],[20,73],[3,73]]);
 else if(shape==='line')geometry=`<line x1="${Math.max(1,sw/2)}" y1="${h/2}" x2="${w-Math.max(1,sw/2)}" y2="${h/2}" stroke-width="${sw||4}"/>`;
 else geometry=`<rect x="${sw/2}" y="${sw/2}" width="${Math.max(.1,w-sw)}" height="${Math.max(.1,h-sw)}" rx="${shape==='rounded'?(settings.radius||Math.min(w,h)*.18):(settings.radius||0)}"/>`;
 return `<svg class="vector-shape" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" fill="${shape==='line'?'none':color}" stroke="${stroke}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true">${geometry}</svg>`;
}
