import os, time, asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SECRET_PATH = os.getenv("SECRET_PATH")
CRON_KEY = os.getenv("CRON_KEY")

if not (BOT_TOKEN and SECRET_PATH and CRON_KEY):
    raise RuntimeError("Faltan variables de entorno obligatorias")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- CONFIG ---
VOLUME = 500  # monto de referencia para cotización (ajústalo si quieres)
EXCHANGES = [
    "binancep2p", "bybitp2p", "bitgetp2p", "paxfulp2p",
    "eldoradop2p", "coinexp2p", "xapo"
]

app = FastAPI()

async def fetch_exchange_price(client: httpx.AsyncClient, ex: str):
    url = f"https://criptoya.com/api/{ex}/USDT/BOB/{VOLUME}"
    try:
        r = await client.get(url, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()
        ask = float(d.get("ask", 0) or 0)
        bid = float(d.get("bid", 0) or 0)
        t = d.get("time", 0)
        ts = datetime.fromtimestamp(t/1000 if t > 1_000_000_000_000 else t, tz=timezone.utc)
        # descarta entradas vacías
        if ask <= 0 and bid <= 0:
            return None
        return {"ex": ex, "ask": ask, "bid": bid, "ts": ts}
    except Exception:
        return None

async def fetch_top2():
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[fetch_exchange_price(client, ex) for ex in EXCHANGES]
        )
    data = [x for x in results if x]

    if not data:
        raise RuntimeError("Sin cotizaciones disponibles en exchanges.")

    # Top 2 para comprar (menor ask)
    best_buy = sorted(
        [d for d in data if d["ask"] > 0],
        key=lambda x: x["ask"]
    )[:2]

    # Top 2 para vender (mayor bid)
    best_sell = sorted(
        [d for d in data if d["bid"] > 0],
        key=lambda x: x["bid"],
        reverse=True
    )[:2]

    # Marca de tiempo más reciente entre los resultados
    ts = max(d["ts"] for d in data if "ts" in d)

    return best_buy, best_sell, ts

async def send_msg(text: str, chat_id: str = None):
    chat_id = chat_id or CHAT_ID
    if not chat_id:
        raise RuntimeError("No hay CHAT_ID configurado")
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text})

def format_top2(best_buy, best_sell, ts_local_str):
    def line(i, row, mode):
        # mode: "BUY" (ask) o "SELL" (bid)
        if mode == "BUY":
            return f"{i}. {row['ex']}: Bs {row['ask']:,.2f}"
        else:
            return f"{i}. {row['ex']}: Bs {row['bid']:,.2f}"

    lines = ["💵 USDT en BOB (volumen ref: {} USDT)".format(VOLUME)]
    if best_buy:
        lines.append("🔽 Mejores para *comprar* (menor ask):")
        for i, r in enumerate(best_buy, 1):
            lines.append(line(i, r, "BUY"))
    else:
        lines.append("🔽 Mejores para *comprar*: sin datos")

    if best_sell:
        lines.append("\n🔼 Mejores para *vender* (mayor bid):")
        for i, r in enumerate(best_sell, 1):
            lines.append(line(i, r, "SELL"))
    else:
        lines.append("\n🔼 Mejores para *vender*: sin datos")

    lines.append(f"\n⏱️ {ts_local_str}")
    return "\n".join(lines)

@app.get("/")
async def root():
    return {"ok": True, "time": int(time.time())}

# Webhook de Telegram
@app.post(f"/{SECRET_PATH}")
async def telegram_webhook(req: Request):
    update = await req.json()
    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip().lower()
    chat = message.get("chat", {}).get("id")

    if text == "/start":
        await send_msg("Listo ✅ Usa /precio para ver los top 2 de compra y venta por exchange.", chat)
    elif text == "/precio":
        try:
            best_buy, best_sell, ts = await fetch_top2()
            ts_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
            await send_msg(format_top2(best_buy, best_sell, ts_local), chat)
        except Exception as e:
            await send_msg(f"⚠️ No pude obtener precios ahora: {e}", chat)
    return {"ok": True}

# Endpoint para cron cada 30 min
@app.get("/send")
async def tick(key: str):
    if key != CRON_KEY:
        raise HTTPException(status_code=401, detail="bad key")
    best_buy, best_sell, ts = await fetch_top2()
    ts_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    await send_msg(format_top2(best_buy, best_sell, ts_local), CHAT_ID)
    return {"sent": True}


