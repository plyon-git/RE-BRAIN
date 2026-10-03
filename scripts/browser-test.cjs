// Actual browser checks. Development-only Playwright; not an app dependency.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'brain-browser-'));
const port = Number(process.env.BRAIN_TEST_PORT || 18990);
const url = `http://127.0.0.1:${port}`;
const env = { ...process.env, BRAIN_DB: path.join(temp,'brain.sqlite3'), BRAIN_API_KEY: '',
  BRAIN_MODEL: path.join(temp,'model.json'), BRAIN_REGISTRY: path.join(temp,'registry'), INTELLIGENCE_URL: '' };
const trained = spawnSync('python3',['-c',"import sys;sys.path.insert(0,'services/intelligence');from engine import OpportunityModel;OpportunityModel(__import__('os').environ['BRAIN_MODEL']).train_reference()"],{cwd:root,env});
if (trained.status) throw Error(trained.stderr.toString());
const app = spawn('python3',['services/api/app.py','--port',String(port)],{cwd:root,env});
let logs='';app.stdout.on('data',b=>logs+=b);app.stderr.on('data',b=>logs+=b);
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  let browser;
  try {
    let ready=false;
    for(let i=0;i<150;i++) {try {const r=await fetch(url+'/api/health');if(r.ok){ready=true;break;}} catch {} await delay(100);}
    if(!ready) throw Error('API failed to start: '+logs);
    const options={headless:true,args:['--no-sandbox']};
    if(process.env.BRAIN_CHROME_PATH)options.executablePath=process.env.BRAIN_CHROME_PATH;
    browser=await chromium.launch(options);
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    await page.locator('#seed-button').click();
    await page.waitForFunction(()=>document.querySelector('#registry-count')?.textContent || document.querySelector('#stat-grid')?.textContent.includes('40'));
    const screenshotDir=path.join(root,'artifacts','screenshots');fs.mkdirSync(screenshotDir,{recursive:true});
    await page.screenshot({path:path.join(screenshotDir,'overview.png'),fullPage:true});
    for(const view of ['registry','scout','sources','watchlist','knowledge','operations']) {
      await page.locator(`a[data-page=${view}]`).click();
      await page.locator('#page-'+view).waitFor({state:'visible'});
    }
    await page.locator('a[data-page=knowledge]').click();
    await page.locator('#knowledge-search').fill('debt service coverage');
    await page.locator('#knowledge-form button[type=submit]').click();
    await page.locator('.knowledge-result').first().waitFor();
    await page.locator('a[data-page=registry]').click();
    await page.locator('#registry-rows button').first().click();
    await page.locator('#property-drawer.open, #property-drawer.visible, #property-drawer:not(.hidden)').waitFor();
    await page.locator('#drawer-title').waitFor();
    await page.screenshot({path:path.join(screenshotDir,'property-evidence.png'),fullPage:true});
    await page.locator('#drawer-close').click();
    await page.locator('a[data-page=brain]').click();
    await page.locator('#brain-save-decision').waitFor();
    const submit = async (selector,endpoint) => {
      const [response] = await Promise.all([
        page.waitForResponse(r=>r.url().includes(endpoint)&&r.request().method()==='POST'),
        page.locator(selector).click()
      ]);
      if(!response.ok())throw Error(endpoint+': '+await response.text());
      return response.json();
    };
    await page.locator('#brain-new-episode').click();
    await page.locator('#brain-create-episode-form [name=asking_price]').fill('185000');
    await page.locator('#brain-create-episode-form [name=target_price]').fill('165000');
    const episode=await submit('#brain-create-episode','/api/brain/episodes');
    const episodeId=episode.id||episode.episode?.id;
    if(!episodeId)throw Error('Created episode has no permanent identifier');
    await page.locator('#brain-episode-dialog').waitFor({state:'hidden'});
    await page.locator('#brain-tab-ledger').click();
    await page.locator('#brain-event-kind').selectOption('offer');
    await page.locator('#brain-event-form [name=data_price]').fill('165000');
    await page.locator('#brain-event-form [name=data_response]').selectOption('pending');
    await submit('#brain-record-event',`/episodes/${episodeId}/events`);
    await page.locator('.event-history-item').first().waitFor();
    await page.locator('#brain-tab-report').click();
    await page.locator('#brain-scenario-form [name=additional_expenses]').fill('1200');
    await submit('#brain-run-scenario','/api/brain/report/');
    await page.locator('#brain-save-decision').waitFor();
    await page.locator('#brain-save-decision').click();
    await page.locator('#brain-decision-form [name=action]').fill('Collect verified inspection evidence before committing.');
    await submit('#brain-decision-form button[type=submit]',`/episodes/${episodeId}/decisions`);
    await page.locator('#brain-decision-dialog').waitFor({state:'hidden'});
    await page.screenshot({path:path.join(screenshotDir,'underwriting.png'),fullPage:true});
    await page.locator('#brain-tab-documents').click();
    await page.locator('#brain-document-form [name=file]').setInputFiles({name:'inspection-evidence.txt',mimeType:'text/plain',buffer:Buffer.from('Verified browser workflow evidence')});
    await submit('#brain-upload-document','/api/documents');
    const downloadButton=page.locator('[id^=brain-document-download-]').first();
    await downloadButton.waitFor();
    const [download]=await Promise.all([page.waitForEvent('download'),downloadButton.click()]);
    if(download.suggestedFilename()!=='inspection-evidence.txt')throw Error('Document download filename was not preserved');
    await download.saveAs(path.join(temp,'download.txt'));
    if(fs.readFileSync(path.join(temp,'download.txt'),'utf8')!=='Verified browser workflow evidence')throw Error('Document download content mismatch');
    for(const tab of ['queue','portfolio','models','rules']) {
      await page.locator(`#brain-tab-${tab}`).click();
      await page.locator(`#brain-view-${tab}`).waitFor({state:'visible'});
    }
    await page.locator('#brain-rule-form [name=jurisdiction]').fill('US');
    await page.locator('#brain-rule-form [name=reason]').fill('Browser verification of versioned operating rules.');
    await submit('#brain-save-rule','/api/brain/rules');
    await page.locator('#brain-rule-versions .rule-card').first().waitFor();
    await page.locator('#brain-tab-models').click();
    await page.locator('#brain-model-train-form [name=kind]').selectOption('valuation');
    const candidate=await submit('#brain-model-train','/api/brain/models/train');
    // Insufficient support is preserved as an unpromotable candidate artifact.
    if(candidate.status!=='candidate'||candidate.gate?.eligible!==false||candidate.support?.usable!==0)
      throw Error('Empty observed ledger must preserve an unpromotable valuation candidate');
    await page.locator('#brain-registry-models .registry-model').first().waitFor();
    if(!await page.locator('#brain-promote-'+candidate.model_id).isDisabled())
      throw Error('Insufficient-support candidate must not expose an enabled promotion control');
    // All views should keep labels and external evidence safe as DOM text.
    if(errors.length)throw Error(errors.join('; '));
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(screenshotDir,'mobile.png'),fullPage:true});
    console.log(JSON.stringify({status:'passed',pages:8,underwriting_tabs:7,knowledge_retrieval:true,property_evidence:true,transaction_event:true,decision_snapshot:true,scenario:true,document_roundtrip:true,versioned_rules:true,training_abstention:true,page_errors:errors}));
  } finally {
    if(browser)await browser.close();
    app.kill();fs.rmSync(temp,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);console.error(logs.slice(-4000));process.exitCode=1;app.kill();});
