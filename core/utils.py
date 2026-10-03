# -*- coding: utf-8 -*-
"""
==========================================
🛠️ أدوات السحب المشتركة (Shared Scraper Tools)
==========================================
كل الدوال المساعدة التي تستخدمها جميع ملفات المواقع:
- الترويسات والجلسات (Headers/Sessions)
- إصلاح روابط الصور
- تحويل التواريخ النسبية
- استخراج أرقام الفصول
- مساعد قالب Madara العام (يستخدمه أكثر من موقع)
- 🆕 التوجيه الذكي (smart_get): بديل تلقائي عند حجب IP السيرفر
"""

import os
import re
import time
import json
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, quote

from .config import MARKAZ_COOKIES

# ==========================================
# 🪪 هويات المستخدم (User Agents) للتبديل بينها
# ==========================================
UA_CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
UA_FIREFOX = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0'
UA_MOBILE = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'

# ==========================================
# 🆕 إعدادات التوجيه الذكي (متغيرات بيئة اختيارية)
# ==========================================
# FLARESOLVR_URL  : رابط خدمة FlareSolverr (مثال: http://flaresolverr:8191)
# SCRAPERAPI_KEY  : مفتاح ScraperAPI المجاني (يُمرر الطلب عبر بروكسي سكني)
# RESIDENTIAL_PROXY : بروكسي عام بصيغة http://user:pass@host:port
FLARESOLVR_URL = os.environ.get('FLARESOLVR_URL', '').rstrip('/')
SCRAPERAPI_KEY = os.environ.get('SCRAPERAPI_KEY', '')
RESIDENTIAL_PROXY = os.environ.get('RESIDENTIAL_PROXY', '')
# CF_WORKER_URL  : رابط Cloudflare Worker خاص بك (مجاني 100,000 طلب/يوم) — يمرر
#                  الطلبات من داخل شبكة Cloudflare نفسها

# 🪪 curl_cffi: انتحال بصمة TLS للمتصفح الحقيقي.
# المشكلة المؤكدة بالفحص: بصمة python-requests مكشوفة جداً — Cloudflare يرجع
# صفحات تحدي (challenge-platform) محتواها 200 حتى مع User-Agent متصفح،
# بينما نفس الرابط عبر curl_cffi بانتحال كروم يرجع المحتوى الحقيقي.
# إن لم تكن المكتبة مثبتة يُستمر بrequests العادي دون أي كسر.
try:
    from curl_cffi import requests as _cffi_requests
    _CFFI_IMPERSONATE = os.environ.get('CFFI_IMPERSONATE', 'chrome')
except Exception:
    _cffi_requests = None


def get_headers(referer=None, use_cookies=False, ua=None, lang='ar,en-US;q=0.7,en;q=0.3'):
    """توليد ترويسات كاملة تحاكي المتصفح"""
    headers = {
        'User-Agent': ua or UA_CHROME,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': lang,
        'Connection': 'keep-alive',
    }
    if referer:
        headers['Referer'] = referer

    if use_cookies and MARKAZ_COOKIES and MARKAZ_COOKIES != 'ضع_هنا_الكوكيز_الخاصة_بك_كاملة':
        headers['Cookie'] = MARKAZ_COOKIES

    return headers


def http_get(url, referer=None, use_cookies=False, ua=None, lang='ar,en-US;q=0.7,en;q=0.3',
             timeout=20, encoding=None):
    """طلب GET موحّد يعيد Response أو None عند الفشل"""
    try:
        r = requests.get(
            url,
            headers=get_headers(referer=referer, use_cookies=use_cookies, ua=ua, lang=lang),
            timeout=timeout,
            allow_redirects=True,
        )
        if encoding:
            r.encoding = encoding
        return r
    except Exception as e:
        print(f"❌ GET failed {url[:80]}: {e}")
        return None


# ==========================================
# 🆕🛰️ التوجيه الذكي (Smart Routing)
# ==========================================
# المشكلة: مواقع كثيرة (FanMTL / RoyalRoad / WuxiaBox ...) تحجب عناوين IP
# الخاصة بمراكز البيانات (Railway وأي سيرفر سحابي) بحماية Cloudflare،
# فيفشل الطلب المباشر بـ 403/400 حتى لو كان الكود صحيحاً.
#
# الحل: smart_get يجرب عدة طرق بالترتيب ويحفظ الطريقة الناجحة لكل نطاق:
#   1) الطلب المباشر (أسرع طريقة — تعمل مع معظم المواقع)
#   2) عبر بروكسي ترجمة جوجل (translate.goog) — يجلب الصفحة من شبكة
#      جوجل التي لا تُحجب، ويُعيد HTML الأصلي بدون ترجمة النص فعلياً
#   3) عبر FlareSolverr إن ضُبط FLARESOLVR_URL (يحل تحديات Cloudflare)
#   4) عبر ScraperAPI إن ضُبط SCRAPERAPI_KEY (بروكسي سكني مجاني جزئياً)
# ==========================================

# ذاكرة مؤقتة لطريقة الطلب الناجحة لكل نطاق (لتسريع سحب الفصول)
_DOMAIN_ROUTE_CACHE = {}

# علامات تدل على أن الرد "صفحة حجب/تحدي" وليس المحتوى الحقيقي
_BLOCK_MARKERS = [
    'just a moment', 'challenge-platform', '_cf_chl_opt', 'cf-chl-bypass',
    'attention required', 'cf-browser-verification', 'checking your browser',
    'verify yourself', 'ddos protection by', 'access denied |',
    'cf-mitigated', 'captcha-form', 'enable javascript and cookies',
]


class SmartResponse:
    """كائن استجابة موحّد (يحاكي requests.Response بما يكفي للسكرابر)"""

    def __init__(self, text, status_code=200, route='direct'):
        self.text = text
        self.content = text.encode('utf-8', errors='replace') if isinstance(text, str) else text
        self.status_code = status_code
        self.route = route
        self.headers = {}

    def json(self):
        return json.loads(self.text)


def translate_proxy_url(url, sl='en', tl='es'):
    """تحويل أي رابط إلى مكافئه عبر بروكسي ترجمة جوجل (translate.goog).
    ملاحظة: المحتوى يُعاد بصيغته الأصلية (الترجمة تُحقن بجافاسكربت للمتصفح فقط)."""
    p = urlparse(url)
    dashed = p.netloc.replace('-', '--').replace('.', '-')
    q = f'_x_tr_sl={sl}&_x_tr_tl={tl}&_x_tr_hl=en'
    path = p.path or '/'
    full = f"https://{dashed}.translate.goog{path}?{q}"
    if p.query:
        full += '&' + p.query
    return full


def _undash_host(dashed):
    """عكس ترميز جوجل: النقاط أصبحت شرطات والشرطات الأصلية أصبحت شرطتين"""
    s = dashed.replace('--', '\x00')
    s = s.replace('-', '.')
    return s.replace('\x00', '-')


def _normalize_translate_html(html, base_url):
    """إعادة كتابة كل روابط translate.goog داخل الصفحة إلى نطاقاتها الأصلية"""
    if not html or 'translate.goog' not in html:
        return html
    p = urlparse(base_url)

    # https://xxx-yyy.translate.goog/path?_x_tr_... -> https://xxx.yyy/path
    pattern = re.compile(r'(https?:)?//([a-z0-9-]+)\.translate\.goog', re.IGNORECASE)

    def _repl(m):
        return f"{p.scheme}://{_undash_host(m.group(2))}"

    html = pattern.sub(_repl, html)

    # صور أغلفة مرّت عبر غلاف جوجل: translate.google.com/website?...&u=URL
    def _img_repl(m):
        from urllib.parse import unquote
        return unquote(m.group(1))

    html = re.sub(
        r'translate\.google\.com/website\?[^"\']*?[&?]u=([^"\'&]+)',
        _img_repl, html, flags=re.IGNORECASE)

    # إزالة معاملات _x_tr_* المتبقية
    html = re.sub(r'\?_x_tr_[^"\'&\s>]*', '', html)
    html = re.sub(r'(&amp;|&)_x_tr_[^"\'&\s>]*', '', html)
    return html


def _looks_blocked(status_code, body):
    """هل هذا الرد صفحة حجب/تحدي وليس المحتوى الحقيقي؟"""
    if body is None:
        return True
    low = str(body)[:5000].lower()
    if any(marker in low for marker in _BLOCK_MARKERS):
        return True
    if status_code in (401, 403, 429, 503, 502, 521, 522, 523, 525, 530):
        return True
    # صفحات الخطأ 400 القصيرة عادةً حجب/رفض وليست محتوى حقيقياً
    if status_code == 400 and len(low) < 8000:
        return True
    return False


def _flaresolverr_get(url, validate=None, post_data=None):
    """طلب عبر FlareSolverr (يحل تحديات Cloudflare بمتصفح حقيقي) — اختياري"""
    if not FLARESOLVR_URL:
        return None
    try:
        payload = {'cmd': 'request.get', 'url': url, 'maxTimeout': 60000}
        if post_data:
            payload['cmd'] = 'request.post'
            payload['postBody'] = '&'.join(
                f"{quote(str(k), safe='')}={quote(str(v), safe='')}"
                for k, v in post_data.items())
        r = requests.post(
            f"{FLARESOLVR_URL}/v1",
            json=payload,
            timeout=75,
        )
        if r.status_code == 200:
            data = r.json()
            sol = data.get('solution') or {}
            body = sol.get('response') or ''
            status = sol.get('status', 200)
            if body and status == 200 and not _looks_blocked(200, body) \
                    and (validate is None or validate(body)):
                print(f"   🛰️ FlareSolverr: success for {url[:70]}")
                return SmartResponse(body, 200, route='flaresolverr')
    except Exception as e:
        print(f"   FlareSolverr failed: {str(e)[:80]}")
    return None


# ==========================================
# 🛰️ محرك ScraperAPI متعدد المفاتيح (Multi-Key Rotation)
# ==========================================
# المفاتيح تُجمع من 3 مصادر بالترتيب (مع إزالة التكرار):
#   1) متغير البيئة SCRAPERAPI_KEYS : عدة مفاتيح مفصولة بفواصل أو أسطر
#   2) متغير البيئة SCRAPERAPI_KEY  : مفتاح واحد (توافق مع الإعداد القديم)
#   3) مفاتيح مرسلة وقت التشغيل عبر POST /scraperapi/keys (من واجهة التطبيق)
#      وعند فراغ كل المصادر يُجرّب سحبها من خادم التطبيق تلقائياً.
#
# إدارة الحالة لكل مفتاح:
#   ok        → يعمل (يُستخدم بالتناوب round-robin)
#   exhausted → استُهلك رصيده الشهري (403 exhausted) — يُتخطى حتى إعادة الإرسال
#   invalid   → مفتاح غير صالح (401) — يُتخطى حتى إعادة الإرسال
import threading as _threading

_SCRAPERAPI_LOCK = _threading.Lock()
_SCRAPERAPI_RUNTIME = {'keys': [], 'status': {}, 'cursor': 0, 'last_app_pull': 0.0}


def _mask_key(key):
    """إخفاء معظم أجزاء المفتاح للسجلات: 6ac34ae7…99a92"""
    k = str(key or '')
    if len(k) <= 12:
        return k[:4] + '…'
    return f"{k[:8]}…{k[-5:]}"


def _parse_keys_text(text):
    """تفكيك نص يحوي مفاتيح مفصولة بفواصل و/أو أسطر جديد إلى قائمة نظيفة"""
    if not text:
        return []
    raw = str(text).replace('\r', '\n').replace(',', '\n').split('\n')
    keys, seen = [], set()
    for part in raw:
        k = part.strip().strip('"').strip("'")
        # مفاتيح ScraperAPI سداسية عشرية بطول ~32؛ نسمح بمجال أوسع مع أي نطاق
        if len(k) >= 15 and len(k) <= 80 and re.fullmatch(r'[A-Za-z0-9_\-]+', k) and k.lower() not in seen:
            seen.add(k.lower())
            keys.append(k)
    return keys


def set_scraperapi_keys(keys):
    """ضبط مفاتيح وقت التشغيل (من واجهة التطبيق) — يعيد ضبط حالات الفشل"""
    if isinstance(keys, str):
        keys = _parse_keys_text(keys)
    clean = _parse_keys_text('\n'.join(str(k) for k in (keys or [])))
    with _SCRAPERAPI_LOCK:
        _SCRAPERAPI_RUNTIME['keys'] = clean
        _SCRAPERAPI_RUNTIME['status'] = {k: 'ok' for k in clean}
        _SCRAPERAPI_RUNTIME['cursor'] = 0
    print(f"🛰️ ScraperAPI keys updated: {len(clean)} key(s) active")
    return clean


def get_all_scraperapi_keys():
    """كل المفاتيح المتاحة: البيئة + وقت التشغيل (بدون تكرار)"""
    env_keys = _parse_keys_text(
        (os.environ.get('SCRAPERAPI_KEYS', '') or '') + '\n' +
        (os.environ.get('SCRAPERAPI_KEY', '') or '')
    )
    with _SCRAPERAPI_LOCK:
        runtime_keys = list(_SCRAPERAPI_RUNTIME['keys'])
    merged, seen = [], set()
    for k in env_keys + runtime_keys:
        if k.lower() not in seen:
            seen.add(k.lower())
            merged.append(k)
    return merged


def _pull_keys_from_app():
    """سحب المفاتيح من خادم التطبيق (مصدرها واجهة المفاتيح) عند الفراغ —
    مرة كل 10 دقائق كحد أقصى حتى لا نثقل الخادم"""
    import time as _t
    with _SCRAPERAPI_LOCK:
        if _t.time() - _SCRAPERAPI_RUNTIME['last_app_pull'] < 600:
            return
        _SCRAPERAPI_RUNTIME['last_app_pull'] = _t.time()
    try:
        from .config import API_SECRET, NODE_BACKEND_URL
        r = requests.get(f"{NODE_BACKEND_URL}/api/admin/scraper-keys",
                         headers={'x-api-secret': API_SECRET}, timeout=20)
        if r.status_code == 200:
            keys = r.json().get('keys') or []
            if keys:
                with _SCRAPERAPI_LOCK:
                    existing = set(k.lower() for k in _SCRAPERAPI_RUNTIME['keys'])
                    added = [k for k in keys if str(k).lower() not in existing]
                    _SCRAPERAPI_RUNTIME['keys'].extend(added)
                    for k in added:
                        _SCRAPERAPI_RUNTIME['status'][k] = 'ok'
                if added:
                    print(f"🛰️ Pulled {len(added)} ScraperAPI key(s) from app server")
    except Exception as e:
        print(f"   ScraperAPI app-pull failed: {str(e)[:70]}")


def get_scraperapi_status():
    """ملخص حالات المفاتيح (مخفاة) للعرض في الواجهة والتقارير"""
    keys = get_all_scraperapi_keys()
    with _SCRAPERAPI_LOCK:
        status = dict(_SCRAPERAPI_RUNTIME['status'])
    out = []
    for k in keys:
        st = status.get(k, 'ok')  # مفاتيح البيئة تعتبر ok افتراضياً
        out.append({'key': _mask_key(k), 'status': st})
    ok = sum(1 for s in out if s['status'] == 'ok')
    return {'total': len(out), 'ok': ok, 'keys': out}


def _scraperapi_request(key, url, referer=None, post_data=None):
    """طلب واحد عبر ScraperAPI بمفتاح محدد — يعيد (response|None, event)
    event: ok | exhausted | invalid | protected | error"""
    try:
        headers = get_headers(referer=referer)
        if post_data:
            # تمرير POST عبر ScraperAPI: يُعاد إرسال الجسم للهدف كما هو
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            r = requests.post('https://api.scraperapi.com/',
                              params={'api_key': key, 'url': url, 'country_code': 'us'},
                              data=post_data, headers=headers, timeout=70)
        else:
            r = requests.get('https://api.scraperapi.com/',
                             params={'api_key': key, 'url': url, 'country_code': 'us'},
                             headers=headers, timeout=70)
    except Exception as e:
        print(f"   ScraperAPI[{_mask_key(key)}] error: {str(e)[:80]}")
        return None, 'error'

    body = r.text or ''
    low = body[:300].lower()
    if r.status_code == 403 and 'exhausted' in low:
        return None, 'exhausted'
    if r.status_code in (401, 403) and ('invalid' in low or 'unauthorized' in low):
        return None, 'invalid'
    if r.status_code in (403, 429) and 'rate' in low:
        return None, 'rate'
    if r.status_code == 500 and ('request failed' in low or 'protected' in low):
        # ScraperAPI يعيد المحاولة داخلياً؛ 500 يعني فشل مؤقت (موقع محمي جداً)
        return None, 'protected'
    if r.status_code == 200 and not _looks_blocked(200, body):
        return r, 'ok'
    return None, 'blocked'


def _scraperapi_get(url, referer=None, validate=None, post_data=None):
    """طلب عبر ScraperAPI ببروكسي سكني — يدور على كل المفاتيح المتاحة.
    يبدأ من مفتاح مختلف كل مرة (round-robin) لتوزيع الاستهلاك بالتساوي،
    ويتخطى تلقائياً المفاتيح المستهلكة/غير الصالحة."""
    keys = get_all_scraperapi_keys()
    if not keys:
        _pull_keys_from_app()
        keys = get_all_scraperapi_keys()
    if not keys:
        return None

    with _SCRAPERAPI_LOCK:
        cursor = _SCRAPERAPI_RUNTIME['cursor']
        _SCRAPERAPI_RUNTIME['cursor'] = (cursor + 1) % max(len(keys), 1)
        status = _SCRAPERAPI_RUNTIME['status']
    ordered = keys[cursor:] + keys[:cursor]

    last_event = 'error'
    for key in ordered:
        st = status.get(key, 'ok')
        if st in ('exhausted', 'invalid'):
            continue

        # محاولتان: بعض الفشل مؤقت (protected) ويعمل في المحاولة التالية
        for attempt in range(2):
            r, event = _scraperapi_request(key, url, referer=referer, post_data=post_data if attempt == 0 else None)
            last_event = event
            if event == 'ok' and r is not None:
                if validate is None or validate(r.text):
                    print(f"   🛰️ ScraperAPI[{_mask_key(key)}]: success for {url[:70]}")
                    return SmartResponse(r.text, 200, route='scraperapi')
                event = 'decoy'
            if event == 'exhausted':
                with _SCRAPERAPI_LOCK:
                    _SCRAPERAPI_RUNTIME['status'][key] = 'exhausted'
                print(f"   ⛔ ScraperAPI[{_mask_key(key)}] exhausted — rotating to next key")
                break
            if event == 'invalid':
                with _SCRAPERAPI_LOCK:
                    _SCRAPERAPI_RUNTIME['status'][key] = 'invalid'
                print(f"   ⛔ ScraperAPI[{_mask_key(key)}] invalid — removing from rotation")
                break
            if event == 'decoy':
                break
            if event in ('protected', 'error', 'rate', 'blocked'):
                time.sleep(2)

    if all(status.get(k, 'ok') in ('exhausted', 'invalid') for k in keys):
        print("⛔ ScraperAPI: ALL keys exhausted/invalid — add new keys from the app UI "
              "(SCRAPERAPI_KEYS=key1,key2,...) or wait for monthly reset")
    _ = last_event
    return None


def _direct_get(url, headers, timeout=20, proxies=None, encoding=None):
    """الطلب المباشر بانتحال بصمة متصفح حقيقي (curl_cffi) إن توفر.
    نحذف User-Agent اليدوي ليدع curl_cffi يضع وكيل المستخدم المطابق للبصمة
    المنتحلة (كروم كامل: TLS + HTTP2 + ترويسات) — فلا تتناقض الهوية."""
    if _cffi_requests is not None:
        try:
            h = {k: v for k, v in (headers or {}).items()
                 if k.lower() != 'user-agent'}
            r = _cffi_requests.get(url, headers=h, timeout=timeout,
                                   allow_redirects=True,
                                   impersonate=_CFFI_IMPERSONATE,
                                   proxies=proxies)
            if encoding:
                try:
                    r.encoding = encoding
                except Exception:
                    pass
            return r
        except Exception as e:
            print(f"   curl_cffi failed {url[:70]}: {str(e)[:70]} — retrying plain requests")
    return requests.get(url, headers=headers, timeout=timeout,
                        allow_redirects=True, proxies=proxies)


def _direct_post(url, data, headers, timeout=20, proxies=None):
    """طلب POST مباشر بانتحال بصمة متصفح حقيقي (curl_cffi) إن توفر —
    ضروري لنقاط admin-ajax خلف Cloudflare حيث تكشف بصمة python الهوية"""
    if _cffi_requests is not None:
        try:
            h = {k: v for k, v in (headers or {}).items()
                 if k.lower() != 'user-agent'}
            return _cffi_requests.post(url, data=data, headers=h, timeout=timeout,
                                       allow_redirects=True,
                                       impersonate=_CFFI_IMPERSONATE,
                                       proxies=proxies)
        except Exception as e:
            print(f"   curl_cffi POST failed {url[:70]}: {str(e)[:70]} — retrying plain requests")
    return requests.post(url, data=data, headers=headers, timeout=timeout,
                         allow_redirects=True, proxies=proxies)


def _cf_worker_get(url, worker_url, validate=None):
    """طلب عبر Cloudflare Worker خاص بالمستخدم — مجاني حتى 100,000 طلب/يوم.
    الطلب يخرج من داخل شبكة Cloudflare نفسها (IP سمعة نظيفة لا تُقيَّم كبوت).
    الـ worker المتوقع: يعيد جسم الصفحة الخام بحالة 200 (انظر README قسم 11).
    اختياري بالكامل: يُفعّل فقط عند ضبط CF_WORKER_URL."""
    try:
        r = requests.get(f"{worker_url}?url={quote(url, safe='')}",
                         headers=get_headers(), timeout=60)
        if r.status_code == 200 and not _looks_blocked(200, r.text) \
                and (validate is None or validate(r.text)):
            print(f"   🛰️ via CF worker: {url[:70]}")
            return SmartResponse(r.text, 200, route='cfworker')
    except Exception as e:
        print(f"   CF worker failed: {str(e)[:80]}")
    return None


def smart_get(url, sl='en', tl='es', referer=None, timeout=25,
              encoding=None, use_cookies=False, ua=None, lang=None, use_route_cache=True,
              validate=None, post_data=None):
    """
    طلب ذكي متعدد الطرق (مخصص للمواقع التي تحجب IP السيرفرات):
      مباشر (انتحال بصمة متصفح) → Cloudflare Worker (اختياري) → بروكسي ترجمة
      جوجل → FlareSolverr (اختياري) → ScraperAPI (اختياري — دوران على كل المفاتيح)
    يعيد SmartResponse/Response أو None إذا فشلت كل الطرق.

    validate: دالة اختيارية (body -> bool) للتحقق أن المحتوى حقيقي وليس صفحة خداع
    (بعض المواقع خلف Cloudflare تُرجع صفحات 200 مزيفة لبروكسي جوجل — مثل twkan.com)؛
    أي رد يفشل التحقق يُعامل كحجب ويُنتقل للطريقة التالية دون تخزين الطريقة الفاشلة.

    post_data: بيانات POST اختيارية (dict) — تُمرر لطريقتي FlareSolverr وScraperAPI
    فقط (المباشر وبروكسي جوجل GET دائماً وهو يعادل POST في admin-ajax).
    """
    parsed = urlparse(url)
    domain = parsed.netloc

    # قراءة الإعدادات من البيئة عند كل نداء (حتى تعمل التغييرات بدون إعادة نشر)
    flaresolverr = os.environ.get('FLARESOLVR_URL', '').rstrip('/')
    scraperapi_key = os.environ.get('SCRAPERAPI_KEY', '') or os.environ.get('SCRAPERAPI_KEYS', '')
    residential = os.environ.get('RESIDENTIAL_PROXY', '')
    cf_worker = os.environ.get('CF_WORKER_URL', '').rstrip('/')

    cached = _DOMAIN_ROUTE_CACHE.get(domain) if use_route_cache else None
    direct_status = None
    direct_body = None

    # ---------- الطريقة 1: الطلب المباشر (بصمة متصفح حقيقية) ----------
    if cached in (None, 'direct'):
        proxies = {'http': residential, 'https': residential} if residential else None
        try:
            r = _direct_get(url, get_headers(referer=referer, use_cookies=use_cookies,
                                             ua=ua, lang=lang),
                            timeout=timeout, proxies=proxies, encoding=encoding)
            if r.status_code == 200 and not _looks_blocked(200, r.text) \
                    and (validate is None or validate(r.text)):
                if use_route_cache:
                    _DOMAIN_ROUTE_CACHE[domain] = 'direct'
                return r
            direct_status = r.status_code
            direct_body = r.text
        except Exception as e:
            print(f"   direct failed {domain}: {str(e)[:70]}")

        if cached == 'direct':
            # كان يعمل مباشرة سابقاً لكن فشل الآن — نمسح الذاكرة
            # ونكمل تلقائياً للطرق البديلة
            _DOMAIN_ROUTE_CACHE.pop(domain, None)
            cached = None

    # ---------- الطريقة 2: Cloudflare Worker (اختياري — مجاني 100k/يوم) ----------
    if cf_worker and cached in (None, 'cfworker'):
        r = _cf_worker_get(url, cf_worker, validate=validate)
        if r is not None:
            if use_route_cache:
                _DOMAIN_ROUTE_CACHE[domain] = 'cfworker'
            return r
        if cached == 'cfworker':
            _DOMAIN_ROUTE_CACHE.pop(domain, None)
            cached = None

    # ---------- الطريقة 3: بروكسي ترجمة جوجل ----------
    if cached in (None, 'translate'):
        turl = translate_proxy_url(url, sl=sl, tl=tl)
        for attempt in range(4):
            try:
                r = requests.get(turl, headers=get_headers(ua=ua, lang='en-US,en;q=0.9'),
                                 timeout=timeout + 15, allow_redirects=True)
            except Exception as e:
                print(f"   translate proxy failed {domain}: {str(e)[:70]}")
                break
            if r.status_code == 429:
                wait = 8 + attempt * 7
                print(f"   ⏳ translate proxy rate-limited, waiting {wait}s ...")
                time.sleep(wait)
                continue
            if r.status_code == 200 and not _looks_blocked(200, r.text):
                body = _normalize_translate_html(r.text, url)
                if validate is None or validate(body):
                    if use_route_cache:
                        _DOMAIN_ROUTE_CACHE[domain] = 'translate'
                    print(f"   🛰️ via translate proxy: {url[:70]}")
                    return SmartResponse(body, 200, route='translate')
                # محتوى مزييف (صفحة خداع متقطعة) — أعد المحاولة قبل الاستسلام
                print(f"   ⚠️ translate proxy decoy for {domain} (attempt {attempt + 1}/4)")
                time.sleep(2 + attempt * 2)
                continue
            break

    # ---------- الطريقة 4: FlareSolverr ----------
    if flaresolverr:
        r = _flaresolverr_get(url, validate=validate, post_data=post_data)
        if r is not None:
            if use_route_cache:
                _DOMAIN_ROUTE_CACHE[domain] = 'flaresolverr'
            return r

    # ---------- الطريقة 5: ScraperAPI (دوران على كل المفاتيح) ----------
    if scraperapi_key or post_data:
        r = _scraperapi_get(url, referer=referer, validate=validate, post_data=post_data)
        if r is not None:
            if use_route_cache:
                _DOMAIN_ROUTE_CACHE[domain] = 'scraperapi'
            return r

    # ---------- كل الطرق فشلت ----------
    if direct_body is not None:
        return SmartResponse(direct_body, direct_status or 403, route='failed')
    return None


def parse_html(content_or_response, parser='html.parser'):
    """تحويل محتوى/استجابة إلى BeautifulSoup مع ترميز صحيح"""
    if content_or_response is None:
        return None
    if hasattr(content_or_response, 'content'):
        return BeautifulSoup(content_or_response.content, parser)
    return BeautifulSoup(content_or_response, parser)


def get_base_url(url):
    """استخراج العنوان الأساسي من أي رابط (scheme://domain)"""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fix_image_url(url, base_url='https://api.rewayat.club'):
    """إصلاح روابط الصور النسبية/المبتورة"""
    if not url:
        return ""
    if url.startswith('//'):
        return 'https:' + url
    elif url.startswith('/'):
        if 'novelfire.net' in base_url:
            return 'https://novelfire.net' + url
        elif 'wuxiabox.com' in base_url or 'wuxiaspot.com' in base_url or 'wuxiaworld.site' in base_url:
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}" + url
        return base_url + url
    elif not url.startswith('http'):
        return base_url + '/' + url
    return url


def parse_relative_date(date_str):
    """تحويل التواريخ النسبية (منذ 5 ساعات، يومين ago) إلى تاريخ حقيقي ISO"""
    try:
        if not date_str:
            return None

        now = datetime.now()
        text = str(date_str).lower().strip()

        # معالجة النصوص العربية الخاصة (يومين، ساعتين، إلخ)
        if 'يومين' in text:
            return (now - timedelta(days=2)).isoformat()
        if 'ساعتين' in text:
            return (now - timedelta(hours=2)).isoformat()
        if 'دقيقتين' in text:
            return (now - timedelta(minutes=2)).isoformat()
        if 'أمس' in text or 'امس' in text:
            return (now - timedelta(days=1)).isoformat()

        # إزالة كلمات زائدة
        text = text.replace('updated', '').replace('ago', '').replace('منذ', '').strip()

        # استخراج الرقم والوحدة (عربي وإنجليزي)
        match = re.search(
            r'(\d+)\s*(sec|min|hour|day|week|month|year|ثانية|ثواني|دقيقة|دقائق|ساعة|ساعات|يوم|أيام|ايام|أسبوع|اسبوع|أسابيع|اسابيع|شهر|أشهر|اشهر|سنة|سنوات)',
            text
        )

        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            delta = timedelta(seconds=0)

            if 'sec' in unit: delta = timedelta(seconds=amount)
            elif 'min' in unit: delta = timedelta(minutes=amount)
            elif 'hour' in unit: delta = timedelta(hours=amount)
            elif 'day' in unit: delta = timedelta(days=amount)
            elif 'week' in unit: delta = timedelta(weeks=amount)
            elif 'month' in unit: delta = timedelta(days=amount * 30)
            elif 'year' in unit: delta = timedelta(days=amount * 365)
            elif 'ثان' in unit: delta = timedelta(seconds=amount)
            elif 'دقيق' in unit: delta = timedelta(minutes=amount)
            elif 'ساع' in unit: delta = timedelta(hours=amount)
            elif 'يوم' in unit or 'أيام' in unit or 'ايام' in unit: delta = timedelta(days=amount)
            elif 'أسبوع' in unit or 'اسبوع' in unit or 'أسابيع' in unit: delta = timedelta(weeks=amount)
            elif 'شهر' in unit or 'أشهر' in unit: delta = timedelta(days=amount * 30)
            elif 'سنة' in unit or 'سنوات' in unit: delta = timedelta(days=amount * 365)

            return (now - delta).isoformat()

        # محاولة قراءة تاريخ ثابت (May 20, 2024 / 2025/12/15)
        for fmt in ['%B %d, %Y', '%Y/%m/%d', '%d/%m/%Y', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S']:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.isoformat()
            except Exception:
                continue

        return None
    except Exception:
        return None


def extract_chapter_number(text, url=''):
    """استخراج رقم الفصل من عنوان أو رابط بأي صيغة (Chapter N / الفصل N / 第N章 / _N)"""
    combined = f"{url} {text or ''}"
    patterns = [
        r'chapter[-_\s.]?(\d+)',
        r'الفصل\s*[-_#]?\s*(\d+)',
        r'فصل\s*[-_#]?\s*(\d+)',
        r'第(\d+)章',
        r'_(\d+)\.html',
        r'/(\d+)(?:/|\.|$)',
    ]
    for pat in patterns:
        m = re.search(pat, combined, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return 0


def clean_text(text):
    """تنظيف النص من الأسطر الزائدة المتكررة"""
    if not text:
        return ""
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def get_meta(soup, prop=None, name=None):
    """قراءة قيمة meta من الصفحة (og:title / description ...)"""
    if soup is None:
        return ""
    try:
        if prop:
            tag = soup.find('meta', property=prop)
        else:
            tag = soup.find('meta', attrs={'name': name})
        if tag and tag.get('content'):
            return tag['content'].strip()
    except Exception:
        pass
    return ""


# ==========================================
# 🏗️ قالب Madara العام (WordPress Madara Theme)
# ==========================================
# يستخدمه: Ar-Novel / Markaz Riwayat / WuxiaWorld.site وأي موقع Madara جديد
# ==========================================

def clean_madara_title(raw_title):
    cleaned = re.sub(r'^\s*(?:Chapter|الفصل|فصل)?\s*\d+\s*[:\-–]\s*', '', raw_title or '', flags=re.IGNORECASE).strip()
    return cleaned if cleaned else raw_title


def madara_extract_novel_id(soup):
    """استخراج معرف الرواية من صفحة Madara (طرق متعددة)"""
    novel_id = None
    shortlink = soup.find("link", rel="shortlink")
    if shortlink:
        match = re.search(r'p=(\d+)', shortlink.get('href', ''))
        if match:
            novel_id = match.group(1)
    if not novel_id:
        id_input = soup.find('input', class_='rating-post-id')
        if id_input:
            novel_id = id_input.get('value')
    if not novel_id:
        body_tag = soup.find('body')
        if body_tag and body_tag.has_attr('class'):
            for c in body_tag.get('class', []):
                if c.startswith('manga-id-'):
                    novel_id = c.replace('manga-id-', '')
    return novel_id


def madara_fetch_metadata(url, use_cookies=False):
    """جلب بيانات رواية من قالب Madara (التصميم القديم والجديد)"""
    try:
        response = http_get(url, use_cookies=use_cookies, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        # --- فحص وجود صفحة "Coming Soon" (مركز الروايات أُغلق) ---
        page_text = soup.get_text()[:3000]
        if 'coming soon' in page_text.lower() and 'wordpress' not in page_text.lower():
            print(f"🚫 Site appears CLOSED (Coming Soon page): {url[:80]}")
            return None

        # --- التصميم الجديد (قوالب المانجا الجديدة) ---
        is_new_design = bool(soup.select_one('.manga-title'))

        if is_new_design:
            title_tag = soup.select_one('h1.manga-title')
            title = title_tag.get_text(strip=True) if title_tag else "Unknown"

            cover = ""
            img_tag = soup.select_one('.manga-cover-wrap img')
            if img_tag:
                cover = img_tag.get('data-src') or img_tag.get('src')
            cover = fix_image_url(cover, base_url=get_base_url(url))

            desc_div = soup.find('div', id='manga-summary')
            description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""

            status = "مستمرة"
            status_pill = soup.select_one('.manga-status-pill')
            if status_pill:
                txt = status_pill.get_text(strip=True)
                if "مكتملة" in txt or "Completed" in txt:
                    status = "مكتملة"

            tags = [pill.get_text(strip=True) for pill in soup.select('.pill-list .pill')]
            category = tags[0] if tags else "عام"

            novel_id = None
            like_btn = soup.select_one('.manga-like-btn')
            if like_btn and like_btn.has_attr('data-manga-id'):
                novel_id = like_btn['data-manga-id']
            if not novel_id:
                rating_btn = soup.select_one('.manga-stat--rating')
                if rating_btn and rating_btn.has_attr('data-manga-id'):
                    novel_id = rating_btn['data-manga-id']

            last_update = None
            first_ch_row = soup.select_one('.ch-list .ch-row .ch-date')
            if first_ch_row:
                last_update = parse_relative_date(first_ch_row.get_text(strip=True))
        else:
            # --- التصميم القياسي القديم (Madara) ---
            title_tag = soup.find(class_='post-title')
            title = title_tag.find('h1').get_text(strip=True) if title_tag else "Unknown"
            title = re.sub(r'\s*~.*$', '', title)

            cover = ""
            og_img = soup.find("meta", property="og:image")
            if og_img:
                cover = og_img["content"]
            if not cover:
                img_container = soup.find(class_='summary_image')
                if img_container:
                    img_tag = img_container.find('img')
                    if img_tag:
                        cover = img_tag.get('data-src') or img_tag.get('src') or img_tag.get('srcset', '').split(' ')[0]
            cover = fix_image_url(cover, base_url=get_base_url(url))

            novel_id = madara_extract_novel_id(soup)

            desc_div = soup.find(class_='summary__content') or soup.find(class_='description-summary')
            description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""
            description = re.sub(r'\n{3,}', '\n\n', description)

            genres_content = soup.find(class_='genres-content')
            category = "عام"
            tags = []
            if genres_content:
                links = genres_content.find_all('a')
                tags = [a.get_text(strip=True) for a in links]
                if tags:
                    category = tags[0]

            status = "مستمرة"
            status_terms = soup.find_all('div', class_='post-status')
            if status_terms:
                for st in status_terms:
                    txt = st.get_text(strip=True).lower()
                    if 'completed' in txt or 'مكتملة' in txt:
                        status = "مكتملة"
                        break

            last_update = None
            timediff_span = soup.select_one('.post-on .timediff')
            if timediff_span:
                last_update = parse_relative_date(timediff_span.get_text(strip=True))
            if not last_update:
                update_node = soup.select_one('.post-on span') or soup.select_one('.post-on')
                if update_node:
                    last_update = parse_relative_date(update_node.get_text(strip=True))

        print(f"Found Novel ID: {novel_id}")

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'novel_id': novel_id, 'sourceUrl': url,
            'lastUpdate': last_update
        }
    except Exception as e:
        print(f"Error Madara Meta: {e}")
        return None


def madara_parse_chapters(soup):
    """تحليل قائمة الفصول من HTML (تصميم Madara القديم والجديد)"""
    chapters = []

    # 1. التصميم الجديد (.ch-list .ch-row)
    new_rows = soup.select('.ch-list .ch-row')
    if new_rows:
        for row in new_rows:
            a = row.find('a')
            if not a:
                continue
            link = a.get('href')
            num_div = row.select_one('.ch-num')
            number = 0
            if num_div:
                try:
                    number = int(num_div.get_text(strip=True))
                except ValueError:
                    pass
            if number == 0 and link:
                num_match = re.search(r'(\d+)', link)
                if num_match:
                    number = int(num_match.group(1))
            title_div = row.select_one('.ch-title')
            raw_title = title_div.get_text(strip=True) if title_div else f"Chapter {number}"
            if number > 0:
                chapters.append({'number': number, 'url': link, 'title': clean_madara_title(raw_title)})
        return chapters

    # 2. التصميم القديم (li.wp-manga-chapter)
    items = soup.find_all('li', class_='wp-manga-chapter')
    if items:
        for item in items:
            a = item.find('a')
            if a:
                link = a.get('href')
                raw_title = a.get_text(strip=True)
                num_match = re.search(r'(\d+)', raw_title)
                number = int(num_match.group(1)) if num_match else extract_chapter_number(raw_title, link or '')
                if number > 0:
                    chapters.append({'number': number, 'url': link, 'title': clean_madara_title(raw_title)})
        return chapters

    return chapters


def madara_fetch_chapter_list(novel_id, novel_url, use_cookies=False):
    """جلب قائمة فصول Madara عبر 3 طرق (AJAX ثم admin-ajax ثم HTML مباشر)"""
    chapters = []
    base_url = get_base_url(novel_url)

    # 1. طلب AJAX القياسي
    if novel_url:
        ajax_endpoint = f"{novel_url.rstrip('/')}/ajax/chapters/"
        try:
            headers = get_headers(use_cookies=use_cookies)
            headers['X-Requested-With'] = 'XMLHttpRequest'
            res = requests.post(ajax_endpoint, headers=headers, timeout=20)
            if res.status_code == 200:
                soup = parse_html(res.content)
                chapters = madara_parse_chapters(soup)
                if chapters:
                    print(f"✅ Chapters fetched via /ajax/chapters/ ({len(chapters)})")
        except Exception as e:
            print(f"AJAX endpoint failed: {e}")

    # 2. admin-ajax (بديل)
    if not chapters and novel_id:
        try:
            admin_ajax_url = f"{base_url}/wp-admin/admin-ajax.php"
            data = {'action': 'manga_get_chapters', 'manga': novel_id}
            res = requests.post(admin_ajax_url, data=data,
                                headers=get_headers(novel_url, use_cookies=use_cookies), timeout=20)
            if res.status_code == 200:
                soup = parse_html(res.content)
                chapters = madara_parse_chapters(soup)
                if chapters:
                    print(f"✅ Chapters fetched via admin-ajax ({len(chapters)})")
        except Exception as e:
            print(f"admin-ajax failed: {e}")

    # 3. تحليل صفحة الرواية مباشرة
    if not chapters and novel_url:
        try:
            res = http_get(novel_url, use_cookies=use_cookies, timeout=15)
            if res is not None and res.status_code == 200:
                soup = parse_html(res)
                chapters = madara_parse_chapters(soup)
                if chapters:
                    print(f"✅ Chapters fetched via direct HTML ({len(chapters)})")
        except Exception as e:
            print(f"Direct HTML fetch failed: {e}")

    if chapters:
        chapters.sort(key=lambda x: x['number'])

    return chapters


def madara_scrape_chapter(url, use_cookies=False):
    """سحب محتوى فصل من قالب Madara مع تنظيف شامل"""
    try:
        res = http_get(url, use_cookies=use_cookies, timeout=15)
        if res is None or res.status_code != 200:
            return None
        soup = parse_html(res)

        container = soup.find(class_='reader-target') or \
            soup.find(class_='reading-content') or \
            soup.find(class_='text-left') or \
            soup.find(class_='text-right') or \
            soup.find(class_='entry-content')

        if not container:
            return None

        inner_text_right = container.find(class_='text-right')
        if inner_text_right:
            container = inner_text_right

        for bad in container.find_all(['div', 'script', 'style', 'input', 'ins', 'iframe', 'button']):
            if bad.get('class') and any(
                c in ['nav-links', 'code-block', 'adsbygoogle', 'pf-ad', 'wpmcr-under-title-row']
                for c in bad.get('class')
            ):
                bad.decompose()
            if bad.get('id') == 'reader-btn':
                bad.decompose()

        for nav in container.find_all('div', class_='nav-links'):
            nav.decompose()

        text = container.get_text(separator="\n\n", strip=True)
        text = clean_text(text)
        text = text.replace('اكمال القراءة', '')
        text = text.replace('إعدادات القراءة', '')

        if len(text) < 200 and 'سجل' in text:
            print("⚠️ Warning: Chapter content seems blocked by login wall.")

        return text or None
    except Exception:
        return None


# ==========================================
# 🎯 فلتر نطاق الفصول (سحب انتقائي لتوفير الاستهلاك)
# ==========================================
# يسمح بسحب فصول محددة بدل الرواية كاملة:
#   "10"        → الفصل 10 فقط
#   "12,50"     → الفصلان 12 و50 فقط
#   "10-20"     → من 10 إلى 20
#   "10-!"      → من 10 إلى آخر فصل
#   "1-50,80,90-!" → مزيج
# يُضبط قبل تشغيل خيط العامل (thread-local) فيقرأه العامل بعد جلب الفهرس،
# والتطابق يكون مع أرقام الفصول الفعلية في الفهرس (كمنطق نطاق الترجمة في التطبيق).
# ==========================================

_chapter_spec_local = threading.local()


def set_current_chapter_spec(spec):
    """ضبط فلتر الفصول للخيط الحالي (من /scrape قبل تشغيل العامل)"""
    _chapter_spec_local.spec = str(spec).strip() if spec and str(spec).strip() else None


def get_current_chapter_spec():
    return getattr(_chapter_spec_local, 'spec', None)


def parse_chapter_spec_tokens(spec):
    """تحليل بنية النص فقط (بلا حاجة للإجمالي) — للتحقق المبكر في /scrape.
    يعيد قائمة توكنات [(kind, a[, b])] أو None إن كان النص غير صالح."""
    if spec is None:
        return None
    text = str(spec).strip().replace('،', ',')  # فاصلة عربية احتياطاً
    if not text:
        return None
    tokens = []
    for raw in text.split(','):
        raw = raw.strip()
        if not raw:
            continue
        m_open = re.fullmatch(r'(\d+)\s*-\s*(!|آخر|last|end)', raw, re.IGNORECASE)
        m_range = re.fullmatch(r'(\d+)\s*-\s*(\d+)', raw)
        m_single = re.fullmatch(r'\d+', raw)
        if m_open:
            tokens.append(('open', int(m_open.group(1))))
        elif m_range:
            a, b = int(m_range.group(1)), int(m_range.group(2))
            if a > b:
                a, b = b, a
            tokens.append(('range', a, b))
        elif m_single:
            tokens.append(('single', int(raw)))
        else:
            return None
    return tokens if tokens else None


def apply_chapter_filter(all_chapters):
    """تطبيق الفلتر على قائمة الفصول داخل خيط العامل (يعيد القائمة كما هي إن لم يُضبط فلتر)."""
    try:
        spec = get_current_chapter_spec()
        if not spec or not all_chapters:
            return all_chapters
        tokens = parse_chapter_spec_tokens(spec)
        if tokens is None:
            print(f"⚠️ تجاهُل فلتر الفصول غير الصالح: {spec!r} — سيُسحب كل الفهرس")
            return all_chapters
        available = {int(c.get('number')) for c in all_chapters if c.get('number') is not None}
        max_num = max(available) if available else 0
        allowed = set()
        for tok in tokens:
            if tok[0] == 'single':
                if tok[1] in available:
                    allowed.add(tok[1])
            elif tok[0] == 'range':
                for n in range(tok[1], tok[2] + 1):
                    if n in available:
                        allowed.add(n)
            elif tok[0] == 'open':
                for n in range(tok[1], max_num + 1):
                    if n in available:
                        allowed.add(n)
        filtered = [c for c in all_chapters if int(c.get('number')) in allowed]
        print(f"🎯 فلتر الفصول '{spec}': {len(all_chapters)} في الفهرس → {len(filtered)} فصلاً للسحب")
        return filtered
    except Exception as e:
        print(f"⚠️ خطأ في فلتر الفصول ({e}) — سيُسحب كل الفهرس")
        return all_chapters


def madara_worker(url, admin_email, metadata, use_cookies=False):
    """العامل الكامل لمواقع Madara"""
    from .backend import send_data_to_backend, check_existing_chapters

    existing_chapters = check_existing_chapters(metadata['title'])
    skip_meta = len(existing_chapters) > 0

    if existing_chapters:
        print(f"📚 Novel exists in app DB: {len(existing_chapters)} chapters (max #{max(existing_chapters)}) — skipping them, resuming after")

    send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': [], 'skipMetadataUpdate': skip_meta})

    all_chapters = madara_fetch_chapter_list(metadata.get('novel_id'), url, use_cookies=use_cookies)

    if not all_chapters:
        print(f"No chapters found for {metadata['title']}")
        return

    # 🎯 سحب انتقائي: طبّق فلتر النطاق إن وُضع من /scrape
    all_chapters = apply_chapter_filter(all_chapters)
    if not all_chapters:
        print("No chapters match the chapter filter — nothing to scrape.")
        return

    print(f"Processing {len(all_chapters)} chapters.")

    batch = []
    for chap in all_chapters:
        if chap['number'] in existing_chapters:
            continue

        print(f"Scraping {metadata['title']} - Ch {chap['number']}...")
        content = madara_scrape_chapter(chap['url'], use_cookies=use_cookies)

        if content:
            batch.append({'number': chap['number'], 'title': chap['title'], 'content': content})
            if len(batch) >= 5:
                send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': batch, 'skipMetadataUpdate': True})
                batch = []
                time.sleep(1.5)

    if batch:
        send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': batch, 'skipMetadataUpdate': True})


# ==========================================
# 🔄 عامل سحب عام (Generic Worker)
# ==========================================
# يستخدمه معظم المواقع الجديدة: يكفي تمرير دالتي القائمة والمحتوى
# ==========================================

def generic_worker(url, admin_email, metadata, chapters_fn, content_fn,
                   batch_size=5, delay=1.0, base_url_for_join=None, site_name=''):
    """
    عامل سحب موحّد لأي موقع:
    1. يفحص الفصول الموجودة في الباك إند
    2. يرسل بيانات الرواية
    3. يسحب الفصول على دفعات ويرسلها

    chapters_fn(url) -> [{'number': int, 'url': str, 'title': str}, ...]
    content_fn(url)  -> str or None
    site_name: اسم الموقع للعرض في رسائل الخطأ (اختياري)
    """
    from .backend import send_data_to_backend, check_existing_chapters, push_log

    try:
        existing_chapters = check_existing_chapters(metadata['title'])
    except Exception:
        existing_chapters = []
    skip_meta = len(existing_chapters) > 0

    if existing_chapters:
        print(f"📚 Novel exists in app DB: {len(existing_chapters)} chapters (max #{max(existing_chapters)}) — skipping them, resuming after")

    send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': [], 'skipMetadataUpdate': skip_meta})

    try:
        all_chapters = chapters_fn(url)
    except Exception as e:
        print(f"❌ chapters_fn failed: {e}")
        all_chapters = []

    if not all_chapters:
        # 🔊 فشل صريح ومرئي في كونسول التطبيق (لا نكتفي بالسجل المحلي)
        tag = site_name or 'الموقع'
        print(f"❌ No chapters found for {metadata['title']} ({tag})")
        push_log(f"❌ [{tag}] فشل جلب قائمة الفصول للرواية '{metadata.get('title', '?')}' — "
                 f"لم يُسحب أي فصل. راجع سبب الفشل في سجلات السكرابر. "
                 f"إن كانت الرسالة تتكرر فأضف/جدد مفاتيح ScraperAPI من واجهة المفاتيح.", 'error')
        return

    # 🎯 سحب انتقائي: طبّق فلتر النطاق إن وُضع من /scrape
    all_chapters = apply_chapter_filter(all_chapters)
    if not all_chapters:
        push_log(f"🎯 [{site_name or 'الموقع'}] فلتر الفصول لم يطابق أي فصل في الفهرس "
                 f"({metadata.get('title', '?')}) — لم يُسحب شيء. تأكد من النطاق.", 'warning')
        return

    print(f"Processing {len(all_chapters)} chapters.")

    batch = []
    for chap in all_chapters:
        if chap['number'] in existing_chapters:
            continue

        print(f"Scraping {metadata.get('title', '?')}: Ch {chap['number']}...")
        try:
            content = content_fn(chap['url'])
        except Exception as e:
            print(f"❌ content_fn failed: {e}")
            content = None

        if content:
            batch.append({'number': chap['number'], 'title': chap['title'], 'content': content})
            if len(batch) >= batch_size:
                send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': batch, 'skipMetadataUpdate': True})
                batch = []
                time.sleep(delay)

    if batch:
        send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': batch, 'skipMetadataUpdate': True})
