import os
import aiohttp
import logging
import time
from fastapi import FastAPI, Request, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import create_client, Client

logger = logging.getLogger()



def get_base_template(title: str, message: str, type: str, icon: str, button_text: str = "Return Home", button_link: str = "/") -> str:
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Valorant Narrator</title>
        <link rel="stylesheet" href="/static/style.css">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet" />
    </head>
    <body class="referral-body">
        <div class="container">
            <div class="status-card {type}">
                <i class="{icon}"></i>
                <h2>{title}</h2>
                <p>{message}</p>
                <a href="{button_link}" class="btn">{button_text}</a>
            </div>
        </div>
    </body>
    </html>
    """

def failure_template(title: str, message: str, button_text: str = "Return Home", button_link: str = "/") -> str:
    return get_base_template(title, message, "error", "fa-solid fa-circle-xmark", button_text, button_link)

def success_template(duration: str, user_id: str) -> str:
    message = f"<strong>Awesome!</strong><br>You've unlocked ValNarrator Premium for <strong>{duration}</strong>.<br>Restart your app to enjoy unlimited access and premium voices!"
    return get_base_template("Referral Applied!", message, "success", "fa-solid fa-circle-check", "Return to Home", f"/?user-id={user_id}")

def rate_limited_template(request: Request, exc: RateLimitExceeded) -> str:
    return get_base_template("Rate Limit Exceeded", "You have made too many requests. Please try again later.", "warning", "fa-solid fa-triangle-exclamation")

async def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return HTMLResponse(content=rate_limited_template(request, exc), status_code=429)

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
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)

templates = Jinja2Templates(directory="templates")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)


@app.get("/favicon.ico")
async def favicon(request: Request):
    return FileResponse("static/app.ico")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/TermsOfService", response_class=HTMLResponse)
async def TOS(request: Request):
    return templates.TemplateResponse("TOS.html"), {"request": request}


@app.get("/PrivacyPolicy", response_class=HTMLResponse)
async def PP(request: Request):
    return templates.TemplateResponse("PP.html", {"request": request})


@app.get("/CancellationRefundPolicy", response_class=HTMLResponse)
async def CRP(request: Request):
    return templates.TemplateResponse("CRP.html", {"request": request})


@app.get("/referral", response_class=HTMLResponse)
async def referral_form(request: Request):
    return templates.TemplateResponse("referral.html", {"request": request})


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



def convert_seconds(seconds):
    SECONDS_IN_MINUTE = 60
    SECONDS_IN_HOUR = 3600
    SECONDS_IN_DAY = 86400
    SECONDS_IN_MONTH = 2629800

    if seconds == 0:
        return "0 seconds"

    months, seconds = divmod(seconds, SECONDS_IN_MONTH)
    days, seconds = divmod(seconds, SECONDS_IN_DAY)
    hours, seconds = divmod(seconds, SECONDS_IN_HOUR)
    minutes, seconds = divmod(seconds, SECONDS_IN_MINUTE)

    result = []
    if months > 0:
        result.append(f"{months} month{'s' if months > 1 else ''}")
    if days > 0:
        result.append(f"{days} day{'s' if days > 1 else ''}")
    if hours > 0:
        result.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes > 0:
        result.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if seconds > 0:
        result.append(f"{seconds} second{'s' if seconds > 1 else ''}")

    return ", ".join(result)

@app.get("/referralApply", response_class=HTMLResponse)
@limiter.limit("9/6hours")
async def handle_referral_apply(
    request: Request, response: Response, referral_code: str = None, user_id: str = None
):
    # Construct retry link
    retry_link = f"/referral?user-id={user_id}&referralCode={referral_code}" if user_id and referral_code else "/referral"
    
    if not user_id or not referral_code:
        return HTMLResponse(
            content=failure_template(
                "Invalid Request", "Missing referral code or user ID!", "Try Again", "/referral"
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    referral_response = (
        supabase.table("accountreferral")
        .select("*")
        .eq("referraltoken", referral_code)
        .execute()
    )
    referral_record = referral_response.data

    if not referral_record:
        return HTMLResponse(
            content=failure_template("Invalid Referral", "Referral code not found!", "Try Again", retry_link),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    duration = referral_record[0]["duration"]
    premium_till = int(time.time()) + duration

    user_response = (
        supabase.table("userhwids").select("*").eq("userid", user_id).execute()
    )
    user_exists = user_response.data

    if not user_exists:
        return HTMLResponse(
            content=failure_template(
                "Invalid User", "User ID does not exist in our records.", "Try Again", retry_link
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Update user and consume referral code
    supabase.table("userhwids").update(
        {"premium": True, "premium_till": premium_till}
    ).eq("userid", user_id).execute()

    supabase.table("accountreferral").delete().eq(
        "referraltoken", referral_code
    ).execute()

    return HTMLResponse(
        content=success_template(convert_seconds(duration), user_id), status_code=200
    )

@app.get("/user/{user_id}")
@limiter.limit("10/1minute")
async def get_user_details(request: Request, response: Response, user_id: str):
    user_response = (
        supabase.table("userhwids").select("quotaused, premium, premium_till").eq("userid", user_id).execute()
    )
    user_data = user_response.data

    if not user_data:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "User not found"}

    return user_data[0]

@app.get("/discord")
async def discord(request: Request):
    return RedirectResponse("https://discord.gg/RWP25YQDcf")
