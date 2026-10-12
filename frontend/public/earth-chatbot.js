/* Earth chatbot: transparent WebGL component. Three.js r160 (MIT). */
(()=>{
let dependency;
function loadThree(){if(window.THREE)return Promise.resolve(window.THREE);return dependency||(dependency=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.min.js';script.onload=()=>resolve(window.THREE);script.onerror=reject;document.head.appendChild(script);}));}
class EarthChatbot extends HTMLElement{
constructor(){super();this.attachShadow({mode:'open'});}
async connectedCallback(){
this.shadowRoot.innerHTML="<div id=\"earth-chat-preview\" >\n  <div class=\"earth-stage\" role=\"img\" aria-label=\"A glossy blue and green Earth rotating once every eight seconds, with a stationary chat bubble and pulsing dots\">\n    <canvas aria-hidden=\"true\"></canvas>\n    <div class=\"chat-badge\" aria-hidden=\"true\"><span></span><span></span><span></span></div>\n  </div>\n  <button type=\"button\" class=\"earth-toggle\" hidden>Pause animation</button>\n  <p class=\"earth-status\" role=\"status\"></p>\n</div>\n<style>\n#earth-chat-preview{display:flex;align-items:center;flex-direction:column;padding:24px 0;gap:16px;font-family:Arial,sans-serif;color:light-dark(#183047,#e1efff)}\n#earth-chat-preview .earth-stage{width:280px;height:280px;position:relative}\n#earth-chat-preview canvas{display:block;width:100%;height:100%;background:transparent}\n#earth-chat-preview .chat-badge{position:absolute;right:10px;bottom:23px;width:92px;height:65px;border-radius:26px;background:linear-gradient(145deg,#fff,#ddecff);box-shadow:0 5px 14px #00305a38;display:flex;align-items:center;justify-content:center;gap:8px;transform:rotate(-7deg)}\n#earth-chat-preview .chat-badge:after{content:'';position:absolute;bottom:-9px;left:15px;width:22px;height:22px;background:#e5f0ff;transform:skewY(-35deg);border-radius:0 0 4px 5px}\n#earth-chat-preview .chat-badge span{position:relative;z-index:1;width:13px;height:13px;background:linear-gradient(#13cdff,#0877e7);border-radius:50%}\n#earth-chat-preview .earth-toggle{font:inherit;padding:9px 16px;border:1px solid light-dark(#bccbd9,#506378);border-radius:8px;background:light-dark(#fff,#203044);color:inherit;cursor:pointer}\n#earth-chat-preview .earth-status{margin:0}\n</style>\n<style>:host{display:inline-block;width:64px;height:64px}#earth-chat-preview{padding:0;gap:0;width:100%;height:100%;position:relative}#earth-chat-preview .earth-stage{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) scale(var(--earth-scale,.228571));transform-origin:center}#earth-chat-preview .earth-toggle,#earth-chat-preview .earth-status{display:none}</style>";
this._resize=new ResizeObserver(()=>this.style.setProperty('--earth-scale',String(this.clientWidth/280)));this._resize.observe(this);
try{const THREE=await loadThree();if(!this.isConnected)return;

const root=this.shadowRoot.getElementById('earth-chat-preview');
const canvas=root.querySelector('canvas'),toggle=root.querySelector('button'),status=root.querySelector('.earth-status');
try{
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(34,1,.1,100);camera.position.z=4.25;
const renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));renderer.setSize(280,280);renderer.setClearColor(0,0);
renderer.outputColorSpace=THREE.SRGBColorSpace;
const geometry=new THREE.SphereGeometry(1,96,64);
const material=new THREE.MeshPhongMaterial({color:0xffffff,specular:0x74b6d9,shininess:24});
const globe=new THREE.Mesh(geometry,material);
const axis=new THREE.Group();axis.rotation.z=-23.4*Math.PI/180;axis.add(globe);scene.add(axis);
scene.add(new THREE.AmbientLight(0xbadfff,2));
const light=new THREE.DirectionalLight(0xffffff,2.7);light.position.set(-3,4,5);scene.add(light);
const atmosphere=new THREE.Mesh(new THREE.SphereGeometry(1.018,64,48),new THREE.ShaderMaterial({transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,vertexShader:'varying vec3 n; varying vec3 v; void main(){vec4 p=modelViewMatrix*vec4(position,1.0);n=normalize(normalMatrix*normal);v=normalize(-p.xyz);gl_Position=projectionMatrix*p;}',fragmentShader:'varying vec3 n; varying vec3 v; void main(){float rim=pow(1.0-max(dot(normalize(n),normalize(v)),0.0),3.0);gl_FragColor=vec4(0.06,0.7,1.0,rim*0.65);}'}));scene.add(atmosphere);
let raf=0,ready=false;this._dispose=()=>{cancelAnimationFrame(raf);geometry.dispose();material.map?.dispose();material.dispose();atmosphere.geometry.dispose();atmosphere.material.dispose();renderer.dispose();};
new THREE.TextureLoader().load('https://cdn.jsdelivr.net/gh/mrdoob/three.js@r160/examples/textures/planets/earth_atmos_2048.jpg',texture=>{if(!this.isConnected){texture.dispose();return;}texture.colorSpace=THREE.SRGBColorSpace;material.map=texture;material.needsUpdate=true;ready=true;status.textContent='';},undefined,()=>{status.textContent='Earth texture could not load. Please reopen this preview.';});
let playing=!window.matchMedia('(prefers-reduced-motion: reduce)').matches,elapsed=0,last=performance.now(),frame=-1;
const dots=[...root.querySelectorAll('.chat-badge span')];
function label(){toggle.textContent=playing?'Pause animation':'Play animation';toggle.setAttribute('aria-pressed',String(playing));}label();
toggle.addEventListener('click',()=>{playing=!playing;label();});
const draw=(now)=>{if(!root.isConnected)return;const dt=Math.min(now-last,100);last=now;if(playing&&ready&&!document.hidden)elapsed+=dt;const tick=Math.floor(elapsed/1000*30);if(tick!==frame||!playing||!ready){frame=tick;const seconds=tick/30;globe.rotation.y=seconds/(Number(this.getAttribute('duration'))||8)*Math.PI*2-1.5;dots.forEach((dot,i)=>{const pulse=(Math.sin(seconds*Math.PI*2-i*.8)+1)/2;dot.style.opacity=String(.45+.55*pulse);dot.style.transform='translateY('+(-3*pulse)+'px)';});renderer.render(scene,camera);}raf=requestAnimationFrame(draw);};raf=requestAnimationFrame(draw);
}catch(error){status.textContent='This preview requires WebGL support in your browser.';toggle.disabled=true;}

}catch(error){this.shadowRoot.querySelector('.earth-status').textContent='Globe unavailable';this.dispatchEvent(new CustomEvent('earth-error',{detail:error,bubbles:true}));}
}
disconnectedCallback(){this._resize?.disconnect();this._dispose?.();}
}
if(!customElements.get('earth-chatbot'))customElements.define('earth-chatbot',EarthChatbot);
})();
