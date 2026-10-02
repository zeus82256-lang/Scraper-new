# -*- coding: utf-8 -*-
"""
==========================================
🍅 TomatoMTL (tomatomtl.com) — قارئ Fanqie مصادق يحفظ النص الصيني الأصلي
==========================================
موقع ترجمة آلية لروايات Fanqie (番茄) — قراءة الفصول تتطلب حساباً مسجلاً،
والنص الصيني يصل مشفراً AES-128-CBC داخل الصفحة نفسها.

🔬 تم التحقق من الموقع حياً (v2.8):
- صفحة الكتاب  /book/{book_id}            ← بيانات const داخل سكربت داخلي
    book_name / authors_zh / book_cover / description / book_tags / isLoggedIn
    + وسوم #book_categories وصفوف .book-meta-item (Status) و#book_last_updated
- الفهرس       /catalog/{book_id}         ← JSON مباشر [{title, id}] — بلا ترقيم
- صفحة الفصل   /book/{book_id}/{chap_id}  ← encryptedData{iv, enc} + unlock_code
- فك التشفير مطابق تماماً لـ chapter_decrypt في /assets/js/tomato.js الرسمي:
    المفتاح = base64decode(unlock_code)[:16] — AES-CBC — حشو PKCS7 — كل القيم base64

🔑 الجلسة والكوكيز (سلسلة المصادر):
    1) إعداد الواجهة (يُدفع من خادم التطبيق أو /tomatomtl/cookies مباشرة)
    2) متغير البيئة TOMATOMTL_COOKIES أو TOMATOMTL_COOKIES_FILE
    3) الثابت في core/config.py (DEFAULT_TOMATOMTL_COOKIES)
   المهم بين الكوكيز: remember_* (تذكّر الدخول ≈ 5 سنوات — هو الثابت بالكود)
   وPHPSESSID (جلسة قصيرة) وcf_clearance (حماية Cloudflare قصيرة ومرتبطة بـ IP
   المتصفح الذي أنشأها — لا تنفع من سيرفر بعنوان مختلف).

⚠️ لا نستخدم smart_get هنا: طرقه البديلة (بروكسيات ترجمة/ScraperAPI) خدمات طرف
ثالث لا تحفظ جلسة الحساب الخاص — الجلسة تمر مباشرة فقط (أو FlareSolverr مع حقن
الكوكيز عند تحدي Cloudflare لعنوان السيرفر).

حساب الكوكيز يستخدم لقراءة محتوى خاص بالمستخدم نفسه فقط — لا نطبع أي قيمة
منه في السجلات، ورسائل الخطأ خالية من القيم الحساسة.
"""

import base64
import html as _html
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from core.config import DEFAULT_TOMATOMTL_COOKIES
from core.utils import UA_CHROME, clean_text, get_meta
from core.registry import register_site

BASE = 'https://tomatomtl.com'
_WANTED_COOKIES = ('PHPSESSID', 'cf_clearance', 'translator_button')
# رواية فحص الجلسة (كتاب حقيقي ثابت — صفحته تظهر isLoggedIn دائماً)
CHECK_BOOK_ID = '7538828586489220121'


class TomatoMTLError(RuntimeError):
    """أخطاء واضحة للمستخدم لا تحتوي أي قيم حساب أو أجسام ردود."""


class TomatoMTLSessionError(TomatoMTLError):
    """انتهت/بطلت جلسة الحساب — الجديد من الواجهة أو الكوكيز الثابتة لا يكفي."""


class TomatoMTLLimitError(TomatoMTLError):
    """حد القراءة من الموقع (تم التحقق حياً من auth.js الرسمي للحديقة):
    121 فصل/ساعة + 676 فصل/يوم — حد مشترك بين قارئ الموقع وقسم الحديقة.
    قابل للتجاوز بالانتظار ساعة كاملة (أو حتى تجدد حصة اليوم) ثم إعادة
    المحاولة لنفس الرابط — العامل يعيد المحاولة تلقائياً حتى الانتهاء."""


# نصوص صفحة «بلغت الحد» التي يعرضها الموقع بدل الفصل (ثبتت حياً من المستخدم:
# «يمكنك قراءة 121 فصل في الساعة فقط / اقرأ أكثر في الساعة التالية»).
# أنماط عالية الدقة فقط — النص العادي للفصل قد يحوي عبارات سردها مشابهة
# («come back in 5 minutes»)، والبديل الآمن (غياب encryptedData) يلقط الباقي.
_LIMIT_TEXT_RE = re.compile(
    r'(?:you\s+(?:have\s+)?(?:reached|hit|exceeded)[^.<>]{0,40}limit'
    r'|(?:reading|hourly|daily)\s+limit'
    r'|limit\s+(?:reached|exceeded)'
    r'|\d+\s*chapters?\s*(?:per|/)\s*(?:hour|day)'
    r'|chapters?\s+per\s+(?:hour|day)'
    r'|read\s+more\s+in\s+the\s+next\s+(?:hour|day)'
    r'|try\s+again\s+in\s+the\s+next\s+(?:hour|day))', re.I)

# الإعداد: مدة انتظار الحد (ثوانٍ) — الافتراضي 63 دقيقة = «ساعة كاملة أو أكثر بقليل»
# كما طلب المستخدم. الحد الأدنى المقبول ساعة كاملة حتى لا نحرق المحاولات عبثاً.
LIMIT_WAIT_DEFAULT = 63 * 60
LIMIT_WAIT_MIN = 60 * 60
# أقصى عدد مرات انتظار لنفس الفصل قبل الاستسلام (26 انتظاراً ≈ أكثر من يوم —
# يغطي حتى حد 676/اليوم: بعد امتلاء حصة الساعة تُنتظر التالية، وحين تنفد حصة
# اليوم كاملاً تجدد تلقائياً عند تصفيرها).
LIMIT_WAITS_MAX_DEFAULT = 26


# ==========================================
# 🍪 مصادر الكوكيز (إعداد ← بيئة ← ثابت بالكود)
# ==========================================
_RUNTIME = {'cookies': '', 'app_cookies': '', 'last_app_pull': 0.0}
_LOCK = threading.Lock()


def set_runtime_cookies(value):
    """ضبط الكوكيز من واجهة الإعدادات (فارغ = إلغاء الاستخدام والرجوع للثابتة)"""
    with _LOCK:
        _RUNTIME['cookies'] = str(value or '').strip()
    state = 'فُرِّغت (تراجع للثابتة بالكود)' if not str(value or '').strip() else 'حُدِّثت'
    print(f"🍅 TomatoMTL cookies {state}")


def _pull_cookies_from_app():
    """سحب كوكيز TomatoMTL المحفوظة في خادم التطبيق (حقل واجهة السكرابر) —
    مرة كل 5 دقائق كحد أقصى حتى لا نثقل الخادم"""
    now = time.time()
    with _LOCK:
        if now - _RUNTIME['last_app_pull'] < 300:
            return
        _RUNTIME['last_app_pull'] = now
    try:
        from core.config import API_SECRET, NODE_BACKEND_URL
        r = requests.get(f"{NODE_BACKEND_URL}/api/admin/scraper-keys",
                         headers={'x-api-secret': API_SECRET}, timeout=20)
        if r.status_code == 200:
            val = str((r.json() or {}).get('tomatomtlCookies') or '').strip()
            with _LOCK:
                _RUNTIME['app_cookies'] = val
            if val:
                print("🍅 Pulled TomatoMTL cookies from app server settings")
    except Exception as e:
        print(f"   TomatoMTL app-pull failed: {str(e)[:70]}")


def get_cookie_header(with_source=False):
    """ترويسة Cookie الجاهزة حسب سلسلة الأولوية — لا تفشل أبداً (الثابتة موجودة)"""
    with _LOCK:
        runtime = _RUNTIME['cookies']
    if runtime:
        return (runtime, 'settings') if with_source else runtime

    with _LOCK:
        app_val = _RUNTIME['app_cookies']
        should_pull = not app_val
    if should_pull:
        _pull_cookies_from_app()
        with _LOCK:
            app_val = _RUNTIME['app_cookies']
    if app_val:
        return (app_val, 'settings') if with_source else app_val

    env = os.environ.get('TOMATOMTL_COOKIES', '').strip()
    if not env:
        path = os.environ.get('TOMATOMTL_COOKIES_FILE', '').strip()
        if path:
            try:
                env = Path(path).read_text(encoding='utf-8').strip()
            except (OSError, UnicodeError):
                env = ''
    if env:
        return (env, 'env') if with_source else env

    return (DEFAULT_TOMATOMTL_COOKIES, 'default') if with_source else DEFAULT_TOMATOMTL_COOKIES


def _cookie_parts(header):
    """تفكيك الترويسة إلى أسماء/قيم مع الاحتفاظ بكوكيز الحساب والقارئ فقط —
    كوكيز الإعلانات والتحليلات تُهمل"""
    parts = {}
    for part in str(header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z0-9_\-]+', name):
            continue
        if name in _WANTED_COOKIES or name.startswith('remember_'):
            parts[name] = value
    return parts


def cookie_summary():
    """ملخص مخفى لحالة الكوكيز (للواجهة — بلا قيم كاملة)"""
    header, source = get_cookie_header(with_source=True)
    parts = _cookie_parts(header)
    masked = []
    for n, v in parts.items():
        show = (v[:6] + '…' + v[-4:]) if len(v) > 12 else '…'
        masked.append(f"{n}={show}")
    has_session = bool(parts.get('PHPSESSID')) or any(n.startswith('remember_') for n in parts)
    return {
        'source': source,  # settings / env / default
        'count': len(parts),
        'cookies': masked,
        'has_session': has_session,
        'has_remember': any(n.startswith('remember_') for n in parts),
        'has_cf_clearance': 'cf_clearance' in parts,
    }


def _ids(url, chapter=False):
    """تحليل رابط TomatoMTL: صفحات /book/{id} أو روابط الحديقة /garden/{site}/{hex}.
    للحديقة يعيد (None, None) ويُعالج التدفق الحديقي عبر _garden_parse —
    (الفحص يتم في fetch_* قبل الاستدعاء)."""
    p = urlparse(url)
    if (p.scheme != 'https' or p.netloc.lower() not in (
            'tomatomtl.com', 'www.tomatomtl.com', 'tomatomtl.com:443', 'www.tomatomtl.com:443')):
        raise TomatoMTLError('TomatoMTL: استخدم رابط HTTPS على tomatomtl.com فقط.')
    if (p.path or '').startswith('/garden/'):
        return None, None  # رابط حديقة — التدفق الخاص به
    m = re.fullmatch(r'/book/(\d+)(?:/(\d+))?/?', p.path)
    if not m or (chapter and not m.group(2)):
        raise TomatoMTLError('TomatoMTL: الرابط المدعوم /book/{book_id} أو /book/{book_id}/{chapter_id} '
                             'أو رابط حديقة /garden/{site}/{hex}.')
    return m.group(1), m.group(2)


# ==========================================
# 🌸 قسم الحديقة (Garden) — أرشيف TomatoMTL لمواقع صينية ميتة
# ==========================================
# بنية الرابط (ثبتت حياً): /garden/{source}/{hex} حيث hex هو رابط الصفحة على
# الموقع الأصلي المشفر hex — مثال: 687474703a2f2f... تفكك إلى
# http://www.bixiangge.top/dsyq/22645 (والمواقع الأصلية ميتة أصلاً — لذلك
# لا بديل عن واجهة الحديقة نفسها).
#
# 🔬 المعمارية المثبتة حياً من auth.js الرسمي للحديقة + تجارب API:
#   - واجهة Go على tomato-garden-api.tomatomtl.com/api (تحت Cloudflare)
#   - التوكن: GET {BASE}/api/garden-token.php بجلسة PHP → {token, expires_in}
#     (توقيع HMAC قصير العمر ≈ 900ث) ويُرفق بترويسة X-Garden-Token
#   - الردود {iv, enc} مشفرة بنفس آلية chapter_decrypt (AES-CBC، المفتاح من
#     unlock_code داخل صفحة الحديقة نفسها) والنتيجة {success, data, error}
#   - حد القراءة المشترك 121/ساعة + 676/يوم (429 مع نص الحد) — نفس معالج الانتظار
#   - /api/sources مؤكد وجوده (401 بلا توكن، وفُكّ تشفيره حياً: unauthorized)
#   - مسارات كتاب/فصول الفردية لم تُثبت من الساندبوكس (Cloudflare) — لذا هي
#     قابلة للضبط بالبيئة مع قائمة مرشحين، والفشل يعطي رسالة تشخيصية واضحة.
GARDEN_API_BASE = os.environ.get(
    'TOMATOMTL_GARDEN_API', 'https://tomato-garden-api.tomatomtl.com/api').rstrip('/')


def _env_paths(name, default):
    """قائمة مسارات مرشحة من البيئة (فواصل) أو الافتراضي"""
    raw = os.environ.get(name, '').strip()
    items = [p.strip().strip('/') for p in raw.split(',')] if raw else list(default)
    return [p for p in items if p]


GARDEN_BOOK_PATHS = _env_paths('TOMATOMTL_GARDEN_BOOK_PATHS', ('book', 'serie', 'novel'))
GARDEN_CHAPTERS_PATHS = _env_paths('TOMATOMTL_GARDEN_CHAPTERS_PATHS', ('chapters', 'serie/chapters', 'book/chapters'))
GARDEN_CHAPTER_PATHS = _env_paths('TOMATOMTL_GARDEN_CHAPTER_PATHS', ('chapter', 'serie/chapter', 'book/chapter'))

_GARDEN_RUNTIME = {'token': '', 'token_at': 0.0, 'unlock': '', 'unlock_at': 0.0,
                   'book_path': '', 'chapters_path': '', 'chapter_path': ''}
_GARDEN_URL_RE = re.compile(r'^/garden/([A-Za-z0-9_\-]+)/([0-9a-fA-F]{16,})/?$')


def is_garden_url(url):
    p = urlparse(url or '')
    return p.netloc.lower() in ('tomatomtl.com', 'www.tomatomtl.com') and (p.path or '').startswith('/garden/')


def _garden_parse(url):
    """رابط حديقة ← (source, الرابط الأصلي المفكوك، رابط صفحة الحديقة)"""
    p = urlparse(url)
    m = _GARDEN_URL_RE.match(p.path or '')
    if not m:
        raise TomatoMTLError('TomatoMTL Garden: الرابط المدعوم /garden/{site}/{hex} '
                             'حيث hex هو رابط الصفحة الأصلية مشفراً hex.')
    source, hexpart = m.group(1), m.group(2)
    try:
        original = bytes.fromhex(hexpart).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        raise TomatoMTLError('TomatoMTL Garden: قسم hex لا يفكك إلى رابط أصلي صالح.') from None
    if not re.match(r'^https?://[^\s]+$', original):
        raise TomatoMTLError('TomatoMTL Garden: الرابط الأصلي المفكوك غير صالح.')
    return source, original, f'{BASE}/garden/{source}/{hexpart}'


def _garden_hex(original):
    """الرابط الأصلي ← قسم hex كما يستخدمه الموقع"""
    return bytes(str(original), 'utf-8').hex()


def _script_value(source, name, default=None):
    """قراءة قيم JSON من تعريفات JS الداخلية — تعمل على HTML الخام مباشرة
    (مهم: البحث عبر BeautifulSoup غير موثوق هنا — بعض المحللات تُسقط محتوى
    <script> الذي يحتوي مقارنات < >) — لا ننفذ أي كود موقع، قراءة نصية فقط"""
    if source is None:
        return default
    if not isinstance(source, str):
        # توافق خلفي: soup — نجمع نصوصه ثم نبحث
        source = source.decode('utf-8', 'ignore') if isinstance(source, bytes) else str(source)
    match = re.search(r'\b(?:const|let|var)\s+' + re.escape(name) + r'\s*=\s*', source)
    if not match:
        return default
    try:
        return json.JSONDecoder().raw_decode(source[match.end():])[0]
    except (ValueError, TypeError):
        raise TomatoMTLError('TomatoMTL: تغير تنسيق بيانات الصفحة.') from None


def _make_soup(html):
    """BeautifulSoup للانتقائيات البنيوية فقط (الوسوم/الصفوف) — بأكثر محلل متاح"""
    for parser in ('lxml', 'html.parser'):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    return BeautifulSoup(html, 'html.parser')


def _cookie_header_configured():
    header = get_cookie_header()
    if not header:
        raise TomatoMTLSessionError('TomatoMTL: لا توجد كوكيز — ضعها من واجهة السكرابر أو TOMATOMTL_COOKIES.')
    if any(ord(c) < 32 or ord(c) == 127 for c in header):
        raise TomatoMTLSessionError('TomatoMTL: إعداد الكوكيز يجب أن يكون ترويسة Cookie واحدة فقط.')
    return header


def _flaresolverr_with_cookies(url):
    """تجاوز تحدي Cloudflare لـ IP السيرفر عبر FlareSolverr مع حقن كوكيز الحساب —
    يعيد HTML الصفحة أو None (لا يوجد FLARESOLVR_URL أو فشل)"""
    base = os.environ.get('FLARESOLVR_URL', '').rstrip('/')
    if not base:
        return None
    payload_cookies = [{'name': n, 'value': v, 'domain': '.tomatomtl.com'}
                       for n, v in _cookie_parts(get_cookie_header()).items()]
    try:
        r = requests.post(base + '/v1',
                          json={'cmd': 'request.get', 'url': url,
                                'maxTimeout': 60000, 'cookies': payload_cookies},
                          timeout=90)
        if r.status_code == 200:
            data = r.json()
            solution = data.get('solution') or {}
            if data.get('status') == 'ok' and solution.get('response'):
                print(f"   🛰️ FlareSolverr: passed challenge for {url[:70]}")
                return solution['response']
    except Exception as e:
        print(f"   FlareSolverr failed: {str(e)[:80]}")
    return None


class TomatoMTLClient:
    def __init__(self):
        # نفحص الإعداد قبل أي طلب شبكة (فشل مبكر وواضح)
        cookies = _cookie_parts(_cookie_header_configured())
        if not cookies.get('PHPSESSID') and not any(k.startswith('remember_') and v for k, v in cookies.items()):
            raise TomatoMTLSessionError('TomatoMTL: الكوكيز لا تحتوي جلسة حساب (PHPSESSID أو remember_*).')
        try:
            from curl_cffi import requests as browser_requests
        except ImportError:
            self.session = requests.Session()
        else:
            self.session = browser_requests.Session(impersonate='chrome')
        self.session.headers.update({
            'User-Agent': os.environ.get('TOMATOMTL_USER_AGENT', '') or UA_CHROME,
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': BASE + '/',
        })
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain='tomatomtl.com', path='/')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    def get(self, path):
        url = urljoin(BASE + '/', path)
        for _ in range(5):
            p = urlparse(url)
            if (p.scheme != 'https' or p.netloc != 'tomatomtl.com'
                    or not re.fullmatch(r'/(?:book/\d+(?:/\d+)?|catalog/\d+)/?', p.path)):
                raise TomatoMTLError('TomatoMTL: رفض تحويل خارج صفحات الكتاب والفصول الموثوقة.')
            try:
                response = self.session.get(url, timeout=30, allow_redirects=False)
            except Exception:
                raise TomatoMTLError('TomatoMTL: تعذر الاتصال بالموقع.') from None
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('Location', ''))
                if urlparse(url).path.startswith('/user/login'):
                    raise TomatoMTLSessionError('TomatoMTL: انتهت الجلسة؛ جدد كوكيز الحساب من واجهة السكرابر.')
                continue
            if response.status_code == 401:
                raise TomatoMTLSessionError('TomatoMTL: الجلسة غير صالحة؛ جدد كوكيز الحساب من واجهة السكرابر.')
            if response.status_code in (403, 429):
                # 429 قد يكون حد القراءة نفسه (121/ساعة) وليس حماية — نفحص جسم الرد؛
                # إن كان نص الحد نرفع خطأ الحد القابل للانتظار بدل الفشل النهائي.
                if response.status_code == 429 and _LIMIT_TEXT_RE.search(response.text or ''):
                    raise TomatoMTLLimitError('TomatoMTL: حد القراءة من الموقع (HTTP 429).')
                # ربما تحدي Cloudflare لعنوان السيرفر — FlareSolverr مع نفس الكوكيز يجاوزه إن وفّرته
                body = _flaresolverr_with_cookies(url)
                if body:
                    return _FlareResponse(body)
                raise TomatoMTLError(f'TomatoMTL: رفض الموقع الطلب (HTTP {response.status_code})؛ '
                                     'إن كان حجب Cloudflare لعنوان السيرفر فوفّر FLARESOLVR_URL أو انتظر قبل إعادة المحاولة.')
            if response.status_code != 200:
                raise TomatoMTLError(f'TomatoMTL: فشل الطلب (HTTP {response.status_code}).')
            # ظهور سكربت jsd/main.js الخاص بـ Cloudflare طبيعي حتى في صفحات الكتاب السليمة —
            # وجوده وحده ليس فشل تحقق. الفشل = صفحة تحدٍّ كاملة.
            title = re.search(r'<title[^>]*>(.*?)</title>', response.text, re.I | re.S)
            if (response.headers.get('cf-mitigated') == 'challenge'
                    or 'window._cf_chl_opt' in response.text
                    or (title and title.group(1).strip().lower().startswith('just a moment'))):
                body = _flaresolverr_with_cookies(url)
                if body:
                    return _FlareResponse(body)
                raise TomatoMTLError('TomatoMTL: ظهر تحقق Cloudflare؛ قد تحتاج جلسة حديثة ووكيل المستخدم نفسه '
                                     '(cf_clearance مرتبط بـ IP المتصفح الذي أنشأه) أو FLARESOLVR_URL.')
            return response
        raise TomatoMTLError('TomatoMTL: عدد تحويلات زائد من الموقع.')

    def _authed_html(self, path):
        """جلب HTML صفحة مع فحص الحماية: صفحة تحدٍّ، جدار دخول، أو جلسة ميتة —
        الفحص على HTML الخام (لا يعتمد على محلل HTML)"""
        html = self.get(path).text
        if (_script_value(html, 'isLoggedIn') is False
                or 'You need to log in to read chapter content' in html
                or re.search(r'<input[^>]+name=["\']password["\']', html)):
            raise TomatoMTLSessionError('TomatoMTL: الحساب غير مسجل الدخول؛ جدد كوكيز الحساب من واجهة السكرابر.')
        return html

    def metadata(self, book_id):
        html = self._authed_html(f'/book/{book_id}')
        soup = _make_soup(html)
        # العنوان الظاهر h1 قد يكون ترجمة مؤقتة؛ البيانات الصينية الأصلية في سكربت الصفحة
        title = _script_value(html, 'book_name')
        if not isinstance(title, str) or not title.strip():
            raise TomatoMTLError('TomatoMTL: لم توجد بيانات رواية صحيحة في الصفحة.')
        description = _script_value(html, 'description', '')
        author = _script_value(html, 'authors_zh', '')
        tags = [a.get_text(' ', strip=True) for a in soup.select('#book_categories a')]
        status = 'مستمرة'
        for row in soup.select('.book-meta-item'):
            text = row.get_text(' ', strip=True)
            if text.startswith('Status:') and re.search(r'\b(?:Completed|Complete|Finished)\b', text, re.I):
                status = 'مكتملة'
        updated = soup.select_one('#book_last_updated')
        return {
            'title': title.strip(), 'description': description,
            'cover': _script_value(html, 'book_cover') or get_meta(soup, prop='og:image'),
            'author': author, 'status': status, 'category': tags[0] if tags else 'عام',
            'tags': tags, 'book_id': book_id, 'sourceUrl': f'{BASE}/book/{book_id}',
            'lastUpdate': updated.get_text(strip=True) if updated else None,
        }

    def chapters(self, book_id):
        response = self.get(f'/catalog/{book_id}')
        try:
            entries = response.json()
        except (ValueError, TypeError):
            raise TomatoMTLError('TomatoMTL: قائمة الفصول ليست JSON صالحًا.') from None
        if not isinstance(entries, list) or not entries:
            raise TomatoMTLError('TomatoMTL: قائمة الفصول فارغة أو تغير تنسيقها.')
        chapters, seen = [], set()
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise TomatoMTLError('TomatoMTL: مدخل غير صالح في قائمة الفصول.')
            cid, title = str(entry.get('id', '')), entry.get('title')
            if not re.fullmatch(r'\d+', cid) or not isinstance(title, str):
                raise TomatoMTLError('TomatoMTL: معرف أو عنوان فصل غير صالح.')
            if cid in seen:
                raise TomatoMTLError('TomatoMTL: معرف فصل مكرر في الفهرس؛ أوقف السحب لحماية الترقيم.')
            seen.add(cid)
            # معرفات الفصول 19 رقماً غير متسلسلة — الترقيم من ترتيب الفهرس نفسه (مثل واجهة الموقع)
            chapters.append({'number': index, 'title': title,
                             'url': f'{BASE}/book/{book_id}/{cid}'})
        return chapters

    def content(self, book_id, chapter_id):
        html = self._authed_html(f'/book/{book_id}/{chapter_id}')
        # 🚦 حد القراءة: الموقع يعرض صفحة «بلغت الحد» (121 فصل/ساعة — حد مشترك مع
        # الحديقة + 676/يوم) بدل بيانات الفصل. نكشفها أولاً لأن معالجتها انتظار
        # وإعادة محاولة، وليست فشلاً نهائياً. (ثبت حياً: الصفحة مسجلة الدخول
        # والعنوان طبيعي والمحتوى المفكك فقط غائب.)
        limit_match = _LIMIT_TEXT_RE.search(html)
        if limit_match:
            snippet = re.sub(r'\s+', ' ', limit_match.group(0)).strip()[:90]
            raise TomatoMTLLimitError(f'TomatoMTL: بلغنا حد قراءة الموقع ({snippet}).')
        # تحقق تطابق الصفحة مع الرابط — ن enforceه فقط حين تعرّف الصفحة المتغيرين
        # (قوالب معينة تُخفيهما وقد تغيّر الموقع قالبَه لاحقاً)
        page_book = _script_value(html, 'book_id')
        page_chap = _script_value(html, 'chap_id')
        if page_book is not None and str(page_book) != book_id:
            raise TomatoMTLError('TomatoMTL: صفحة الفصل لا تطابق الرابط المطلوب.')
        if page_chap is not None and str(page_chap) != chapter_id:
            raise TomatoMTLError('TomatoMTL: صفحة الفصل لا تطابق الرابط المطلوب.')
        encrypted = _script_value(html, 'encryptedData')
        key = _script_value(html, 'unlock_code')
        if not isinstance(encrypted, dict) or not isinstance(key, str):
            # بلا نص حد صريح: صفحة قارئ مسجلة الدخول بلا بيانات مشفرة هي عملياً
            # نفس جدار الحد بقالب آخر (هذا بالضبط ما رآه المستخدم حياً) — نعامله
            # كحد قابل للانتظار، والفشل الحقيقي (تغير القالب) يستسلم بعد سلسلة
            # الانتظارات عبر سقف المحاولات في العامل.
            raise TomatoMTLLimitError('TomatoMTL: لا توجد بيانات فصل في الصفحة — على الأغلب حد القراءة الساعي '
                                      '(121 فصل/ساعة) وليس تغيّر القالب; سنتحقق بالانتظار وإعادة المحاولة.')
        try:
            # مطابق لـ chapter_decrypt في tomato.js: القيم base64 (وليست hex)
            key_bytes = base64.b64decode(key, validate=True)[:16]
            iv = base64.b64decode(encrypted['iv'], validate=True)
            ciphertext = base64.b64decode(encrypted['enc'], validate=True)
            decryptor = Cipher(algorithms.AES(key_bytes), modes.CBC(iv)).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = PKCS7(128).unpadder()
            payload = (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')
        except (KeyError, ValueError, TypeError, UnicodeError):
            raise TomatoMTLError('TomatoMTL: تعذر فك نص الفصل؛ لم يُحفظ محتوى غير صالح.') from None
        text = clean_text(_payload_to_text(payload))
        if not text:
            raise TomatoMTLError('TomatoMTL: نص الفصل فارغ.')
        return text


class _FlareResponse:
    """غلاف بسيط لرد FlareSolverr (نفس واجهة .text و.json التي يستخدمها الكود)"""

    def __init__(self, html):
        self.text = html
        self.status_code = 200

    def json(self):
        return json.loads(self.text)


def _payload_to_text(raw):
    """نص الفصل المفكك: يصل عادة نصاً عادياً بأسطر، وقد يصل وسم HTML بسيطاً
    إذا غيّر الموقع قالب القارئ — نوحّد الشكلين إلى نص بأسطر نظيفة (دون تنفيذ
    أي شيء: إزالة وسوم فقط ثم فك كيانات HTML الشائعة)."""
    text = str(raw).replace('\r\n', '\n').replace('\r', '\n')
    if re.search(r'<(?:p\b|br\b|div\b|/p\b)', text, re.I):
        text = re.sub(r'(?i)<br\s*/?>', '\n', text)
        text = re.sub(r'(?i)</p\s*>', '\n\n', text)
        text = re.sub(r'(?i)<p[^>]*>', '', text)
        text = re.sub(r'(?i)<[^>]+>', '', text)
        text = _html.unescape(text)
    return text


def quick_session_check():
    """فحص حي للجلسة من واجهة الإعدادات: يفتح صفحة كتاب حقيقية ويتأكد أن الحساب
    مسجل الدخول — النتيجة تُعرض مباشرة للإدارة (الموقع والتطبيق)."""
    header, source = get_cookie_header(with_source=True)
    try:
        with TomatoMTLClient() as client:
            html = client._authed_html(f'/book/{CHECK_BOOK_ID}')
        logged_in = _script_value(html, 'isLoggedIn')
        if logged_in is False:
            return {'ok': False, 'loggedIn': False,
                    'message': 'الكوكيز وصلت للموقع لكن الحساب غير مسجل الدخول — '
                               'انسخ ترويسة Cookie جديدة بعد تسجيل الدخول والصقها في الإعدادات.'}
        return {'ok': True, 'loggedIn': True, 'source': source,
                'message': 'الجلسة تعمل — الحساب مسجل الدخول ويمكن السحب فوراً.'}
    except TomatoMTLSessionError as e:
        return {'ok': False, 'loggedIn': False, 'source': source, 'message': str(e)}
    except TomatoMTLError as e:
        return {'ok': False, 'loggedIn': None, 'source': source,
                'message': str(e) + ' — ملاحظة: cf_clearance مرتبط بـ IP المتصفح الذي أنشأه، '
                                    'فمن السيرفر قد يظهر تحدٍّ حتى لو كانت الكوكيز سليمة.'}


# ==========================================
# 🌸 عميل الحديقة (Garden Client)
# ==========================================
def _garden_token(client):
    """تبادل جلسة PHP بتوكن حديقة قصير العمر من /api/garden-token.php
    (نفس آلية auth.js الرسمية: token ≈ 900ث، يُكاشى حتى قبل انتهائه بدقيقتين)"""
    now = time.time()
    with _LOCK:
        if _GARDEN_RUNTIME['token'] and now - _GARDEN_RUNTIME['token_at'] < 780:
            return _GARDEN_RUNTIME['token']
    url = urljoin(BASE + '/', '/api/garden-token.php')
    try:
        response = client.session.get(url, timeout=30, allow_redirects=False)
    except Exception:
        raise TomatoMTLError('TomatoMTL Garden: تعذر طلب توكن الحديقة من الموقع.') from None
    if response.status_code == 401:
        raise TomatoMTLSessionError('TomatoMTL Garden: الجلسة غير صالحة عند طلب التوكن؛ جدد كوكيز الحساب.')
    if response.status_code != 200:
        raise TomatoMTLError(f'TomatoMTL Garden: فشل طلب التوكن (HTTP {response.status_code}).')
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise TomatoMTLError('TomatoMTL Garden: رد التوكن ليس JSON — ربما تحدٍّ Cloudflare؛ '
                             'وفّر FLARESOLVR_URL أو جدد الكوكيز من متصفح بنفس IP السيرفر.') from None
    token = str((data or {}).get('token') or '')
    if not (data or {}).get('success') or not token:
        raise TomatoMTLSessionError('TomatoMTL Garden: الموقع رفض إصدار توكن الحديقة — '
                                    'الحساب غير مسجل الدخول (جدد الكوكيز من واجهة السكرابر).')
    with _LOCK:
        _GARDEN_RUNTIME['token'] = token
        _GARDEN_RUNTIME['token_at'] = time.time()
    return token


def _garden_unlock(client, garden_page_url):
    """unlock_code من صفحة الحديقة نفسها (موجود دائماً داخل السكربت — ثبت حياً)"""
    now = time.time()
    with _LOCK:
        if _GARDEN_RUNTIME['unlock'] and now - _GARDEN_RUNTIME['unlock_at'] < 1800:
            return _GARDEN_RUNTIME['unlock']
    html = client._authed_html(urljoin(BASE + '/', urlparse(garden_page_url).path))
    value = _script_value(html, 'unlock_code')
    if not isinstance(value, str) or not value:
        raise TomatoMTLError('TomatoMTL Garden: لم أجد unlock_code في صفحة الحديقة — تغير قالبها.')
    with _LOCK:
        _GARDEN_RUNTIME['unlock'] = value
        _GARDEN_RUNTIME['unlock_at'] = time.time()
    return value


def _garden_api_get(client, path, params, unlock):
    """نداء واجهة الحديقة بالتوكن ثم فك الرد {iv, enc} بآلية chapter_decrypt —
    يعيد dict {success, data, error}"""
    token = _garden_token(client)
    url = f'{GARDEN_API_BASE}/{path.lstrip("/")}'
    try:
        response = client.session.get(url, params=params, timeout=40,
                                      headers={'X-Garden-Token': token, 'Accept': 'application/json',
                                               'Referer': BASE + '/'})
    except Exception:
        raise TomatoMTLError('TomatoMTL Garden: تعذر الاتصال بواجهة الحديقة.') from None
    if response.status_code == 401:
        with _LOCK:
            _GARDEN_RUNTIME['token'] = ''
        raise TomatoMTLSessionError('TomatoMTL Garden: توكن الحديقة مرفوض (401) — جدد كوكيز الحساب.')
    if response.status_code == 404:
        return None  # مسار غير موجود — للمرشحين
    if response.status_code in (403, 429):
        if response.status_code == 429 and _LIMIT_TEXT_RE.search(response.text or ''):
            raise TomatoMTLLimitError('TomatoMTL Garden: حد القراءة من الموقع (HTTP 429) — مشترك 121/ساعة.')
        raise TomatoMTLError(f'TomatoMTL Garden: رفضت الواجهة الطلب (HTTP {response.status_code}) — '
                             'ربما حماية Cloudflare لعنوان السيرفر؛ وفّر FLARESOLVR_URL.')
    if response.status_code != 200:
        raise TomatoMTLError(f'TomatoMTL Garden: فشل الطلب (HTTP {response.status_code}).')
    try:
        enc = response.json()
    except (ValueError, TypeError):
        raise TomatoMTLError('TomatoMTL Garden: رد الحديقة ليس JSON مشفراً كما هو متوقع.') from None
    if not isinstance(enc, dict) or 'iv' not in enc or 'enc' not in enc:
        # رد غير مشفر (شكل مستقبلي) — إن كان dict نجاحاً مرره كما هو
        if isinstance(enc, dict) and enc.get('success'):
            return enc
        raise TomatoMTLError('TomatoMTL Garden: شكل رد الحديقة غير معروف.')
    try:
        key_bytes = base64.b64decode(unlock, validate=True)[:16]
        iv = base64.b64decode(enc['iv'], validate=True)
        ciphertext = base64.b64decode(enc['enc'], validate=True)
        decryptor = Cipher(algorithms.AES(key_bytes), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        plain = (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')
        data = json.loads(plain)
    except (KeyError, ValueError, TypeError, UnicodeError):
        raise TomatoMTLError('TomatoMTL Garden: فشل فك تشفير رد الحديقة (unlock_code لا يطابق الرد).') from None
    return data if isinstance(data, dict) else {'success': True, 'data': data}


def _first_str(mapping, *keys):
    for k in keys:
        v = (mapping or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def _garden_novel_from_data(data, source, original, page_url):
    """مستخرج متسامح لبيانات الرواية من رد الحديقة (أشكال مفاتيح شائعة)"""
    node = data if isinstance(data, dict) else {}
    inner = node.get('data') if isinstance(node.get('data'), dict) else node
    title = _first_str(inner, 'title', 'book_name', 'name')
    if not title:
        return None
    status_text = _first_str(inner, 'status', 'book_status').lower()
    return {
        'title': title,
        'description': _first_str(inner, 'description', 'desc', 'intro'),
        'cover': _first_str(inner, 'cover', 'image', 'img', 'book_cover'),
        'author': _first_str(inner, 'author', 'authors_zh', 'author_zh'),
        'status': 'مكتملة' if any(w in status_text for w in ('complete', 'finished', '完')) else 'مستمرة',
        'category': 'عام',
        'tags': [],
        'book_id': f'garden:{source}:{_garden_hex(original)[:24]}',
        'sourceUrl': page_url,
        'lastUpdate': _first_str(inner, 'updated_at', 'last_updated', 'update_time') or None,
    }


def _garden_chapters_from_data(data):
    """مستخرج متسامح لقائمة فصول الحديقة: قائمة ({title, url|id|hex}|نصوص) أو
    dict يحمل chapters/data/items — يعيد [{number, title, url}] بروابط حديقة"""
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        node = data.get('data') if isinstance(data.get('data'), (list, dict)) else data
        if isinstance(node, dict):
            for k in ('chapters', 'items', 'list', 'data'):
                if isinstance(node.get(k), list):
                    items = node[k]
                    break
        elif isinstance(node, list):
            items = node
    if not items:
        return None
    chapters, seen = [], set()
    for index, entry in enumerate(items, start=1):
        if isinstance(entry, str):
            chapters.append({'number': index, 'title': entry, 'url': None, 'raw': entry})
            continue
        if not isinstance(entry, dict):
            continue
        title = _first_str(entry, 'title', 'name', 'chapter_title') or f'فصل {index}'
        url = _first_str(entry, 'url', 'chapter_url', 'link')
        cid = _first_str(entry, 'id', 'chapter_id', 'cid')
        hexed = _first_str(entry, 'hex', 'url_hex', 'hex_url')
        chapters.append({'number': index, 'title': title, 'url': url or None,
                         'id': cid or None, 'hex': hexed or None, 'raw': None})
    if not chapters:
        return None
    for i, ch in enumerate(chapters, start=1):
        ch['number'] = i  # الترقيم من ترتيب القائمة (كواجهة الموقع)
    return chapters


def _garden_candidate_get(client, paths_cache_key, candidates, params, unlock, garden_page_url):
    """تجربة مسارات الحديقة المرشحة مع كاش المسار الناجح — يعيد (path, data)
    أو يرفع خطأ تشخيصياً واضحاً حين لا يعمل أي مرشح"""
    with _LOCK:
        cached_path = _GARDEN_RUNTIME[paths_cache_key]
    order = ([cached_path] if cached_path else []) + [p for p in candidates if p != cached_path]
    last_shape_err = ''
    for path in order:
        try:
            data = _garden_api_get(client, path, params, unlock)
        except (TomatoMTLSessionError, TomatoMTLLimitError):
            raise
        except TomatoMTLError as e:
            last_shape_err = str(e)
            continue
        if data is None:
            continue  # 404 — مسار خاطئ
        if isinstance(data, dict) and data.get('success') is False:
            err = str(data.get('error') or '')
            if any(w in err.lower() for w in ('unauthorized', 'login', 'auth', 'token')):
                raise TomatoMTLSessionError('TomatoMTL Garden: الجلسة مرفوضة من واجهة الحديقة — جدد الكوكيز.')
            last_shape_err = err or 'الواجهة أعادت فشلاً بلا تفاصيل'
            continue
        with _LOCK:
            _GARDEN_RUNTIME[paths_cache_key] = path
        return path, data
    raise TomatoMTLError(
        'TomatoMTL Garden: لم يعمل أي مسار معروف لواجهة الحديقة لهذه العملية '
        f'({", ".join(candidates)}). إن ظهرت الرسالة باستمرار فافتح رابط الحديقة في متصفحك '
        'وأنت مسجل الدخول، وافتح أدوات المطور ← Network، وانسخ مسار نداء '
        + ('الكتاب/الفهرس/الفصل' if paths_cache_key != 'chapter_path' else 'الفصل') +
        ' ثم اضبطه في متغير البيئة المناسب (TOMATOMTL_GARDEN_*_PATHS).'
        + (f' — آخر خطأ: {last_shape_err[:120]}' if last_shape_err else ''))


def garden_metadata(url):
    """بيانات رواية حديقة: صفحة الحديقة (unlock_code + جلسة) ثم واجهة الحديقة"""
    source, original, page_url = _garden_parse(url)
    with TomatoMTLClient() as client:
        unlock = _garden_unlock(client, page_url)
        _, data = _garden_candidate_get(
            client, 'book_path', GARDEN_BOOK_PATHS,
            {'url': original, 'source': source}, unlock, page_url)
        novel = _garden_novel_from_data(data, source, original, page_url)
        if not novel:
            raise TomatoMTLError('TomatoMTL Garden: رد بيانات الحديقة بلا عنوان قابل للقراءة — '
                                 'أرسل مسار نداء الكتاب من Network لتضبيطه.')
        return novel


def garden_chapters(url):
    """فهرس رواية حديقة — القائمة بترتيبها وترقيمها تسلسلياً (كواجهة الموقع).
    روابط الفصول تبقى بصيغة الحديقة: /garden/{source}/{hex(رابط الفصل الأصلي)}"""
    source, original, page_url = _garden_parse(url)
    with TomatoMTLClient() as client:
        unlock = _garden_unlock(client, page_url)
        _, data = _garden_candidate_get(
            client, 'chapters_path', GARDEN_CHAPTERS_PATHS,
            {'url': original, 'source': source}, unlock, page_url)
        chapters = _garden_chapters_from_data(data)
        if not chapters:
            raise TomatoMTLError('TomatoMTL Garden: رد فهرس الحديقة بلا فصول مقروءة — '
                                 'أرسل مسار نداء الفهرس من Network لتضبيطه.')
        out = []
        for ch in chapters:
            if ch.get('url'):
                ch_url = f'{BASE}/garden/{source}/{_garden_hex(ch["url"])}'
            elif ch.get('hex'):
                ch_url = f'{BASE}/garden/{source}/{ch["hex"]}'
            else:
                ch_url = page_url  # فصل بلا معرف قابل للبناء — يفشل لاحقاً برسالة واضحة
            out.append({'number': ch['number'], 'title': ch['title'], 'url': ch_url})
        return out


def garden_content(url):
    """محتوى فصل حديقة: فك {iv,enc} بآلية chapter_decrypt بمفتاح صفحة الحديقة"""
    source, original, page_url = _garden_parse(url)
    with TomatoMTLClient() as client:
        unlock = _garden_unlock(client, page_url)
        _, data = _garden_candidate_get(
            client, 'chapter_path', GARDEN_CHAPTER_PATHS,
            {'url': original, 'source': source}, unlock, page_url)
        node = data.get('data') if isinstance(data.get('data'), dict) else data
        body = None
        for k in ('content', 'body', 'text', 'chapter_content'):
            v = node.get(k) if isinstance(node, dict) else None
            if isinstance(v, str) and v.strip():
                body = v
                break
        if body is None:
            raise TomatoMTLError('TomatoMTL Garden: رد الفصل بلا نص مقروء — '
                                 'أرسل مسار نداء الفصل من Network لتضبيطه.')
        text = clean_text(_payload_to_text(body))
        if not text:
            raise TomatoMTLError('TomatoMTL Garden: نص الفصل فارغ.')
        return text


# ==========================================
# 🚀 نقاط الاستدعاء (نفس توقيع كل المواقع)
# ==========================================
def fetch_metadata_tomatomtl(url):
    if is_garden_url(url):
        return garden_metadata(url)
    bid, _ = _ids(url)
    with TomatoMTLClient() as client:
        return client.metadata(bid)


def fetch_chapter_list_tomatomtl(url):
    if is_garden_url(url):
        return garden_chapters(url)
    bid, _ = _ids(url)
    with TomatoMTLClient() as client:
        return client.chapters(bid)


def scrape_chapter_tomatomtl(url):
    if is_garden_url(url):
        return garden_content(url)
    bid, cid = _ids(url, chapter=True)
    with TomatoMTLClient() as client:
        return client.content(bid, cid)


def worker_tomatomtl(url, admin_email, metadata):
    """جلسة واحدة لكل الرواية، مهلة بين الفصول، إرسال دفعات، توقف نظيف عند انتهاء الجلسة.
    🚦 حد القراءة (121 فصل/ساعة + 676/يوم — ثبت حياً): عند بلوغه نرسل الدفعة
    المعلقة أولاً (حفظ التقدم)، ننتظر ساعة كاملة أو أكثر بقليل (TOMATOMTL_LIMIT_WAIT،
    الافتراضي 63 دقيقة)، ثم نعيد المحاولة لنفس الفصل — حتى اكتمال الرواية أو
    نفاد سقف الانتظارات (TOMATOMTL_MAX_LIMIT_WAITS، الافتراضي 26 ≈ يغطي يوم الحد اليومي)."""
    from core.backend import check_existing_chapters, send_data_to_backend, push_log

    batch = []

    def send(chapters, skip_metadata):
        payload = {'adminEmail': admin_email, 'novelData': metadata,
                   'chapters': list(chapters), 'skipMetadataUpdate': skip_metadata}
        for attempt in range(3):
            if send_data_to_backend(payload):
                return True
            if attempt < 2:
                time.sleep(2)
        push_log('❌ [TomatoMTL] فشل إرسال الدفعة 3 مرات؛ توقف السحب. '
                 'الفصول غير المحفوظة تُعاد تلقائياً عند استئناف السحب لنفس الرابط.', 'error')
        return False

    def flush_batch():
        """إرسال ما تراكم قبل أي توقف (انتظار الحد أو الفشل) حتى لا يضيع تقدم"""
        nonlocal done
        if batch:
            if not send(batch, True):
                return False
            done += len(batch)
            batch.clear()
        return True

    try:
        garden = is_garden_url(url)
        bid = None
        if garden:
            _garden_parse(url)  # تحقق مبكر من صحة رابط الحديقة
        else:
            bid, _ = _ids(url)
        delay = max(1.0, float(os.environ.get('TOMATOMTL_DELAY', '1.5')))
        wait_seconds = float(os.environ.get('TOMATOMTL_LIMIT_WAIT', str(LIMIT_WAIT_DEFAULT)))
        if wait_seconds < LIMIT_WAIT_MIN:
            wait_seconds = float(LIMIT_WAIT_MIN)
        max_waits = max(1, int(os.environ.get('TOMATOMTL_MAX_LIMIT_WAITS', str(LIMIT_WAITS_MAX_DEFAULT))))
        with TomatoMTLClient() as client:
            chapters = garden_chapters(url) if garden else client.chapters(bid)
            existing = set(check_existing_chapters(metadata['title']))
            if not send([], bool(existing)):
                return
            pending = [ch for ch in chapters if ch['number'] not in existing]
            push_log(f"🍅 [TomatoMTL] بدء سحب «{metadata.get('title', '?')}» — "
                     f"{len(chapters)} فصلاً في الفهرس، الموجود مسبقاً {len(existing)}، "
                     f"المتبقي {len(pending)} (حد الموقع 121 فصل/ساعة — السحب يتوقف مؤقتاً تلقائياً عند بلوغه).", 'success')
            done = 0
            waits = 0
            index = 0
            while index < len(pending):
                chapter = pending[index]
                time.sleep(delay)
                try:
                    if garden:
                        text = garden_content(chapter['url'])
                    else:
                        _, cid = _ids(chapter['url'], chapter=True)
                        text = client.content(bid, cid)
                except TomatoMTLLimitError as limit_err:
                    # 🚦 بلوغ الحد: حفظ التقدم ثم انتظار ساعة كاملة+ ثم نفس الفصل
                    waits += 1
                    if waits > max_waits:
                        raise TomatoMTLError(
                            f'TomatoMTL: بقي حد القراءة بعد {max_waits} انتظاراً متتالياً '
                            f'({int(wait_seconds // 60)} دقيقة لكل انتظار) — توقف احترازياً. '
                            'استأنف بنفس الرابط لاحقاً وسيكمل من حيث توقف.') from limit_err
                    if not flush_batch():
                        return
                    minutes = int(wait_seconds // 60)
                    push_log(f"⏳ [TomatoMTL] بلغنا حد الموقع ({str(limit_err)[:60]}...) — "
                             f"توقف مؤقت {minutes} دقيقة ثم نكمل تلقائياً نفس الفصل "
                             f"(#{chapter['number']}). أُرسل {done}/{len(pending)} — "
                             f"الانتظار {waits}/{max_waits}.", 'warning')
                    time.sleep(wait_seconds)
                    continue  # نفس الفصل — لا نزيد index
                batch.append({'number': chapter['number'], 'title': chapter['title'], 'content': text})
                index += 1
                if len(batch) >= 5:
                    if not send(batch, True):
                        return
                    done += len(batch)
                    batch.clear()
                    push_log(f"🍅 [TomatoMTL] تقدم السحب: {done}/{len(pending)} فصلاً أُرسل "
                             f"(آخر فصل #{chapter['number']}).", 'info')
            if batch:
                if not send(batch, True):
                    return
                done += len(batch)
            push_log(f"✅ [TomatoMTL] اكتمل سحب «{metadata.get('title', '?')}» — {done} فصلاً جديداً."
                     + (f' (بلغنا الحد {waits} مرة وانتظرنا تلقائياً)' if waits else ''), 'success')
    except (TomatoMTLError, ValueError) as error:
        if batch:
            send(batch, True)
        # لا نطبع أبداً قيم الكوكيز أو أجسام الردود — رسالة جاهزة فقط
        reason = str(error) if isinstance(error, TomatoMTLError) else 'TomatoMTL: قيمة إعداد (DELAY/WAIT) غير صالحة.'
        print(reason)
        push_log(f'❌ [{reason}] توقف السحب؛ استأنف بنفس الرابط بعد معالجة السبب '
                 '(إن انتهت الجلسة فجدد الكوكيز من واجهة السكرابر).', 'error')


register_site(
    domain_patterns=['tomatomtl.com', 'www.tomatomtl.com'],
    name='TomatoMTL (番茄小说)',
    language='chinese',
    fetch_metadata=fetch_metadata_tomatomtl,
    fetch_chapters=fetch_chapter_list_tomatomtl,
    fetch_content=scrape_chapter_tomatomtl,
    worker=worker_tomatomtl,
    status='active',
    notes='جديد (v2.8)! قراءة محتوى تتطلب جلسة حساب — الكوكيز من واجهة السكرابر '
          '(موقع/تطبيق بنفس الواجهة) وإلا تُستخدم الثابتة بالكود (remember_* ≈ 5 سنوات). '
          'البيانات من سكربت صفحة الكتاب، الفهرس /catalog/{id} جدول JSON، والنص مشفر '
          'AES-CBC يُفك بمطابقة tomato.js الرسمي. عند تحدٍّ Cloudflare لعنوان السيرفر '
          'يمكن تجاوزه بـ FLARESOLVR_URL مع حقن كوكيز الحساب.'
)
