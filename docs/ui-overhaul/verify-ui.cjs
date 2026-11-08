const {chromium}=require('playwright');const fs=require('node:fs');const assert=require('node:assert/strict');
const path=require('node:path'); const out=process.env.FINLARP_QA_OUTPUT || path.join(__dirname,'screenshots');const errors=[];const results=[];
async function capture(page,name){await page.screenshot({path:`${out}/${name}.png`})}
async function load(page,url){await page.goto(url);await page.locator('.gn').first().waitFor();await page.waitForTimeout(850)}
async function advise(page,mobile=false){if(mobile)await page.getByRole('button',{name:'Ask the copilot',exact:true}).click();await page.getByRole('button',{name:'Can I afford a car?',exact:true}).click();await page.locator('.advice').waitFor();await page.waitForTimeout(850)}
async function mark(page,label){results.push(label);console.log('PASS',label)}
(async()=>{const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const context=await browser.newContext({viewport:{width:1280,height:1000},colorScheme:'dark',hasTouch:true});await context.route('**/api/advise',r=>r.fulfill({contentType:'text/event-stream',body:fs.readFileSync((process.env.FINLARP_QA_ADVICE || '/private/tmp/finlarp-qa/advise.sse'),'utf8')}));const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
// Matched before/after states, using the same real overview and deterministic offline advice.
for(const [kind,port] of [['before',5174],['after',5173]]){
 await load(page,`http://127.0.0.1:${port}`);await capture(page,`${kind}-dark-1280-dashboard`);await advise(page);await page.locator('.copilot').screenshot({path:`${out}/${kind}-dark-1280-copilot.png`});
 await page.locator('.gn-account > circle').first().click({force:true});await page.waitForTimeout(400);await capture(page,`${kind}-dark-1280-graph`);
 await page.locator('.gforecast:not(.inline)').click();await page.locator('.modal-dialog').waitFor();await page.waitForTimeout(400);await capture(page,`${kind}-dark-1280-modal`);
 if(kind==='after'){
  assert(await page.locator('.modal-dialog').evaluate(e=>e.contains(document.activeElement)));
  const chart=await page.locator('.fcatch').boundingBox();for(const frac of [.05,.35,.65,.95])await page.mouse.move(chart.x+chart.width*frac,chart.y+chart.height/2);
  assert.equal(await page.locator('.ftip-value').first().evaluate(e=>getComputedStyle(e).fontVariantNumeric),'tabular-nums');
  const widths=await page.locator('.ftip-value').first().evaluate(e=>{const old=e.textContent;e.textContent='$1,111';const a=e.getComputedTextLength();e.textContent='$8,888';const b=e.getComputedTextLength();e.textContent=old;return[a,b]});assert(Math.abs(widths[0]-widths[1])<.1);
  await mark(page,'forecast scrubbing uses stable tabular digit widths');
  await page.getByRole('button',{name:'Close Projected balance',exact:false}).click();await page.waitForTimeout(60);const before=await page.locator('.modal-dialog').evaluate(e=>+getComputedStyle(e).transform.match(/matrix\(([^,]+)/)[1]);await page.locator('.gforecast:not(.inline)').dispatchEvent('click');const after=await page.locator('.modal-dialog').evaluate(e=>+getComputedStyle(e).transform.match(/matrix\(([^,]+)/)[1]);assert(Math.abs(before-after)<.015);assert.equal(await page.locator('.modal-dialog').count(),1);await mark(page,'modal close/reopen retargets without replacing the dialog');
 }
 await page.keyboard.press('Escape');await page.waitForTimeout(400);
}
// Both themes and requested viewport widths, including visible text size and overflow.
for(const theme of ['dark','light'])for(const width of [1280,390]){
 await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:theme,reducedMotion:'no-preference',forcedColors:'none'});await load(page,'http://127.0.0.1:5173');
 const overflow=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth}));assert(overflow.document<=overflow.viewport,`${theme} ${width}: horizontal overflow`);
 const glass=await page.evaluate(()=>[...document.querySelectorAll('*')].filter(e=>{const r=e.getBoundingClientRect();return getComputedStyle(e).backdropFilter!=='none'&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth}).length);assert(glass<=3,'at most three visible glass surfaces');
 await capture(page,`after-${theme}-${width}-dashboard`);
 await advise(page,width===390);if(width===390){await page.getByRole('slider',{name:'Copilot sheet height'}).focus();await page.keyboard.press('End');await page.waitForTimeout(700)}
 await capture(page,`after-${theme}-${width}-copilot`);
 const tiny=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.children.length===0&&e.textContent.trim()&&e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<12).map(e=>[e.className,getComputedStyle(e).fontSize]));assert.deepEqual(tiny,[]);
 await mark(page,`${theme} ${width}px: no horizontal overflow; text >=12px`);
 if(width===390){
  assert(await page.locator('main').evaluate(e=>e.inert));const grip=page.getByRole('slider',{name:'Copilot sheet height'});await grip.focus();await page.keyboard.press('ArrowDown');await page.waitForTimeout(700);assert.equal(await page.locator('.mobile-sheet').getAttribute('data-snap'),'1');
  const b=await grip.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();for(let i=1;i<=6;i++){await page.mouse.move(b.x+b.width/2,b.y+b.height/2+i*55);await page.waitForTimeout(12)}await page.mouse.up();await page.waitForTimeout(650);assert.equal(await page.locator('.mobile-sheet').getAttribute('data-snap'),'0');assert(!(await page.locator('main').evaluate(e=>e.inert)));
  await page.getByRole('button',{name:'Ask the copilot',exact:true}).click();await page.waitForTimeout(80);await page.getByRole('button',{name:'Close',exact:true}).click({force:true});await page.waitForTimeout(50);const y0=await page.locator('.mobile-sheet').evaluate(e=>new DOMMatrix(getComputedStyle(e).transform).m42);await page.getByRole('button',{name:'Ask the copilot',exact:true}).click();const y1=await page.locator('.mobile-sheet').evaluate(e=>new DOMMatrix(getComputedStyle(e).transform).m42);assert(Math.abs(y0-y1)<80);await page.waitForTimeout(700);await page.keyboard.press('Escape');await page.waitForTimeout(700);await mark(page,`${theme}: sheet snap, drag-to-dismiss, focus release and mid-exit reopen`);
 }
}
// Preference emulation, including features unsupported by Playwright's high-level API.
await page.setViewportSize({width:1280,height:1000});await load(page,'http://127.0.0.1:5173');const cdp=await context.newCDPSession(page);
for(const theme of ['dark','light'])for(const [feature,value] of [['prefers-reduced-motion','reduce'],['prefers-reduced-transparency','reduce'],['prefers-contrast','more'],['forced-colors','active']]){
 await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme},{name:feature,value}]});await page.waitForTimeout(150);
 assert(await page.evaluate(([f,v])=>matchMedia(`(${f}: ${v})`).matches,[feature,value]));
 if(feature!=='prefers-reduced-motion'){const p=await page.locator('.sidebar').evaluate(e=>({blur:getComputedStyle(e).backdropFilter,bg:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderTopWidth}));assert.equal(p.blur,'none');assert.equal(p.border,'1px');assert.equal(await page.locator('.ambient').evaluate(e=>getComputedStyle(e).display),'none')}
 await mark(page,`${theme} ${feature}: ${value}`)
}
await cdp.send('Emulation.setEmulatedMedia',{features:[]});
// Long aliases and names must retain layout and full-title affordances.
await page.route('**/api/overview',async route=>{const response=await route.fetch();const data=await response.json();data.accounts[0].alias='VeryLongAccountAliasWithoutSpaces'.repeat(10);data.accounts[0].spending_by_category={['VeryLongCategoryWithoutSpaces'.repeat(10)]:99};await route.fulfill({response,json:data})});
await load(page,'http://127.0.0.1:5173');assert(await page.locator('.bar-name').first().getAttribute('title'));await page.setViewportSize({width:390,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await mark(page,'long alias/category strings wrap or expose full titles');
assert.deepEqual(errors,[],'no browser runtime errors');fs.writeFileSync(path.join(__dirname,'results.json'),JSON.stringify({results,errors},null,2));await browser.close()})();
