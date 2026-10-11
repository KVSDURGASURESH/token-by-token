#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const require=createRequire(path.join(repo,'dashboard/package.json'));
const {chromium}=require('playwright');
const out=path.resolve(process.argv[process.argv.indexOf('--out')+1]);
const spec=JSON.parse(fs.readFileSync(path.join(out,'inputs/spec.json'),'utf8'));
const build=path.join(out,'work/dashboard');
const candidates=fs.existsSync(path.join(process.env.HOME,'.cache/hyperframes/chrome/chrome-headless-shell'))?fs.readdirSync(path.join(process.env.HOME,'.cache/hyperframes/chrome/chrome-headless-shell')):[];
const installed=candidates.map(v=>path.join(process.env.HOME,'.cache/hyperframes/chrome/chrome-headless-shell',v,'chrome-headless-shell-mac-arm64/chrome-headless-shell')).filter(fs.existsSync);
const executable=process.env.TBT_CHROMIUM || installed.at(-1) || chromium.executablePath();
if(!fs.existsSync(executable)) throw Error('No installed Chromium. Set TBT_CHROMIUM; downloads are disabled.');
const server=http.createServer((req,res)=>{
 const relative=decodeURIComponent(req.url.split('?')[0]);
 let target=path.resolve(build,'.'+relative);
 if(target!==build&&!target.startsWith(build+path.sep)){res.writeHead(403);res.end();return;}
 if(!fs.existsSync(target)||!fs.statSync(target).isFile()) target=path.join(build,'index.html');
 const types={'.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.woff2':'font/woff2','.html':'text/html'};
 res.setHeader('Content-Type',types[path.extname(target)]||'application/octet-stream');
 fs.createReadStream(target).pipe(res);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({executablePath:executable});
const shotFlag=process.argv.indexOf('--shot');
const requestedShot=shotFlag<0?null:process.argv[shotFlag+1];
const manifest=requestedShot&&fs.existsSync(path.join(out,'inputs/capture-manifest.json'))?JSON.parse(fs.readFileSync(path.join(out,'inputs/capture-manifest.json'),'utf8')).filter(s=>s.id!==requestedShot):[];
try {
 for(const shot of spec.captures.filter(s=>!requestedShot||s.id===requestedShot)) {
  const crop=shot.crop||{x:348,y:100,width:1012,height:900};
  const page=await browser.newPage({viewport:shot.viewport||{width:1440,height:1100}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  await page.goto(base+'/'+shot.route);
  await page.waitForSelector('[data-tbt]',{timeout:15000}).catch(async e=>{
   await page.screenshot({path:path.join(out,'work/capture-error.png')});
   throw Error('Dashboard not mounted: '+errors.join('; ')+'; '+e.message);
  });
  await page.evaluate(()=>document.fonts.ready);
  await page.waitForTimeout(500);
  if(await page.locator('.tbt-notice').count()) throw Error('Dashboard route notice in '+shot.id);
  if(!await page.locator('[data-tbt][data-theme="dark"]').count()) throw Error('Dark theme not active');
  const brand=await page.locator('.tbt-brand').evaluate(el=>({family:getComputedStyle(el).fontFamily,weight:getComputedStyle(el).fontWeight}));
  if(!brand.family.includes('Oswald')||brand.weight!=='600') throw Error('Dashboard brand drift: '+JSON.stringify(brand));
  if(shot.mask) await page.addStyleTag({content:shot.mask.map(sel=>`${sel}{visibility:hidden!important}`).join('')});
  const requestedStart=await page.locator(shot.selector).first().evaluate(el=>el.getBoundingClientRect().top+window.scrollY-120);
  await page.evaluate(y=>window.scrollTo({top:y,behavior:'instant'}),requestedStart);
  // Freeze the actual initial position. Unfolding increases document height:
  // an initially clamped requested position must not jump when that height grows.
  const start=await page.evaluate(()=>window.scrollY);
  const frameDir=path.join(out,'work/capture',shot.id);
  fs.mkdirSync(frameDir,{recursive:true});
  const count=Math.round(shot.duration*spec.fps), positions=[], actions=[];
  for(let frame=0;frame<count;frame++) {
   const t=frame/spec.fps;
   const clicks=shot.actions||[];
   for(const action of clicks) {
    if(frame===Math.round(action.at*spec.fps)) {
     const before=await page.evaluate(()=>window.scrollY);
     await page.locator(action.selector).click({force:false});
     actions.push({...action,frame,scrollBefore:before});
    }
   }
   const progress=Math.max(0,Math.min(1,(t-(shot.scroll_start||0))/Math.max(.001,shot.duration-(shot.scroll_start||0)-1/spec.fps)));
   const observed=await page.evaluate(async y=>{
    window.scrollTo({top:y,behavior:'instant'});
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    return window.scrollY;
   },start+(shot.travel||0)*progress);
   positions.push(observed);
   await page.screenshot({path:path.join(frameDir,`frame-${String(frame).padStart(4,'0')}.png`),clip:crop});
  }
  if(positions.some((y,i)=>i&&y<positions[i-1])) throw Error('Scroll reversed: '+shot.id);
  if(errors.length) throw Error('Dashboard errors: '+errors.join('; '));
  const clip=path.join(out,'composition/assets/clips',shot.id+'.mp4');
  const result=spawnSync('ffmpeg',['-v','error','-y','-framerate',String(spec.fps),'-i',path.join(frameDir,'frame-%04d.png'),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-r',String(spec.fps),clip],{encoding:'utf8'});
  if(result.status!==0) throw Error(result.stderr);
  const stills=path.join(out,'composition/assets/frames');fs.mkdirSync(stills,{recursive:true});
  fs.copyFileSync(path.join(frameDir,'frame-0000.png'),path.join(stills,shot.id+'-first.png'));
  fs.copyFileSync(path.join(frameDir,`frame-${String(count-1).padStart(4,'0')}.png`),path.join(stills,shot.id+'-last.png'));
  manifest.push({...shot,frames:count,fps:spec.fps,crop,brand,actions,scrollPositions:positions,monotonicDownward:true,consoleErrors:errors,clip:'composition/assets/clips/'+shot.id+'.mp4'});
  console.log('Captured',shot.id,count,'frames');
  await page.close();
 }
 manifest.sort((a,b)=>spec.captures.findIndex(s=>s.id===a.id)-spec.captures.findIndex(s=>s.id===b.id));
 fs.writeFileSync(path.join(out,'inputs/capture-manifest.json'),JSON.stringify(manifest,null,2));
} finally {await browser.close();server.close();}
