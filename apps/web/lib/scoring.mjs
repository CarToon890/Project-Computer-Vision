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
  const rows = [['question','exam_key','cnn_model','cla_model','cnn_human','cla_human','cnn_needs_review','cla_needs_review','cnn_model_correct','cnn_human_correct','cla_model_correct','cla_human_correct','score_status','cla_score_status']];
  const scores = score(job.result, job.reviews, key);
  for (let i=0;i<100;i++) {
    const a = job.result?.methods?.cnn?.[i], b = job.result?.methods?.cla?.[i];
    const ca = job.reviews?.cnn?.[i+1]?.answer, cb = job.reviews?.cla?.[i+1]?.answer;
    rows.push([i+1,key[i],a?.proposed_answer,b?.proposed_answer,ca,cb,a?.needs_review,b?.needs_review,
      key[i] ? a?.proposed_answer === key[i] : '', key[i] && ca ? ca === key[i] : '',
      key[i] ? b?.proposed_answer === key[i] : '', key[i] && cb ? cb === key[i] : '',
      scores.cnn.final ? 'human_confirmed' : 'provisional',scores.cla.final ? 'human_confirmed' : 'provisional']);
  }
  return '\ufeff' + rows.map(row => row.map(escape).join(',')).join('\r\n');
}
