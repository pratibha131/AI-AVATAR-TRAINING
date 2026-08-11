/* Shared avatar engine: parametric professional presenter avatars (SVG)
   with a live facial rig: viseme mouth, blinking eyelids, brows, hand gestures,
   gaze direction, and body posture shifts. Used by both editor preview & renderer. */

const AVATARS = [
  { id:'maya',   name:'Maya',   role:'Corporate Trainer',      gender:'Female', skin:'#a5673f', skinD:'#8a5330', hair:'#2d2016', hairStyle:'bun',    attire:'blazer', attireC:'#39415c', shirtC:'#e8e6f5', bg:'#e7ecf7', lip:'#7a3b2e', glasses:false, smileBase:.45 },
  { id:'david',  name:'David',  role:'Business Professional',  gender:'Male',   skin:'#e8b48c', skinD:'#cf9a72', hair:'#3d2e22', hairStyle:'short',  attire:'suit',   attireC:'#2b3345', shirtC:'#ffffff', bg:'#e9f1ef', lip:'#a95f4b', glasses:false, tie:'#8b2f3d', smileBase:.3 },
  { id:'priya',  name:'Priya',  role:'Technology Speaker',     gender:'Female', skin:'#c98d5f', skinD:'#ad7449', hair:'#1d1712', hairStyle:'long',   attire:'blazer', attireC:'#5b3d6e', shirtC:'#f4eef8', bg:'#f0eaf6', lip:'#8a4034', glasses:true,  smileBase:.5 },
  { id:'james',  name:'James',  role:'University Professor',   gender:'Male',   skin:'#7c5138', skinD:'#654127', hair:'#242424', hairStyle:'short',  attire:'tweed',  attireC:'#54514a', shirtC:'#dfe8f2', bg:'#efeee8', lip:'#5d3428', glasses:true,  beard:true, smileBase:.3 },
  { id:'elena',  name:'Elena',  role:'Healthcare Expert',      gender:'Female', skin:'#f0c8a8', skinD:'#d8ab86', hair:'#7a4a26', hairStyle:'bun',    attire:'coat',   attireC:'#f2f5f9', shirtC:'#9fb8d8', bg:'#e6f2f0', lip:'#b06050', glasses:false, smileBase:.5 },
  { id:'kenji',  name:'Kenji',  role:'Engineer',               gender:'Male',   skin:'#ecc194', skinD:'#d3a677', hair:'#15120e', hairStyle:'short',  attire:'polo',   attireC:'#2e6e63', shirtC:'#2e6e63', bg:'#eaf0ea', lip:'#a3644c', glasses:false, smileBase:.35 },
  { id:'amara',  name:'Amara',  role:'Finance Expert',         gender:'Female', skin:'#6e4630', skinD:'#583722', hair:'#171310', hairStyle:'long',   attire:'suit',   attireC:'#232a3a', shirtC:'#f5f0e8', bg:'#f2ece2', lip:'#59291f', glasses:false, smileBase:.4 },
  { id:'carlos', name:'Carlos', role:'Teacher',                gender:'Male',   skin:'#d9a06d', skinD:'#bf8654', hair:'#2c211a', hairStyle:'wavy',   attire:'sweater',attireC:'#7a4133', shirtC:'#ede4da', bg:'#eef0e6', lip:'#96543f', smileBase:.45 },
];

function avatarById(id){ return AVATARS.find(a=>a.id===id) || AVATARS[0]; }

/* SVG bust in a 200x200 viewBox, centered for a circular or card frame. */
function avatarSVG(cfg){
  const c = (typeof cfg==='string') ? avatarById(cfg) : cfg;
  const hair = hairSVG(c);
  const attire = attireSVG(c);
  const glasses = c.glasses ? `
    <g class="av-glasses" stroke="#2c2c34" stroke-width="2.6" fill="rgba(255,255,255,.08)">
      <rect x="66" y="86" width="28" height="20" rx="9"/>
      <rect x="106" y="86" width="28" height="20" rx="9"/>
      <line x1="94" y1="94" x2="106" y2="94"/>
    </g>` : '';
  const beard = c.beard ? `<path class="av-beard" fill="${c.hair}" opacity=".92"
      d="M64 106 q-2 34 36 38 q38 -4 36 -38 q-2 22 -36 24 q-34 -2 -36 -24 z"/>` : '';
  return `
<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" class="av-svg">
  <defs>
    <clipPath id="avclip"><circle cx="100" cy="100" r="100"/></clipPath>
    <radialGradient id="avbg" cx="50%" cy="38%" r="80%">
      <stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="${c.bg}"/>
    </radialGradient>
  </defs>
  <g clip-path="url(#avclip)">
    <rect width="200" height="200" fill="url(#avbg)"/>
    <g class="av-all">
      <g class="av-body">
        ${attire}
        <!-- Left Arm & Hand -->
        <g class="av-armL" style="transform-origin: 52px 156px;">
          <path d="M 44 154 Q 28 174 22 196 L 36 198 Q 42 178 54 158 Z" fill="${c.attireC}" />
          <ellipse cx="20" cy="196" rx="7" ry="5" fill="${c.skin}" class="av-handL"/>
        </g>
        <!-- Right Arm & Hand -->
        <g class="av-armR" style="transform-origin: 148px 156px;">
          <path d="M 156 154 Q 172 174 178 196 L 164 198 Q 158 178 146 158 Z" fill="${c.attireC}" />
          <ellipse cx="180" cy="196" rx="7" ry="5" fill="${c.skin}" class="av-handR"/>
        </g>
      </g>
      <g class="av-head" style="transform-origin: 100px 110px;">
        <ellipse cx="100" cy="100" rx="38" ry="44" fill="${c.skin}"/>
        <path d="M62 100 q0 -52 38 -52 q38 0 38 52 q0 -10 -6 -22 q-10 -20 -32 -20 q-22 0 -32 20 q-6 12 -6 22z" fill="${c.skinD}" opacity=".25"/>
        <ellipse cx="62"  cy="100" rx="6" ry="10" fill="${c.skin}"/>
        <ellipse cx="138" cy="100" rx="6" ry="10" fill="${c.skin}"/>
        ${hair}
        <g class="av-browL"><path d="M68 82 q10 -6 22 -2" stroke="${c.hair}" stroke-width="3.4" fill="none" stroke-linecap="round"/></g>
        <g class="av-browR"><path d="M110 80 q12 -4 22 2" stroke="${c.hair}" stroke-width="3.4" fill="none" stroke-linecap="round"/></g>
        <g class="av-eyeL">
          <ellipse cx="80" cy="95" rx="7.5" ry="8" fill="#fff"/>
          <circle class="av-pupilL" cx="80" cy="95" r="4.4" fill="#2b2119"/>
          <circle cx="81.6" cy="93.4" r="1.3" fill="#fff"/>
          <ellipse class="av-lidL" cx="80" cy="88" rx="8.4" ry="8" fill="${c.skin}"/>
        </g>
        <g class="av-eyeR">
          <ellipse cx="120" cy="95" rx="7.5" ry="8" fill="#fff"/>
          <circle class="av-pupilR" cx="120" cy="95" r="4.4" fill="#2b2119"/>
          <circle cx="121.6" cy="93.4" r="1.3" fill="#fff"/>
          <ellipse class="av-lidR" cx="120" cy="88" rx="8.4" ry="8" fill="${c.skin}"/>
        </g>
        ${glasses}
        <path class="av-nose" d="M100 100 q-3 8 0 11 q2 2 5 0" stroke="${c.skinD}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
        <ellipse class="av-cheekL" cx="74" cy="110" rx="6" ry="3.6" fill="#e2745e" opacity="0"/>
        <ellipse class="av-cheekR" cx="126" cy="110" rx="6" ry="3.6" fill="#e2745e" opacity="0"/>
        ${beard}
        <g class="av-mouthG">
          <path class="av-smile" d="M86 124 q14 8 28 0" stroke="${c.lip}" stroke-width="3.2" fill="none" stroke-linecap="round"/>
          <g class="av-mouthOpen" opacity="0">
            <ellipse class="av-mouthCav" cx="100" cy="126" rx="10" ry="7" fill="#5d2a24"/>
            <rect class="av-teeth" x="91" y="119.5" width="18" height="4.6" rx="2.2" fill="#fff"/>
            <ellipse class="av-tongue" cx="100" cy="131" rx="6.4" ry="3" fill="#c96b5e"/>
          </g>
        </g>
      </g>
    </g>
  </g>
  <circle cx="100" cy="100" r="98.5" fill="none" stroke="rgba(255,255,255,.85)" stroke-width="3"/>
</svg>`;
}

function hairSVG(c){
  const h = c.hair;
  switch(c.hairStyle){
    case 'bun': return `<path fill="${h}" d="M60 96 q-4 -46 40 -46 q44 0 40 46 q-2 -12 -10 -14 q4 -18 -30 -18 q-34 0 -30 18 q-8 2 -10 14z"/>
      <circle cx="100" cy="46" r="13" fill="${h}"/>`;
    case 'long': return `<path fill="${h}" d="M58 150 q-6 -30 2 -62 q6 -38 40 -38 q34 0 40 38 q8 32 2 62 l-16 4 q6 -40 -2 -58 q-4 16 -24 16 q-20 0 -24 -16 q-8 18 -2 58 z"/>`;
    case 'wavy': return `<path fill="${h}" d="M60 98 q-6 -50 40 -50 q46 0 40 50 q-4 -14 -12 -16 q2 -6 -6 -10 q2 8 -8 6 q-6 -8 -14 -6 q-8 -2 -14 6 q-10 2 -8 -6 q-8 4 -6 10 q-8 2 -12 16z"/>`;
    default:     return `<path fill="${h}" d="M61 96 q-5 -44 39 -44 q44 0 39 44 q-3 -12 -9 -14 q2 -14 -30 -14 q-32 0 -30 14 q-6 2 -9 14z"/>`;
  }
}

function attireSVG(c){
  const base = `<path d="M40 200 q2 -46 34 -52 q10 10 26 10 q16 0 26 -10 q32 6 34 52 z"`;
  switch(c.attire){
    case 'suit': case 'blazer': {
      const tie = c.tie ? `<path d="M100 158 l-6 10 l6 26 l6 -26 z" fill="${c.tie}"/><path d="M94 152 l6 8 l6 -8 l-6 -4 z" fill="${c.tie}"/>` : '';
      return `${base} fill="${c.attireC}"/>
        <path d="M84 150 q14 12 32 0 l-8 20 l-8 -8 l-8 8 z" fill="${c.shirtC}"/>
        <path d="M74 152 l14 -4 l-2 30 l-16 -14 z" fill="${c.attireC}" stroke="rgba(0,0,0,.18)" stroke-width="1.4"/>
        <path d="M126 152 l-14 -4 l2 30 l16 -14 z" fill="${c.attireC}" stroke="rgba(0,0,0,.18)" stroke-width="1.4"/>${tie}`;
    }
    case 'coat':
      return `${base} fill="${c.attireC}" stroke="#c9d4e2" stroke-width="1.5"/>
        <path d="M86 150 q14 12 28 0 l0 50 l-28 0 z" fill="${c.shirtC}"/>
        <path d="M72 154 l16 -6 l0 52 l-22 0 z" fill="${c.attireC}" stroke="#c9d4e2" stroke-width="1.4"/>
        <path d="M128 154 l-16 -6 l0 52 l22 0 z" fill="${c.attireC}" stroke="#c9d4e2" stroke-width="1.4"/>`;
    case 'polo':
      return `${base} fill="${c.attireC}"/>
        <path d="M88 150 q12 10 24 0 l-4 12 l-16 0 z" fill="rgba(255,255,255,.85)"/>`;
    case 'sweater':
      return `${base} fill="${c.attireC}"/>
        <path d="M84 152 q16 12 32 0 l0 8 q-16 10 -32 0 z" fill="${c.shirtC}"/>`;
    default: return `${base} fill="${c.attireC}"/>`;
  }
}

/* Expression director: subtle, professional facial targets per narration
   context. brow>0 raises, brow<0 furrows; tilt in degrees; deltas blend in
   with opts.exprK so expressions ease on with the sentence. */
const EXPRESSIONS = {
  welcome:  {smile: .25, brow: 1.2, tilt: 0,   energy: .15},
  positive: {smile: .18, brow: .5,  tilt: 0,   energy: .05},
  focused:  {smile:-.12, brow:-.9,  tilt: 0,   energy: 0},
  concern:  {smile:-.28, brow:-1.6, tilt: 1.5, energy:-.05},
  question: {smile: 0,   brow: 2.2, tilt: 2.2, energy: 0},
  confident:{smile: .15, brow: .6,  tilt:-.5,  energy: .1},
  neutral:  {smile: 0,   brow: 0,   tilt: 0,   energy: 0},
  idle:     {smile: 0,   brow: 0,   tilt: 0,   energy:-.18},
};

/* Deterministic per-frame pose. t seconds; mouth 0..1; opts: {energy, smile,
   gesture, eye, gazeDir, emphasis, expr, exprK}. Everything is a pure
   function of (t, mouth, opts). */
function poseAvatar(root, t, mouth, opts){
  const o = Object.assign({energy:.6, smile:.5, gesture:.5, eye:.7,
                           gazeDir:'center', expr:'neutral', exprK:0}, opts||{});
  const head = root.querySelector('.av-head');
  const body = root.querySelector('.av-body');
  const all  = root.querySelector('.av-all');
  const armL = root.querySelector('.av-armL');
  const armR = root.querySelector('.av-armR');
  if(!head) return;
  const cl = (v,a,b)=>Math.max(a,Math.min(b,v));
  const ex = EXPRESSIONS[o.expr] || EXPRESSIONS.neutral;
  const xk = cl(o.exprK||0, 0, 1);
  const E = .4 + cl(o.energy + ex.energy*xk, 0, 1)*.9;

  // Gaze & Head orientation toward content element or audience.
  // gk ramps 0..1 so head turns / gestures glide instead of snapping
  // (defaults to 1 for callers that don't drive the ramp, e.g. the editor).
  const gk = cl(o.gazeK != null ? o.gazeK : 1, 0, 1);
  let headTurn = 0, pupilX = 0, pupilY = 0;
  if(o.gazeDir === 'left'){
    headTurn = -7.5*gk; pupilX = -2.8*gk; pupilY = 0.2*gk;
  } else if(o.gazeDir === 'right'){
    headTurn = 7.5*gk; pupilX = 2.8*gk; pupilY = 0.2*gk;
  }

  // breathing + weight shift
  const breathe = Math.sin(t*2*Math.PI/3.6)* .8 * E;
  const sway    = Math.sin(t*2*Math.PI/7.3)* 1.1 * E * (.4+o.gesture);
  const bob     = Math.sin(t*2*Math.PI/2.9)* .7 * E + mouth*1.2;
  const tilt    = headTurn + ex.tilt*xk + Math.sin(t*2*Math.PI/11.7)* 1.8 * E + Math.sin(t*1.31)*.5;
  const lean    = (o.emphasis ? 2.5 : 0) + Math.sin(t*1.5)*0.5;

  all.setAttribute('transform', `translate(${sway.toFixed(2)} ${(lean*0.4).toFixed(2)})`);
  body.setAttribute('transform', `translate(0 ${(breathe*.5).toFixed(2)})`);
  head.setAttribute('transform',
    `translate(0 ${(breathe+bob+lean).toFixed(2)}) rotate(${tilt.toFixed(2)} 100 110)`);

  // Arms and Hand Gestures — blend from the resting sway toward the gesture
  // pose with gk so hands ease toward the content, never jump-cut
  const gCycle = Math.sin(t * 2.8);
  const restL = Math.sin(t * 2.1) * 3, restR = -Math.sin(t * 2.1) * 3;
  let tgtL = restL, tgtR = restR, tTrL = 0, tTrR = 0;
  if(o.gazeDir === 'right' || o.gestureMode === 'explain_right'){
    // Gesture right hand toward slide content
    tgtR = -32 + gCycle * 4; tTrR = -6;
    tgtL = 4 + Math.sin(t * 1.5) * 2;
  } else if(o.gazeDir === 'left' || o.gestureMode === 'explain_left'){
    // Gesture left hand toward slide content
    tgtL = 32 + gCycle * 4; tTrL = -6;
    tgtR = -4 + Math.sin(t * 1.5) * 2;
  } else if(o.emphasis){
    // Both hands gesture emphasis
    tgtL = 22 + gCycle * 3;
    tgtR = -22 - gCycle * 3;
  }
  const rotL = restL + (tgtL - restL) * gk;
  const rotR = restR + (tgtR - restR) * gk;
  const transL = tTrL * gk, transR = tTrR * gk;

  // SVG attribute syntax: rotate about the shoulder pivot, then lift
  if(armL) armL.setAttribute('transform',
    `rotate(${rotL.toFixed(2)} 52 156) translate(0 ${transL.toFixed(2)})`);
  if(armR) armR.setAttribute('transform',
    `rotate(${rotR.toFixed(2)} 148 156) translate(0 ${transR.toFixed(2)})`);

  // blink: deterministic schedule ~ every 3.1-4.3s
  const cyc = 3.1 + (Math.floor(t/3.7)%3)*.6;
  const ph = (t % cyc)/cyc;
  const blink = ph > .96 ? Math.sin((ph-.96)/.04*Math.PI) : 0;
  const lidY = 84 + blink*11;
  const lidL = root.querySelector('.av-lidL'), lidR = root.querySelector('.av-lidR');
  if(lidL){ lidL.setAttribute('cy', lidY); lidR.setAttribute('cy', lidY); }

  // eye contact: direct or gaze-shifted
  const px = pupilX + Math.sin(t*.83)*0.8*(1-o.eye), py = pupilY + Math.cos(t*.61)*0.5*(1-o.eye);
  const pL = root.querySelector('.av-pupilL'), pR = root.querySelector('.av-pupilR');
  if(pL){ pL.setAttribute('cx', 80+px); pL.setAttribute('cy', 95+py);
          pR.setAttribute('cx', 120+px); pR.setAttribute('cy', 95+py); }

  // brows: raise with emphasis, speaking energy & expression (negative = furrow)
  const raise = mouth*2.6*E + (o.emphasis ? 2.0 : 0) + ex.brow*xk;
  root.querySelector('.av-browL').setAttribute('transform',`translate(0 ${-raise})`);
  root.querySelector('.av-browR').setAttribute('transform',`translate(0 ${-raise})`);

  // mouth: crossfade closed-smile <-> open viseme
  const openG = root.querySelector('.av-mouthOpen');
  const smileP = root.querySelector('.av-smile');
  const m = Math.max(0, Math.min(1, mouth));
  openG.setAttribute('opacity', m>.06 ? Math.min(1, m*1.6) : 0);
  smileP.setAttribute('opacity', m>.06 ? Math.max(0, 1-m*1.8) : 1);
  const cav = root.querySelector('.av-mouthCav');
  const ry = 2.2 + m*6.5, rx = 8.2 + m*2.6 + Math.sin(t*31)*.5*m;
  cav.setAttribute('ry', ry.toFixed(2)); cav.setAttribute('rx', rx.toFixed(2));
  root.querySelector('.av-tongue').setAttribute('cy', 126 + ry*.62);
  root.querySelector('.av-teeth').setAttribute('y', 126 - ry - 1.2);

  // smile curvature + cheeks (expression-adjusted)
  const sm = cl(o.smile + ex.smile*xk, 0, 1)*(1-m*.5);
  smileP.setAttribute('d', `M86 ${124-sm*2} q14 ${4+sm*9} 28 0`);
  const cheek = root.querySelector('.av-cheekL');
  if(cheek){ cheek.setAttribute('opacity', (sm*.35).toFixed(2));
    root.querySelector('.av-cheekR').setAttribute('opacity', (sm*.35).toFixed(2)); }
}
if (typeof module!=='undefined') module.exports = {AVATARS, avatarSVG, poseAvatar};
