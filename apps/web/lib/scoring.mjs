export const ANSWERS = ['1','2','3','4','5','blank','multiple'];
export function score(result, reviews, key) {
  const completeKey = Array.isArray(key) && key.length === 100 && key.every(x => /^[1-5]$/.test(x));
  const methods = {};
  for (const method of ['cnn','cla']) {
    let automatic = 0, current = 0, confirmed = 0, confirmedCorrect = 0;
    const rows = result?.methods?.[method] || [];
    for (const row of rows) {
      const human = reviews?.[method]?.[row.question_no]?.answer;
      const expected = key?.[row.question_no-1];
      if (expected && row.proposed_answer === expected) automatic++;
      if (human && ANSWERS.includes(human)) { confirmed++; if (human === expected) confirmedCorrect++; }
      if (expected && (human || row.proposed_answer) === expected) current++;
    }
    methods[method] = {automatic, current, confirmed, confirmedCorrect, total:100,
      final: completeKey && confirmed === 100, completeKey};
  }
  return methods;
}
export function exportCsv(job) {
  const key = job.grading?.key || [];
  const escape = v => '"' + String(v ?? '').replaceAll('"','""') + '"';
  const rows = [['question','exam_key','cnn_model','cla_model','cnn_human','cla_human','cnn_needs_review','cla_needs_review','cnn_model_correct','cnn_human_correct','cla_model_correct','cla_human_correct','score_status','cla_score_status','key_name','score_full','penalty_per_wrong','score_min','score_max','score_raw']];
  const scores = score(job.result, job.reviews, key);
  const risk = job.grading?.policy === 'risk-reviewed-v1' ? riskScore(job.result,job.reviews,job.grading) : null;
  for (let i=0;i<100;i++) {
    const a = job.result?.methods?.cnn?.[i], b = job.result?.methods?.cla?.[i];
    const ca = job.reviews?.cnn?.[i+1]?.answer, cb = job.reviews?.cla?.[i+1]?.answer;
    rows.push([i+1,key[i],a?.proposed_answer,b?.proposed_answer,ca,cb,a?.needs_review,b?.needs_review,
      key[i] ? a?.proposed_answer === key[i] : '', key[i] && ca ? ca === key[i] : '',
      key[i] ? b?.proposed_answer === key[i] : '', key[i] && cb ? cb === key[i] : '',
      risk ? (risk.cnn.ready ? 'risk_reviewed' : 'provisional') : scores.cnn.final ? 'human_confirmed' : 'provisional', risk ? (risk.cla.ready ? 'risk_reviewed' : 'provisional') : scores.cla.final ? 'human_confirmed' : 'provisional', job.grading?.name,job.grading?.rules?.full,job.grading?.rules?.penalty,risk?.cnn.min,risk?.cnn.max,risk?.cnn.raw]);
  }
  return '\ufeff' + rows.map(row => row.map(escape).join(',')).join('\r\n');
}
export function riskScore(result, reviews, grading) {
  const key=grading?.key, rules=grading?.rules;
  const completeKey=Array.isArray(key) && key.length===100 && key.every(x=>typeof x==='string' && /^[1-5]$/.test(x));
  const valid=completeKey && rules && Number.isFinite(rules.full) && rules.full>0 && Number.isFinite(rules.penalty) && rules.penalty>=0;
  const methods={};
  for(const method of ['cnn','cla']) {
    const rows=result?.methods?.[method] || [], byQuestion=new Map(rows.map(r=>[r.question_no,r]));
    let correct=0, incorrect=0, blank=0, unresolved=0, confirmed=0;
    for(let q=1;q<=100;q++) {
      const row=byQuestion.get(q), human=reviews?.[method]?.[q]?.answer;
      if(human && ANSWERS.includes(human)) confirmed++;
      const answer=human || row?.proposed_answer;
      if(!row || (!human && row.needs_review) || !ANSWERS.includes(answer)) {unresolved++;continue;}
      if(answer==='blank') blank++;
      else if(answer===key?.[q-1]) correct++;
      else incorrect++;
    }
    const raw=valid?correct*rules.full/100-incorrect*rules.penalty:null;
    const rawMin=valid?raw-unresolved*rules.penalty:null;
    const rawMax=valid?raw+unresolved*rules.full/100:null;
    methods[method]={completeKey:!!completeKey,correct,incorrect,blank,unresolved,confirmed,total:100,
      ready:!!valid && unresolved===0, raw, rawMin, rawMax, min:valid?Math.max(0,rawMin):null, max:valid?Math.max(0,rawMax):null, full:rules?.full};
  }
  return methods;
}
