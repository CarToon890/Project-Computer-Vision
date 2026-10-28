"""Measure local inference of reviewed A/B pairs without changing labels or models."""
import argparse, csv, json, sys, time, tempfile, statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import torch
import omr_inference as inf
from omr_model import load_trained_model
from omr_runtime import build_methods

IDS=['S0009','S0011','S0012','S0014','S0016','S0020','S0026','S0035','S0037','S0001']

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists(): raise SystemExit('Existing report preserved; choose a new output path.')
    with (ROOT/'data/metadata/image_inventory_verified.csv').open(encoding='utf-8-sig',newline='') as f:
        images={(r['sheet_id'],r['capture_role']):ROOT/r['relative_path'] for r in csv.DictReader(f) if r['pair_status']=='verified'}
    with (ROOT/'data/metadata/heic_conversion_map.csv').open(encoding='utf-8-sig',newline='') as f:
        mapping={r['source_relative_path']:r['normalized_relative_path'] for r in csv.DictReader(f)}
    config=json.loads((ROOT/'models/retrained_v3_verified/model_config.json').read_text())
    torch.set_num_threads(2);start=time.perf_counter();model,device=load_trained_model(ROOT/'models/retrained_v3_verified/row_cnn.pt','cpu',config['weights_sha256']);load=time.perf_counter()-start
    timings={}; originals={}
    for name in ('read_image','rectify_sheet','row_crop','predict_cnn','bubble_scores','display_row'):
        original=getattr(inf,name);originals[name]=original
        def wrap(*args,_fn=original,_name=name,**kwargs):
            t=time.perf_counter()
            try:return _fn(*args,**kwargs)
            finally:timings[_name]=timings.get(_name,0)+time.perf_counter()-t
        setattr(inf,name,wrap)
    cases=[]
    with tempfile.TemporaryDirectory(prefix='omr-benchmark-') as tmp:
      for sid in IDS:
        captures={}
        for role in ('A','B'):
          timings.clear();start=time.perf_counter()
          try:
            captures[role]=inf.read_role(model,device,images[(sid,role)],ROOT,mapping,Path(tmp),sid,role)
            cases.append({'sheet_id':sid,'role':role,'total_s':time.perf_counter()-start,'stages':dict(timings),'predictions':captures[role]['predictions'],'confidence':captures[role]['confidence'],'cla_scores':captures[role]['cla_scores']})
          except Exception as e:
            cases.append({'sheet_id':sid,'role':role,'error':type(e).__name__})
          print(sid,role,round(time.perf_counter()-start,2),flush=True)
        if len(captures)==2:
          methods,pair=build_methods(captures['A'],captures['B'],config,sid)
          cases.append({'sheet_id':sid,'role':'A+B','pair_check':pair,'methods':methods})
    valid=[r for r in cases if 'total_s' in r]
    report={'model_load_seconds':load,'cases':cases,'median_image_seconds':statistics.median(r['total_s'] for r in valid) if valid else None,'stage_medians':{k:statistics.median(r['stages'].get(k,0) for r in valid) for k in originals}}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('median',report['median_image_seconds'],flush=True)
if __name__=='__main__':main()
