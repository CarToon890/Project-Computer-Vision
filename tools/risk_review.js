// Review suggestions remain separate from confirmed labels until a person clicks.
let riskKeyboardActive=false,riskActiveKey='';
const riskCardElements=new Map();
function installRiskReview(){
 if(!DATA.risk_review)return;
 state.riskAudit=state.riskAudit||{};
 $('riskReview').classList.toggle('hidden',false);
 $('riskReviewFilter').onchange=()=>{riskActiveKey='';renderRiskReview()};
 $('focusRiskReview').onclick=()=>{riskKeyboardActive=true;renderRiskReview();revealRiskCard()};
 $('riskReviewRefresh').onclick=renderRiskReview;
 $('riskReviewExport').onclick=exportRiskAudit;
 $('riskReviewExportDrafts').onclick=exportRiskTrainDrafts;
 document.addEventListener('pointerdown',e=>{riskKeyboardActive=!!(e.target?.closest?.('#riskReviewCards')||e.target?.closest?.('#focusRiskReview'))});
 document.addEventListener('keydown',handleRiskKey);
 renderRiskReview();
}
function riskKeyTarget(){
 if(!DATA.risk_review||!riskKeyboardActive)return false;
 const active=document.activeElement,tag=active?.tagName;
 if(['INPUT','SELECT','TEXTAREA'].includes(tag)||active?.isContentEditable)return false;
 if(tag==='BUTTON'&&active.id!=='focusRiskReview')return false;
 return !active||tag==='BODY'||active.id==='focusRiskReview'||!!active.closest?.('#riskReviewCards');
}
function revealRiskCard(){riskCardElements.get(riskActiveKey)?.scrollIntoView?.({behavior:'smooth',block:'nearest'})}
function handleRiskKey(e){
 if(!riskKeyTarget()||e.altKey||e.ctrlKey||e.metaKey||e.repeat)return;
 const kind=$('riskReviewFilter').value||'risk',entries=riskPending(kind).slice(0,10),keys=entries.map(([key])=>key);
 if(!keys.length)return;
 if(!keys.includes(riskActiveKey))riskActiveKey=keys[0];
 const k=e.key.toLowerCase(),mark=({'b':'blank','m':'multiple','u':'ambiguous'})[k]||(['1','2','3','4','5'].includes(k)?k:null);
 if(mark){e.preventDefault();selectRiskAnswer(riskActiveKey,mark);revealRiskCard()}
 else if(k==='enter'){
  e.preventDefault();
  if(kind==='sample'){notify('คิวสุ่มซ่อนคำตอบโมเดล กรุณาเลือกคำตอบจากภาพด้วย 1–5, B, M หรือ U');return}
  const proposed=DATA.risk_review.items[riskActiveKey]?.proposal;
  if(!marks.has(proposed)){notify('ข้อนี้ไม่มีคำตอบ CNN ที่ยืนยันได้ กรุณาเลือกจากภาพ');return}
  selectRiskAnswer(riskActiveKey,proposed);revealRiskCard();
 }else if(['arrowdown','arrowright','arrowup','arrowleft'].includes(k)){
  e.preventDefault();const direction=['arrowup','arrowleft'].includes(k)?-1:1;
  riskActiveKey=keys[(keys.indexOf(riskActiveKey)+direction+keys.length)%keys.length];renderRiskReview();revealRiskCard();
 }else if(k==='escape'){riskKeyboardActive=false;e.preventDefault();$('riskReviewActive').textContent='ออกจากคีย์ลัดแล้ว'}
}
function riskPending(kind){
 return Object.entries(DATA.risk_review?.items||{}).filter(([key,item])=>{
  const [sheet,q]=key.split(':');
  if(!known.has(sheet)||isHeld(sheet)||humanVerified(sheet,Number(q)))return false;
  return kind==='sample'?!!item.audit_sample:kind==='risk'?item.group==='risk':item.group==='agreement'&&!item.audit_sample;
 }).sort((a,b)=>{const [sa,qa]=a[0].split(':'),[sb,qb]=b[0].split(':');return (kind==='risk'?(b[1].priority||0)-(a[1].priority||0):0)||sa.localeCompare(sb)||Number(qa)-Number(qb)});
}
function riskReasonText(reasons){
 const descriptions={pair_warning:'ภาพคู่มีสัญญาณขัดแย้ง',missing_reading:'มีภาพหรือผลอ่านไม่ครบ',
  special_or_uncertain:'อาจเว้นว่าง หลายช่อง หรือไม่ชัด',cnn_ab_disagree:'CNN อ่าน A/B ต่างกัน',
  cla_ab_disagree:'CLA อ่าน A/B ต่างกัน',methods_disagree:'CNN และ CLA อ่านต่างกัน',
  low_cnn_confidence:'CNN ไม่มั่นใจ',existing_review_flag:'ผลอ่านเดิมแจ้งว่าควรตรวจ'};
 return reasons.map(r=>descriptions[r]||r).join(' · ');
}
function selectRiskAnswer(key,mark){
 const item=DATA.risk_review?.items?.[key],parts=key.split(':'),sheet=parts[0],q=Number(parts[1]);
 if(!item||!known.has(sheet)||!Number.isInteger(q)||q<1||q>100||!marks.has(mark)||isHeld(sheet)||humanVerified(sheet,q))return;
 state.answers[key]=mark;recordHumanChoice(sheet,q,mark,'risk_review');state.reviewed[sheet]=false;
 if(item.audit_sample){state.riskAudit=state.riskAudit||{};state.riskAudit[key]={answer:mark,model_answer:item.proposal,method:DATA.risk_review.version,run_id:DATA.risk_review.run_id};}
 save();renderCounts();renderQuestion();renderRiskReview();
 notify('บันทึกว่าคุณตรวจ '+sheet+' ข้อ '+q+' แล้ว');
}
function renderRiskReview(){
 if(!DATA.risk_review)return;
 const kind=$('riskReviewFilter').value||'risk';
 const risk=riskPending('risk'),sample=riskPending('sample'),agreement=riskPending('agreement');
 const audited=validRiskAudits().map(([,value])=>value),matched=audited.filter(x=>x.answer===x.model_answer).length;
 $('riskReviewSummary').textContent='รอตรวจตามสัญญาณ '+risk.length.toLocaleString()+' ข้อ · คิวสุ่มที่เหลือ '+sample.length+'/'+DATA.risk_review.sample_size+' ข้อ · ผลสอดคล้องอื่น '+agreement.length.toLocaleString()+' ข้อ';
 $('riskReviewNote').textContent=kind==='sample'?'คิวสุ่มซ่อนคำตอบ CNN เพื่อให้ดูรอยฝนก่อนเลือก แต่อาจไม่เป็นอิสระหากคุณเคยเห็นร่างมาก่อน · ตอบแล้ว '+audited.length+' ข้อ · ตรงกับ CNN '+matched+' ข้อ':
  'แสดงครั้งละ 10 ข้อ กดคำตอบหลังดูภาพเท่านั้น · ถ้าคุณมีร่างอยู่แล้ว ระบบจะไม่เปลี่ยนจนกว่าคุณเลือกคำตอบ';
 const cardArea=$('riskReviewCards');cardArea.replaceChildren();
 const entries=riskPending(kind).slice(0,10);
 const keys=entries.map(([key])=>key);if(!keys.includes(riskActiveKey))riskActiveKey=keys[0]||'';
 riskCardElements.clear();$('riskReviewActive').textContent=riskKeyboardActive&&riskActiveKey?'คีย์ลัดเลือก '+riskActiveKey.replace(':',' ข้อ '):'';
 for(const [key,item] of entries){
  const [sheet,rawq]=key.split(':'),q=Number(rawq),form=sheets.find(s=>s.id===sheet),card=document.createElement('article');
  card.className='queue-card'+(riskKeyboardActive&&riskActiveKey===key?' risk-active':'');card.dataset.riskKey=key;riskCardElements.set(key,card);
  card.onclick=()=>{riskKeyboardActive=true;riskActiveKey=key;for(const [id,node] of riskCardElements)node.classList.toggle('risk-active',id===key);$('riskReviewActive').textContent='คีย์ลัดเลือก '+key.replace(':',' ข้อ ')};
  const title=document.createElement('strong');title.textContent=sheet+' · ข้อ '+q+(kind==='sample'?' · สุ่มตรวจ':'');card.append(title);
  if(kind!=='sample'){
   const why=document.createElement('p');why.textContent=riskReasonText(item.reasons)||'CNN และ CLA อ่านภาพ A/B สอดคล้องกัน';card.append(why);
   const old=value(sheet,q),info=document.createElement('p');info.className='risk-cnn-label';info.textContent='CNN เสนอ '+(item.proposal?textMark(item.proposal):'ไม่มีผลเสนอ')+(old?' · คำตอบร่างที่มีอยู่ '+textMark(old):' · ยังไม่มีคำตอบ');card.append(info);
  }
  for(const role of ['A','B']){
   const source=DATA.pilot?.sheets?.[sheet]?.[role];
   const label=document.createElement('p');label.textContent='ภาพ '+role;card.append(label);
   if(source?.sprite&&source.rows?.length===100){
    const frame=document.createElement('div');frame.className='queue-crop';
    const image=document.createElement('img');image.src=source.sprite;image.alt='ภาพ '+role+' ข้อ '+q;image.loading='lazy';image.style.top=(-(q-1)*100)+'%';frame.append(image);card.append(frame);
   }else{
    const unavailable=document.createElement('p');unavailable.textContent='ไม่มีภาพตัดรายข้อ กรุณาเปิดภาพเต็มก่อนเลือกคำตอบ';card.append(unavailable);
   }
   const link=document.createElement('a');link.href=form[role].url;link.target='_blank';link.rel='noopener';link.textContent='เปิดภาพเต็ม '+role;card.append(link);
  }
  const buttons=document.createElement('div');buttons.className='queue-answer-buttons';
  for(const mark of marks){const button=document.createElement('button');const suggested=kind!=='sample'&&mark===item.proposal;button.textContent=textMark(mark)+(suggested?' · CNN เสนอ':'');button.type='button';button.dataset.riskMark=mark;button.className=[mark.length>1?'queue-special':'',suggested?'risk-suggested':''].filter(Boolean).join(' ');button.setAttribute('aria-label',textMark(mark)+(suggested?' คำตอบที่ CNN เสนอ':''));button.onclick=e=>{e?.stopPropagation?.();selectRiskAnswer(key,mark)};buttons.append(button)}
  card.append(buttons);cardArea.append(card);
 }
 if(!entries.length){const empty=document.createElement('p');empty.textContent='ไม่มีข้อรอตรวจในคิวนี้';cardArea.append(empty)}
}
function validRiskAudits(){return Object.entries(state.riskAudit||{}).filter(([key,item])=>{
 const [sheet,q]=key.split(':');return item.run_id===DATA.risk_review.run_id&&DATA.risk_review.items[key]?.audit_sample&&humanVerified(sheet,Number(q))&&value(sheet,Number(q))===item.answer;
})}
function exportRiskAudit(){
 const entries=validRiskAudits();
 const rows=[['sheet_id','question_no','human_answer','cnn_answer','matches','queue_version','run_id','sample_method','independent_evaluation']];
 for(const [key,item] of entries){const [sheet,q]=key.split(':');rows.push([sheet,q,item.answer,item.model_answer,item.answer===item.model_answer?'1':'0',item.method,item.run_id,DATA.risk_review.sample_method,'false'])}
 const csv='\ufeff'+rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
 download('answer_risk_audit.csv',csv,'text/csv;charset=utf-8');notify('ส่งออกผลสุ่มตรวจแล้ว ผลนี้ไม่ใช่การทดสอบอิสระ');
}
function exportRiskTrainDrafts(){
 const rows=[['sheet_id','question_no','pseudo_label','status','reviewed_by_human','split','cnn_a','cnn_b','cla_a','cla_b','confidence_a','confidence_b','queue_version','run_id']];
 for(const [key,item] of Object.entries(DATA.risk_review.items)){
  const [sheet,q]=key.split(':');
  if(item.split!=='train'||item.group!=='agreement'||item.audit_sample||isHeld(sheet)||humanVerified(sheet,Number(q)))continue;
  rows.push([sheet,q,item.proposal,'machine_generated_not_verified','false',item.split,item.cnn_a,item.cnn_b,item.cla_a,item.cla_b,item.confidence_a,item.confidence_b,DATA.risk_review.version,DATA.risk_review.run_id]);
 }
 const csv='\ufeff'+rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
 download('answer_train_pseudo_labels.csv',csv,'text/csv;charset=utf-8');notify('ส่งออกร่าง Train '+(rows.length-1)+' ข้อ แยกจากคำตอบที่คนตรวจ และไม่นำข้อสุ่มตรวจมาใช้');
}
