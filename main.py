import os
import base64
import hashlib
from typing import List

import pypdfium2 as pdfium
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        from database import db  # type: ignore

        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:  # noqa: BLE001
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:  # noqa: BLE001
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


def _png_base64_from_pdf(pdf_bytes: bytes, dpi: int = 180) -> List[str]:
    """Render PDF pages to PNG data URLs using pypdfium2."""
    pdf = pdfium.PdfDocument(pdf_bytes)
    images: List[str] = []
    scale = dpi / 72.0  # 72pt == 1 inch
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale, rotation=0)
        pil_image = bitmap.to_pil()
        from io import BytesIO
        bio = BytesIO()
        pil_image.save(bio, format="PNG")
        data = bio.getvalue()
        images.append("data:image/png;base64," + base64.b64encode(data).decode("ascii"))
        page.close()
    pdf.close()
    return images


def _build_single_file_html(images: List[str], title: str, password_hash_hex: str) -> str:
    images_js = "[" + ",".join([f'"{img}"' for img in images]) + "]"
    html = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\" />
  <title>%%TITLE%%</title>
  <style>
    :root {
      --page-width: min(92vw, 520px);
      --page-ratio: 1.4142; /* A-series portrait ratio (sqrt(2)) */
      --page-height: calc(var(--page-width) * var(--page-ratio));
      --bg: #0b0b0f;
    }
    html, body { height: 100%; margin: 0; background: var(--bg); color: #fff; }
    body {
      -webkit-user-select: none; user-select: none; -webkit-touch-callout: none;
      overscroll-behavior: contain; touch-action: pan-y;
    }
    @media print { body { display: none !important; } }

    .wrap { height: 100%; width: 100%; display: grid; place-items: center; }
    .stage { position: relative; width: var(--page-width); height: var(--page-height);
      box-shadow: 0 30px 80px rgba(0,0,0,.6); border-radius: 8px; background: #111;
      perspective: 1600px; -webkit-tap-highlight-color: transparent; }
    canvas { position: absolute; inset: 0; width: 100%; height: 100%; }

    .lock { position: fixed; inset: 0; display: grid; place-items: center; background: rgba(10,10,14,.9); backdrop-filter: blur(6px); }
    .panel { width: min(92vw, 420px); background: #151521; border: 1px solid #2a2a3b; border-radius: 12px; padding: 20px; box-shadow: 0 20px 60px rgba(0,0,0,.55); }
    .panel h1 { margin: 0 0 10px; font: 600 18px/1.3 system-ui, -apple-system, Segoe UI, Roboto; }
    .panel p { margin: 0 0 14px; color: #c9c9d2; font: 400 14px/1.45 system-ui; }
    .row { display: flex; gap: 10px; }
    input[type=password] { flex: 1; background: #0f0f16; color: #fff; border: 1px solid #2c2c3a; border-radius: 10px; padding: 12px 14px; font-size: 14px; outline: none; }
    button { background: #5b7cfa; color: white; border: 0; border-radius: 10px; padding: 12px 16px; font-weight: 600; cursor: pointer; }
    .err { color: #ff6b6b; font-size: 13px; min-height: 18px; margin-top: 8px; }

    .edge-hint { position: absolute; top: 0; bottom: 0; width: 18px; opacity: .35; pointer-events: none; }
    .edge-left { left: 0; background: linear-gradient(90deg, rgba(255,255,255,.08), transparent); }
    .edge-right { right: 0; background: linear-gradient(270deg, rgba(255,255,255,.08), transparent); }
  </style>
</head>
<body>
<div class=\"wrap\"> <div class=\"stage\" id=\"stage\"> <canvas id=\"flip\"></canvas>
  <div class=\"edge-hint edge-left\"></div><div class=\"edge-hint edge-right\"></div> </div></div>
<div class=\"lock\" id=\"lock\"><div class=\"panel\"><h1>Protected Flipbook</h1>
  <p>Enter password to view. Copying and printing are disabled.</p>
  <div class=\"row\"><input id=\"pw\" type=\"password\" placeholder=\"Password\" autocomplete=\"off\" />
  <button id=\"unlockBtn\">Unlock</button></div>
  <div class=\"err\" id=\"err\"></div></div></div>
<script>
  document.addEventListener('contextmenu', e => e.preventDefault());
  document.addEventListener('copy', e => e.preventDefault());
  document.addEventListener('keydown', e => { const k = e.key.toLowerCase(); if ((e.ctrlKey||e.metaKey) && (k==='p'||k==='s'||k==='c')) e.preventDefault(); if (k==='printscreen') e.preventDefault(); });

  const IMAGES = %%IMAGES%%;
  const PASSWORD_HASH_HEX = '%%PASSWORD_HASH_HEX%%';
  async function sha256Hex(str) { const buf = new TextEncoder().encode(str); const hash = await crypto.subtle.digest('SHA-256', buf); return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join(''); }

  const lockEl = document.getElementById('lock');
  const errEl = document.getElementById('err');
  const pwEl = document.getElementById('pw');
  document.getElementById('unlockBtn').addEventListener('click', async ()=>{ const ok = (await sha256Hex(pwEl.value)) === PASSWORD_HASH_HEX; if (ok) { lockEl.style.display='none'; initFlip(); } else { errEl.textContent = 'Incorrect password'; } });
  pwEl.addEventListener('keydown', e=>{ if(e.key==='Enter') document.getElementById('unlockBtn').click(); });

  let page = 0, dragging = false, dragX = 0, startX = 0; let width, height, dpi, ctx, canvas; const EDGE_ZONE = 28;
  function devicePixelRatioSafe(){ return Math.min(window.devicePixelRatio||1, 2); }
  function resize(){ const stage=document.getElementById('stage'); width=stage.clientWidth; height=stage.clientHeight; dpi=devicePixelRatioSafe(); canvas=document.getElementById('flip'); canvas.width=Math.floor(width*dpi); canvas.height=Math.floor(height*dpi); ctx=canvas.getContext('2d'); ctx.setTransform(dpi,0,0,dpi,0,0); render(0);} 
  function clamp(v,min,max){ return Math.max(min, Math.min(max, v)); }
  const cache=new Map(); function getImg(i){ if(!cache.has(i)){ const im=new Image(); im.src=IMAGES[i]; cache.set(i,im);} return cache.get(i);} 
  function drawPage(img){ ctx.drawImage(img,0,0,width,height);} 
  function drawShadow(x,intensity){ const grd=ctx.createLinearGradient(x-60,0,x+60,0); grd.addColorStop(0,`rgba(0,0,0,${0.0})`); grd.addColorStop(0.5,`rgba(0,0,0,${intensity})`); grd.addColorStop(1,`rgba(0,0,0,${0.0})`); ctx.fillStyle=grd; ctx.fillRect(x-60,0,120,height);} 
  function drawFold(imgFront,imgBack,t,dir){ const fold=(1-Math.cos(t*Math.PI))*0.92; const foldX=dir===1?width - fold*width: fold*width; const ctrlOff=0.18*width*(0.6+0.4*(1-t)); ctx.save(); drawPage(imgBack); ctx.restore(); ctx.save(); ctx.beginPath(); ctx.moveTo(0,0); ctx.lineTo(dir===1?foldX:width,0); ctx.quadraticCurveTo(dir===1?foldX-ctrlOff:foldX+ctrlOff,height*0.5,dir===1?foldX:width,height); ctx.lineTo(0,height); ctx.closePath(); ctx.clip(); drawPage(imgFront); ctx.restore(); drawShadow(foldX,0.35*(0.3+0.7*t)); const curlWidth=Math.max(18,0.14*width*(1-t+0.2)); const curlX=dir===1?foldX - curlWidth*0.5: foldX + curlWidth*0.5; const grd2=ctx.createLinearGradient(dir===1?curlX-curlWidth:curlX,0, dir===1?curlX:curlX+curlWidth,0); grd2.addColorStop(0,'rgba(255,255,255,0.18)'); grd2.addColorStop(1,'rgba(0,0,0,0.28)'); ctx.fillStyle=grd2; ctx.globalCompositeOperation='multiply'; ctx.fillRect(Math.min(curlX-curlWidth,curlX),0,curlWidth,height); ctx.globalCompositeOperation='source-over'; }
  function render(){ ctx.clearRect(0,0,width,height); const cur=getImg(page); const next=getImg(clamp(page+1,0,IMAGES.length-1)); const prev=getImg(clamp(page-1,0,IMAGES.length-1)); if(!dragging){ drawPage(cur); return;} const dir=dragX < startX ? 1:-1; const dist=Math.abs(dragX-startX); const t=clamp(dist/(width*0.9),0,1); if(dir===1 && page < IMAGES.length-1){ drawFold(cur,next,t,1);} else if(dir===-1 && page>0){ drawFold(cur,prev,t,-1);} else { drawPage(cur);} }
  function animateTo(targetPage,dir){ const steps=38; let k=0; function step(){ const t=k/steps; ctx.clearRect(0,0,width,height); const cur=getImg(page); const other=getImg(targetPage); drawFold(cur,other,t,dir); k++; if(k<=steps) requestAnimationFrame(step); else { page=targetPage; dragging=false; render(); } } requestAnimationFrame(step);} 
  function onPointerDown(x){ const leftEdge=x<EDGE_ZONE; const rightEdge=x>(width-EDGE_ZONE); if(leftEdge && page>0){ dragging=true; startX=x; dragX=x+0.01; } else if(rightEdge && page<IMAGES.length-1){ dragging=true; startX=x; dragX=x-0.01; } }
  function onPointerMove(x){ if(dragging){ dragX=x; render(); } }
  function onPointerUp(){ if(!dragging) return; const dir=dragX < startX ? 1:-1; const dist=Math.abs(dragX-startX); const commit=dist>width*0.22; if(commit){ const target=page+(dir===1?1:-1); animateTo(target,dir);} else { dragging=false; render(); } }
  function initFlip(){ resize(); window.addEventListener('resize',resize); const stage=document.getElementById('stage'); const rect=()=>stage.getBoundingClientRect(); stage.addEventListener('pointerdown',e=>{ onPointerDown(e.clientX-rect().left); }); stage.addEventListener('pointermove',e=>{ onPointerMove(e.clientX-rect().left); }); window.addEventListener('pointerup',()=>{ onPointerUp(); }); stage.addEventListener('touchstart',e=>{ if(e.touches[0]) onPointerDown(e.touches[0].clientX-rect().left); },{passive:true}); stage.addEventListener('touchmove',e=>{ if(e.touches[0]) onPointerMove(e.touches[0].clientX-rect().left); },{passive:true}); stage.addEventListener('touchend',()=>{ onPointerUp(); }); }
</script>
</body>
</html>
"""
    # Replace placeholders
    html = html.replace("%%TITLE%%", title)
    html = html.replace("%%IMAGES%%", images_js)
    html = html.replace("%%PASSWORD_HASH_HEX%%", password_hash_hex)
    return html


@app.post("/convert")
async def convert_pdf(
    pdf: UploadFile = File(...),
    password: str = Form(...),
    title: str = Form("Flipbook"),
    dpi: int = Form(180),
):
    if pdf.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Please upload a valid PDF file")

    data = await pdf.read()
    try:
        images = _png_base64_from_pdf(data, dpi=dpi)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PDF processing failed: {e}")

    if not images:
        raise HTTPException(status_code=400, detail="No pages found in the PDF")

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    html = _build_single_file_html(images, title, pw_hash)

    filename = os.path.splitext(pdf.filename or 'flipbook')[0] + "_flipbook.html"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\""
    }
    return Response(content=html, media_type="text/html; charset=utf-8", headers=headers)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
