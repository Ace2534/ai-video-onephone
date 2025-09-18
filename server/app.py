# === server/app.py ===
import os, uuid, re
from pathlib import Path
from typing import List, Dict
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, concatenate_videoclips

DATA_DIR = Path(os.getenv("STORE_DIR", "/app/data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

app = FastAPI(title="One-Phone Video Bot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def split_script(script: str):
    parts = [s.strip() for s in re.split(r"[。！？!?，,\n]+", script) if s.strip()]
    return parts[:8] or ["你好，這是示範影片。"]

def captions_from_script(script: str, total:int=15):
    lines = split_script(script)
    total = max(5, min(30, total)); per = max(1.0, total/max(1,len(lines)))
    caps, t = [], 0.0
    for line in lines:
        start, end = t, min(total, t+per)
        caps.append({"text": line, "start": start, "end": end}); t = end
    return caps

W,H = 1080,1920
def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for ch in list(text):
        test = line + ch; w,_ = draw.textsize(test, font=font)
        if w <= max_w: line = test
        else: lines.append(line); line = ch
    if line: lines.append(line); return lines

def _frame(text:str, bg=(12,12,16)):
    img = Image.new("RGB",(W,H),bg); draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except: font = ImageFont.load_default()
    lines = _wrap(draw, text, font, W-160); y = int(H*0.75) - (len(lines)*80)//2
    for ln in lines:
        w,h = draw.textsize(ln, font=font); x=(W-w)//2
        draw.text((x+2,y+2), ln, font=font, fill=(0,0,0))
        draw.text((x,y),     ln, font=font, fill=(255,255,255)); y += 80
    return img

def render_video(captions, out_path, duration:int=15, bg=(12,12,16)):
    clips=[]; tmpdir = Path(out_path).with_suffix("").parent; tmpdir.mkdir(parents=True, exist_ok=True)
    for c in captions:
        p = tmpdir / f"_frame_{int(c['start']*100)}.jpg"; _frame(c["text"], bg).save(p)
        clips.append(ImageClip(str(p)).set_duration(max(0.8, c["end"]-c["start"])))
    concatenate_videoclips(clips, method="compose").resize((W,H))\
        .write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac")

JOBS = {}
def public_url(job_id): return f"/files/{job_id}.mp4"
def out_path(job_id):   return str(DATA_DIR / f"{job_id}.mp4")

@app.post("/v1/videos")
async def create_video(req: Request):
    body = await req.json()
    script  = (body.get("script") or "你好，這是示範影片。").strip()
    seconds = int(body.get("duration") or 15)
    job_id  = uuid.uuid4().hex
    JOBS[job_id] = {"status":"running","progress":0.1}
    try:
        caps = captions_from_script(script, seconds)
        render_video(caps, out_path(job_id), seconds)
        JOBS[job_id] = {"status":"done","progress":1.0,"url": public_url(job_id)}
    except Exception as e:
        JOBS[job_id] = {"status":"failed","progress":1.0,"message": str(e)}
    return {"job_id": job_id}

@app.get("/v1/videos/{job_id}")
async def get_status(job_id: str):
    st = JOBS.get(job_id)
    if not st: return JSONResponse(status_code=404, content={"detail":"not found"})
    return st

@app.get("/files/{name}")
async def files(name: str):
    p = DATA_DIR / name
    if not p.exists(): return JSONResponse(status_code=404, content={"detail":"not found"})
    return FileResponse(str(p))

@app.get("/")
async def root(): return {"ok": True, "hint": "POST /v1/videos"}
