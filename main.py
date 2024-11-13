import os
import aiohttp
import asyncpg
import json
import time
import requests
import sanic
from sanic.response import text as sanic_textify
from sanic.response import file as send_file
from sanic.response import html as sanic_htmlify
from sanic.response import redirect
from sanic.request import Request
import logging

app = sanic.Sanic(__name__)
app.static("/static", "./static")
logger = logging.getLogger()


async def render_template(template_name):
    try:
        with open(f"templates/{template_name}", "r") as file:
            return sanic_htmlify(file.read())
    except FileNotFoundError:
        return sanic_textify("Internal Server Error. Try again later.", status=500)
    except OSError:
        return sanic_textify("Internal Server Error. Try again later.", status=500)


async def create_db_pool():
    return await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST"),
        port=6543,
        database=os.environ.get("POSTGRES_DATABASE"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
    )


@app.route("/favicon.ico")
async def favicon(request: Request):
    return await send_file("static/app.ico")


@app.route("/", methods=["GET", "HEAD"])
async def index(request: Request):
    logger.info(f"VALTECH({request.headers['X-Forwarded-For']}) /")
    # await send_discord_webhook_async(f"VALTECH({request.headers['X-Forwarded-For']}) /")
    return await render_template("index.html")


@app.route("/TermsOfService")
async def TOS(request: Request):
    # await send_discord_webhook_async(f"({request.headers['X-Forwarded-For']}) /TermsOfService")
    return await render_template("TOS.html")


@app.route("/PrivacyPolicy")
async def PP(request: Request):
    # await send_discord_webhook_async(f"({request.headers['X-Forwarded-For']}) /PrivacyPolicy")
    return await render_template("PP.html")


@app.route("/CancellationRefundPolicy")
async def CRP(request: Request):
    # await send_discord_webhook_async(f"({request.headers['X-Forwarded-For']}) /CancellationRefundPolicy")
    return await render_template("CRP.html")


@app.route("/referral")
async def referral_form(request: Request):
    return await render_template("referral.html")


# Endpoint to handle version downloads
@app.route("/download/<version:number>", methods=["GET"])
async def download_release(request: Request, version: float):
    # await send_discord_webhook_async(f"VALTECH({request.headers['X-Forwarded-For']}) /download/{version}")

    db = await create_db_pool()
    async with db.acquire() as connection:
        # Check if the version exists in the database
        result = await connection.fetchrow(
            "SELECT releaseurl FROM valchatreleases WHERE version=$1", version
        )

        if result is not None:
            release_url = result["releaseurl"]
            # Redirect to the release URL
            return redirect(release_url)
        else:
            # Version not found, return a 404 error with a suitable message
            return sanic_textify("Version not found", status=404)


# Endpoint to handle version downloads
@app.route("/download", methods=["GET"])
async def download_latest_release(request: Request):
    # await send_discord_webhook_async(f"VALTECH({request.headers['X-Forwarded-For']}) /download")

    db = await create_db_pool()
    async with db.acquire() as connection:
        # Fetch the latest version and release URL from the database
        result = await connection.fetchrow(
            "SELECT version, releaseurl FROM valchatreleases ORDER BY version DESC LIMIT 1"
        )

        if result is not None:
            latest_version = result["version"]
            release_url = result["releaseurl"]
            # Redirect to the release URL with the latest version
            return redirect(release_url)
        else:
            # No releases found in the database, return a 404 error with a suitable message
            return sanic_textify("No releases found", status=404)


@app.route("/discord", methods=["GET"])
async def discord(request: Request):
    # await send_discord_webhook_async(f"VALTECH({request.headers['X-Forwarded-For']}) /discord")
    return redirect("https://discord.gg/RWP25YQDcf")


async def clear_quota_used():
    db = await create_db_pool()

    async with db.acquire() as connection:
        # Set quotaUsed to 0 for non-premium users
        await connection.execute("UPDATE userhwids SET quotaused=0 WHERE premium=false")


async def _refresh_token(token, refresh_token, expires_in, api_key):
    url = "https://securetoken.googleapis.com/v1/token?key=" + api_key
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as response:
            if response.status == 200:
                token_data = await response.json()
                access_token = token_data.get("access_token")
                new_expires_in = int(time.time()) + int(token_data.get("expires_in"))
                return access_token, refresh_token, new_expires_in
            else:
                print(f"Refreshing token failed with code: {response.status}")
                return None


async def get_api_key():
    url = "https://speechifymobile.firebaseapp.com/__/firebase/init.json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data["apiKey"]
            else:
                return None


async def update_tokens_in_database():
    api_key = await get_api_key()
    db = await create_db_pool()
    async with db.acquire() as connection:
        # Fetch tokens from the database
        query = "SELECT * FROM accounttokens;"
        records = await connection.fetch(query)

        # Iterate over each record and refresh the token
        for record in records:
            token, refresh_token, valid, expires_in = (
                record["token"],
                record["refresh_token"],
                record["valid"],
                record["expires_in"],
            )
            refreshed_token = await _refresh_token(
                token, refresh_token, expires_in, api_key
            )

            if refreshed_token:
                update_query = """
                        UPDATE public.accounttokens
                        SET "token" = $1, "refresh_token" = $2, "expires_in" = $3
                        WHERE "token" = $4;
                    """
                await connection.execute(update_query, *refreshed_token, token)


def send_discord_webhook(message, webhook_url=None):
    if webhook_url is None:
        webhook_url = os.getenv("WEBHOOK")
    """
    Sends a message to a Discord webhook.

    Args:
        webhook_url (str): The URL of the Discord webhook.
        message (str): The message to send.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    try:
        payload = {"content": message}

        headers = {"Content-Type": "application/json"}

        response = requests.post(webhook_url, data=json.dumps(payload), headers=headers)

        print(f"Sent message. Status code: {response.status_code}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return False


async def send_discord_webhook_async(message, webhook_url=None):
    if webhook_url is None:
        webhook_url = os.getenv("WEBHOOK")
    """
    Sends a message to a Discord webhook asynchronously.

    Args:
        webhook_url (str): The URL of the Discord webhook.
        message (str): The message to send.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    try:
        payload = {"content": message}

        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, data=json.dumps(payload), headers=headers
            ):
                pass
    except Exception as e:
        print(f"Error sending Discord webhook: {e}")
        return False
