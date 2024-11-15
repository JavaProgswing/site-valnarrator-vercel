import os
import aiohttp
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import create_client, Client

logger = logging.getLogger()


async def send_discord_webhook_async(message: str):
    payload = {"content": message}
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            os.getenv("WEBHOOK"), json=payload, headers=headers
        ) as response:
            if response.status != 204:
                logger.error("Failed to send Discord webhook")


app = FastAPI()
limiter = Limiter(key_func=get_remote_address, headers_enabled=True, storage_uri=os.getenv("REDIS_URL"))
app.mount("/static", StaticFiles(directory="static"), name="static")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory="templates")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)


@app.get("/favicon.ico")
async def favicon(request: Request):
    return FileResponse("static/app.ico")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    logger.info(f"VALTECH({request.client.host}) /")
    return templates.TemplateResponse("index.html")


@app.get("/TermsOfService", response_class=HTMLResponse)
async def TOS(request: Request):
    return templates.TemplateResponse("TOS.html")


@app.get("/PrivacyPolicy", response_class=HTMLResponse)
async def PP(request: Request):
    return templates.TemplateResponse("PP.html")


@app.get("/CancellationRefundPolicy", response_class=HTMLResponse)
async def CRP(request: Request):
    return templates.TemplateResponse("CRP.html")


@app.get("/referral", response_class=HTMLResponse)
async def referral_form(request: Request):
    return templates.TemplateResponse("referral.html")


@app.get("/download/{version}", response_class=RedirectResponse)
async def download_release(request: Request, version: float):
    db_response = (
        supabase.table("valchatreleases")
        .select("releaseurl")
        .eq("version", version)
        .single()
        .execute()
    )

    if db_response.data:
        release_url = db_response.data["releaseurl"]
        return RedirectResponse(release_url)
    else:
        raise HTTPException(status_code=404, detail="Version not found")


@app.get("/download", response_class=RedirectResponse)
async def download_latest_release(request: Request):
    db_response = (
        supabase.table("valchatreleases")
        .select("version", "releaseurl")
        .order("version", desc=True)
        .limit(1)
        .execute()
    )

    if db_response.data:
        latest_version = db_response.data[0]["version"]
        release_url = db_response.data[0]["releaseurl"]
        return RedirectResponse(release_url)
    else:
        raise HTTPException(status_code=404, detail="No releases found")


@app.get("/discord")
async def discord(request: Request):
    return RedirectResponse("https://discord.gg/RWP25YQDcf")
