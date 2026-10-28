import test from 'node:test';
import assert from 'node:assert/strict';
import {riskScore,exportCsv} from '../lib/scoring.mjs';
const make=()=>Array.from({length:100},(_,i)=>({question_no:i+1,proposed_answer:'1',needs_review:false}));
const grade={key:Array(100).fill('1'),name:'exam',rules:{full:50,penalty:1},policy:'risk-reviewed-v1'};
test('counts risk, blanks and multiple marks and bounds provisional scores',()=>{
  const rows=make();rows[0].needs_review=true;rows[1].proposed_answer='blank';rows[2].proposed_answer='multiple';
  const result={methods:{cnn:rows,cla:rows}}, r=riskScore(result,{},grade).cnn;
  assert.deepEqual([r.correct,r.incorrect,r.blank,r.unresolved],[97,1,1,1]);
  assert.equal(r.min,46.5);assert.equal(r.max,48);assert.equal(r.ready,false);
  const checked=riskScore(result,{cnn:{1:{answer:'1'}}},grade).cnn;
  assert.equal(checked.ready,true);assert.equal(checked.raw,48);
  assert.match(exportCsv({result,reviews:{},grading:grade}),/"score_min"/);
});
test('negative score retains raw value and displayed score is capped at zero',()=>{
  const rows=make().map(r=>({...r,proposed_answer:'2'}));
  const r=riskScore({methods:{cnn:rows,cla:rows}},{},grade).cnn;
  assert.equal(r.raw,-100);assert.equal(r.min,0);assert.equal(r.max,0);assert.equal(r.ready,true);
});
test('missing rows or ambiguous marks are always unresolved',()=>{
 const rows=make().slice(0,99);rows[0].proposed_answer='ambiguous';
 const r=riskScore({methods:{cnn:rows,cla:rows}},{},grade).cnn;
 assert.equal(r.unresolved,2);assert.equal(r.ready,false);
});
