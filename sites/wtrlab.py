# -*- coding: utf-8 -*-
"""
==========================================
🌐 WTR-LAB (wtr-lab.com) — قارئ ترجمة آلية إنجليزي (Next.js)
==========================================
موقع ترجمة آلية لروايات fanqienovel وغيرها — واجهة Next.js ببيانات
__NEXT_DATA__ وواجهات API عامة. تم التحقق حياً (v2.9):

- البحث/التصفح   /_next/data/{buildId}/en/novel-finder.json?...&text=  ← مجاني بلا جلسة
                   (buildId يُجلب طازجاً من /en/novel-finder — يتغير مع كل نشر)
- بيانات الرواية  صفحة /en/serie-{raw_id}/{slug} تحتاج جلسة (تحوّل لـ /auth/login)
                   ← البديل المجاني: نفس بحث novel-ficker مع مطابقة raw_id
- الفهرس          /api/chapters/{raw_id}?start=1&end=500  ← مجاني بلا جلسة (دفعات 500)
- محتوى الفصل     POST /api/reader/get {translate: ai|webplus|web, language: en,
                   raw_id, chapter_no, retry:false, force_retry:false}
                   ← يحصّن نفسه بـ Turnstile: {"requireTurnstile":true, "threshold":15}
                   مع جلسة مسجلة الدخول (كوكيز من الواجهة) يمر مباشرة.
- جسم الفصل إما:
    * قائمة فقرات إنجليزية (ترجمة ai/web) — كل عنصر فقرة
    * نص مشفر «arr:iv:tag:ct» أو «str:...» (AES-256-GCM، المفتاح أول 32 حرفاً
      بعد العلامة TextEncoder().encode(" في حزم JS العامة) — فكّه يعطي أسطراً
      صينية خام (فصول لم تُترجم بعد — تُحفظ كما هي مثل باقي المواقع الصينية)
- علامات المسرد في النص: ※N ⛬ أو ※N 〓 ← تُستبدل بـ glossary_data.terms[N]

🔑 الكوكيز (سلسلة المصادر):
    1) إعداد الواجهة (يُدفع من خادم التطبيق أو /wtrlab/cookies مباشرة)
    2) متغير البيئة WTRLAB_COOKIES
    3) لا ثابت بالكود — الموقع يحتاج حسابك أنت (التسجيل مجاني؛ انسخ ترويسة
       Cookie من المتصفح بعد تسجيل الدخول وحل أي تحدٍّ Turnstile مرة واحدة).
   بدون كوكيز: البيانات والفهرس يعملان، ومحتوى الفصول يرفض بتحدي Turnstile.
"""

import base64
import json
import os
import re
import threading
import time
from urllib.parse import quote_plus, urlparse

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.utils import UA_CHROME, clean_text
from core.registry import register_site

BASE = 'https://wtr-lab.com'
LANG = 'en'
READER_MODES = ('ai', 'webplus', 'web')
CHAPTERS_BATCH = 500
KEY_MARKER = 'TextEncoder().encode("'


class WtrLabError(RuntimeError):
    """أخطاء واضحة للمستخدم لا تحتوي قيم كوكيز أو أجسام ردود."""


class WtrLabSessionError(WtrLabError):
    """الجلسة غير كافية (تحدي Turnstile / انتهاء تسجيل الدخول) — جدّد الكوكيز."""


# ==========================================
# 🍪 الكوكيز + كاش مشترك (buildId / مفتاح AES)
# ==========================================
_RUNTIME = {'cookies': '', 'build_id': '', 'build_at': 0.0, 'aes_key': ''}
_LOCK = threading.Lock()


def set_runtime_cookies(value):
    """ضبط الكوكيز من واجهة الإعدادات (فارغ = تصفير)"""
    with _LOCK:
        _RUNTIME['cookies'] = str(value or '').strip()
    state = 'فُرِّغت' if not str(value or '').strip() else 'حُدِّثت'
    print(f"🌐 WTR-LAB cookies {state}")


def get_cookie_header():
    """كوكيز WTR-LAB: إعداد الواجهة ← البيئة ← لا شيء (مجهول)"""
    with _LOCK:
        runtime = _RUNTIME['cookies']
    if runtime:
        return runtime
    return os.environ.get('WTRLAB_COOKIES', '').strip() or ''


def cookie_summary():
    """ملخص مخفى لحالة الكوكيز (للواجهة — بلا قيم كاملة)"""
    header = get_cookie_header()
    names = []
    for part in str(header or '').split(';'):
        name = part.strip().partition('=')[0]
        if name and re.fullmatch(r'[A-Za-z0-9_\-]+', name):
            names.append(name)
    return {
        'source': 'settings' if _RUNTIME['cookies'] else ('env' if os.environ.get('WTRLAB_COOKIES', '').strip() else 'none'),
        'count': len(names),
        'cookies': names,
        'has_session': bool(names),
    }


def _session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': os.environ.get('WTRLAB_USER_AGENT', '') or UA_CHROME,
        'Accept-Language': 'en-US,en;q=0.9',
    })
    header = get_cookie_header()
    if header:
        if any(ord(c) < 32 or ord(c) == 127 for c in header):
            raise WtrLabSessionError('WTR-LAB: إعداد الكوكيز يجب أن يكون ترويسة Cookie واحدة فقط.')
        for part in header.split(';'):
            name, sep, value = part.strip().partition('=')
            if sep and re.fullmatch(r'[A-Za-z0-9_\-]+', name or ''):
                s.cookies.set(name, value, domain='wtr-lab.com', path='/')
    return s


def _get(url, referer=None, timeout=30):
    """GET مع كوكيز الجلسة — يرفع WtrLabError عند الفشل"""
    try:
        with _session() as s:
            headers = {'Referer': referer} if referer else {}
            r = s.get(url, headers=headers, timeout=timeout)
    except WtrLabSessionError:
        raise
    except Exception:
        raise WtrLabError('WTR-LAB: تعذر الاتصال بالموقع.') from None
    if r.status_code != 200:
        raise WtrLabError(f'WTR-LAB: فشل الطلب (HTTP {r.status_code}).')
    return r


def _get_json(url, referer=None):
    r = _get(url, referer=referer)
    try:
        return r.json()
    except (ValueError, TypeError):
        raise WtrLabError('WTR-LAB: الرد ليس JSON صالحاً.') from None


def _post_json(url, payload, referer=None):
    try:
        with _session() as s:
            r = s.post(url, json=payload, timeout=40,
                       headers={'Referer': referer or BASE + '/', 'Origin': BASE,
                                'Content-Type': 'application/json', 'Accept': 'application/json'})
    except Exception:
        raise WtrLabError('WTR-LAB: تعذر الاتصال بالموقع.') from None
    try:
        data = r.json()
    except (ValueError, TypeError):
        raise WtrLabError(f'WTR-LAB: رد غير متوقع (HTTP {r.status_code}) — ربما حماية Cloudflare.') from None
    if isinstance(data, dict) and (data.get('requireTurnstile') or data.get('require_turnstile')):
        raise WtrLabSessionError(
            'WTR-LAB: طلب الموقع تحقق Turnstile — جدّد كوكيز الحساب من واجهة السكرابر '
            '(انسخ ترويسة Cookie وأنت مسجل الدخول وبعد حل التحدي في المتصفح).')
    return data


# ==========================================
# 🧩 أدوات: الروابط، buildId، مفتاح AES، تنظيف العناوين
# ==========================================
_URL_RE = re.compile(r'/(?:[a-z]{2}/)?(?:serie-(\d+)|novel/(\d+))/([^/?#]+)(?:/chapter-(\d+))?', re.I)


def _ids(url, chapter=False):
    """استخراج raw_id و slug (و chapter_no عند طلب فصل) من رابط wtr-lab.com"""
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or p.netloc.lower().lstrip('www.') not in ('wtr-lab.com', 'wtr-lab.com:443'):
        if p.netloc.lower() not in ('wtr-lab.com', 'www.wtr-lab.com', 'wtr-lab.com:443', 'www.wtr-lab.com:443'):
            raise WtrLabError('WTR-LAB: استخدم رابطاً على wtr-lab.com فقط.')
    m = _URL_RE.search(p.path or '')
    if not m:
        raise WtrLabError('WTR-LAB: الرابط المدعوم /en/serie-{id}/{slug} أو /en/novel/{id}/{slug}.')
    raw_id = m.group(1) or m.group(2)
    slug = m.group(3) or ''
    chapter_no = m.group(4)
    if chapter and not chapter_no:
        raise WtrLabError('WTR-LAB: رابط الفصل يجب أن ينتهي بـ /chapter-{رقم}.')
    return str(raw_id), slug, (int(chapter_no) if chapter_no else None)


def _clean_title(text):
    """عناوين wtr-lab تحمل قوالب متغيرات %{الاسم|base64} — نظّفها للاسم الظاهر
    (تُستخدم أيضاً للوصف لأنه يحمل نفس القوالب)"""
    out = str(text or '')
    out = re.sub(r'%\{([^|}]*)\|[^}]*\}', r'\1', out)
    return out.strip()


def _build_id():
    """buildId الحالي لتطبيق Next.js — يُجلب طازجاً ويُكاشى 10 دقائق"""
    with _LOCK:
        if _RUNTIME['build_id'] and time.time() - _RUNTIME['build_at'] < 600:
            return _RUNTIME['build_id']
    r = _get(f'{BASE}/{LANG}/novel-finder')
    m = re.search(r'"buildId"\s*:\s*"([^"]+)"', r.text)
    if not m:
        raise WtrLabError('WTR-LAB: لم أجد buildId — ربما غيّر الموقع بنيته.')
    with _LOCK:
        _RUNTIME['build_id'] = m.group(1)
        _RUNTIME['build_at'] = time.time()
    return _RUNTIME['build_id']


def _aes_key(serie_url=None):
    """مفتاح فك التشفير: أول 32 محرفاً بعد TextEncoder().encode(" في حزم JS
    (نفس طريقة إضافة LNReader — تُجلب من صفحة السلسلة نفسها لأن شريحة القارئ
    لا تُحمّل في الصفحات العامة). يُكاشى بعد أول نجاح؛ وفشل الفحص يُكاشى 10
    دقائق حتى لا نعscan الحزم في كل فصل. تتطلب جلسة صالحة (الكوكيز)."""
    with _LOCK:
        cached = _RUNTIME['aes_key']
        now = time.time()
        if cached:
            return cached
        if now - _RUNTIME.get('key_fail_at', 0.0) < 600:
            raise WtrLabError('WTR-LAB: لم أجد مفتاح فك التشفير مؤخراً — '
                              'تأكد أن الكوكيز جلسة صالحة ثم أعد المحاولة.')

    def fail():
        with _LOCK:
            _RUNTIME['key_fail_at'] = time.time()

    pages = []
    if serie_url:
        pages.append(serie_url)
    pages += [f'{BASE}/{LANG}', f'{BASE}/{LANG}/novel-finder']
    script_urls = []
    for page in pages:
        try:
            html = _get(page).text
        except WtrLabError:
            continue
        script_urls.extend(re.findall(r'<script[^>]+src="(/_next/[^"]+\.js[^"]*)"', html))
        script_urls.extend(re.findall(r'<script[^>]+src="(https://wtr-lab\.com/_next/[^"]+\.js[^"]*)"', html))
        if script_urls:
            break
    seen = set()
    for src in script_urls[:20]:
        url = src if src.startswith('http') else BASE + src
        if url in seen:
            continue
        seen.add(url)
        try:
            code = _get(url, timeout=20).text
        except WtrLabError:
            continue
        idx = code.find(KEY_MARKER)
        if idx >= 0:
            key = code[idx + len(KEY_MARKER): idx + len(KEY_MARKER) + 32]
            if len(key) == 32 and re.fullmatch(r'[!-~]+', key):
                with _LOCK:
                    _RUNTIME['aes_key'] = key
                return key
    fail()
    raise WtrLabError('WTR-LAB: لم أجد مفتاح فك التشفير في حزم JS — '
                      'يحتاج جلسة صالحة (جدّد الكوكيز من واجهة السكرابر).')


def _decrypt_payload(encrypted, serie_url=None):
    """فك «arr:iv:tag:ct» / «str:...» — AES-256-GCM (مطابق لإضافة LNReader):
    المفتاح أول 32 بايت من مفتاح الصفحة، القيم الثلاث base64، والنتيجة نص
    أو JSON (حسب البادئة). لا ننفذ أي كود — فك تشفير قراءة فقط."""
    enc = str(encrypted or '')
    is_json = enc.startswith('arr:')
    if enc.startswith('arr:') or enc.startswith('str:'):
        enc = enc[4:]
    parts = enc.split(':')
    if len(parts) != 3:
        raise WtrLabError('WTR-LAB: تنسيق بيانات الفصل المشفرة غير معروف.')
    try:
        iv, tag, ciphertext = (base64.b64decode(p) for p in parts)
        key = _aes_key(serie_url).encode('utf-8')
        decryptor = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
        plain = (decryptor.update(ciphertext) + decryptor.finalize()).decode('utf-8')
    except (ValueError, TypeError, UnicodeError) as e:
        raise WtrLabError('WTR-LAB: فشل فك تشفير الفصل (المفتاح/البيانات غير متوافقة).') from e
    if is_json:
        try:
            return json.loads(plain)
        except (ValueError, TypeError):
            raise WtrLabError('WTR-LAB: بيانات الفصل المشفرة ليست JSON بعد الفك.') from None
    return plain


_GLOSS_MARK_RE = re.compile(r'(?:wtr-lab\s+)?※([0-9]+)[⛬〓]')


def _body_to_text(body, glossary_terms, serie_url=None):
    """جسم الفصل ← نص بأسطر نظيفة:
    - قائمة فقرات إنجليزية (ترجمة ai/web) ← فقرات مفصولة بسطرين
    - نص مشفر arr:/str: ← فك GCM؛ JSON يعطي قائمة أسطر صينية خام (فصول غير
      مترجمة — تُحفظ كما هي مثل باقي المواقع الصينية في السكرابر)
    - علامات المسرد ※N ⛬/〓 ← تُستبدل بمصطلحها من glossary_data"""
    items = None
    if isinstance(body, list):
        items = [str(x) for x in body]
    elif isinstance(body, str) and (body.startswith('arr:') or body.startswith('str:')):
        decoded = _decrypt_payload(body, serie_url)
        if isinstance(decoded, list):
            items = [str(x) for x in decoded]
        else:
            items = [str(decoded)]
    if items is None:
        # نص عادي غير مشفر (شكل مستقبلي محتمل)
        items = [str(body)]

    terms = [str(t[0]) for t in (glossary_terms or []) if isinstance(t, (list, tuple)) and t]

    out_lines = []
    for line in items:
        line = line.strip()
        if not line:
            continue
        if terms:
            line = _GLOSS_MARK_RE.sub(
                lambda m: terms[int(m.group(1))] if int(m.group(1)) < len(terms) else m.group(0), line)
        out_lines.append(line)
    if not out_lines:
        return ''
    # فصول إنجليزية = فقرات (سطران بينها)؛ أسطر صينية مفكوكة = سطر واحد بينها
    is_chinese_raw = any(re.search(r'[\u4e00-\u9fff]', ln) for ln in out_lines[:5])
    joiner = '\n' if is_chinese_raw else '\n\n'
    return clean_text(joiner.join(out_lines))


# ==========================================
# 📖 بيانات الرواية
# ==========================================
def _novel_from_serie_data(sd, raw_id, slug, tag_map=None):
    data = sd.get('data') or {}
    title = _clean_title(data.get('title') or '')
    if not title:
        raise WtrLabError('WTR-LAB: بيانات الرواية بلا عنوان.')
    status = 'مستمرة'
    if sd.get('status') == 1:
        status = 'مكتملة'
    # التصنيفات أرقام في بيانات السلسلة — تُحلّ إلى أسمائها عبر خريطة novel-finder
    names = []
    for g in list(sd.get('genres') or []) + list(sd.get('tags') or []):
        try:
            gid = int(g)
        except (ValueError, TypeError):
            name = str(g) if g else ''
            if name and name not in names:
                names.append(name)
            continue
        label = (tag_map or {}).get(gid)
        name = label or (f'#{gid}' if not label else '')
        if name and name not in names:
            names.append(name)
    return {
        'title': title,
        'description': _clean_title(data.get('description') or ''),
        'cover': data.get('image') or '',
        'author': str(data.get('author') or ''),
        'status': status,
        'category': names[0] if names else 'عام',
        'tags': names[:12] or ['عام'],
        'book_id': str(raw_id),
        'sourceUrl': f'{BASE}/{LANG}/serie-{raw_id}/{slug}',
        'lastUpdate': (sd.get('updated_at') or sd.get('update_at') or ''),
    }


def _tags_map_from_pp(pp):
    """خريطة id→اسم من pageProps.tags لبحث novel-finder:
    {category: [{value: id, label: name, ...}, ...]}"""
    mapping = {}
    tags = (pp or {}).get('tags')
    if not isinstance(tags, dict):
        return mapping
    for items in tags.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and it.get('value') is not None and it.get('label'):
                try:
                    mapping[int(it['value'])] = str(it['label'])
                except (ValueError, TypeError):
                    continue
    return mapping


def _metadata_via_finder(raw_id, slug):
    """المسار المجاني لبيانات الرواية: بحث novel-ficker مع مطابقة raw_id —
    (صفحة السلسلة نفسها تتحول لجدار تسجيل الدخول بلا جلسة)"""
    build = _build_id()
    text = quote_plus(slug.replace('-', ' ').strip()[:80])
    for page in (1, 2, 3):
        url = (f'{BASE}/_next/data/{build}/{LANG}/novel-finder.json'
               f'?orderBy=update&order=desc&status=all&release_status=all&addition_age=all'
               f'&page={page}&text={text}')
        j = _get_json(url, referer=f'{BASE}/{LANG}/novel-finder')
        pp = j.get('pageProps') or {}
        series = pp.get('series') or []
        tag_map = _tags_map_from_pp(pp)
        for item in series:
            if str(item.get('raw_id')) == str(raw_id):
                return _novel_from_serie_data(item, raw_id, slug, tag_map)
        if len(series) < 10:
            break
    return None


# ==========================================
# 🚀 نقاط الاستدعاء (نفس توقيع كل المواقع)
# ==========================================
def fetch_metadata_wtrlab(url):
    raw_id, slug, _ = _ids(url)
    # 1) صفحة السلسلة (تعمل مع جلسة صالحة — وتحول لجدار الدخول بلا جلسة)
    try:
        html = _get(f'{BASE}/{LANG}/serie-{raw_id}/{slug}').text
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
                      html, re.S)
        if m:
            page = json.loads(m.group(1))
            pp = (page.get('props') or {}).get('pageProps') or {}
            sd = ((pp.get('serie') or {}).get('serie_data'))
            if isinstance(sd, dict) and sd.get('raw_id'):
                return _novel_from_serie_data(sd, raw_id, slug, _tags_map_from_pp(pp))
    except WtrLabSessionError:
        raise
    except WtrLabError:
        pass
    # 2) البحث العام (مجاني بلا جلسة)
    novel = _metadata_via_finder(raw_id, slug)
    if novel:
        return novel
    raise WtrLabError('WTR-LAB: لم أجد بيانات الرواية — تأكد من صحة الرابط '
                      '(وإن كنت تستخدم جلسة فجدّد الكوكيز من واجهة السكرابر).')


def fetch_chapter_list_wtrlab(url):
    raw_id, slug, _ = _ids(url)
    referer = f'{BASE}/{LANG}/serie-{raw_id}/{slug}'
    chapters, seen = [], set()
    start = 1
    while True:
        end = start + CHAPTERS_BATCH - 1
        j = _get_json(f'{BASE}/api/chapters/{raw_id}?start={start}&end={end}', referer=referer)
        lst = j.get('chapters') if isinstance(j, dict) else None
        if lst is None and isinstance(j, dict):
            lst = (j.get('data') or {}).get('chapters')
        if not isinstance(lst, list) or not lst:
            break
        for c in lst:
            if not isinstance(c, dict):
                continue
            try:
                order = int(str(c.get('order')))
            except (ValueError, TypeError):
                continue
            if order in seen:
                continue
            seen.add(order)
            title = _clean_title(c.get('title') or c.get('name') or f'Chapter {order}')
            chapters.append({'number': order, 'title': title,
                             'url': f'{BASE}/{LANG}/serie-{raw_id}/{slug}/chapter-{order}'})
        if len(lst) < CHAPTERS_BATCH:
            break
        start = end + 1
    if not chapters:
        raise WtrLabError('WTR-LAB: قائمة الفصول فارغة أو تغير تنسيقها.')
    chapters.sort(key=lambda c: c['number'])
    return chapters


def scrape_chapter_wtrlab(url):
    raw_id, slug, chapter_no = _ids(url, chapter=True)
    last_err = ''
    for mode in READER_MODES:
        data = _post_json(
            f'{BASE}/api/reader/get',
            {'translate': mode, 'language': LANG, 'raw_id': int(raw_id),
             'chapter_no': int(chapter_no), 'retry': False, 'force_retry': False},
            referer=url,
        )
        if not isinstance(data, dict):
            last_err = 'رد غير معروف'
            continue
        if data.get('error') or data.get('success') is False:
            last_err = str(data.get('error') or data.get('message') or 'فشل الطلب')
            continue
        inner = (data.get('data') or {})
        inner_data = inner.get('data') or {}
        body = inner_data.get('body')
        if body is None:
            last_err = 'الرد بلا جسم فصل'
            continue
        terms = ((inner_data.get('glossary_data') or {}).get('terms') or [])
        serie_url = f'{BASE}/{LANG}/serie-{raw_id}/{slug}'
        text = _body_to_text(body, terms, serie_url)
        if text:
            return text
        last_err = 'جسم الفصل فارغ'
    raise WtrLabError(f'WTR-LAB: تعذر جلب محتوى الفصل ({last_err}). '
                      'جرّب جلسة مسجلة الدخول (كوكيز من واجهة السكرابر).')


def worker_wtrlab(url, admin_email, metadata):
    from core.utils import generic_worker
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_wtrlab, scrape_chapter_wtrlab,
                   site_name='WTR-LAB')


def quick_session_check():
    """فحص حي من واجهة الإعدادات: هل الكوكيز تجعل قراءة الفصول ممكنة؟
    يجرّب قراءة فصل حقيقي ويعيد نتيجة واضحة بلا أي قيم حساسة."""
    header = get_cookie_header()
    if not header:
        return {'ok': False, 'message': 'لا توجد كوكيز — البيانات والفهرس يعملان مجاناً لكن '
                                        'قراءة الفصول ستصطدم بتحدي Turnstile. الصق ترويسة Cookie '
                                        'من متصفحك بعد تسجيل الدخول.'}
    # رواية وفصل حقيقيان ثابتان (من الفحص الحي)
    test_url = f'{BASE}/{LANG}/serie-93530/sorcerer-world-starting-with-the-flame-flame-fruit/chapter-1'
    try:
        text = scrape_chapter_wtrlab(test_url)
        return {'ok': True, 'message': f'الجلسة تعمل — فصل تجريبي جلب {len(text)} حرفاً بنجاح.'}
    except WtrLabSessionError as e:
        return {'ok': False, 'message': str(e)}
    except WtrLabError as e:
        return {'ok': False, 'message': str(e)}


register_site(
    domain_patterns=['wtr-lab.com', 'www.wtr-lab.com'],
    name='WTR-LAB',
    language='english',
    fetch_metadata=fetch_metadata_wtrlab,
    fetch_chapters=fetch_chapter_list_wtrlab,
    fetch_content=scrape_chapter_wtrlab,
    worker=worker_wtrlab,
    status='active',
    notes='جديد (v2.9)! بيانات الرواية والفهرس يعملان بلا جلسة (بحث novel-finder + /api/chapters). '
          'محتوى الفصول يحتاج جلسة (Turnstile) — الكوكيز من واجهة السكرابر (موقع/تطبيق بنفس الواجهة). '
          'الترجمة ai ثم webplus ثم web؛ الفصول غير المترجمة تُفك (AES-GCM بمفتاح حزم JS) وتُحفظ صينية خام. '
          'علامات المسرد ※N تُستبدل تلقائياً بمصطلحات glossary_data.'
)
