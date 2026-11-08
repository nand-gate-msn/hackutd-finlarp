import { readFileSync, writeFileSync } from 'node:fs'
const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
const rgb = hex => hex.match(/[a-f\d]{2}/gi).map(v => parseInt(v, 16))
const lum = c => c.map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4 }).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0)
const ratio = (a,b) => { const x=lum(a),y=lum(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05) }
const blend = (a,b,alpha) => a.map((v,i)=>v*alpha+b[i]*(1-alpha))
let failed = false
const rows=[]
for (const theme of ['light','dark']) {
 const block = theme === 'light' ? css.match(/\[data-theme="light"\] \{([^}]+)/)[1] : css.match(/:root\[data-theme="dark"\] \{([^}]+)/)[1]
 const t = Object.fromEntries([...block.matchAll(/--([\w-]+): (#[a-f\d]{6})/gi)].map(m=>[m[1],rgb(m[2])]))
 const check=(name,fg,bg,min=4.5)=> { const value=ratio(fg,bg); rows.push({theme,pair:name,ratio:+value.toFixed(3),minimum:min}); if(value<min) {failed=true;console.error('FAIL',theme,name,value)} }
 for (const bg of ['canvas','surface','track','accent-subtle']) {
  for(const fg of ['ink','ink-muted','accent','positive','ok-text','warn-text','negative']) check(`${fg} / ${bg}`,t[fg],t[bg])
  if (['canvas','surface'].includes(bg)) check(`control border / ${bg}`,t['line-control'],t[bg],3)
 }
 for(const [fg,bg] of [['positive','positive-subtle'],['ok-text','caution-subtle'],['warn-text','warning-subtle'],['negative','negative-subtle']]) check(`${fg} / ${bg}`,t[fg],t[bg])
 for (const fill of ['accent','negative']) check(`on-solid / ${fill}`,t['on-solid'],t[fill])
 for(const tone of ['positive','caution','warning','negative']) check(`${tone} fill / track`,t[tone],t.track,3)
 // State overlays are used on controls. Check actual composited label colors.
 for(const fill of ['accent','track','surface']) for(const [state,a] of [['hover',theme==='light'?.06:.07],['pressed',theme==='light'?.12:.13]]) {
  const bg=blend(theme==='light'?t.ink:[255,255,255],t[fill],a)
  check(`${fill} ${state} label`,t[fill==='accent'?'on-solid':'ink'],bg)
 }
 // Glass gets added in step 7; test the actual declared alpha when present.
 const glass = [...block.matchAll(/--glass-(bg|panel): rgb\((\d+) (\d+) (\d+) \/ ([.\d]+)\)/g)]
 for(const m of glass) for(const mark of ['canvas','surface','ink','ink-muted','accent','positive','caution','warning','negative']) {
  // Include extreme backdrops, stronger than the approved low-opacity ambient fields.
  for(const backdrop of [t[mark],[0,0,0],[255,255,255]]) {
   const bg=blend(m.slice(2,5).map(Number),backdrop,+m[5])
   for(const fg of ['ink','ink-muted']) check(`${m[1]} ${fg} / ${mark} or extreme`,t[fg],bg)
   check(`${m[1]} focus / ${mark} or extreme`,t.accent,bg,3)
  }
 }
}
writeFileSync(new URL('../../docs/ui-contrast.json',import.meta.url),JSON.stringify(rows,null,2)+'\n')
console.log(`${rows.length} contrast pairs checked in both themes; minimum text ${Math.min(...rows.filter(r=>r.minimum===4.5).map(r=>r.ratio))}:1`)
if(failed) process.exitCode=1
