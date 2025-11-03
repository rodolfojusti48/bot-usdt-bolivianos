import os, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")          # tu chat o canal (con @)
SECRET_PATH = os.getenv("SECRET_PATH")  # ruta secreta del webhook, ej: "tg-<token recortado>"
CRON_KEY = os.getenv("CRON_KEY")        # clave para proteger el endpoint /send
API_URL = "https://criptoya.com/api/USDT/BOB/1"

if not (BOT_TOKEN and SECRET_PATH and CRON_KEY):
    raise RuntimeError("Faltan variables de entorno obligatorias")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()

async def fetch_price():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(API_URL)
        r.raise_for_status()
        data = r.json()
    ask = float(data.get("ask", 0))
    bid = float(data.get("bid", 0))
    t = data.get("time", 0)
    ts = datetime.fromtimestamp(t/1000 if t > 1_000_000_000_000 else t, tz=timezone.utc)
    return ask, bid, ts

async def send_msg(text: str, chat_id: str = None):
    chat_id = chat_id or CHAT_ID
    if not chat_id:
        raise RuntimeError("No hay CHAT_ID configurado")
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text})

@app.get("/")
async def root():
    return {"ok": True, "time": int(time.time())}

# 2) Webhook de Telegram (se despierta gratis cuando alguien escribe al bot)
@app.post(f"/{SECRET_PATH}")
async def telegram_webhook(req: Request):
    update = await req.json()
    # Si envías /start, responde y, si quieres, guarda el chat_id de quien habló.
    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip().lower()
    from_chat = message.get("chat", {}).get("id")
    if text == "/start":
        await send_msg("Listo ✅ Te enviaré el precio cada 30 minutos. Usa /precio para ver ahora mismo.", from_chat)
    elif text == "/precio":
        ask, bid, ts = await fetch_price()
        bolivia = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        await send_msg(
            f"💵 USDT en BOB\n• Compra (ask): Bs {ask:,.2f}\n• Venta (bid): Bs {bid:,.2f}\n⏱️ {bolivia} (hora local)",
            from_chat
        )
    return {"ok": True}

# 3) Endpoint que llamará cron-job.org cada 30 min
@app.get("/send")
async def tick(key: str):
    if key != CRON_KEY:
        raise HTTPException(status_code=401, detail="bad key")
    ask, bid, ts = await fetch_price()
    local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    await send_msg(
        f"💵 USDT en BOB\n• Compra (ask): Bs {ask:,.2f}\n• Venta (bid): Bs {bid:,.2f}\n⏱️ {local}",
        CHAT_ID
    )
    return {"sent": True}
