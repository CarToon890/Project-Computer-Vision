"""Build a browser-based, human-reviewed A/B pairing interface."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data" / "metadata"
INVENTORY = META / "image_inventory.csv"
THUMBS = META / "review_thumbnails"
OUTPUT = META / "pair_review.html"
HEIF = shutil.which("heif-convert") or Path(
    r"C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\libheif\libheif\bin\heif-convert.exe"
)


def make_thumb(source: Path, destination: Path) -> None:
    if source.suffix.lower() in {".heic", ".heif"}:
        if not Path(HEIF).is_file():
            raise RuntimeError("heif-convert is required to preview HEIC files")
        with tempfile.TemporaryDirectory(prefix="omr-thumb-", dir=THUMBS) as folder:
            converted = Path(folder) / "image.jpg"
            subprocess.run([str(HEIF), str(source), str(converted)], check=True, capture_output=True)
            with Image.open(converted) as image:
                thumb = ImageOps.exif_transpose(image).convert("RGB")
                thumb.thumbnail((300, 420), Image.Resampling.LANCZOS)
                thumb.save(destination, "JPEG", quality=75, optimize=True)
        return
    with Image.open(source) as image:
        thumb = ImageOps.exif_transpose(image).convert("RGB")
        thumb.thumbnail((300, 420), Image.Resampling.LANCZOS)
        thumb.save(destination, "JPEG", quality=75, optimize=True)


def main() -> None:
    with INVENTORY.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    THUMBS.mkdir(parents=True, exist_ok=True)
    items = []
    for row in rows:
        source = ROOT / row["relative_path"]
        thumb_name = row["image_id"] + ".jpg"
        thumb = THUMBS / thumb_name
        if not thumb.exists() or thumb.stat().st_mtime < source.stat().st_mtime:
            make_thumb(source, thumb)
        item = dict(row)
        item["thumbnail"] = "review_thumbnails/" + thumb_name
        item["source_url"] = "../../" + "/".join(quote(part) for part in Path(row["relative_path"]).parts)
        items.append(item)

    data = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    html = r'''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ตรวจคู่ภาพ OMR</title><style>
body{font-family:Segoe UI,Tahoma,sans-serif;margin:0;background:#f2f5f7;color:#17212b}header{position:sticky;top:0;background:#fff;padding:12px 18px;border-bottom:1px solid #ccd4db;z-index:2}h1{font-size:20px;margin:0 0 6px}p{margin:4px 0 10px}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}select,input,button{font:inherit;padding:7px 9px;border:1px solid #aab4be;border-radius:5px;background:white}button{cursor:pointer}.primary{background:#174a6e;color:white}.content{display:grid;grid-template-columns:minmax(0,1fr) 350px;gap:12px;padding:12px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:8px;align-content:start}.card{background:white;border:2px solid transparent;border-radius:7px;padding:7px}.card.a{border-color:#2563eb}.card.b{border-color:#ea580c}.card.paired{opacity:.38}.card img{width:100%;height:190px;object-fit:contain;background:#e8edf1}.filename{font-size:11px;word-break:break-all;margin:4px 0}.meta{font-size:10px;color:#52606d}.buttons{display:flex;gap:5px}.buttons button{flex:1;font-size:12px;padding:5px}.side{position:sticky;top:130px;align-self:start;background:#fff;border-radius:7px;padding:10px;max-height:calc(100vh - 150px);overflow:auto}.side h2{font-size:15px}.pair{border-top:1px solid #ddd;padding:7px 0;font-size:11px}.pair img{width:48%;height:80px;object-fit:contain}.imgs{display:flex;justify-content:space-between}.warn{color:#9a3412}.hidden{display:none}
</style><body><header><h1>ตรวจและจับคู่ภาพ A/B</h1><p>เลือกรูป A และ B ของกระดาษแผ่นเดียวกัน ตรวจว่าคำตอบ 100 ข้อตรงกันก่อนยืนยัน ห้ามอาศัยลำดับไฟล์อย่างเดียว</p><div class="toolbar"><label>ผู้ถ่าย <select id="who"></select></label><label>แสดง <select id="show"><option value="open">ยังไม่จับคู่</option><option value="all">ทั้งหมด</option></select></label><input id="q" placeholder="ค้นหาชื่อไฟล์"><button id="clear">ล้างการเลือก</button><button id="confirm" class="primary">ยืนยันคู่ A/B</button><button id="export" class="primary">ส่งออก pair_decisions.csv</button><button id="save">บันทึกสำรอง JSON</button><button id="restore">กู้คืน JSON</button><input id="restoreFile" type="file" accept="application/json" hidden><span id="status"></span></div><div id="selected" class="warn"></div></header>
<div class="content"><main id="grid" class="grid"></main><aside class="side"><h2>คู่ที่ยืนยันในเครื่องนี้</h2><div id="pairs"></div></aside></div>
<script>
const images=__DATA__,key='omr-pair-review-v1';let state=JSON.parse(localStorage.getItem(key)||'{"pairs":[],"next":1}'),selA=null,selB=null;
const $=id=>document.getElementById(id), contributors=[...new Set(images.map(x=>x.contributor_id))].sort();
for(const c of contributors){let o=document.createElement('option');o.value=c;o.textContent=c;$('who').append(o)}
const paired=id=>state.pairs.find(p=>p.image_a_id===id||p.image_b_id===id);
function draw(){let c=$('who').value,q=$('q').value.toLowerCase(),all=$('show').value==='all';let list=images.filter(x=>x.contributor_id===c&&(all||!paired(x.image_id))&&(`${x.file_name} ${x.image_id}`.toLowerCase().includes(q)));
$('grid').innerHTML=list.map(x=>`<article class="card ${x.image_id===selA?'a':x.image_id===selB?'b':''} ${paired(x.image_id)?'paired':''}"><a href="${x.source_url}" target="_blank"><img loading="lazy" src="${x.thumbnail}"></a><div class="filename">${x.file_name}</div><div class="meta">โฟลเดอร์: ${x.capture_role} · ${x.captured_at||'ไม่มีเวลา EXIF'}<br>${x.image_id}</div><div class="buttons"><button onclick="pick('${x.image_id}','A')">เลือก A</button><button onclick="pick('${x.image_id}','B')">เลือก B</button></div></article>`).join('');
let a=images.find(x=>x.image_id===selA),b=images.find(x=>x.image_id===selB);$('selected').textContent=(a||b)?`A: ${a?.file_name||'ยังไม่เลือก'} | B: ${b?.file_name||'ยังไม่เลือก'} — ต้องเป็นกระดาษแผ่นเดียวกัน`:'';
$('status').textContent=`ภาพ ${list.length} · ยืนยันแล้ว ${state.pairs.length} คู่`;
$('pairs').innerHTML=state.pairs.map(p=>{let a=images.find(x=>x.image_id===p.image_a_id),b=images.find(x=>x.image_id===p.image_b_id);return `<div class="pair"><b>${p.sheet_id}</b> <button onclick="removePair('${p.sheet_id}')">ยกเลิก</button><div class="imgs"><img src="${a.thumbnail}"><img src="${b.thumbnail}"></div>${a.file_name}<br>${b.file_name}</div>`}).join('')||'<p>ยังไม่มีคู่ที่ยืนยัน</p>';localStorage.setItem(key,JSON.stringify(state))}
function pick(id,role){if(paired(id)){alert('ภาพนี้ถูกจับคู่แล้ว');return}let x=images.find(i=>i.image_id===id),other=images.find(i=>i.image_id===(role==='A'?selB:selA));if(x.capture_role&&x.capture_role!==role){alert(`โฟลเดอร์ระบุภาพนี้เป็น ${x.capture_role}; เลือกบทบาท ${x.capture_role} ให้ภาพนี้`);return}if(other&&other.contributor_id!==x.contributor_id){alert('จับคู่ได้เฉพาะภาพจากผู้ถ่ายคนเดียวกัน');return}if(role==='A')selA=id;else selB=id;draw()}
function confirmPair(){if(!selA||!selB||selA===selB){alert('เลือกภาพ A และภาพ B คนละไฟล์ก่อน');return}let a=images.find(x=>x.image_id===selA),b=images.find(x=>x.image_id===selB);if(a.contributor_id!==b.contributor_id){alert('ผู้ถ่ายไม่ตรงกัน');return}let n=state.next++;state.pairs.push({sheet_id:'S'+String(n).padStart(4,'0'),image_a_id:selA,image_b_id:selB,contributor_id:a.contributor_id,pair_status:'verified'});selA=null;selB=null;draw()}
function removePair(id){state.pairs=state.pairs.filter(p=>p.sheet_id!==id);draw()}
function csv(rows){return rows.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n')}
function download(name,data,type){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([data],{type}));a.download=name;a.click();URL.revokeObjectURL(a.href)}
function exportCsv(){let h=['sheet_id','image_a_id','image_b_id','contributor_id','pair_status'];download('pair_decisions.csv',csv([h,...state.pairs.map(p=>h.map(k=>p[k]))]),'text/csv;charset=utf-8')}
function saveJson(){download('pair_review_progress.json',JSON.stringify(state,null,2),'application/json')}
function restoreJson(file){let reader=new FileReader();reader.onload=()=>{try{let value=JSON.parse(reader.result);if(!Array.isArray(value.pairs)||!Number.isInteger(value.next))throw new Error('รูปแบบไฟล์ไม่ถูกต้อง');let ids=new Set(images.map(x=>x.image_id)),used=new Set(),sheets=new Set();for(let p of value.pairs){if(!ids.has(p.image_a_id)||!ids.has(p.image_b_id)||p.image_a_id===p.image_b_id||!p.sheet_id||sheets.has(p.sheet_id)||used.has(p.image_a_id)||used.has(p.image_b_id))throw new Error('พบคู่ซ้ำหรือ image_id ที่ไม่มีในชุดนี้');let a=images.find(x=>x.image_id===p.image_a_id),b=images.find(x=>x.image_id===p.image_b_id);if(a.contributor_id!==b.contributor_id||a.contributor_id!==p.contributor_id)throw new Error('พบคู่ข้ามผู้ถ่าย');if((a.capture_role&&a.capture_role!=='A')||(b.capture_role&&b.capture_role!=='B'))throw new Error('บทบาท A/B ไม่ตรงกับโฟลเดอร์');used.add(p.image_a_id);used.add(p.image_b_id);sheets.add(p.sheet_id)}state=value;draw();alert(`กู้คืนแล้ว ${state.pairs.length} คู่`)}catch(e){alert('กู้คืนไม่สำเร็จ: '+e.message)}};reader.readAsText(file)}
function clear(){selA=null;selB=null;draw()}
window.pick=pick;window.removePair=removePair;$('who').onchange=draw;$('show').onchange=draw;$('q').oninput=draw;$('clear').onclick=clear;$('confirm').onclick=confirmPair;$('export').onclick=exportCsv;$('save').onclick=saveJson;$('restore').onclick=()=>$('restoreFile').click();$('restoreFile').onchange=e=>{if(e.target.files[0])restoreJson(e.target.files[0])};draw();
</script></body></html>'''.replace("__DATA__", data)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Created {OUTPUT.relative_to(ROOT)} with {len(items)} images")
    print(f"Created thumbnails under {THUMBS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

