import io
import os
import time
import httpx
import json
import base64
import re
import threading
from collections import defaultdict
from typing import Tuple, Optional
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor
from Crypto.Cipher import AES
from google.protobuf import json_format
from cachetools import TTLCache

# ================= SETTINGS =================
MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB54"
USERAGENT = "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)"
SUPPORTED_REGIONS = {"IND", "BR", "US", "SAC", "NA", "SG", "RU", "ID", "TW", "VN", "TH", "ME", "PK", "CIS", "BD", "EU"}

# ================= IMAGE SETTINGS =================
AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0  
AVATAR_SHIFT_X = 0  
BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

ICON_BASE_URL = "https://iconapi.wasmer.app"

DEFAULT_AVATAR_ID = "1001000001"
DEFAULT_BANNER_ID = "1001000001"

# ================= FONT SETTINGS =================
FONT_FILE = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"

# ================= OUTFIT SETTINGS =================
BACKGROUND_FILENAME = "outfit.png"    
IMAGE_TIMEOUT = 8                     
CANVAS_SIZE = (800, 800)            
BACKGROUND_MODE = 'cover'             
OUTFIT_SIZE = (150, 150)

# ================= FLASK APP =================
app = Flask(__name__)
CORS(app)

# ================= GLOBAL VARIABLES =================
cached_tokens = defaultdict(dict)
image_cache = TTLCache(maxsize=300, ttl=3600)
process_pool = ThreadPoolExecutor(max_workers=10)
client = None

# ================= HELPER FUNCTIONS =================
def get_client():
    global client
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USERAGENT},
            timeout=30.0,
            follow_redirects=True
        )
    return client

def clean_text(text):
    """Bersihkan karakter khusus untuk PIL"""
    if not text:
        return "Unknown"
    
    text = re.sub(r'[\u3164\uFFFD\u200B-\u200F\u2028-\u202F\u3000]', ' ', text)
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    text = re.sub(r'[^\w\s.,!?\-()\[\]{}@#$%^&*+=|\\:;"/\'\u0E00-\u0E7F\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]', '', text)
    text = ' '.join(text.split())
    
    return text.strip() or "Unknown"

def is_cherokee(c):
    return 0x13A0 <= ord(c) <= 0x13FF or 0xAB70 <= ord(c) <= 0xABBF

def load_unicode_font(size, font_file=FONT_FILE):
    try:
        font_path = os.path.join(os.path.dirname(__file__), font_file)
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
    except:
        pass
    return ImageFont.load_default()

def load_cherokee_font(size):
    return load_unicode_font(size, FONT_CHEROKEE)

def safe_text(text):
    """Ganti karakter aneh dengan yang aman"""
    if not text:
        return ""
    replacements = {
        '•': '-',
        '·': '-',
        '●': '-',
        '◦': '-',
        '◆': '-',
        '◇': '-',
        '▪': '-',
        '▫': '-',
        '\u2022': '-',  # bullet
        '\u00b7': '-',  # middle dot
        '\u2219': '-',  # bullet operator
        '\u25cf': '-',  # black circle
        '\u25e6': '-',  # white bullet
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return clean_text(text)

# ================= FREE FIRE API FUNCTIONS (SYNC) =================
def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))

def decode_protobuf(encoded_data: bytes, message_type):
    instance = message_type()
    instance.ParseFromString(encoded_data)
    return instance

def json_to_proto_sync(json_data: str, proto_message):
    json_format.ParseDict(json.loads(json_data), proto_message)
    return proto_message.SerializeToString()

def get_account_credentials(region: str) -> str:
    return "uid=5479057360&password=QNGE829627SAK"

def get_access_token_sync(account: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = account + "&response_type=token&client_type=2&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3&client_id=100067"
    headers = {
        'User-Agent': USERAGENT, 
        'Connection': "Keep-Alive", 
        'Accept-Encoding': "gzip", 
        'Content-Type': "application/x-www-form-urlencoded"
    }
    try:
        client = get_client()
        resp = client.post(url, data=payload, headers=headers)
        data = resp.json()
        return data.get("access_token", "0"), data.get("open_id", "0")
    except Exception as e:
        print(f"Error getting access token: {e}")
        return "0", "0"

def create_jwt_sync(region: str):
    try:
        account = get_account_credentials(region)
        token_val, open_id = get_access_token_sync(account)
        
        if token_val == "0" or open_id == "0":
            print(f"Failed to get token for region {region}")
            return
        
        body = json.dumps({
            "open_id": open_id, 
            "open_id_type": "4", 
            "login_token": token_val, 
            "orign_platform_type": "4"
        })
        
        try:
            from proto import FreeFire_pb2
        except ImportError:
            print("Proto file not found")
            return
        
        proto_bytes = json_to_proto_sync(body, FreeFire_pb2.LoginReq())
        payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)
        
        url = "https://loginbp.ggpolarbear.com/MajorLogin"
        headers = {
            'User-Agent': USERAGENT, 
            'Connection': "Keep-Alive", 
            'Accept-Encoding': "gzip",
            'Content-Type': "application/octet-stream", 
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1", 
            'X-GA': "v1 1", 
            'ReleaseVersion': RELEASEVERSION
        }
        client = get_client()
        resp = client.post(url, data=payload, headers=headers)
        msg = json.loads(json_format.MessageToJson(decode_protobuf(resp.content, FreeFire_pb2.LoginRes)))
        cached_tokens[region] = {
            'token': f"Bearer {msg.get('token','0')}",
            'region': msg.get('lockRegion','0'),
            'server_url': msg.get('serverUrl','0'),
            'expires_at': time.time() + 25200
        }
        print(f"Token generated for region {region}")
    except Exception as e:
        print(f"Error generating token for {region}: {e}")

def initialize_tokens_sync():
    for r in SUPPORTED_REGIONS:
        create_jwt_sync(r)

def get_token_info_sync(region: str) -> Tuple[str, str, str]:
    info = cached_tokens.get(region)
    if info and time.time() < info['expires_at']:
        return info['token'], info['region'], info['server_url']
    create_jwt_sync(region)
    info = cached_tokens[region]
    return info['token'], info['region'], info['server_url']

def get_region_by_uid_sync(uid: str) -> str:
    try:
        regions_to_try = ["IND", "BR", "US", "SG", "ID", "TH", "VN"]
        for region in regions_to_try:
            try:
                token, lock, server = get_token_info_sync(region)
                if token != "Bearer 0":
                    return region
            except:
                continue
        return "IND"
    except:
        return "IND"

def get_account_information_sync(uid, unk, region, endpoint):
    try:
        from proto import main_pb2, AccountPersonalShow_pb2
        
        payload = json_to_proto_sync(json.dumps({'a': uid, 'b': unk}), main_pb2.GetPlayerPersonalShow())
        data_enc = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, payload)
        token, lock, server = get_token_info_sync(region)
        
        headers = {
            'User-Agent': USERAGENT, 
            'Connection': "Keep-Alive", 
            'Accept-Encoding': "gzip",
            'Content-Type': "application/octet-stream", 
            'Expect': "100-continue",
            'Authorization': token, 
            'X-Unity-Version': "2018.4.11f1", 
            'X-GA': "v1 1",
            'ReleaseVersion': RELEASEVERSION
        }
        client = get_client()
        resp = client.post(server + endpoint, data=data_enc, headers=headers)
        return json.loads(json_format.MessageToJson(decode_protobuf(resp.content, AccountPersonalShow_pb2.AccountPersonalShowInfo)))
    except Exception as e:
        print(f"Error getting account info: {e}")
        raise

def format_response(data):
    if not data:
        return {"error": "No data received"}
    
    raw_name = data.get("basicInfo", {}).get("nickname", "Unknown")
    raw_guild = data.get("clanBasicInfo", {}).get("clanName", "")
    raw_avatar = data.get("basicInfo", {}).get("headPic")
    raw_banner = data.get("basicInfo", {}).get("bannerId")
    raw_level = data.get("basicInfo", {}).get("level", "0")
    raw_uid = data.get("basicInfo", {}).get("playerId", "")
    raw_weapons = data.get("basicInfo", {}).get("weaponSkinShows", [])  # Weapon skin
    
    return {
        "AccountInfo": {
            "AccountAvatarId": raw_avatar,
            "AccountBPBadges": data.get("basicInfo", {}).get("badgeCnt"),
            "AccountBPID": data.get("basicInfo", {}).get("badgeId"),
            "AccountBannerId": raw_banner,
            "AccountCreateTime": data.get("basicInfo", {}).get("createAt"),
            "AccountEXP": data.get("basicInfo", {}).get("exp"),
            "AccountLastLogin": data.get("basicInfo", {}).get("lastLoginAt"),
            "AccountLevel": raw_level,
            "AccountLikes": data.get("basicInfo", {}).get("liked"),
            "AccountName": raw_name,
            "AccountRegion": data.get("basicInfo", {}).get("region"),
            "AccountSeasonId": data.get("basicInfo", {}).get("seasonId"),
            "AccountType": data.get("basicInfo", {}).get("accountType"),
            "AccountUID": raw_uid,
            "BrMaxRank": data.get("basicInfo", {}).get("maxRank"),
            "BrRankPoint": data.get("basicInfo", {}).get("rankingPoints"),
            "CsMaxRank": data.get("basicInfo", {}).get("csMaxRank"),
            "CsRankPoint": data.get("basicInfo", {}).get("csRankingPoints"),
            "EquippedWeapon": raw_weapons,  # Weapon skin
            "ReleaseVersion": data.get("basicInfo", {}).get("releaseVersion"),
            "ShowBrRank": data.get("basicInfo", {}).get("showBrRank"),
            "ShowCsRank": data.get("basicInfo", {}).get("showCsRank"),
            "Title": data.get("basicInfo", {}).get("title")
        },
        "AccountProfileInfo": {
            "EquippedOutfit": data.get("profileInfo", {}).get("clothes", []),
            "EquippedSkills": data.get("profileInfo", {}).get("equipedSkills", [])  # Outfit dari sini
        },
        "GuildInfo": {
            "GuildCapacity": data.get("clanBasicInfo", {}).get("capacity"),
            "GuildID": str(data.get("clanBasicInfo", {}).get("clanId")),
            "GuildLevel": data.get("clanBasicInfo", {}).get("clanLevel"),
            "GuildMember": data.get("clanBasicInfo", {}).get("memberNum"),
            "GuildName": raw_guild,
            "GuildOwner": str(data.get("clanBasicInfo", {}).get("captainId"))
        },
        "captainBasicInfo": data.get("captainBasicInfo", {}),
        "creditScoreInfo": data.get("creditScoreInfo", {}),
        "petInfo": data.get("petInfo", {}),
        "socialinfo": data.get("socialInfo", {})
    }
# ================= IMAGE FUNCTIONS =================
def fetch_image_bytes_sync(item_id):
    if not item_id or str(item_id) in ["0", "None", "null", ""]:
        item_id = DEFAULT_AVATAR_ID
    
    cache_key = f"img_{item_id}"
    if cache_key in image_cache:
        return image_cache[cache_key]
    
    url = f"{ICON_BASE_URL}/{item_id}"
    
    try:
        client = get_client()
        resp = client.get(url, timeout=IMAGE_TIMEOUT)
        if resp.status_code == 200:
            content = resp.content
            try:
                img = Image.open(io.BytesIO(content))
                png_io = io.BytesIO()
                img.save(png_io, 'PNG')
                png_io.seek(0)
                result = png_io.getvalue()
                image_cache[cache_key] = result
                return result
            except:
                image_cache[cache_key] = content
                return content
    except:
        pass
    
    if item_id != DEFAULT_AVATAR_ID:
        return fetch_image_bytes_sync(DEFAULT_AVATAR_ID)
    
    return None

def draw_text_safe(draw, x, y, text, font_main, font_alt, color, stroke=0):
    """Draw text dengan safe character handling"""
    if not text or not text.strip():
        return
    
    cx = x
    for ch in text:
        try:
            # Pilih font berdasarkan karakter
            f = font_alt if is_cherokee(ch) else font_main
            
            # Stroke (bayangan hitam)
            if stroke > 0:
                for dx in range(-stroke, stroke + 1):
                    for dy in range(-stroke, stroke + 1):
                        if dx != 0 or dy != 0:
                            draw.text((cx + dx, y + dy), ch, font=f, fill="black")
            
            # Text utama
            draw.text((cx, y), ch, font=f, fill=color)
            cx += f.getlength(ch)
        except:
            # Skip karakter yang error
            continue

# ================= CARD IMAGE FUNCTIONS (UPDATE) =================

def fetch_outfit_for_card(outfit_id: str, size: tuple = (80, 80)):
    """Fetch outfit image untuk card"""
    cache_key = f"card_outfit_{outfit_id}"
    if cache_key in image_cache:
        img_data = image_cache[cache_key]
        return Image.open(io.BytesIO(img_data)).convert("RGBA")
    
    try:
        url = f"{ICON_BASE_URL}/{outfit_id}"
        client = get_client()
        resp = client.get(url, timeout=IMAGE_TIMEOUT)
        if resp.status_code == 200:
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            if size:
                img = img.resize(size, Image.LANCZOS)
            img_io = io.BytesIO()
            img.save(img_io, 'PNG')
            image_cache[cache_key] = img_io.getvalue()
            return img
    except Exception as e:
        print(f"DEBUG: Error fetching outfit {outfit_id}: {e}")
    return None

# ================= CARD IMAGE FUNCTIONS (FINAL) =================

def fetch_icon_for_card(item_id: str, size: tuple = (60, 60)):
    """Fetch icon untuk card (outfit/weapon)"""
    if not item_id or str(item_id) in ["0", "None", "null", ""]:
        return None
    
    cache_key = f"card_icon_{item_id}"
    if cache_key in image_cache:
        img_data = image_cache[cache_key]
        return Image.open(io.BytesIO(img_data)).convert("RGBA")
    
    try:
        url = f"{ICON_BASE_URL}/{item_id}"
        client = get_client()
        resp = client.get(url, timeout=IMAGE_TIMEOUT)
        if resp.status_code == 200:
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            if size:
                img = img.resize(size, Image.LANCZOS)
            img_io = io.BytesIO()
            img.save(img_io, 'PNG')
            image_cache[cache_key] = img_io.getvalue()
            return img
    except Exception as e:
        print(f"DEBUG: Error fetching icon {item_id}: {e}")
    return None

def process_card_image(data, avatar_bytes):
    """Buat kartu info player dengan outfit & weapon skin - UKURAN PAS"""
    print("DEBUG: Processing card image...")
    
    # Canvas ukuran sedang
    canvas_w, canvas_h = 750, 650
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (10, 10, 20, 255))
    
    # Background gradient
    draw = ImageDraw.Draw(canvas)
    for i in range(canvas_h):
        color = int(10 + (i / canvas_h) * 15)
        draw.rectangle([0, i, canvas_w, i+1], fill=(color, color, color+8, 255))
    
    # Border tipis
    draw.rectangle([8, 8, canvas_w-8, canvas_h-8], outline=(255, 215, 0, 80), width=1)
    
    # === AVATAR ===
    avatar_size = 100
    try:
        if avatar_bytes:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)
            
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            
            canvas.paste(avatar_img, (25, 30), mask)
            draw.ellipse([22, 27, avatar_size+27, avatar_size+27], outline=(255, 215, 0, 150), width=2)
        else:
            draw.ellipse([25, 30, 125, 130], fill=(50, 50, 60, 255))
            draw.ellipse([25, 30, 125, 130], outline=(255, 215, 0, 150), width=2)
    except:
        draw.ellipse([25, 30, 125, 130], fill=(50, 50, 60, 255))
        draw.ellipse([25, 30, 125, 130], outline=(255, 215, 0, 150), width=2)
    
    # Load fonts
    font_title = load_unicode_font(28)
    font_name = load_unicode_font(22)
    font_sub = load_unicode_font(16)
    font_small = load_unicode_font(13)
    font_label = load_unicode_font(12)
    
    font_cherokee_title = load_cherokee_font(28)
    font_cherokee_name = load_cherokee_font(22)
    font_cherokee_sub = load_cherokee_font(16)
    font_cherokee_small = load_cherokee_font(13)
    
    # Data
    account = data.get("AccountInfo", {})
    name = safe_text(account.get("AccountName", "Unknown"))
    level = account.get("AccountLevel", "0")
    uid = account.get("AccountUID", "")
    region = account.get("AccountRegion", "")
    guild = data.get("GuildInfo", {}).get("GuildName", "")
    guild = safe_text(guild)
    weapons = account.get("EquippedWeapon", []) or []
    
    # === HEADER ===
    draw_text_safe(draw, 150, 20, "FF INFO", font_title, font_cherokee_title, (255, 215, 0))
    
    # === INFO ===
    draw_text_safe(draw, 150, 55, name, font_name, font_cherokee_name, "white")
    draw_text_safe(draw, 150, 82, f"UID: {uid}", font_sub, font_cherokee_sub, (180, 180, 180))
    draw_text_safe(draw, 150, 105, f"Lv.{level}  |  {region}", font_sub, font_cherokee_sub, (255, 215, 0))
    
    if guild:
        draw_text_safe(draw, 150, 128, f"Guild: {guild}", font_small, font_cherokee_small, (150, 200, 255))
    
    # Garis pemisah
    draw.line([25, 155, canvas_w-25, 155], fill=(255, 215, 0, 50), width=1)
    
    # === OUTFIT SECTION (dari equipedSkills) ===
    draw_text_safe(draw, 25, 170, "OUTFIT", font_label, font_cherokee_small, (255, 215, 0, 150))
    
    # Ambil outfit dari equipedSkills
    profile_info = data.get("AccountProfileInfo", {})
    outfit_ids = profile_info.get("EquippedSkills", []) or []
    outfit_ids = [str(oid) for oid in outfit_ids if oid]
    
    # Ambil 6 outfit
    outfit_images = []
    for oid in outfit_ids[:6]:
        img = fetch_icon_for_card(oid, (60, 60))
        if img:
            outfit_images.append(img)
        else:
            placeholder = Image.new("RGBA", (60, 60), (35, 35, 45, 255))
            outfit_images.append(placeholder)
    
    while len(outfit_images) < 6:
        placeholder = Image.new("RGBA", (60, 60), (35, 35, 45, 255))
        outfit_images.append(placeholder)
    
    # Paste outfit (2 baris x 3 kolom) - DI TENGAH
    # Hitung posisi tengah untuk outfit
    outfit_cols = 3
    outfit_rows = 2
    outfit_size = 60
    outfit_gap = 10
    total_outfit_width = (outfit_cols * outfit_size) + ((outfit_cols - 1) * outfit_gap)
    outfit_start_x = 30
    outfit_start_y = 185
    
    for idx, img in enumerate(outfit_images):
        row = idx // outfit_cols
        col = idx % outfit_cols
        x = outfit_start_x + (col * (outfit_size + outfit_gap))
        y = outfit_start_y + (row * (outfit_size + outfit_gap))
        canvas.paste(img, (x, y), img)
        draw.rectangle([x-1, y-1, x+outfit_size+1, y+outfit_size+1], outline=(255, 215, 0, 30), width=1)
    
    # === WEAPON SKIN SECTION ===
    weapon_label_y = 170
    draw_text_safe(draw, 250, weapon_label_y, "WEAPONS", font_label, font_cherokee_small, (100, 180, 255, 150))
    
    # Ambil weapon skin
    weapon_ids = [str(w) for w in weapons[:6] if w]
    
    weapon_images = []
    for wid in weapon_ids[:6]:
        img = fetch_icon_for_card(wid, (55, 55))
        if img:
            weapon_images.append(img)
        else:
            placeholder = Image.new("RGBA", (55, 55), (25, 25, 35, 255))
            weapon_images.append(placeholder)
    
    while len(weapon_images) < 6:
        placeholder = Image.new("RGBA", (55, 55), (25, 25, 35, 255))
        weapon_images.append(placeholder)
    
    # Paste weapon (2 baris x 3 kolom)
    weapon_cols = 3
    weapon_rows = 2
    weapon_size = 55
    weapon_gap = 10
    weapon_start_x = 250
    weapon_start_y = 185
    
    for idx, img in enumerate(weapon_images):
        row = idx // weapon_cols
        col = idx % weapon_cols
        x = weapon_start_x + (col * (weapon_size + weapon_gap))
        y = weapon_start_y + (row * (weapon_size + weapon_gap))
        canvas.paste(img, (x, y), img)
        draw.rectangle([x-1, y-1, x+weapon_size+1, y+weapon_size+1], outline=(100, 180, 255, 30), width=1)
    
    # === FOOTER ===
    footer_y = canvas_h - 50
    draw.rectangle([25, footer_y, canvas_w-25, canvas_h-10], fill=(0, 0, 0, 60))
    
    footer_texts = [
        "TG @FFLK_COMMUNITY",
        "Discord gg/EBQ9XeYRZg"
    ]
    
    y_pos = footer_y + 8
    for txt in footer_texts:
        draw_text_safe(draw, 35, y_pos, txt, font_small, font_cherokee_small, (100, 150, 255, 150))
        y_pos += 18
    
    # Watermark
    draw_text_safe(draw, canvas_w-150, footer_y+8, "@FreeFire_Dev", font_small, font_cherokee_small, (255, 215, 0, 80))
    draw_text_safe(draw, canvas_w-150, footer_y+28, "FFDEV", font_small, font_cherokee_small, (255, 215, 0, 60))
    
    # Corner decorations
    draw.rectangle([12, 12, 25, 25], fill=(255, 215, 0, 60))
    draw.rectangle([canvas_w-25, 12, canvas_w-12, 25], fill=(255, 215, 0, 60))
    draw.rectangle([12, canvas_h-25, 25, canvas_h-12], fill=(255, 215, 0, 60))
    draw.rectangle([canvas_w-25, canvas_h-25, canvas_w-12, canvas_h-12], fill=(255, 215, 0, 60))
    
    img_io = io.BytesIO()
    canvas.save(img_io, "PNG")
    img_io.seek(0)
    print("DEBUG: Card image processed successfully")
    return img_io

# ================= ROUTE HANDLERS =================
def handle_card(uid: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        region = get_region_by_uid_sync(uid)
        if not region or region not in SUPPORTED_REGIONS:
            return None, "Invalid region"
        
        data_raw = get_account_information_sync(uid, "7", region, "/GetPlayerPersonalShow")
        data = format_response(data_raw)
        
        account = data.get("AccountInfo", {})
        captain = data.get("captainBasicInfo", {})
        
        if not account:
            return None, "Account not found"
        
        avatar_id = account.get("AccountAvatarId") or captain.get("headPic")
        avatar_bytes = fetch_image_bytes_sync(avatar_id)
        
        img_io = process_card_image(data, avatar_bytes)
        return img_io.getvalue(), None
        
    except Exception as e:
        print(f"Error in handle_card: {e}")
        import traceback
        traceback.print_exc()
        return None, str(e)

def handle_avatar(uid: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        region = get_region_by_uid_sync(uid)
        if not region or region not in SUPPORTED_REGIONS:
            return None, "Invalid region"
        
        data_raw = get_account_information_sync(uid, "7", region, "/GetPlayerPersonalShow")
        data = format_response(data_raw)
        
        account = data.get("AccountInfo", {})
        captain = data.get("captainBasicInfo", {})
        
        if not account:
            return None, "Account not found"
        
        avatar_id = account.get("AccountAvatarId") or captain.get("headPic")
        avatar_bytes = fetch_image_bytes_sync(avatar_id)
        
        img_io = process_avatar_image(avatar_bytes)
        return img_io.getvalue(), None
        
    except Exception as e:
        print(f"Error in handle_avatar: {e}")
        return None, str(e)

def handle_banner(uid: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        region = get_region_by_uid_sync(uid)
        if not region or region not in SUPPORTED_REGIONS:
            return None, "Invalid region"
        
        data_raw = get_account_information_sync(uid, "7", region, "/GetPlayerPersonalShow")
        data = format_response(data_raw)
        
        account = data.get("AccountInfo", {})
        captain = data.get("captainBasicInfo", {})
        
        if not account:
            return None, "Account not found"
        
        banner_id = account.get("AccountBannerId") or captain.get("bannerId")
        banner_bytes = fetch_image_bytes_sync(banner_id)
        
        img_io = process_banner_image(banner_bytes)
        return img_io.getvalue(), None
        
    except Exception as e:
        print(f"Error in handle_banner: {e}")
        return None, str(e)

def handle_info(uid: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        region = get_region_by_uid_sync(uid)
        if not region or region not in SUPPORTED_REGIONS:
            return None, "Invalid region"
        
        data_raw = get_account_information_sync(uid, "7", region, "/GetPlayerPersonalShow")
        formatted = format_response(data_raw)
        return formatted, None
        
    except Exception as e:
        print(f"Error in handle_info: {e}")
        return None, str(e)

def handle_outfit(uid: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        player_data = fetch_player_info(uid)
        if not player_data:
            return None, "Failed to fetch player info"
        
        img_io = create_outfit_image(player_data)
        return img_io.getvalue(), None
        
    except Exception as e:
        print(f"Error in handle_outfit: {e}")
        return None, str(e)

# ================= IMAGE PROCESS FUNCTIONS =================
def process_avatar_image(avatar_bytes):
    """Process avatar only"""
    try:
        if avatar_bytes:
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        else:
            avatar_img = Image.new("RGBA", (400, 400), (40, 40, 50, 255))
    except:
        avatar_img = Image.new("RGBA", (400, 400), (40, 40, 50, 255))
    
    avatar_img = avatar_img.resize((400, 400), Image.LANCZOS)
    
    img_io = io.BytesIO()
    avatar_img.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

def process_banner_image(banner_bytes):
    """Process banner only"""
    try:
        if banner_bytes:
            banner_img = Image.open(io.BytesIO(banner_bytes)).convert("RGBA")
        else:
            banner_img = Image.new("RGBA", (800, 400), (40, 40, 50, 255))
    except:
        banner_img = Image.new("RGBA", (800, 400), (40, 40, 50, 255))
    
    try:
        b_w, b_h = banner_img.size
        if b_w > 100 and b_h > 100:
            banner_img = banner_img.rotate(3, expand=True)
            bw_rot, bh_rot = banner_img.size
            crop_left = bw_rot * BANNER_START_X
            crop_top = bh_rot * BANNER_START_Y
            crop_right = bw_rot * BANNER_END_X
            crop_bottom = bh_rot * BANNER_END_Y
            banner_img = banner_img.crop((crop_left, crop_top, crop_right, crop_bottom))
            
            b_w, b_h = banner_img.size
            aspect = (b_w / b_h) if b_h > 0 else 2.0
            new_banner_w = int(400 * aspect * 2)
            banner_img = banner_img.resize((new_banner_w, 400), Image.LANCZOS)
        else:
            banner_img = banner_img.resize((800, 400), Image.LANCZOS)
    except:
        banner_img = banner_img.resize((800, 400), Image.LANCZOS)
    
    img_io = io.BytesIO()
    banner_img.save(img_io, "PNG")
    img_io.seek(0)
    return img_io

def fetch_player_info(uid: str):
    try:
        region = get_region_by_uid_sync(uid)
        if not region or region not in SUPPORTED_REGIONS:
            return None
        
        data_raw = get_account_information_sync(uid, "7", region, "/GetPlayerPersonalShow")
        return format_response(data_raw)
    except Exception as e:
        print(f"Error fetching player info: {e}")
        return None

def fetch_outfit_image(outfit_id: str, size: tuple = OUTFIT_SIZE):
    cache_key = f"outfit_{outfit_id}"
    if cache_key in image_cache:
        img_data = image_cache[cache_key]
        return Image.open(io.BytesIO(img_data)).convert("RGBA")
    
    try:
        url = f"{ICON_BASE_URL}/{outfit_id}"
        client = get_client()
        resp = client.get(url, timeout=IMAGE_TIMEOUT)
        if resp.status_code == 200:
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            if size:
                img = img.resize(size, Image.LANCZOS)
            img_io = io.BytesIO()
            img.save(img_io, 'PNG')
            image_cache[cache_key] = img_io.getvalue()
            return img
    except Exception as e:
        print(f"DEBUG: Error fetching outfit {outfit_id}: {e}")
    return None

def create_outfit_image(data):
    profile_info = data.get("AccountProfileInfo", {})
    outfit_ids = profile_info.get("EquippedOutfit", []) or []
    
    outfit_ids = [str(oid) for oid in outfit_ids]
    
    required_starts = ["211", "214", "208", "203", "204", "205", "212"]
    fallback_ids = ["211000000", "214000000", "208000000", "203000000",
                    "204000000", "205000000", "212000000"]
    
    used_ids = set()
    
    def get_outfit_id(idx, code):
        matched = None
        for oid in outfit_ids:
            if oid.startswith(code) and oid not in used_ids:
                matched = oid
                used_ids.add(oid)
                break
        if matched is None:
            matched = fallback_ids[idx]
        return matched
    
    outfit_images = []
    for idx, code in enumerate(required_starts):
        outfit_id = get_outfit_id(idx, code)
        img = fetch_outfit_image(outfit_id)
        if img:
            outfit_images.append(img)
        else:
            placeholder = Image.new("RGBA", OUTFIT_SIZE, (50, 50, 50, 255))
            outfit_images.append(placeholder)
    
    bg_path = os.path.join(os.path.dirname(__file__), BACKGROUND_FILENAME)
    try:
        background = Image.open(bg_path).convert("RGBA")
    except FileNotFoundError:
        background = Image.new("RGBA", CANVAS_SIZE, (30, 30, 40, 255))
    
    bg_w, bg_h = background.size
    
    if CANVAS_SIZE:
        canvas_w, canvas_h = CANVAS_SIZE
        scale = max(canvas_w / bg_w, canvas_h / bg_h) if BACKGROUND_MODE == 'cover' \
                else min(canvas_w / bg_w, canvas_h / bg_h)
        new_w, new_h = int(bg_w * scale), int(bg_h * scale)
        bg_resized = background.resize((new_w, new_h), Image.LANCZOS)
        offset_x = (canvas_w - new_w) // 2
        offset_y = (canvas_h - new_h) // 2
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))
        canvas.paste(bg_resized, (offset_x, offset_y), bg_resized)
    else:
        canvas = background.copy()
        canvas_w, canvas_h = bg_w, bg_h
        offset_x = offset_y = 0
        scale = 1.0
    
    positions = [
        {'x': 350, 'y': 30, 'width': 150, 'height': 150},
        {'x': 575, 'y': 130, 'width': 150, 'height': 150},
        {'x': 665, 'y': 350, 'width': 150, 'height': 150},
        {'x': 575, 'y': 550, 'width': 150, 'height': 150},
        {'x': 350, 'y': 654, 'width': 150, 'height': 150},
        {'x': 135, 'y': 570, 'width': 150, 'height': 150},
        {'x': 135, 'y': 130, 'width': 150, 'height': 150}
    ]
    
    for idx, img in enumerate(outfit_images):
        if not img:
            continue
        pos = positions[idx]
        paste_x = offset_x + int(pos['x'] * scale)
        paste_y = offset_y + int(pos['y'] * scale)
        paste_w = max(1, int(pos['width'] * scale))
        paste_h = max(1, int(pos['height'] * scale))
        resized = img.resize((paste_w, paste_h), Image.LANCZOS)
        canvas.paste(resized, (paste_x, paste_y), resized)
    
    draw = ImageDraw.Draw(canvas)
    account_info = data.get("AccountInfo", {})
    player_name = safe_text(account_info.get("AccountName", "Player"))
    level = account_info.get("AccountLevel", "0")
    
    font = load_unicode_font(30)
    
    text = f"{player_name} | Lv.{level}"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_x = (canvas_w - text_w) // 2
    text_y = canvas_h - 60
    
    draw.rectangle([text_x - 20, text_y - 10, text_x + text_w + 20, text_y + 40], fill=(0, 0, 0, 180))
    draw.text((text_x, text_y), text, font=font, fill="white")
    
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    output.seek(0)
    return output

# ================= FLASK ROUTES =================
@app.route('/card', methods=['GET'])
def get_card():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "UID required"}), 400
    
    result, error = handle_card(uid)
    if error:
        return jsonify({"error": error}), 400
    
    return Response(
        result, 
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=300"}
    )

@app.route('/avatar', methods=['GET'])
def get_avatar():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "UID required"}), 400
    
    result, error = handle_avatar(uid)
    if error:
        return jsonify({"error": error}), 400
    
    return Response(
        result, 
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=300"}
    )

@app.route('/banner', methods=['GET'])
def get_banner():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "UID required"}), 400
    
    result, error = handle_banner(uid)
    if error:
        return jsonify({"error": error}), 400
    
    return Response(
        result, 
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=300"}
    )

@app.route('/info', methods=['GET'])
def get_account_info():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "UID required"}), 400
    
    result, error = handle_info(uid)
    if error:
        return jsonify({"error": error}), 400
    
    return jsonify(result), 200

@app.route('/outfit', methods=['GET'])
def get_outfit():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "UID required"}), 400
    
    result, error = handle_outfit(uid)
    if error:
        return jsonify({"error": error}), 400
    
    return Response(
        result, 
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=300"}
    )

@app.route('/refresh', methods=['GET', 'POST'])
def refresh_tokens():
    try:
        initialize_tokens_sync()
        return jsonify({"message": "Tokens refreshed for all regions."}), 200
    except Exception as e:
        return jsonify({"error": f"Refresh failed: {e}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    token_count = sum(1 for v in cached_tokens.values() if v.get('token') != 'Bearer 0')
    return jsonify({
        "status": "running", 
        "regions": len(cached_tokens),
        "active_tokens": token_count,
        "image_cache": len(image_cache)
    }), 200

@app.route('/tokens', methods=['GET'])
def view_tokens():
    tokens_status = {}
    for region, info in cached_tokens.items():
        tokens_status[region] = {
            'token': info.get('token', 'None')[:20] + "..." if info.get('token') else "None",
            'expires_at': info.get('expires_at', 0),
            'is_valid': time.time() < info.get('expires_at', 0)
        }
    return jsonify(tokens_status), 200

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "name": "Free Fire API",
        "version": "2.0",
        "status": "stable",
        "endpoints": {
            "/card?uid=UID": "Get player info card (PNG) - NEW!",
            "/info?uid=UID": "Get account info (JSON)",
            "/avatar?uid=UID": "Get avatar image only (PNG)",
            "/banner?uid=UID": "Get banner image only (PNG)",
            "/outfit?uid=UID": "Get outfit collage (PNG)",
            "/refresh": "Refresh tokens",
            "/health": "Health check",
            "/tokens": "View tokens status"
        }
    }), 200

# ================= STARTUP =================
def start_background_refresh():
    def run_refresh():
        while True:
            time.sleep(25200)
            try:
                print("🔄 Refreshing tokens...")
                initialize_tokens_sync()
                print("✅ Tokens refreshed successfully")
            except Exception as e:
                print(f"❌ Error refreshing tokens: {e}")
    
    thread = threading.Thread(target=run_refresh, daemon=True)
    thread.start()
    print("✅ Background token refresh started")

if __name__ == '__main__':
    print("=" * 60)
    print("🔥 FREE FIRE API SERVER (FLASK) - STABLE")
    print("=" * 60)
    print("📌 Features:")
    print("   ✅ Fully synchronous - NO asyncio errors")
    print("   ✅ Image caching - faster responses")
    print("   ✅ Auto token refresh every 7 hours")
    print("   ✅ Player info card generator")
    print("   ✅ Outfit collage generator")
    print("   ✅ Using arial_unicode_bold.otf & NotoSansCherokee.ttf")
    print("=" * 60)
    print("📌 Endpoints:")
    print("   GET /card?uid=UID         - Get player info card (PNG) ✨NEW")
    print("   GET /info?uid=UID         - Get account info (JSON)")
    print("   GET /avatar?uid=UID       - Get avatar image only (PNG)")
    print("   GET /banner?uid=UID       - Get banner image only (PNG)")
    print("   GET /outfit?uid=UID       - Get outfit collage (PNG)")
    print("   GET /refresh              - Refresh tokens manually")
    print("   GET /health               - Health check")
    print("   GET /tokens               - View tokens status")
    print("   GET /                     - API Info")
    print("=" * 60)
    print("🚀 Server running on http://localhost:5080")
    print("=" * 60)
    
    print("🔄 Initializing tokens...")
    initialize_tokens_sync()
    print("✅ Tokens initialized")
    
    start_background_refresh()
    
    app.run(host='0.0.0.0', port=5080, debug=False, use_reloader=False)