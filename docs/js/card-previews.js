// One on-demand player for all visible cards. Posters remain normal lazy-loaded images.
export function mediaUrl(ref, extension) {
  return new RegExp(`^media/[a-f0-9]{64}\\.${extension}$`).test(ref?.path || '')
    ? new URL(`../data/${ref.path}`, import.meta.url).href : null;
}
export class CardPreviews {
  constructor() {
    this.active=null;this.hovered=null;this.timer=null;this.version=0;
    this.scrolling=false;this.scrollIdleTimer=null;
    this.observer=new IntersectionObserver(entries=>{
      for(const entry of entries)if(!entry.isIntersecting){
        if(this.hovered?.card===entry.target)this.hovered=null;
        if(this.active?.card===entry.target)this.stop();
      }
    });
    // Scrolling never starts a decoder. Resume only after scroll settles and a fresh hover delay.
    window.addEventListener('scroll',()=>this.onScroll(),{passive:true,capture:true});
    document.addEventListener('visibilitychange',()=>{if(document.hidden)this.stop();});
    this.motion=matchMedia('(prefers-reduced-motion: reduce)');
    this.motion.addEventListener('change',()=>this.stop());
  }
  allowed(){return !document.hidden&&!this.motion.matches&&!navigator.connection?.saveData;}
  state(target,state,message=''){
    target.card.dataset.previewState=state;
    target.card.dataset.previewError=message;
    const label=target.card.querySelector('.hover-hint');
    if(label)label.textContent=({idle:'HOVER TO PLAY',waiting:'HOVER TO PLAY',loading:'LOADING PREVIEW…',playing:'PLAYING PREVIEW',error:'CLICK PREVIEW',manual:'CLICK PREVIEW'})[state];
    target.card.title=message;
  }
  onScroll(){
    if(!this.scrolling){this.scrolling=true;this.stop({keepHover:true});}
    clearTimeout(this.scrollIdleTimer);
    this.scrollIdleTimer=setTimeout(()=>{
      this.scrolling=false;
      if(this.hovered?.card.isConnected)this.arm(this.hovered);
    },180);
  }
  arm(target){
    this.stop({keepHover:true});
    if(this.scrolling||!this.allowed())return;
    const version=this.version;this.active=target;this.state(target,'waiting');
    this.timer=setTimeout(async()=>{
      this.timer=null;
      if(version!==this.version||this.scrolling||!this.allowed())return;
      if(target.posterUrl)target.video.poster=target.posterUrl;
      this.state(target,'loading');target.video.src=target.url;
      try{await target.video.play();if(version===this.version){target.card.classList.add('is-playing');this.state(target,'playing');}}
      catch(error){if(version===this.version){this.stop();this.state(target,'error',error.name==='NotAllowedError'?'Autoplay was blocked. Click Preview to play.':'Preview could not play. Click Preview to open the viewer.');}}
    },300);
  }
  bind(card, entry) {
    const url=mediaUrl(entry.preview?.clip,'mp4');
    const poster=card.querySelector('img');
    if(poster)poster.addEventListener('error',()=>{poster.hidden=true;card.classList.remove('has-image');});
    if(!url)return;
    const video=document.createElement('video');video.muted=true;video.defaultMuted=true;video.loop=true;video.playsInline=true;video.preload='none';video.setAttribute('aria-hidden','true');
    video.className='card-preview-video';card.prepend(video);this.observer.observe(card);
    const surface=card.closest('.dataset')||card;
    surface.addEventListener('pointerenter',event=>{
      // Real mouse input is reliable even when an embedded/hybrid browser reports hover:none.
      if(event.pointerType!=='mouse')return;
      card.classList.add('mouse-preview');
      if(!this.allowed()){this.state({card},'manual','Automatic previews are disabled by reduced-motion or data-saving preferences. Click Preview to play.');return;}
      this.hovered={card,video,url,posterUrl:poster?.currentSrc||poster?.src};this.arm(this.hovered);
    });
    surface.addEventListener('pointerleave',()=>{
      if(this.hovered?.card===card)this.hovered=null;
      if(this.active?.card===card)this.stop();
    });
    video.addEventListener('error',()=>{if(this.active?.video===video){const target=this.active;this.stop();this.state(target,'error','Preview could not load. Click Preview to open the viewer.');}});
  }
  stop({keepHover=false}={}){
    this.version++;clearTimeout(this.timer);this.timer=null;
    if(!keepHover)this.hovered=null;
    if(this.active){const {card,video}=this.active;this.active=null;this.state({card},'idle');card.classList.remove('is-playing');video.pause();video.removeAttribute('src');video.load();}
  }
  clear(){this.stop();this.observer.disconnect();}
}
