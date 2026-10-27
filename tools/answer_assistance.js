// Tentative machine labels and inspected answers have separate provenance.
let visibleReviewKeys=[];
let queueKeyboardActive=false;
const queueCardElements=new Map();
function humanVerified(sheet,q){
 const k=sheet+':'+q,v=value(sheet,q);if(!v||isHeld(sheet))return false;
 if(DATA.initial[k]===v)return true;
 const meta=state.answerMeta?.[k];if(meta&&meta.mark===v)return meta.verified===true;
 return DATA.initial[k]===v;
}
function statusCode(sheet,q){
 if(isHeld(sheet))return 'pairing_hold';
 if(humanVerified(sheet,q))return 'human_verified';
 const k=sheet+':'+q,v=value(sheet,q);if(!v)return 'pending_review';
 return ({omr:'omr_draft',visual:'visual_draft',legacy:'previous_entry_unverified'})[state.answerMeta?.[k]?.source]||'previous_entry_unverified';
}
function statusText(sheet,q){return ({human_verified:'คนตรวจแล้ว',omr_draft:'ร่าง OMR ยังไม่ตรวจ',visual_draft:'ร่างอ่านจากภาพ ยังไม่ตรวจ',previous_entry_unverified:'คำตอบเดิม รอรับรอง',pending_review:'รอตรวจ',pairing_hold:'พักระหว่างแก้คู่ A/B'})[statusCode(sheet,q)]}
function recordHumanChoice(sheet,q,mark,via='row'){
 state.answerMeta=state.answerMeta||{};
 state.answerMeta[sheet+':'+q]={mark,source:'human',verified:!!mark,via};
}
function reviewWholeSheet(sheet,checked){
 for(let q=1;q<=100;q++){
  const k=sheet+':'+q;
  if(checked&&!humanVerified(sheet,q))recordHumanChoice(sheet,q,value(sheet,q),'sheet');
  else if(!checked&&state.answerMeta[k]?.via==='sheet')state.answerMeta[k].verified=false;
 }
}
function installAssistance(){
 if(!DATA.assistance)return;
 $('reviewWorkflow').classList.toggle('hidden',false);
 const queue=DATA.assistance.queue,risk=queue.filter(e=>e.kind==='risk').length,sample=queue.filter(e=>e.kind==='sample').length;
 $('reviewWorkflowTitle').textContent='ตรวจเฉพาะจุดสำคัญ · คิว '+queue.length.toLocaleString()+' ข้อ';
 for(const option of $('queueFilter').options||[]){if(option.value==='risk')option.textContent=risk+' ข้อเสี่ยง';else if(option.value==='sample')option.textContent=sample+' ข้อสุ่ม'}
 $('reviewInstructions').textContent='เลือกแผ่นและดูภาพ A/B เทียบกับคำตอบที่เสนอ สีเทาคือร่างที่ยังไม่ตรวจ กดคำตอบเพื่อยืนยันหรือแก้รายข้อ หลังดูครบทุกข้อจึงติ๊กตรวจทานครบแผ่น แล้วส่งออกคำตอบที่ตรวจแล้ว';
 $('export').textContent='ส่งออกคำตอบที่คนตรวจแล้ว';
 $('answerHelp').textContent='สีเขียว = คนตรวจแล้ว · สีเทา = ร่างหรือคำตอบเดิมรอรับรอง · สีขาว = ยังไม่กรอก · สีเหลือง = ดูไม่ชัด คุณยังตรวจทีละข้อด้วยปุ่มคำตอบหรือ Enter และตรวจรับรองทั้งแผ่นได้';
 state.answerMeta=state.answerMeta||{};state.queueEdits=state.queueEdits||{};state.queueDeferred=state.queueDeferred||{};
 if(!state.assistanceInitialized){
  if(storageOkay){try{const backupKey=key+'-before-bulk-review';if(!localStorage.getItem(backupKey)){const old=localStorage.getItem(key);if(old)localStorage.setItem(backupKey,old)}}catch{notify('สำรองสถานะก่อนเริ่มร่างอัตโนมัติไม่ได้ โปรดใช้ปุ่มสำรอง JSON')}}
  for(const [k,v] of Object.entries(state.answers)){
   if(!v)continue;const sheet=k.split(':')[0],official=DATA.initial[k]===v,reviewed=state.reviewed[sheet]&&count(sheet)===100;
   state.answerMeta[k]={mark:v,source:official?'official':DATA.drafts?.answers?.[k]===v?'visual':'legacy',verified:!!(official||reviewed),via:official?'official':reviewed?'sheet':'legacy'};
  }
  state.assistanceInitialized=true;
  if(state.sheet<DATA.assistance.start){state.sheet=DATA.assistance.start;state.question=1}
 }
 for(const [k,item] of Object.entries(DATA.assistance.items)){
  if(item.confident&&!Object.prototype.hasOwnProperty.call(state.answers,k)&&!isHeld(k.split(':')[0])){
   state.answers[k]=item.proposed;state.answerMeta[k]={mark:item.proposed,source:'omr',verified:false};
   state.reviewed[k.split(':')[0]]=false;
  }
 }
 for(const [k,item] of Object.entries(DATA.draft_supplement?.items||{})){
  if(!Object.prototype.hasOwnProperty.call(state.answers,k)&&!isHeld(k.split(':')[0])&&!Object.hasOwn(DATA.initial,k)){
   state.answers[k]=item.proposed;state.answerMeta[k]={mark:item.proposed,source:'omr',verified:false,method:DATA.draft_supplement.method,run_id:DATA.draft_supplement.run_id};
   state.reviewed[k.split(':')[0]]=false;
  }
 }
 const supplementalCount=Object.keys(DATA.draft_supplement?.items||{}).length;
 if(supplementalCount)$('reviewInstructions').textContent+=' · มีร่างเสริมจากคะแนนภาพ A/B '+supplementalCount+' ข้อ ยังไม่ได้รับรองโดยคน ไม่จำเป็นต้องตรวจร่างเสริมทั้งหมดในรอบนี้ และแยกจากคิวเดิม';
 if(supplementalCount){
  const option=document.createElement('option');option.value='supplement';option.textContent='ร่างเสริมจาก A/B '+supplementalCount+' ข้อ (เลือกดู)';$('queueFilter').append(option);
  $('reviewSupplement').classList.toggle('hidden',false);$('reviewSupplement').textContent='ดูร่างเสริมจาก A/B '+supplementalCount+' ข้อ';
  $('reviewSupplement').onclick=()=>{$('queueFilter').value='supplement';$('queueFilter').onchange();queueKeyboardActive=true;$('reviewWorkflow').scrollIntoView?.({behavior:'smooth',block:'start'})};
 }
 $('queueFilter').value=state.queueFilter||'all';
 $('queueFilter').onchange=()=>{state.queueFilter=$('queueFilter').value;state.queuePageKeys=[];state.queuePageDeferred={};save();renderReviewQueue()};
 $('confirmQueuePage').onclick=e=>{if(e?.detail>1)return;confirmQueueKeys(visibleReviewKeys)};
 $('undoQueue').onclick=undoQueueReview;
 $('focusQueue').onclick=()=>{queueKeyboardActive=true;renderReviewQueue();revealQueueCard()};
 $('exportDrafts').onclick=exportMachineDrafts;
 document.addEventListener('pointerdown',e=>{queueKeyboardActive=!!e.target?.closest?.('#reviewWorkflow')});
 document.addEventListener('keydown',handleQueueKey);
}
function reviewEntries(){
 return $('queueFilter').value==='supplement'?Object.keys(DATA.draft_supplement?.items||{}).map(key=>({key,kind:'supplement'})):DATA.assistance.queue;
}
function reviewItem(k){return $('queueFilter').value==='supplement'?DATA.draft_supplement?.items?.[k]:DATA.assistance.items[k]}
function pendingReviewEntries(){
 const filter=$('queueFilter').value||'all';
 return reviewEntries().filter(entry=>{
  const [s,q]=entry.key.split(':');return (filter==='all'||entry.kind===filter)&&!isHeld(s)&&!humanVerified(s,Number(q));
 }).sort((a,b)=>(state.queueDeferred[a.key]||0)-(state.queueDeferred[b.key]||0));
}
function confirmQueueKeys(keys,overrides={}){
 let accepted=0;const transaction={id:Date.now()+'-'+(state.queueActionSequence=(state.queueActionSequence||0)+1),rows:[],page:[...(state.queuePageKeys||[])],deferred:{...(state.queuePageDeferred||{})},active:state.queueActiveKey,filter:$('queueFilter').value||'all'};
 for(const k of keys){
  const [s,qText]=k.split(':'),q=Number(qText),item=reviewItem(k);
  if(!item||isHeld(s)||humanVerified(s,q))continue;
  const mark=overrides[k]||state.queueEdits[k]||value(s,q)||item.proposed;if(!marks.has(mark))continue;
  transaction.rows.push({key:k,hadAnswer:Object.prototype.hasOwnProperty.call(state.answers,k),answer:state.answers[k],meta:state.answerMeta[k]?{...state.answerMeta[k]}:null,reviewed:!!state.reviewed[s],edit:state.queueEdits[k],deferred:state.queueDeferred[k],after:mark});
  state.answers[k]=mark;recordHumanChoice(s,q,mark);state.reviewed[s]=false;
  state.answerMeta[k].reviewTransaction=transaction.id;
  delete state.queueEdits[k];delete state.queueDeferred[k];accepted++;
 }
 if(accepted){state.queueUndo=state.queueUndo||[];state.queueUndo.push(transaction);state.queueUndo=state.queueUndo.slice(-20)}
 save();renderCounts();renderQuestion();notify('บันทึกว่าคุณตรวจภาพแล้ว '+accepted+' ข้อ ร่างอื่นยังไม่ถูกยืนยัน');
}
function quickReviewAnswer(k,mark){confirmQueueKeys([k],{[k]:mark})}
function undoQueueReview(){
 const transaction=state.queueUndo?.pop();if(!transaction)return;let restored=0;
 for(const row of transaction.rows){
  if(state.answerMeta[row.key]?.reviewTransaction!==transaction.id||state.answers[row.key]!==row.after)continue;
  if(row.hadAnswer)state.answers[row.key]=row.answer;else delete state.answers[row.key];
  if(row.meta)state.answerMeta[row.key]=row.meta;else delete state.answerMeta[row.key];
  state.reviewed[row.key.split(':')[0]]=row.reviewed;
  if(row.edit===undefined)delete state.queueEdits[row.key];else state.queueEdits[row.key]=row.edit;
  if(row.deferred===undefined)delete state.queueDeferred[row.key];else state.queueDeferred[row.key]=row.deferred;
  restored++;
 }
 state.queuePageKeys=transaction.page;state.queuePageDeferred=transaction.deferred;state.queueActiveKey=transaction.active;
 $('queueFilter').value=transaction.filter;state.queueFilter=transaction.filter;
 save();renderCounts();renderQuestion();notify('ย้อนกลับ '+restored+' ข้อแล้ว คำตอบที่แก้ต่อภายหลังจะถูกเก็บไว้');
}
function deferReviewKey(k){state.deferredTick=(state.deferredTick||0)+1;state.queueDeferred[k]=state.deferredTick;state.queuePageDeferred=state.queuePageDeferred||{};state.queuePageDeferred[k]=true;save();renderReviewQueue()}
function openReviewKey(k){queueKeyboardActive=false;const [s,q]=k.split(':');changeSheet(s);state.question=Number(q);save();renderQuestion();$('sheetTitle').scrollIntoView?.({behavior:'smooth',block:'start'})}
function queueKeyTarget(){
 if(!DATA.assistance||!queueKeyboardActive||!$('legacyQueue').open)return false;
 const active=document.activeElement,tag=active?.tagName;
 if(['INPUT','SELECT','TEXTAREA'].includes(tag)||active?.isContentEditable)return false;
 return !active||tag==='BODY'||!!active.closest?.('#reviewWorkflow');
}
function handleQueueKey(e){
 if(!queueKeyTarget()||e.altKey||e.repeat)return;
 const keyName=e.key.toLowerCase();
 if(e.ctrlKey||e.metaKey){
  if(keyName==='enter'){e.preventDefault();confirmQueueKeys(visibleReviewKeys)}
  else if(keyName==='z'&&!e.shiftKey){e.preventDefault();undoQueueReview()}
  return;
 }
 // Enter on a tab-focused button should retain that button's native action.
 if(keyName==='enter'&&document.activeElement?.tagName==='BUTTON'&&document.activeElement.id!=='focusQueue')return;
 const mark=({'b':'blank','m':'multiple','u':'ambiguous'})[keyName]||(['1','2','3','4','5'].includes(keyName)?keyName:null);
 const pending=visibleReviewKeys.filter(k=>{const [s,q]=k.split(':');return !humanVerified(s,Number(q))&&!state.queuePageDeferred?.[k]});
 const active=pending.includes(state.queueActiveKey)?state.queueActiveKey:pending[0];
 if(!active)return;
 if(mark){e.preventDefault();quickReviewAnswer(active,mark);revealQueueCard()}
 else if(keyName==='enter'){e.preventDefault();confirmQueueKeys([active]);revealQueueCard()}
 else if(keyName==='s'){e.preventDefault();deferReviewKey(active);revealQueueCard()}
 else if(['arrowdown','arrowright','arrowup','arrowleft'].includes(keyName)){
  e.preventDefault();const direction=['arrowup','arrowleft'].includes(keyName)?-1:1;state.queueActiveKey=pending[(pending.indexOf(active)+direction+pending.length)%pending.length];renderReviewQueue();revealQueueCard();
 }
 else if(keyName==='escape'){queueKeyboardActive=false;e.preventDefault()}
}
function revealQueueCard(){queueCardElements.get(state.queueActiveKey)?.scrollIntoView?.({behavior:'smooth',block:'nearest'})}
function renderReviewQueue(){
 if(!DATA.assistance)return;
 const filter=$('queueFilter').value||'all',entryMap=new Map(reviewEntries().map(e=>[e.key,e]));
 const isOpen=k=>{const [s,q]=k.split(':');return !isHeld(s)&&!humanVerified(s,Number(q))&&!state.queuePageDeferred?.[k]};
 let page=(state.queuePageKeys||[]).filter(k=>entryMap.has(k)&&!isHeld(k.split(':')[0])&&(filter==='all'||entryMap.get(k).kind===filter));
 let nextPage=false;
 if(!page.some(isOpen)){nextPage=page.length>0;page=pendingReviewEntries().slice(0,10).map(e=>e.key);state.queuePageDeferred={}}
 state.queuePageKeys=page;visibleReviewKeys=page.filter(isOpen);
 if(!visibleReviewKeys.includes(state.queueActiveKey))state.queueActiveKey=visibleReviewKeys[0]||'';
 const container=$('queueCards');container.replaceChildren();queueCardElements.clear();const entries=page.map(k=>entryMap.get(k));
 $('confirmQueuePage').disabled=!visibleReviewKeys.length;$('confirmQueuePage').textContent='ตรวจครบแล้ว ยืนยันอีก '+visibleReviewKeys.length+' ข้อ · Ctrl+Enter';
 $('undoQueue').disabled=!state.queueUndo?.length;
 $('queueActive').textContent=state.queueActiveKey?'คีย์ลัดกำลังเลือก '+state.queueActiveKey.replace(':',' ข้อ '):'ตรวจครบคิวที่เลือกแล้ว';
 const reasonText={ab_disagree:'ผลอ่านเดิม A/B ไม่ตรงกัน',special_mark:'ว่าง / หลายช่อง / ไม่ชัด',low_confidence:'รอยฝนจางหรือคะแนนใกล้กัน',single_image:'อ่านได้เพียงภาพเดียว',template_registration:'ใช้การจัดแนวสำรอง',alternative_image:'ร่างจาก A เมื่อ B อ่านว่าเว้นว่าง โปรดดูรอยฝนทั้งสองภาพ',paired_peak_agreement:'คะแนนรอยฝน A/B สูงสุดที่ช่องเดียวกัน ผ่านเกณฑ์ร่างเสริม ยังไม่ใช่คำตอบที่คนตรวจแล้ว'};
 for(const entry of entries){
  const k=entry.key,[s,qText]=k.split(':'),q=Number(qText),item=reviewItem(k),predictions=DATA.pilot.sheets[s];
  const checked=humanVerified(s,q),deferred=!!state.queuePageDeferred?.[k],disabled=checked||deferred;
  const card=document.createElement('article');card.className='queue-card'+(checked?' queue-done':'')+(deferred?' queue-deferred':'')+(state.queueActiveKey===k?' queue-active':'');card.dataset.key=k;queueCardElements.set(k,card);
  card.onclick=()=>{if(disabled)return;queueKeyboardActive=true;state.queueActiveKey=k;for(const [id,node] of queueCardElements)node.classList.toggle('queue-active',id===k);$('queueActive').textContent='คีย์ลัดกำลังเลือก '+k.replace(':',' ข้อ ')};
  const heading=document.createElement('strong');heading.textContent=s+' · ข้อ '+q+' · '+(entry.kind==='supplement'?'ร่างเสริมจาก A/B':entry.kind==='sample'?'ข้อสุ่ม':'ข้อเสี่ยง');card.append(heading);
  const why=document.createElement('p');why.textContent=item.reasons.map(r=>reasonText[r]).join(' · ')||'ตัวอ่านให้ความมั่นใจสูง ต้องสุ่มตรวจ';card.append(why);
  for(const role of ['A','B']){
   const result=predictions[role];if(!result?.sprite||result.rows?.length!==100)continue;
   const label=document.createElement('div');label.textContent='ภาพ '+role+(role===item.role?' · ภาพที่ใช้เสนอคำตอบ':'');card.append(label);
   const frame=document.createElement('div');frame.className='queue-crop';const img=document.createElement('img');img.src=entry.crops?.[role]||result.sprite;img.alt=s+' ข้อ '+q+' ภาพ '+role;img.loading='lazy';img.style.top=entry.crops?.[role]?'0':(-(q-1)*100)+'%';frame.append(img);card.append(frame);
  }
  const current=state.queueEdits[k]||value(s,q)||item.proposed;
  const status=document.createElement('p');status.className='queue-choice-state';status.textContent=checked?'ตรวจแล้ว: '+textMark(value(s,q)):deferred?'พักไว้ท้ายคิว':'คำตอบที่แสดง: '+textMark(current)+' · กดคำตอบด้านล่างครั้งเดียวเพื่อยืนยัน';card.append(status);
  const choices=document.createElement('div');choices.className='queue-answer-buttons';
  for(const mark of marks){const button=document.createElement('button');button.textContent=textMark(mark);button.dataset.queueMark=mark;button.disabled=disabled;button.className=(current===mark?'selected ':'')+(mark.length>1?'queue-special':'');button.setAttribute('aria-label',s+' ข้อ '+q+' ตรวจแล้วตอบ '+textMark(mark));button.setAttribute('aria-pressed',String(current===mark));button.onclick=e=>{e?.stopPropagation?.();if(!disabled)quickReviewAnswer(k,mark)};choices.append(button)}
  card.append(choices);
  const controls=document.createElement('div');controls.className='toolbar';
  const accept=document.createElement('button');accept.className='primary queue-accept';accept.disabled=disabled;accept.textContent=checked?'ยืนยันแล้ว':deferred?'พักไว้':'ถูกแล้ว · '+textMark(current);accept.onclick=e=>{e?.stopPropagation?.();if(!disabled)confirmQueueKeys([k])};controls.append(accept);
  const full=document.createElement('button');full.textContent='ดูภาพเต็ม A/B';full.onclick=e=>{e?.stopPropagation?.();openReviewKey(k)};controls.append(full);
  const later=document.createElement('button');later.textContent='พักข้อนี้ · S';later.disabled=disabled;later.onclick=e=>{e?.stopPropagation?.();if(!disabled)deferReviewKey(k)};controls.append(later);card.append(controls);container.append(card);
 }
 if(!entries.length){const empty=document.createElement('p');empty.textContent='ตรวจครบคิวที่เลือกแล้ว ข้ออื่นในชุดข้อมูลยังคงสถานะตามการตรวจจริง';container.append(empty)}
 if(nextPage)container.scrollIntoView?.({behavior:'smooth',block:'start'});
}
function renderAssistance(){
 $('reviewWorkflowTitle').textContent=$('queueFilter').value==='supplement'?'ดูร่างเสริมจาก A/B · '+Object.keys(DATA.draft_supplement?.items||{}).length+' ข้อ':'ตรวจเฉพาะจุดสำคัญ · คิว '+DATA.assistance.queue.length.toLocaleString()+' ข้อ';
 let human=0,machine=0,visual=0,legacy=0,pending=0,held=0;
 for(const s of sheets)for(let q=1;q<=100;q++){
  const status=statusCode(s.id,q);if(status==='human_verified')human++;else if(status==='omr_draft')machine++;else if(status==='visual_draft')visual++;else if(status==='previous_entry_unverified')legacy++;else if(status==='pairing_hold')held++;else pending++;
 }
 $('workflowSummary').textContent='คนตรวจแล้ว '+human.toLocaleString()+' ข้อ · ร่าง OMR '+machine.toLocaleString()+' ข้อ · ร่างอ่านจากภาพ '+visual.toLocaleString()+' ข้อ · คำตอบเดิมรอรับรอง '+legacy.toLocaleString()+' ข้อ · ยังไม่กรอก '+pending.toLocaleString()+' ข้อ'+(held?' · พักแก้คู่ภาพ '+held.toLocaleString()+' ข้อ':'');
 const all=DATA.assistance.queue,queue=all.filter(e=>!isHeld(e.key.split(':')[0])),done=queue.filter(e=>{const [s,q]=e.key.split(':');return humanVerified(s,Number(q))});
 $('queueProgress').textContent='คิวนี้ตรวจแล้ว '+done.length+'/'+queue.length+' ข้อที่ใช้งาน · เสี่ยง '+done.filter(e=>e.kind==='risk').length+'/'+queue.filter(e=>e.kind==='risk').length+' · สุ่ม '+done.filter(e=>e.kind==='sample').length+'/'+queue.filter(e=>e.kind==='sample').length+(all.length!==queue.length?' · พัก '+(all.length-queue.length)+' ข้อระหว่างแก้คู่ภาพ':'')+' · ตรวจคิวครบไม่ได้แปลว่าข้อที่เหลือถูกทั้งหมด';
 if($('queueFilter').value==='supplement'){
  const extras=reviewEntries().filter(e=>!isHeld(e.key.split(':')[0])),checked=extras.filter(e=>{const [s,q]=e.key.split(':');return humanVerified(s,Number(q))}).length;
  $('queueProgress').textContent+=' · มุมมองร่างเสริม ตรวจแล้ว '+checked+'/'+extras.length+' ข้อ (แยกจากคิวเดิม)';
 }
 renderReviewQueue();
}
function exportMachineDrafts(){
 const rows=[['sheet_id','question_no','proposed_answer','current_answer','label_status','source','reviewed_by_human','proposal_role','image_a_id','image_b_id','confidence_tag','risk_reasons','queue_type','method','run_id']];
 const queueMap=new Map(DATA.assistance.queue.map(e=>[e.key,e.kind]));
 for(const s of sheets)for(let q=1;q<=100;q++){
  if(humanVerified(s.id,q))continue;const k=s.id+':'+q,item=DATA.assistance.items[k],p=displayProposalFor(s.id,q),batch=batchForSheet(s.id);
  rows.push([s.id,q,p?.proposed||'',value(s.id,q),statusCode(s.id,q),state.answerMeta?.[k]?.source||'', 'false',p?.role||'',s.A.id||'',s.B.id||'',p?.supplemental?(p.reasons.includes('paired_peak_agreement')?'paired_consensus_needs_review':'alternative_image_needs_review'):item?.confident?'heuristic_high':'needs_review',(p?.supplemental?p.reasons:item?.reasons||[]).join(';'),queueMap.get(k)||'',p?.supplemental?p.method:batch?.method||'',p?.supplemental?p.run_id:batch?.run_id||'']);
 }
 const csv='\ufeff'+rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');download('answer_omr_drafts.csv',csv,'text/csv;charset=utf-8');notify('ส่งออกร่างและข้อรอตรวจแล้ว ไฟล์นี้แยกจากคำตอบที่คนตรวจ และใช้แทน ground truth ไม่ได้');
}
