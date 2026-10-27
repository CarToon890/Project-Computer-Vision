import test from 'node:test';
import assert from 'node:assert/strict';
import {hashPassword,verifyPassword} from '../lib/password.mjs';
import {score,exportCsv} from '../lib/scoring.mjs';
test('scrypt hashes are salted and reject incorrect passwords',()=>{
  const value=hashPassword('local-test-password-123');
  assert.equal(verifyPassword('local-test-password-123',value),true);
  assert.equal(verifyPassword('incorrect',value),false);
  assert.notEqual(value,hashPassword('local-test-password-123'));
  assert.equal(verifyPassword('anything','bad hash'),false);
});
const rows=Array.from({length:100},(_,i)=>({question_no:i+1,proposed_answer:'1',needs_review:false}));
const result={methods:{cnn:rows,cla:rows}};
test('an automatic 100/100 is still provisional until every answer is confirmed',()=>{
  const key=Array(100).fill('1'), reviews={cnn:{},cla:{}};
  assert.equal(score(result,reviews,key).cnn.final,false);
  for(let i=1;i<=100;i++)reviews.cnn[i]={answer:'1'};
  assert.equal(score(result,reviews,key).cnn.final,true);
  assert.equal(score(result,reviews,[...key.slice(0,99),null]).cnn.final,false);
});
test('human correction is separate from the immutable model and CSV preserves both',()=>{
  const key=Array(100).fill('1'), reviews={cnn:{1:{answer:'blank'}},cla:{}};
  const scores=score(result,reviews,key);
  assert.equal(scores.cnn.automatic,100);assert.equal(scores.cnn.current,99);
  assert.equal(scores.cnn.confirmed,1);assert.equal(scores.cnn.final,false);
  assert.equal(result.methods.cnn[0].proposed_answer,'1');
  const csv=exportCsv({result,reviews,grading:{key}});
  assert.match(csv, /"cnn_model"/);assert.match(csv, /"blank"/);assert.match(csv, /"provisional"/);
});
