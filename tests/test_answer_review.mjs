// Run the actual annotation script against a tiny DOM/storage substitute.
// No browser, production answers or image files are changed by this check.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const template=fs.readFileSync(new URL('../tools/answer_review_template.html',import.meta.url),'utf8');
const script=template.match(/<script>\s*([\s\S]*?)<\/script>/)[1].replace('/* __ANSWER_ASSISTANCE__ */',fs.readFileSync(new URL('../tools/answer_assistance.js',import.meta.url),'utf8')).replace('/* __RISK_REVIEW__ */',fs.readFileSync(new URL('../tools/risk_review.js',import.meta.url),'utf8'));
const fixture={fingerprint:'test-fixture',initial:{'S0001:1':'3'},sheets:['S0001','S0002'].map(id=>({id,contributor:'Fixture',A:{name:'a.jpg',url:'a.jpg'},B:{name:'b.jpg',url:'b.jpg'}}))};
fixture.pilot={method:'fixture-reader',run_id:'fixture-run',sheets:{S0001:{A:{rows:[]},B:{rows:Array.from({length:100},(_,i)=>({question_no:i+1,proposed:'2',uncertain:false})),sprite:'fixture.jpg',overlay:'fixture-overlay.jpg'}}}};

function boot(storage=new Map(),data=fixture){
 const elements=new Map(),handlers={};let downloaded;
 class Element{
  constructor(id=''){this.id=id;this.value='';this.textContent='';this.children=[];this.options=this.children;this.dataset={};this.style={};this.checked=false;this.disabled=false;this.tagName='BUTTON';this.clientWidth=500;this.naturalWidth=1000;this.naturalHeight=1400;const tokens=new Set();this.classList={toggle(name,active){active?tokens.add(name):tokens.delete(name)},contains:name=>tokens.has(name)}}
  append(child){this.children.push(child)}
  replaceChildren(){this.children.length=0}
  setAttribute(){} scrollTo(){}
  click(){this.onclick?.()}
 }
 const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
 get('annotation-data').textContent=JSON.stringify(data);get('autoNext').checked=true;get('zoomA').value='100';get('zoomB').value='100';
 const markButtons=['1','2','3','4','5','blank','multiple','ambiguous'].map(mark=>{const e=new Element();e.dataset.mark=mark;return e});
 const document={getElementById:get,activeElement:{tagName:'BODY'},createElement:()=>new Element(),querySelectorAll:selector=>selector==='[data-mark]'?markButtons:selector==='[data-question]'?get('questions').children:[],addEventListener:(name,fn)=>{const previous=handlers[name];handlers[name]=previous?event=>{previous(event);fn(event)}:fn}};
 const context=vm.createContext({document,window:{addEventListener(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},URL:{createObjectURL:blob=>{downloaded=blob;return 'blob:test'},revokeObjectURL(){}},Blob,Date,Set,Map,JSON,console,setTimeout:fn=>fn(),confirm:()=>true});
 vm.runInContext(script,context);
 return {run:code=>vm.runInContext(code,context),get,storage,document,handlers,downloaded:()=>downloaded};
}

let app=boot();
assert.equal(app.run('count("S0001")'),1);
assert.equal(app.run('value("S0001",1)'),'3','Existing human answers must take precedence over proposals');
app.get('autoNext').checked=false;
app.run('choose("")');
assert.equal(app.run('count("S0001")'),0);
app=boot(app.storage);
assert.equal(app.run('count("S0001")'),0,'Cleared answers must stay cleared after reload');
assert.equal(app.run('proposalFor("S0001",1).proposed'),'2');
assert.equal(app.run('count("S0001")'),0,'Unconfirmed proposals must not count as ground truth');
app.document.activeElement.tagName='BUTTON';
app.handlers.keydown({key:'Enter',preventDefault(){}});
assert.equal(app.run('state.question'),2,'Answer choice must advance to the next question');
app.document.activeElement.tagName='BUTTON';
app.handlers.keydown({key:'b',preventDefault(){}});
assert.equal(app.run('value("S0001",2)'),'blank','Keyboard shortcuts must work after button clicks');
app.run('exportCsv()');
const exported=await app.downloaded().text();
const rows=exported.replace(/^\ufeff/,'').split('\r\n');
assert.equal(rows.length,201);
assert.equal(rows[1],'"S0001","1","2"');
assert.equal(rows[2],'"S0001","2","blank"');
assert.equal(rows[3],'"S0001","3",""','Unconfirmed proposals must stay out of ground-truth exports');
assert.equal(app.run('pilotStatistics().compared'),0,'Accuracy must wait for whole-sheet review');
await app.run('importFile({name:"answers.csv",text:async()=>"sheet_id,question_no,ground_truth\\nS0001,1,\\nS0002,100,ambiguous"})');
assert.equal(app.run('value("S0001",1)'),'2','Imported blanks must not erase existing answers');
assert.equal(app.run('value("S0002",100)'),'ambiguous');
const before=app.run('JSON.stringify(state.answers)');
await app.run('importFile({name:"bad.csv",text:async()=>"sheet_id,question_no,ground_truth\\nS0001,3,6"})');
assert.equal(app.run('JSON.stringify(state.answers)'),before,'Invalid imports must not partially change answers');
assert.match(app.get('message').textContent,/นำเข้าไม่สำเร็จ/);
app.run('for(let q=1;q<=100;q++)state.answers["S0001:"+q]="2";state.answers["S0001:2"]="blank";state.reviewed.S0001=true;renderCounts()');
assert.equal(app.run('pilotStatistics().compared'),100);
assert.equal(app.run('pilotStatistics().matched'),99);
app.run('exportPilot()');
const evaluation=(await app.downloaded().text()).replace(/^\ufeff/,'').split('\r\n');
assert.equal(evaluation.length,101);
assert.equal(evaluation[2].split(',')[6],'"0"','Corrected human labels must count against the original proposal');
app.run('state.question=1;choose("4")');
assert.equal(app.run('pilotStatistics().compared'),0,'Editing a reviewed sheet must require re-review');
app.run('DATA.pilot.sheets.S0002=DATA.pilot.sheets.S0001;DATA.sheets[1].split="test";changeSheet("S0002")');
assert.equal(app.get('acceptProposal').disabled,true,'Test sheets must be transcribed without displaying suggestions');
assert.equal(app.get('acceptProposal').classList.contains('hidden'),true);
app.get('acceptProposal').click();
assert.equal(app.run('value("S0002",1)'),'', 'A hidden test-sheet proposal must never populate ground truth');
fixture.initial['S0001:1']='5';
fixture.corrections=[{id:'confirmed-fix',key:'S0001:1',mark:'5'}];
app=boot(app.storage);
assert.equal(app.run('value("S0001",1)'),'5','A human-confirmed correction must replace an older cached answer');
app.run('changeSheet("S0001");choose("4")');
app=boot(app.storage);
assert.equal(app.run('value("S0001",1)'),'4','An already applied correction must not erase later intentional edits');
fixture.pilot.sheets.S0002=JSON.parse(JSON.stringify(fixture.pilot.sheets.S0001));
fixture.pilot.batches=[{id:'first',sheet_ids:['S0001'],method:'old-reader',run_id:'old-run'},{id:'next',sheet_ids:['S0002'],method:'new-reader',run_id:'new-run'}];
fixture.pilot.active_batch='next';
app=boot(app.storage);
assert.equal(app.run('state.sheet'),'S0002','A newly prepared batch should start at its first incomplete sheet');
assert.equal(app.run('value("S0001",1)'),'4','Switching batches must preserve existing human answers');
assert.equal(app.run('pilotStatistics().total'),100,'Batch totals must not include earlier batches');
app.run('exportPilot()');
const batchExport=(await app.downloaded().text()).split('\r\n');
assert.equal(batchExport.length,101);
assert.ok(batchExport[1].startsWith('"S0002"'));
assert.ok(batchExport[1].includes('"new-reader","new-run"'),'Exports must use the selected batch original run ID');
assert.ok(batchExport[1].endsWith('"reviewed_label_agreement","false"'),'Agreement exports must not claim independent evaluation');
fixture.drafts={answers:Object.fromEntries(Array.from({length:100},(_,i)=>['S0002:'+(i+1),'1'])),sheets:{S0002:{id:'draft-version-1',annotator:'Codex visual',count:100,review_questions:[2,3]}}};
app=boot(app.storage);
assert.equal(app.run('count("S0002")'),100,'Visual drafts should prefill the review form');
assert.equal(app.run('value("S0002",100)'),'ambiguous','Cached human edits must take precedence over draft values');
assert.equal(app.run('state.reviewed.S0002'),false,'A new visual draft must require user review');
app.run('exportCsv()');
let draftExport=(await app.downloaded().text()).split('\r\n');
assert.equal(draftExport[101],'"S0002","1",""','Unreviewed visual drafts must not leak into ground truth exports');
app.get('reviewed').checked=true;app.get('reviewed').onchange();
app.run('exportCsv()');draftExport=(await app.downloaded().text()).split('\r\n');
assert.equal(draftExport[101],'"S0002","1","1"','User-approved drafts should be exportable');
app=boot(app.storage);assert.equal(app.run('state.reviewed.S0002'),true,'Reviewed status must persist for the same draft version');
fixture.pairing_holds={S0002:'A/B pair mismatch under review'};
app=boot(app.storage);
assert.equal(app.run('count("S0002")'),0,'Held pairs must not count as completed label sheets');
const heldValue=app.run('value("S0002",1)');app.run('changeSheet("S0002");choose("5")');
assert.equal(app.run('value("S0002",1)'),heldValue,'Held-pair label edits must be blocked without erasing stored values');
app.run('exportCsv()');
assert.equal((await app.downloaded().text()).split('\r\n')[101],'"S0002","1",""','Held-pair labels must stay out of exports even if previously reviewed');
delete fixture.pairing_holds;
const oldStored=app.storage.get('omr-answer-review-v1-test-fixture');
fixture.fingerprint='repaired-fixture';
fixture.pairing_migrations=[{from_fingerprint:'test-fixture',to_fingerprint:'repaired-fixture',reset_sheets:['S0002']}];
app=boot(app.storage);
assert.equal(app.run('value("S0001",1)'),'4','Pair repair must preserve cached human edits on unaffected sheets');
assert.equal(app.run('value("S0002",100)'),'1','Pair repair must discard old-pair cached answers and use the new source draft');
assert.equal(app.run('state.reviewed.S0002'),false,'A repaired pair must require a new answer review');
assert.equal(app.storage.get('omr-answer-review-v1-test-fixture'),oldStored,'The previous browser cache must stay available as a backup');
app.run('changeSheet("S0002");state.question=100;choose("3")');
app=boot(app.storage);
assert.equal(app.run('value("S0002",100)'),'3','Reloading a repaired page must preserve subsequent human edits');
fixture.annotation_mode='omr_assisted';delete fixture.drafts;
app=boot();app.run('changeSheet("S0002")');
assert.equal(app.get('acceptProposal').disabled,false,'User-authorized assisted mode must allow suggestions on Test sheets');
assert.equal(app.get('acceptProposal').classList.contains('hidden'),false);
assert.match(app.get('proposalText').textContent,/เสนอ:/);
assert.equal(app.run('value("S0002",1)'),'','Showing proposals must not prefill ground truth');
app.get('acceptProposal').click();
assert.equal(app.run('value("S0002",1)'),'2','An explicit acceptance may fill a Test answer in assisted mode');
app.run('exportPilot()');
assert.match(await app.downloaded().text(),/"omr_assisted","reviewed_label_agreement","false"/);
fixture.assistance={version:'workload-v1',start:'S0002',items:Object.fromEntries([1,2,3,4,5,6].map(q=>['S0002:'+q,{proposed:q===4?'blank':'2',role:'B',confident:q!==4,reasons:q===4?['special_mark']:[],risk_score:q===4?900:0}])),queue:[1,2,3,4,5].map(q=>({key:'S0002:'+q,kind:q===5?'sample':'risk'}))};
{
 const testData=JSON.parse(JSON.stringify(fixture));
 testData.risk_review={version:'test',run_id:'run-1',sample_size:1,sample_method:'test',items:{
  'S0002:1':{group:'risk',proposal:'3',reasons:['methods_disagree'],split:'train'},
  'S0002:2':{group:'agreement',proposal:'2',reasons:[],audit_sample:true,split:'train'},
  'S0002:3':{group:'agreement',proposal:'2',reasons:[],split:'train'}}};
 const risk=boot(new Map(),testData);
 assert.equal(risk.run('humanVerified("S0002",1)'),false,'Showing the risk queue never confirms a draft');
 assert.equal(risk.run('value("S0002",1)'),'2','Existing tentative answer must not be overwritten');
 risk.get('riskReviewExportDrafts').click();
 const pseudoCsv=await risk.downloaded().text();
 assert.doesNotMatch(pseudoCsv.split('\r\n')[0],/ground_truth/,'Machine answers must never look like verified labels');
 assert.match(pseudoCsv,/"S0002","3","2","machine_generated_not_verified","false","train"/);
 assert.doesNotMatch(pseudoCsv,/"S0002","2","2","machine_generated_not_verified"/,'Frozen random audit must not enter pseudo-labels');
 const first=risk.get('riskReviewCards').children[0];
 assert.match(first.children[1].textContent,/CNN และ CLA อ่านต่างกัน/);
 const buttons=first.children.find(e=>e.className==='queue-answer-buttons');
 const suggested=buttons.children.find(e=>e.dataset.riskMark==='3');
 assert.match(suggested.className,/risk-suggested/,'The CNN proposal is visually highlighted');
 assert.match(suggested.textContent,/CNN เสนอ/,'The proposal is identified without relying on color');
 risk.get('focusRiskReview').click();
 risk.handlers.keydown({key:'Enter',preventDefault(){}});
 assert.equal(risk.run('humanVerified("S0002",1)'),true,'Enter confirms the active CNN proposal');
 assert.equal(risk.run('value("S0002",1)'),'3','Enter uses the CNN proposal, not the different older draft');
 risk.get('riskReviewFilter').value='sample';risk.get('riskReviewFilter').onchange();
 const sampleCard=risk.get('riskReviewCards').children[0];
 assert.ok(!sampleCard.children.some(e=>String(e.textContent).includes('CNN เสนอ')),'Random audit hides the suggestion');
 assert.ok(!sampleCard.children.find(e=>e.className==='queue-answer-buttons').children.some(e=>e.className.includes('risk-suggested')),'Random audit never reveals the model answer through highlighting');
 risk.handlers.keydown({key:'Enter',preventDefault(){}});
 assert.equal(risk.run('humanVerified("S0002",2)'),false,'Enter must never silently accept a blind audit suggestion');
 risk.handlers.keydown({key:'2',preventDefault(){}});
 assert.equal(risk.run('validRiskAudits().length'),1);
 risk.get('backup').click();const saved=await risk.downloaded().text();
 const restoredRisk=boot(new Map(),testData);
 await restoredRisk.run('importFile({name:"backup.json",text:async()=>'+JSON.stringify(saved)+'})');
 assert.equal(restoredRisk.run('validRiskAudits().length'),1,'Backup restore keeps audited sample and provenance');
 restoredRisk.run('changeSheet("S0002");state.question=2;choose("4")');
 assert.equal(restoredRisk.run('validRiskAudits().length'),0,'Changed sample answers must not leave stale comparison results');
 const emptyData=JSON.parse(JSON.stringify(testData));emptyData.risk_review.items['S0002:1'].proposal='';
 const noSuggestion=boot(new Map(),emptyData);noSuggestion.get('focusRiskReview').click();
 noSuggestion.handlers.keydown({key:'Enter',preventDefault(){}});
 assert.equal(noSuggestion.run('humanVerified("S0002",1)'),false,'Enter cannot invent a missing model proposal');
 const multiData=JSON.parse(JSON.stringify(testData));multiData.risk_review.items['S0002:4']={group:'risk',proposal:'5',reasons:[],split:'train'};
 const keyboard=boot(new Map(),multiData);keyboard.get('focusRiskReview').click();
 keyboard.handlers.keydown({key:'ArrowRight',preventDefault(){}});
 assert.equal(keyboard.run('riskActiveKey'),'S0002:4','Arrow keys select the next risk card');
 keyboard.handlers.keydown({key:'Enter',repeat:true,preventDefault(){throw Error('Repeated keys should be ignored')}});
 assert.equal(keyboard.run('humanVerified("S0002",4)'),false,'Holding Enter must not confirm extra rows');
 keyboard.handlers.keydown({key:'1',preventDefault(){}});
 assert.equal(keyboard.run('value("S0002",4)'),'1','Number keys correct the active card');
 assert.equal(keyboard.run('humanVerified("S0002",1)'),false,'Keyboard actions must not confirm a different card');
}
fixture.pilot.sheets.S0002.B.rows[3].proposed='blank';fixture.pilot.sheets.S0002.B.rows[3].uncertain=true;
const legacyCache=new Map([['omr-answer-review-v1-'+fixture.fingerprint,JSON.stringify({answers:{'S0001:2':'4','S0002:2':'5','S0002:3':''},reviewed:{},sheet:'S0001',question:2})]]);
app=boot(legacyCache);
assert.equal(app.run('value("S0001",2)'),'4','Existing protected-range entries must survive bulk assistance');
assert.equal(app.run('value("S0002",2)'),'5','Existing later entries must take precedence over automatic drafts');
assert.equal(app.run('value("S0002",3)'),'','Bulk assistance must respect an explicitly cleared answer');
assert.equal(app.run('value("S0002",4)'),'','Low-confidence proposals must remain pending rather than autofilled');
assert.equal(app.run('value("S0002",1)'),'2');
assert.equal(app.run('humanVerified("S0002",1)'),false,'Automatic drafts must never become human verified');
assert.equal(app.run('state.sheet'),'S0002','The assisted workflow starts after the user-protected range');
const navigation=boot(new Map());
navigation.run('changeSheet("S0002");state.question=1');
navigation.get('nextEmpty').click();
assert.equal(navigation.run('state.question'),2,'Next unreviewed finds a filled but unverified draft');
navigation.run('choose("3")');
assert.equal(navigation.run('humanVerified("S0002",2)'),true);
assert.equal(navigation.run('state.question'),3,'Confirming advances to the next unverified question');
assert.match(navigation.get('sheetCount').textContent,/มีคำตอบ .*รวมร่าง/);
assert.match(navigation.get('sheetCount').textContent,/คนตรวจแล้ว 1 ข้อ/);
navigation.run('state.question=1');navigation.get('nextEmpty').click();
assert.equal(navigation.run('state.question'),3,'Navigation skips previously inspected questions');
app.run('exportCsv()');
assert.equal((await app.downloaded().text()).split('\r\n')[101],'"S0002","1",""');
app.run('exportMachineDrafts()');const machineCsv=await app.downloaded().text();
assert.match(machineCsv,/"omr_draft","omr","false"/);
assert.doesNotMatch(machineCsv.split('\r\n')[0],/"ground_truth"/,'Machine exports must not masquerade as ground-truth input');
assert.ok(app.storage.has('omr-answer-review-v1-'+fixture.fingerprint+'-before-bulk-review'));
const firstCard=app.get('queueCards').children[0],choices=firstCard.children.find(e=>e.className==='queue-answer-buttons'),pick=choices.children.find(e=>e.dataset.queueMark==='3');
pick.click();
assert.equal(app.run('humanVerified("S0002",1)'),true,'One direct answer click is an explicit human confirmation');
assert.equal(app.run('value("S0002",1)'),'3');
assert.equal(app.get('queueCards').children[0].dataset.key,'S0002:1','Completed cards must keep their slot until the group is finished');
assert.equal(app.get('queueCards').children[0].children.find(e=>e.className==='queue-answer-buttons').children[0].disabled,true,'Completed cards must not accept accidental repeated clicks');
app.get('undoQueue').click();
assert.equal(app.run('value("S0002",1)'),'2');
assert.equal(app.run('humanVerified("S0002",1)'),false,'Undo must return an automatic answer to its tentative provenance');
app.run('state.queueEdits["S0002:1"]="3";save()');
app=boot(app.storage);
assert.equal(app.run('state.queueEdits["S0002:1"]'),'3','Edits saved by the previous interface must survive reload');
app.run('confirmQueueKeys(["S0002:1"])');
assert.equal(app.run('value("S0002",1)'),'3');assert.equal(app.run('humanVerified("S0002",1)'),true);
app.run('exportCsv()');
assert.equal((await app.downloaded().text()).split('\r\n')[101],'"S0002","1","3"','Individually inspected queue answers must export without requiring 100 reviewed answers');
assert.equal(app.run('humanVerified("S0002",6)'),false,'Reviewing a queue must not verify unrelated drafts');
app.run('deferReviewKey("S0002:2")');
assert.notEqual(app.run('visibleReviewKeys[0]'),'S0002:2','Deferred tasks must move behind unreviewed tasks');
app.get('confirmQueuePage').click();
assert.equal(app.run('humanVerified("S0002",2)'),false,'Group confirmation must not silently accept a deferred card');
app.get('confirmQueuePage').click();
assert.equal(app.run('value("S0002",2)'),'5','Bulk review must use the displayed existing answer rather than overwrite it with OMR');
assert.equal(app.run('humanVerified("S0002",6)'),false);
app.run('changeSheet("S0002");state.question=1;choose("")');app=boot(app.storage);
assert.equal(app.run('value("S0002",1)'),'','Cleared automatic answers must stay cleared on reload');
assert.equal(app.run('humanVerified("S0002",1)'),false);
app.get('backup').click();const backupJson=await app.downloaded().text();
app.run('state.question=1;choose("4")');
await app.run('importFile({name:"backup.json",text:async()=>'+JSON.stringify(backupJson)+'})');
assert.equal(app.run('value("S0002",1)'),'','JSON restore must preserve clear tombstones');
assert.equal(app.run('humanVerified("S0002",6)'),false,'JSON restore must preserve tentative provenance');
assert.equal(app.run('humanVerified("S0002",2)'),true,'JSON restore must preserve inspected provenance');
app.run('DATA.initial["S0002:6"]="2"');
assert.equal(app.run('humanVerified("S0002",6)'),true,'Authoritative imported human labels must take precedence over stale tentative cache metadata');

// Keyboard actions must target the queue, never the separate whole-sheet form.
app=boot(new Map());
assert.equal(app.run('queueKeyTarget()'),false,'Hidden queue must not capture keyboard actions');
app.handlers.keydown({key:'Enter',ctrlKey:true,preventDefault(){throw Error('Hidden queue must not consume Ctrl+Enter')}});
assert.equal(app.run('humanVerified("S0002",1)'),false,'Hidden queue must not confirm drafts');
app.get('legacyQueue').open=true;
app.get('focusQueue').click();
app.handlers.keydown({key:'4',preventDefault(){}});
assert.equal(app.run('value("S0002",1)'),'4');assert.equal(app.run('humanVerified("S0002",1)'),true);
assert.equal(app.run('value("S0002",2)'),'2','One keypress must confirm only one card');
app.handlers.keydown({key:'4',repeat:true,preventDefault(){}});
assert.equal(app.run('humanVerified("S0002",2)'),false,'Holding a key must not silently confirm additional cards');
app.handlers.keydown({key:'z',ctrlKey:true,preventDefault(){}});
assert.equal(app.run('humanVerified("S0002",1)'),false);
app.handlers.keydown({key:'Enter',ctrlKey:true,preventDefault(){}});
assert.equal(app.run('DATA.assistance.queue.every(e=>{const [s,q]=e.key.split(":");return humanVerified(s,Number(q))})'),true);
assert.equal(app.run('humanVerified("S0002",6)'),false);
app.handlers.keydown({key:'z',ctrlKey:true,preventDefault(){}});
assert.equal(app.run('humanVerified("S0002",1)'),false,'A group undo must restore the complete transaction');
app.get('legacyQueue').open=false;
app.handlers.keydown({key:'Enter',ctrlKey:true,preventDefault(){throw Error('Closed queue must not consume Ctrl+Enter')}});
assert.equal(app.run('humanVerified("S0002",1)'),false,'Closing queue must disable its keyboard shortcuts');
app.run('quickReviewAnswer("S0002:1","3");changeSheet("S0002");state.question=1;choose("5");undoQueueReview()');
assert.equal(app.run('value("S0002",1)'),'5','Undo must preserve subsequent manual edits made outside the queue');
const heldBrowser=app.storage;fixture.pairing_holds={S0002:'Different source papers; pairing audit pending'};
app=boot(heldBrowser);
assert.equal(app.run('visibleReviewKeys.length'),0,'Reported held sheets must disappear even from an already-saved review page');
assert.equal(app.run('value("S0002",1)'),'5','A pairing hold must preserve stored answers for a later source audit');
assert.equal(app.run('humanVerified("S0002",1)'),false,'A prior inspection cannot make a mismatched pair exportable');
app.run('quickReviewAnswer("S0002:1","4")');
assert.equal(app.run('value("S0002",1)'),'5','Held-sheet quick confirmation must be blocked');
app.run('exportCsv()');assert.equal((await app.downloaded().text()).split('\r\n')[101],'"S0002","1",""');
app.run('exportMachineDrafts()');assert.match(await app.downloaded().text(),/"pairing_hold"/);
assert.match(app.get('queueProgress').textContent,/พัก 5 ข้อ/);
delete fixture.pairing_holds;
console.log('Annotation checks passed: legacy storage, isolated drafts, explicit review, queue edits, deferred tasks, separate exports and backups.');

const reduced=JSON.parse(JSON.stringify(fixture));reduced.fingerprint='retired-fixture';reduced.sheets=reduced.sheets.filter(s=>s.id==='S0001');
reduced.pilot.sheets={S0001:reduced.pilot.sheets.S0001};reduced.pilot.batches=[{id:'kept',sheet_ids:['S0001'],method:'fixture',run_id:'kept-run'}];reduced.pilot.active_batch='kept';
reduced.assistance={start:'S0001',items:{'S0001:3':{proposed:'2',role:'B',confident:true,reasons:[],risk_score:0}},queue:[{key:'S0001:3',kind:'risk'}]};
reduced.pairing_migrations=[{from_fingerprint:fixture.fingerprint,to_fingerprint:'retired-fixture',reset_sheets:[],removed_sheets:['S0002']}];
const legacyState=JSON.stringify({answers:{'S0001:2':'4','S0002:1':'5'},answerMeta:{'S0001:2':{mark:'4',source:'human',verified:true},'S0002:1':{mark:'5',source:'human',verified:true}},assistanceInitialized:true,reviewed:{S0002:true},sheet:'S0002',question:1,queuePageKeys:['S0002:1'],queueUndo:[{rows:[]}]});
const retiredStorage=new Map([['omr-answer-review-v1-'+fixture.fingerprint,legacyState]]),retiredApp=boot(retiredStorage,reduced);
assert.equal(retiredApp.run('storageOkay'),true,'Retired keys must be filtered before validating the new inventory');
assert.equal(retiredApp.run('value("S0001",2)'),'4');assert.equal(retiredApp.run('humanVerified("S0001",2)'),true,'Unchanged human provenance must survive a smaller inventory');
assert.equal(retiredApp.run('Object.hasOwn(state.answers,"S0002:1")'),false);
assert.equal(retiredApp.run('Object.hasOwn(state.answerMeta,"S0002:1")'),false);
assert.equal(retiredApp.run('state.queueUndo.length'),0,'Undo records from retired mappings must not leak into the repaired inventory');
assert.equal(retiredStorage.get('omr-answer-review-v1-'+fixture.fingerprint),legacyState,'The old cache must retain retired answers for source auditing');

const alternativeFixture=JSON.parse(JSON.stringify(reduced));
alternativeFixture.fingerprint='alternative-draft-fixture';alternativeFixture.annotation_mode='omr_assisted';
alternativeFixture.pilot.sheets.S0001.A={rows:Array.from({length:100},(_,i)=>({question_no:i+1,proposed:'5',uncertain:false})),sprite:'a-rows.jpg'};
alternativeFixture.pilot.sheets.S0001.B.rows=Array.from({length:100},(_,i)=>({question_no:i+1,proposed:'blank',uncertain:true}));
alternativeFixture.draft_supplement={method:'alternative-image-draft-v1',run_id:'extra-run',items:Object.fromEntries([20,21,22].map(q=>['S0001:'+q,{proposed:'5',role:'A',reasons:['ab_disagree','alternative_image']}]))};
alternativeFixture.draft_supplement.items['S0001:23']={proposed:'5',role:'B',reasons:['paired_peak_agreement']};
const altStorage=new Map([['omr-answer-review-v1-alternative-draft-fixture',JSON.stringify({answers:{'S0001:21':'4','S0001:22':''},answerMeta:{'S0001:21':{mark:'4',source:'human',verified:true}},assistanceInitialized:true,reviewed:{},sheet:'S0001',question:20})]]);
const altApp=boot(altStorage,alternativeFixture);
assert.equal(altApp.run('value("S0001",20)'),'5');
assert.equal(altApp.run('humanVerified("S0001",20)'),false,'Alternative readings are tentative drafts');
assert.equal(altApp.run('value("S0001",21)'),'4','Alternative drafts must preserve cached inspected choices');
assert.equal(altApp.run('humanVerified("S0001",21)'),true);
assert.equal(altApp.run('value("S0001",22)'),'', 'An explicit clear must prevent alternative autofill');
assert.equal(altApp.run('displayProposalFor("S0001",20).role'),'A');
assert.equal(altApp.run('displayProposalFor("S0001",23).role'),'B');
assert.equal(altApp.run('displayProposalFor("S0001",23).proposed'),'5','Paired evidence may rescue a frozen blank without altering it');
assert.equal(altApp.run('proposalFor("S0001",23).proposed'),'blank');
assert.equal(altApp.run('proposalFor("S0001",20).proposed'),'blank','Frozen comparison must retain the original B proposal');
altApp.run('exportCsv()');
assert.equal((await altApp.downloaded().text()).split('\r\n')[20],'"S0001","20",""');
altApp.run('exportMachineDrafts()');
assert.match(await altApp.downloaded().text(),/"alternative_image_needs_review","ab_disagree;alternative_image","","alternative-image-draft-v1","extra-run"/);
const originalTaskCount=altApp.run('DATA.assistance.queue.length');
altApp.get('reviewSupplement').click();
assert.equal(altApp.run('visibleReviewKeys.length'),3,'The optional view excludes inspected alternatives');
assert.equal(altApp.run('DATA.assistance.queue.length'),originalTaskCount,'Optional alternatives must never replace frozen tasks');
altApp.run('quickReviewAnswer("S0001:20","5")');
assert.equal(altApp.run('humanVerified("S0001",20)'),true);
altApp.run('undoQueueReview()');
assert.equal(altApp.run('humanVerified("S0001",20)'),false,'Undo restores an alternative draft without certification');
altApp.get('acceptProposal').click();
assert.equal(altApp.run('humanVerified("S0001",20)'),true,'A draft becomes inspected only through explicit confirmation');

// Optional local-data smoke check uses the generated page without a browser.
const generated=new URL('../data/metadata/answer_review.html',import.meta.url);
if(fs.existsSync(generated)){
 const html=fs.readFileSync(generated,'utf8'),real=JSON.parse(html.match(/<script id="annotation-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 if(real.assistance){
  const savedAnswers=Object.fromEntries(Array.from({length:100},(_,i)=>['S0038:'+(i+1),'5']));
  const storage=new Map([['omr-answer-review-v1-'+real.fingerprint,JSON.stringify({answers:savedAnswers,reviewed:{S0038:true},sheet:'S0038',question:100})]]);
  const live=boot(storage,real);
  assert.equal(live.run('value("S0038",100)'),'5');
  assert.equal(live.run('humanVerified("S0038",100)'),true);
  assert.equal(live.run('state.sheet'),'S0039');
  assert.ok(live.run('DATA.assistance.queue.length')>0&&live.run('DATA.assistance.queue.length')<=1000);
  const pendingTasks=real.assistance.queue.filter(e=>!real.pairing_holds[e.key.split(':')[0]]&&!real.initial[e.key]&&!savedAnswers[e.key]).length;
  assert.equal(live.run('visibleReviewKeys.length'),Math.min(10,pendingTasks));
  if(pendingTasks)assert.equal(live.get('queueCards').children.length,Math.min(10,pendingTasks));
  const omrKeys=live.run('Object.keys(state.answerMeta).filter(k=>state.answerMeta[k].source==="omr")');
  const expectedDrafts=Object.entries(real.assistance.items).filter(([k,item])=>item.confident&&!real.pairing_holds[k.split(':')[0]]&&!Object.hasOwn(real.initial,k)&&!Object.hasOwn(real.drafts?.answers||{},k)&&!Object.hasOwn(savedAnswers,k)).length;
  const originalDraftKeys=new Set(Object.entries(real.assistance.items).filter(([k,item])=>item.confident).map(([k])=>k));
  const supplementalDrafts=Object.keys(real.draft_supplement?.items||{}).filter(k=>!originalDraftKeys.has(k)&&!real.pairing_holds[k.split(':')[0]]&&!Object.hasOwn(real.initial,k)&&!Object.hasOwn(real.drafts?.answers||{},k)&&!Object.hasOwn(savedAnswers,k)).length;
  assert.equal(omrKeys.length,expectedDrafts+supplementalDrafts,'Automatic drafts must exclude every held sheet while preserving prior entries');
  assert.equal(live.run('Object.keys(state.answerMeta).filter(k=>state.answerMeta[k].source==="omr"&&state.answerMeta[k].verified).length'),0);
  live.run('exportCsv()');const humanExport=await live.downloaded().text();
  const expectedHumanKeys=new Set([...Object.keys(real.initial),...Object.keys(savedAnswers)].filter(k=>!real.pairing_holds[k.split(':')[0]]));
  assert.equal(humanExport.replace(/^\ufeff/,'').split('\r\n').slice(1).filter(r=>/,"[^"]+"$/.test(r)).length,expectedHumanKeys.size);
  const previouslyReviewed=live.run('DATA.assistance.queue.filter(e=>{const [s,q]=e.key.split(":");return humanVerified(s,Number(q))}).length');
  const shown=live.run('visibleReviewKeys.length');
  live.run('confirmQueueKeys(visibleReviewKeys)');
  assert.equal(live.run('DATA.assistance.queue.filter(e=>{const [s,q]=e.key.split(":");return humanVerified(s,Number(q))}).length'),previouslyReviewed+shown);
  assert.equal(live.run('visibleReviewKeys.length'),Math.min(10,pendingTasks-shown),'Completing a group must show the next remaining tasks automatically');
  live.get('confirmQueuePage').onclick({detail:2});
  assert.equal(live.run('DATA.assistance.queue.filter(e=>{const [s,q]=e.key.split(":");return humanVerified(s,Number(q))}).length'),previouslyReviewed+shown,'An accidental double-click must not confirm the next group');
  live.run('undoQueueReview()');
  assert.equal(live.run('DATA.assistance.queue.filter(e=>{const [s,q]=e.key.split(":");return humanVerified(s,Number(q))}).length'),previouslyReviewed);
  console.log('Generated-page smoke check passed: S0038 retained, S0039 start, surviving frozen tasks, retired/held sheets excluded, stable cards and explicit confirmations.');
  const archivedBackup=new URL('../presentation_build/omr_refinement_20261026/answer_review_backup.json',import.meta.url);
  if(fs.existsSync(archivedBackup)){
   const backup=JSON.parse(fs.readFileSync(archivedBackup,'utf8').replace(/^\ufeff/,''));
   const backupMigration=real.pairing_migrations?.find(m=>m.from_fingerprint===backup.fingerprint);
   if(backup.fingerprint===real.fingerprint||backupMigration){
    const savedKey='omr-answer-review-v1-'+backup.fingerprint,originalJson=JSON.stringify(backup),backupStorage=new Map([[savedKey,originalJson]]),restored=boot(backupStorage,real);
    assert.equal(restored.run('storageOkay'),true);
    const activeIds=new Set(real.sheets.map(s=>s.id)),resetIds=new Set(backupMigration?.reset_sheets||[]);
    const approvedUpdates=new Map((real.corrections||[]).filter(c=>!(backup.correctionsApplied||[]).includes(c.id)).map(c=>[c.key,c.mark]));
    for(const [k,v] of Object.entries(backup.answers)){
     const sid=k.split(':')[0];
     if(!activeIds.has(sid))assert.equal(restored.run('Object.hasOwn(state.answers,'+JSON.stringify(k)+')'),false,'Withdrawn records must leave the active answer cache');
     else if(!resetIds.has(sid))assert.equal(restored.run('state.answers['+JSON.stringify(k)+']'),approvedUpdates.get(k)??v,'Provided backup answers must stay intact except for human-approved corrections: '+k);
    }
    if(backupMigration)assert.equal(backupStorage.get(savedKey),originalJson,'Original backup cache keeps every withdrawn answer');
    for(const k of Object.keys(real.draft_supplement?.items||{})){
     if(Object.hasOwn(backup.answers,k))continue;
     if(Object.hasOwn(real.initial,k)){
      assert.equal(restored.run('humanVerified('+JSON.stringify(k.split(':')[0])+','+Number(k.split(':')[1])+')'),true,'Newly imported official answers remain verified');
      continue;
     }
     assert.equal(restored.run('state.answerMeta['+JSON.stringify(k)+'].verified'),false,'New paired drafts must remain unverified');
    }
    assert.equal(restored.run('DATA.assistance.queue.length'),real.assistance.queue.length);
    assert.equal(restored.run('humanVerified("S0294",14)'),false);
    restored.run('exportCsv()');
    const heldExport=(await restored.downloaded().text()).split('\r\n').filter(row=>row.startsWith('"S0294",'));
    assert.equal(heldExport.length,activeIds.has('S0294')?100:0);assert.ok(heldExport.every(row=>row.endsWith(',""')));
    if(!activeIds.has('S0294'))assert.equal(restored.run('DATA.assistance.queue.length'),859,'Only the 27 previously held tasks leave the active queue');
    console.log('Provided-backup replay passed: active answers retained, withdrawn answers archived in old cache, paired drafts unverified and queue preserved.');
   }
  }
  const natMigration=real.pairing_migrations?.find(m=>m.removed_sheets?.includes('S0077'));
  if(natMigration){
   const oldProgress=JSON.stringify({answers:{'S0038:100':'5','S0068:1':'4','S0076:1':'5','S0077:1':'3'},answerMeta:Object.fromEntries([['S0038:100','5'],['S0068:1','4'],['S0076:1','5'],['S0077:1','3']].map(([k,mark])=>[k,{mark,source:'human',verified:true}])),reviewed:{S0077:true},assistanceInitialized:true,sheet:'S0077',question:1,queuePageKeys:['S0077:1'],queueUndo:[]});
   const previousKey='omr-answer-review-v1-'+natMigration.from_fingerprint,oldCache=new Map([[previousKey,oldProgress]]),migrated=boot(oldCache,real);
   assert.equal(migrated.run('storageOkay'),true);
   assert.equal(migrated.run('value("S0038",100)'),'5');assert.equal(migrated.run('humanVerified("S0038",100)'),true);
   assert.equal(migrated.run('value("S0068",1)'),'4');assert.equal(migrated.run('humanVerified("S0068",1)'),true,'Unchanged confirmed Nat pairs retain previous human answers');
   if(real.initial['S0076:1'])assert.equal(migrated.run('value("S0076",1)'),real.initial['S0076:1'],'Current official labels may have been reviewed after the source repair');
   else assert.equal(migrated.run('humanVerified("S0076",1)'),false,'The repaired B source must require fresh answer review');
   assert.equal(migrated.run('Object.hasOwn(state.answers,"S0077:1")'),false);
   assert.equal(oldCache.get(previousKey),oldProgress);
   assert.equal(migrated.run('DATA.assistance.queue.length'),real.assistance.queue.length);
   console.log('Confirmed Nat repair smoke check passed: retired answers archived in old cache, unchanged user progress retained, S0076 reset and original surviving queue retained.');
  }
 }
}
