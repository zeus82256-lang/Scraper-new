# -*- coding: utf-8 -*-
"""
==========================================
🟨 مواقع صينية إضافية (Extra Chinese Sites)
==========================================
5 مواقع جديدة (v3.0) — كلها بدعم كامل: بيانات + فهرس بعناوين حقيقية +
محتوى نظيف + أغلفة، مع كشف صادق للمحتوى المحجوب بدل إرسال نص ناقص:

1.  Tadu      - www.tadu.com            ✅ بيانات/فهرس/محتوى عبر نقطة JSONP داخلية.
                                          الزائر يقرأ أول 30 فصلاً كاملة ثم معاينات؛
                                          كوكيز حساب (اختيارية) توسّع القراءة — تُدار
                                          من واجهة السكرابر أو البيئة TADU_COOKIES.
2.  Bixiange  - www.bixiange.top        ✅ قالب Empire CMS بترميز GBK — فهرس كامل
                                          بصفحة الكتاب + محتوى div#mycontent.
3.  FFXS8     - www.ffxs8.com           ✅ نفس القالب — فهرس /book/{cls}-{id}-{n}.html.
4.  JPXS123   - jpxs123.com             ✅ نفس القالب — محتوى div.read_chapterDetail.
5.  TaobaoJH  - jhbook.taobao.com       ⚠️ بيانات وفهرس مجانيان (SSR JSON مضمّن)،
                                          قراءة الفصول تتطلب جلسة تسجيل دخول
                                          (كوكيز من واجهة السكرابر أو JHBOOK_COOKIES).

📝 ملاحظة مشتركة: أول فصل في مواقع القالب الثلاثة يبدأ بمقدمة الكتاب الملحقة
(عنوان/مؤلف/简介/源名/别名/标签) — تُنزع تلقائياً عبر إيجاد عنوان الفصل الحقيقي
«第N章» داخل النص (يعمل حتى بلا أي كاش).

📄 تنزيلات TXT لهذه المواقع اختُبرت فعلياً (التقرير الكامل في README قسم 17):
الملفات تُنزّل لكنها قديمة/غير محاذية لفهرس الموقع فلا تصلح لخط الترجمة
المحاذي — السحب المباشر هو المعتمد.
"""

import os
import re
import json
import time
import threading
from urllib.parse import urljoin, urlparse

from core.registry import register_site
from core.utils import (
    smart_get, parse_html, get_headers, get_base_url, fix_image_url,
    clean_text, get_meta,
    UA_CHROME, SmartResponse,
    generic_worker,
)

# ==========================================
# 🧰 مساعد الترميز الصيني (GBK-Safe Fetcher)
# ==========================================
# curl_cffi يفك النص تلقائياً بترميز خاطئ للصفحات GBK، وBeautifulSoup يفك GBK
# كـ windows-1252 عند تمرير .content الخام — لذلك نفك البايتات بأنفسنا دائماً:
# نقيس سلامة النص (نمط 第N章 + مجموعات CJK + محارف التلف U+FFFD) ونختار
# الترميز الأفضل (utf-8 ثم gb18030) ثم نُطبّق التحقق على النص المُصلَح لا قبله.

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_CHAPTER_HEAD_RE = re.compile(r'第\s*\d+\s*[章節节回]')
_META_CHARSET_RE = re.compile(r'charset\s*=\s*["\']?([\w-]+)', re.I)


def _best_cjk_decode(raw, hint=None):
    """فك بايتات الصفحة بأفضل ترميز: utf-8 → gb18030 (الشامل لـ GBK/GB2312).
    يعيد (النص، اسم الترميز)."""
    if hint:
        try:
            enc = hint.lower().replace('gb2312', 'gb18030').replace('gbk', 'gb18030')
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        return raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode('gb18030'), 'gb18030'
    except UnicodeDecodeError:
        return raw.decode('gb18030', errors='replace'), 'gb18030'


def _cjk_health(text):
    """قياس سلامة نص صيني: (نسبة CJK، وجود عنوان فصل، عدد محارف التلف)"""
    if not text:
        return 0.0, False, 0
    cjk = len(_CJK_RE.findall(text))
    return cjk / max(1, len(text)), bool(_CHAPTER_HEAD_RE.search(text)), text.count('\ufffd')


def _looks_blocked_cjk(text):
    """كشف صفحات الحجب (تحديات إنجليزية أو رسائل صينية)"""
    if not text or len(text) < 80:
        return True
    low = text[:1500].lower()
    for marker in ('just a moment', 'challenge-platform', '_cf_chl_opt',
                   'attention required', 'checking your browser', 'cf-mitigated'):
        if marker in low:
            return True
    return False


def _smart_to_text(resp):
    """توحيد أي استجابة (SmartResponse أو Response خام) إلى نص مفكوك صحيحاً"""
    if resp is None:
        return None
    if isinstance(resp, SmartResponse):
        return resp.text
    # Response خام: نفك من البايتات بأنفسنا (قد يكون .text مفكوكاً خطأً)
    raw = getattr(resp, 'content', None) or b''
    hint = None
    head = raw[:800]
    m = _META_CHARSET_RE.search(head.decode('ascii', errors='ignore'))
    if m:
        hint = m.group(1)
    text, _enc = _best_cjk_decode(raw, hint)
    return text


def _cjk_get(url, referer=None, timeout=25, validate=None, extra_headers=None):
    """طلب نصي آمن للترميز الصيني:
    1) مباشر (curl_cffi — بصمة متصفح) مع فك البايتات بأنفسنا + إعادات محاولة قصيرة
       (بعض مواقع القالب تُقيّد الطلبات المتتالية فتحجب مؤقتاً ثم تعود)
    2) عند الفشل/الحجب: التوجيه الذكي (بروكسي جوجل → FlareSolverr → ScraperAPI)
    يعيد SmartResponse نصياً دائماً أو None."""
    headers = get_headers(referer=referer, lang='zh-CN,zh;q=0.9,en;q=0.5')
    if extra_headers:
        headers.update(extra_headers)
    # ---------- الطريقة 1: المباشر (3 محاولات) ----------
    from curl_cffi import requests as _cffi
    for attempt in range(3):
        try:
            r = _cffi.get(url, headers=headers, timeout=timeout, impersonate='chrome131')
            if r.status_code == 200:
                hint = None
                m = _META_CHARSET_RE.search(r.content[:800].decode('ascii', errors='ignore'))
                if m:
                    hint = m.group(1)
                text, _enc = _best_cjk_decode(r.content, hint)
                if not _looks_blocked_cjk(text) and (validate is None or validate(text)):
                    return SmartResponse(text, 200, route='direct')
        except Exception as e:
            print(f"   cjk direct failed {url[:70]}: {str(e)[:70]}")
        if attempt < 2:
            time.sleep(1.5 + attempt * 1.5)  # 1.5ث ثم 3ث — تقييد الطلبات يزول غالباً
    # ---------- الطريقة 2: التوجيه الذكي ----------
    resp = smart_get(url, sl='zh-CN', tl='es', referer=referer, timeout=timeout,
                     validate=validate)
    text = _smart_to_text(resp)
    if text is None or _looks_blocked_cjk(text) or (validate is not None and not validate(text)):
        return None
    return SmartResponse(text, 200, route=getattr(resp, 'route', 'smart'))


def _html_to_text(html_fragment):
    """تحويل جسم فصل HTML (وسوم <p>) إلى نص بأسطر نظيفة — دون تنفيذ أي شيء"""
    if not html_fragment:
        return ''
    text = str(html_fragment)
    if re.search(r'<(?:p\b|br\b|div\b|/p\b)', text, re.I):
        text = re.sub(r'(?i)<br\s*/?>', '\n', text)
        text = re.sub(r'(?i)</p\s*>', '\n\n', text)
        text = re.sub(r'(?i)<p[^>]*>', '', text)
        text = re.sub(r'(?i)<[^>]+>', '', text)
    import html as _html
    return _html.unescape(text)


# إعلانات/ضجيج يتكرر في مواقع القالب الصيني — يُنزع من سطر كامل فقط
_AD_LINE_RE = re.compile(
    r'^(?:www\.|\S{0,12}(?:com|cn|net|cc|top|xyz|info)\b.{0,30})$',
    re.I)


def _clean_chapter_text(text):
    """تنظيف نهائي لنص الفصل: محارف تالفة + أسطر إعلانات + أسطر فارغة زائدة"""
    if not text:
        return ''
    text = text.replace('\ufffd', '')  # بايتات «——» التالفة في ffxs8 وأشباهها
    lines = []
    for line in text.split('\n'):
        l = line.strip()
        if not l:
            lines.append('')
            continue
        if len(l) <= 40 and _AD_LINE_RE.match(l):
            continue
        lines.append(l)
    return clean_text('\n'.join(lines))


def _tadu_deobfuscate(text):
    """نزع إعلانات Tadu المُشوَّشة (تتكرر عشوائياً داخل كل فصل).
    التشويش يبدّل حرفاً من كل كلمة برموز (~>*@&^—.) والإعلان دائماً سطر
    مستقل قصير يحمل العلامة التجارية — نفحص كل سطر بعد إزالة الرموز."""
    if not text:
        return ''
    out = []
    for line in text.split('\n'):
        stripped = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', line)
        if stripped and len(stripped) <= 60 and '塔读' in stripped:
            continue  # سطر إعلان مشوَّش (قد يتضاعف: 首发APP + 免费无广告 بسطر واحد)
        out.append(line)
    return '\n'.join(out)


def _strip_book_intro(lines, chapter_no, book_title):
    """نزع مقدمة الكتاب الملحقة بأول فصل (عنوان/مؤلف/简介/源名/别名/标签).
    الأساس: إيجاد عنوان الفصل الحقيقي «第N章» في بداية النص وقطع ما قبله؛
    واحتياطاً: نزع الأسطر الوصفية المتتالية من أول النص فقط (لا نمس الحكي أبداً)."""
    # 1) القص بعنوان الفصل (مؤكد حياً على المواقع الثلاثة)
    if chapter_no:
        head_re = re.compile(rf'^\s*第\s*{int(chapter_no)}\s*[章節节回]')
        limit = max(12, int(len(lines) * 0.4))
        for i in range(min(limit, len(lines))):
            if head_re.match(lines[i]):
                return lines[i:]
    # 2) احتياط: أسطر وصفية متتالية من البداية فقط
    meta_re = re.compile(r'^(?:源名|别名|原名|标签|主角|作者|状态|字数|更新|内容简介|简介)\s*[：:]')
    start = 0
    title_key = (book_title or '')[:8]
    while start < len(lines):
        l = lines[start].strip()
        if not l:
            start += 1
            continue
        if meta_re.match(l) or (title_key and l.startswith(title_key)):
            start += 1
            continue
        break
    return lines[start:]


# ==========================================
# 🟠 1. TADU (www.tadu.com — 塔读文学)
# ==========================================
# - بيانات الكتاب: وسوم og:novel:* داخل صفحة /book/{id}
# - الفهرس: /book/catalogue/{id} — كل الفصول بصفحة واحدة
#   (روابط href="  /book/{id}/{chapter_id}/ " مُحاطة بمسافات)
# - المحتوى: نقطة JSONP داخلية /getPartContentByCodeTable/{book}/{seq}
#   حيث seq = ترتيب الفصل في الفهرس (مؤكد حياً: الفصل الأخير = 454).
# - قاعدة القراءة (مؤكدة حياً): الزائر أول 30 فصلاً كاملة (msg=«成功» +
#   نص طويل) ثم معاينات ~200 محرف (msg=null). الكوكيز توسّع القراءة.

_TADU_BASE = 'https://www.tadu.com'
_TADU_CHECK_BOOK = '1034377'          # كتاب الفحص (سلسلة قائمة قيد الكتابة)
_TADU_FREE_LIMIT_HINT = 30            # آخر فصل مجاني للزائر (مؤكد حياً)
_TADU_SEQ_CACHE = {}                  # book_id -> {'by_id': {chapter_id: seq}, 'at': ts}
_TADU_LOCK = threading.Lock()
_TADU_RUNTIME = {'cookies': '', 'app_cookies': '', 'last_app_pull': 0.0}
_TADU_WARNED = set()                  # كتب أُبلغ عن المعاينة مرة واحدة

# وسوم og:novel:* لا يفكها html.parser في صفحات هذا الموقع (مؤكد حياً) —
# لذلك تُستخرج من HTML الخام بـ regex (كل ترتيبات الخصائص).
_TADU_OG_RES = {
    key: re.compile(
        r'<meta[^>]*?(?:property|name)\s*=\s*["\']og:novel:' + key +
        r'["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']', re.I | re.S)
    for key in ('book_name', 'author', 'category', 'status',
                'latest_chapter_name', 'latest_chapter_url', 'read_url')
}
_TADU_OG_IMAGE_RE = re.compile(
    r'<meta[^>]*?(?:property|name)\s*=\s*["\']og:image["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']',
    re.I | re.S)
_TADU_INTRO_RE = re.compile(
    r'<(?:div|p)[^>]*class\s*=\s*["\'][^"\']*\bintro\b[^"\']*["\'][^>]*>(.*?)</(?:div|p)>',
    re.I | re.S)


def _tadu_meta_value(html, key, default=''):
    m = _TADU_OG_RES.get(key)
    if m:
        found = m.search(html)
        if found:
            return found.group(1).strip()
    return default


class TaduError(Exception):
    pass


def set_tadu_runtime_cookies(value):
    """ضبط كوكيز Tadu من واجهة الإعدادات (فارغ = وضع الزائر)"""
    with _TADU_LOCK:
        _TADU_RUNTIME['cookies'] = str(value or '').strip()
    print(f"🍊 Tadu cookies {'فُرِّغت (وضع الزائر)' if not str(value or '').strip() else 'حُدِّثت'}")


def _pull_tadu_cookies_from_app():
    """سحب كوكيز Tadu من خادم التطبيق (حقل taduCookies) — كل 5 دقائق كحد أقصى"""
    now = time.time()
    with _TADU_LOCK:
        if now - _TADU_RUNTIME['last_app_pull'] < 300:
            return
        _TADU_RUNTIME['last_app_pull'] = now
    try:
        from core.config import API_SECRET, NODE_BACKEND_URL
        import requests
        r = requests.get(f"{NODE_BACKEND_URL}/api/admin/scraper-keys",
                         headers={'x-api-secret': API_SECRET}, timeout=20)
        if r.status_code == 200:
            val = str((r.json() or {}).get('taduCookies') or '').strip()
            with _TADU_LOCK:
                _TADU_RUNTIME['app_cookies'] = val
            if val:
                print("🍊 Pulled Tadu cookies from app server settings")
    except Exception as e:
        print(f"   Tadu app-pull failed: {str(e)[:70]}")


def _tadu_cookie_header():
    """ترويسة Cookie حسب سلسلة الأولوية: إعداد ← خادم التطبيق ← بيئة ← فارغ (زائر)"""
    with _TADU_LOCK:
        runtime = _TADU_RUNTIME['cookies']
    if runtime:
        return runtime
    with _TADU_LOCK:
        app_val = _TADU_RUNTIME['app_cookies']
        should_pull = not app_val
    if should_pull:
        _pull_tadu_cookies_from_app()
        with _TADU_LOCK:
            app_val = _TADU_RUNTIME['app_cookies']
    if app_val:
        return app_val
    return os.environ.get('TADU_COOKIES', '').strip()


def tadu_cookie_summary():
    """ملخص مخفى لحالة كوكيز Tadu (للواجهة — بلا قيم كاملة)"""
    header = _tadu_cookie_header()
    parts = {}
    for part in str(header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        if sep and re.fullmatch(r'[A-Za-z0-9_\-]+', name):
            parts[name] = value
    masked = [f"{n}={(v[:6] + '…' + v[-4:]) if len(v) > 12 else '…'}" for n, v in parts.items()]
    if not parts:
        return {'source': 'guest', 'count': 0, 'cookies': [], 'has_session': False,
                'message': 'وضع الزائر — أول 30 فصلاً كاملة فقط؛ الكوكيز اختيارية لتوسيع القراءة.'}
    return {'source': 'settings', 'count': len(parts), 'cookies': masked, 'has_session': True,
            'message': 'الكوكيز مضبوطة — ستوسّع القراءة إن كان الحساب صالحاً.'}


def _tadu_ids(url, chapter=False):
    """تحليل رابط Tadu: /book/{id} أو /book/{id}/{chapter_id}/"""
    p = urlparse(url)
    if p.netloc.lower() not in ('tadu.com', 'www.tadu.com'):
        raise TaduError('Tadu: استخدم رابطاً على tadu.com فقط.')
    m = re.fullmatch(r'/book/(\d+)(?:/(\d+))?/?', p.path or '')
    if not m or (chapter and not m.group(2)):
        raise TaduError('Tadu: الرابط المدعوم /book/{book_id} أو /book/{book_id}/{chapter_id}/.')
    return m.group(1), m.group(2)


def fetch_metadata_tadu(url):
    """بيانات الرواية من وسوم og:novel:* في صفحة الكتاب (تقبل رابط فصل أيضاً)"""
    try:
        bid, _ = _tadu_ids(url)
        book_url = f'{_TADU_BASE}/book/{bid}'
        # نرفض الصفحات المتدهورة (بلا وسوم og:novel ولا كتلة bookIntro)
        r = _cjk_get(book_url, timeout=30,
                     validate=lambda t: 'og:novel:' in t or 'bookIntro' in t)
        if r is None:
            print(f"Tadu metadata: page fetch failed for {bid}")
            return None
        raw = r.text
        soup = parse_html(r)
        title = _tadu_meta_value(raw, 'book_name')
        author = _tadu_meta_value(raw, 'author')
        category = _tadu_meta_value(raw, 'category')
        status_txt = _tadu_meta_value(raw, 'status')
        cover_m = _TADU_OG_IMAGE_RE.search(raw)
        cover = cover_m.group(1).strip() if cover_m else ''
        # احتياط: كتلة bookIntro تحمل العنوان/الغلاف/المؤلف إن أخفت الصفحة الوسوم
        if not title:
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(' ', strip=True)
        if not cover:
            img = soup.select_one('.bookCover img, .bookImg img')
            if img:
                cover = img.get('src') or img.get('data-src') or ''
        if not author:
            m = re.search(r'作者[：:]\s*([^\s<|，,]{1,25})', soup.get_text('\n', strip=True))
            if m:
                author = m.group(1)
        description = ''
        intro_m = _TADU_INTRO_RE.search(raw)
        if intro_m:
            description = _html_to_text(intro_m.group(1)).strip()
        if not description:
            description = get_meta(soup, name='description')
        description = re.sub(r'^《[^》]+》是.{0,30}在塔读文学原创首发的.{0,12}，', '', description or '').strip()
        if not description:
            description = '—'
        tags = [t for t in [category] if t]
        if author and author not in tags:
            tags.append(author)
        status = 'مكتملة' if '完' in (status_txt or '') else 'مستمرة'
        return {
            'title': title or 'Unknown Title', 'description': description,
            'cover': fix_image_url(cover, base_url=_TADU_BASE),
            'status': status, 'category': category or 'عام', 'tags': tags,
            'sourceUrl': book_url, 'lastUpdate': None,
        }
    except TaduError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error Tadu Meta: {e}")
        return None


def _tadu_catalogue(bid):
    """فهرس كامل من صفحة /book/catalogue/{id} — الترتيب في الصفحة هو seq المحتوى"""
    r = _cjk_get(f'{_TADU_BASE}/book/catalogue/{bid}', timeout=30,
                 validate=lambda t: '/book/' in t)
    if r is None:
        return []
    soup = parse_html(r)
    rows = []
    for a in soup.select('div.chapter a'):
        href = (a.get('href') or '').strip()
        m = re.search(r'/book/(\d+)/(\d+)/?$', href)
        if not m or m.group(1) != bid:
            continue
        rows.append({'chapter_id': m.group(2), 'title': a.get_text(' ', strip=True)})
    # الترتيب في الصفحة = ترتيب الفصل (seq) المستخدم في نقطة المحتوى
    chapters = []
    for i, row in enumerate(rows):
        chapters.append({
            'number': i + 1,
            'url': f'{_TADU_BASE}/book/{bid}/{row["chapter_id"]}/',
            'title': row['title'] or f'第{i + 1}章',
        })
    with _TADU_LOCK:
        _TADU_SEQ_CACHE[bid] = {
            'by_id': {row['chapter_id']: i + 1 for i, row in enumerate(rows)},
            'at': time.time(),
        }
    return chapters


def _tadu_seq_for(bid, chapter_id):
    """إيجاد ترتيب الفصل (seq): كاش ← بناء الفهرس ← مرجع صفحة الفصل"""
    with _TADU_LOCK:
        cache = _TADU_SEQ_CACHE.get(bid)
        if cache and time.time() - cache['at'] < 6 * 3600:
            seq = cache['by_id'].get(chapter_id)
            if seq:
                return seq
    chapters = _tadu_catalogue(bid)
    if chapters:
        with _TADU_LOCK:
            cache = _TADU_SEQ_CACHE.get(bid)
            if cache:
                seq = cache['by_id'].get(chapter_id)
                if seq:
                    return seq
    # احتياط أخير: صفحة الفصل نفسها تحمل مرجع نقطة المحتوى بـ seq الصحيح
    r = _cjk_get(f'{_TADU_BASE}/book/{bid}/{chapter_id}/', timeout=25)
    if r is not None:
        m = re.search(r'getPartContentByCodeTable/' + re.escape(bid) + r'/(\d+)', r.text)
        if m:
            return int(m.group(1))
    raise TaduError(f'Tadu: تعذر تحديد ترتيب الفصل {chapter_id} من كتاب {bid}.')


def _tadu_warn_preview_once(bid, number):
    """تحذير صادق مرة واحدة لكل كتاب عند أول معاينة محجوبة"""
    key = f'tadu:{bid}'
    if key in _TADU_WARNED:
        return
    _TADU_WARNED.add(key)
    try:
        from core.backend import push_log
        push_log(f'🍊 [Tadu] الفصول بعد رقم {_TADU_FREE_LIMIT_HINT} معاينات محجوبة لوضع الزائر '
                 f'(فصل #{number}). لإكمال الرواية كاملة: الصق كوكيز حساب Tadu من '
                 'واجهة السكرابر (موقع/تطبيق بنفس الواجهة) — الفصول المحفوظة تُتخطى عند الاستئناف.', 'warning')
    except Exception:
        pass


def fetch_chapter_list_tadu(url):
    try:
        bid, _ = _tadu_ids(url)
        chapters = _tadu_catalogue(bid)
        if not chapters:
            print(f"Tadu: no chapters in catalogue of {bid}")
        return chapters
    except TaduError as e:
        print(str(e))
        return []


def scrape_chapter_tadu(url):
    """محتوى فصل Tadu من نقطة JSONP — كشف صادق للمعاينة المحجوبة"""
    try:
        bid, cid = _tadu_ids(url, chapter=True)
        seq = _tadu_seq_for(bid, cid)
        cookies = _tadu_cookie_header()
        extra = {'Referer': f'{_TADU_BASE}/book/{bid}/', 'X-Requested-With': 'XMLHttpRequest'}
        if cookies:
            extra['Cookie'] = cookies
        r = _cjk_get(f'{_TADU_BASE}/getPartContentByCodeTable/{bid}/{seq}',
                     referer=f'{_TADU_BASE}/book/{bid}/', extra_headers=extra, timeout=25)
        if r is None:
            return None
        try:
            data = json.loads(r.text)
        except Exception:
            print("Tadu: content endpoint returned non-JSON")
            return None
        content = (data.get('data') or {}).get('content') or ''
        msg = data.get('msg')
        text = _html_to_text(content)
        plain_len = len(re.sub(r'\s', '', text))
        # الفصل الكامل: msg=«成功» ونص طويل. المعاينة: نص ~200 محرف وmsg=null
        if plain_len < 400 and msg != '成功':
            _tadu_warn_preview_once(bid, seq)
            print(f"Tadu: chapter seq={seq} is a blocked preview ({plain_len} chars)")
            return None
        if plain_len < 50:
            print(f"Tadu: chapter seq={seq} returned empty content")
            return None
        return _clean_chapter_text(_tadu_deobfuscate(text))
    except TaduError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error Tadu Chapter: {e}")
        return None


def worker_tadu(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_tadu, scrape_chapter_tadu,
                   site_name='Tadu')


def tadu_quick_session_check():
    """فحص حي: هل كوكيز Tadu توسّع القراءة فعلاً؟ (فصل ما بعد الحد المجاني)"""
    header = _tadu_cookie_header()
    try:
        bid = _TADU_CHECK_BOOK
        probe_seq = _TADU_FREE_LIMIT_HINT + 1  # فصل معروف أنه معاينة للزائر
        extra = {'Referer': f'{_TADU_BASE}/book/{bid}/', 'X-Requested-With': 'XMLHttpRequest'}
        if header:
            extra['Cookie'] = header
        r = _cjk_get(f'{_TADU_BASE}/getPartContentByCodeTable/{bid}/{probe_seq}',
                     referer=f'{_TADU_BASE}/book/{bid}/', extra_headers=extra, timeout=25)
        if r is None:
            return {'ok': False, 'guest': None, 'message': 'تعذر الوصول لـ tadu.com من السيرفر — '
                    'جرّب الفحص لاحقاً أو أضف مفاتيح ScraperAPI.'}
        try:
            data = json.loads(r.text)
        except Exception:
            return {'ok': False, 'guest': None, 'message': 'رد غير متوقع من نقطة المحتوى — ربما تغير القالب.'}
        content = (data.get('data') or {}).get('content') or ''
        plain_len = len(re.sub(r'\s', '', _html_to_text(content)))
        if plain_len > 400:
            return {'ok': True, 'guest': False, 'source': 'settings' if header else 'env',
                    'message': 'القراءة موسّعة — الفصول بعد الحد المجاني تُقرأ كاملة. السحب سيمر بالكامل.'}
        if not header:
            return {'ok': True, 'guest': True,
                    'message': f'وضع الزائر — أول {_TADU_FREE_LIMIT_HINT} فصلاً كاملة فقط. '
                               'لتوسيع القراءة الصق كوكيز حساب Tadu في الإعدادات.'}
        return {'ok': False, 'guest': True, 'source': 'settings',
                'message': 'الكوكيز موجودة لكنها لا توسّع القراءة — انتهت صلاحيتها أو الحساب غير صالح. '
                           'انسخ ترويسة Cookie جديدة بعد تسجيل الدخول والصقها في الإعدادات.'}
    except Exception as e:
        return {'ok': False, 'guest': None, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}


# ==========================================
# 🟩 2-4. عائلة القالب المشترك (Bixiange + FFXS8 + JPXS123)
# ==========================================
# Empire CMS صيني بترميز GBK:
#   - صفحة الكتاب: /{تصنيف}/{id}.html (بيكسينج/جي بي إكس إس) أو /{تصنيف}/{id}/ (ffxs8)
#     وفيها كل روابط الفصول (لا ترقيم).
#   - الفصول: /{تصنيف}/{id}/{N}.html أو /book/{cls}-{id}-{N}.html (ffxs8)
#   - المحتوى: div حاوٍ واحد (يختلف اسمه قليلاً بين المواقع).
#   - أول فصل يبدأ بمقدمة الكتاب الملحقة — تُنزع بذكاء.
#   - H1 يذكر عدداً مضللاً أحياناً (ffxs8 يذكر 622 والفعلي 591) — نعتمد ما يوجد فعلاً.

_CMS_SITES = {
    'bixiange': {
        'name': 'Bixiange (笔仙阁)',
        'domains': ('bixiange.top',),
        'base': 'http://www.bixiange.top',
        'book_re': r'/(?:[a-z]+)/(\d+)\.html',
        'chapter_re': r'/(?:[a-z]+)/(\d+)/(\d+)\.html',
        'chapter_in_book_page': r'/[a-z]+/(\d+)/(\d+)\.html',
        'content_sel': ('div#mycontent', 'div.content'),
        'cover_hints': ('/d/file/',),
        'desc_from': 'meta',
    },
    'ffxs8': {
        'name': 'FFXS8 (饭饭小说)',
        'domains': ('ffxs8.com',),
        'base': 'https://www.ffxs8.com',
        'book_re': r'/(?:[a-z]+)/(\d+)/?',
        'chapter_re': r'/book/[a-z0-9]+-(\d+)-(\d+)\.html',
        'chapter_in_book_page': r'/book/[a-z0-9]+-(\d+)-(\d+)\.html',
        'content_sel': ('div.content',),
        'cover_hints': (),
        'desc_from': 'block',
        'title_strip': r'\(\d+-\d+\)\s*$',
    },
    'jpxs123': {
        'name': 'JPXS123 (精校小说网)',
        'domains': ('jpxs123.com',),
        'base': 'http://jpxs123.com',
        'book_re': r'/(?:[a-z]+)/(\d+)\.html',
        'chapter_re': r'/(?:[a-z]+)/(\d+)/(\d+)\.html',
        'chapter_in_book_page': r'/[a-z]+/(\d+)/(\d+)\.html',
        'content_sel': ('div#read_chapterDetail', 'div.read_chapterDetail', 'div.content'),
        'cover_hints': ('/d/file/',),
        'desc_from': 'meta',
    },
}


def _cms_key(url):
    host = urlparse(url).netloc.lower()
    for key, cfg in _CMS_SITES.items():
        for domain in cfg['domains']:
            if domain in host:
                return key
    return None


def _cms_cfg(url):
    key = _cms_key(url)
    if not key:
        raise ValueError(f'CMS: نطاق غير مدعوم {url[:80]}')
    return key, _CMS_SITES[key]


def _cms_book_id(url, cfg):
    """استخراج معرف الكتاب من رابط كتاب أو فصل"""
    m = re.search(cfg['book_re'], urlparse(url).path or '')
    if m:
        return m.group(1)
    m = re.search(cfg['chapter_re'], urlparse(url).path or '')
    if m:
        return m.group(1)
    return None


def _cms_book_url(url, cfg):
    bid = _cms_book_id(url, cfg)
    if not bid:
        return None
    # ffxs8 يحتاج تصنيف الرابط الأصلي — نعيد استخدام المسار إن كان رابط كتاب
    path = urlparse(url).path or ''
    m = re.match(r'(/[a-z]+/)' + re.escape(bid) + r'(?:\.html)?/?$', path)
    if m:
        return cfg['base'] + f"{m.group(1)}{bid}/" if 'ffxs8' in url else cfg['base'] + f"{m.group(1)}{bid}.html"
    return None


def fetch_metadata_cms(url):
    try:
        key, cfg = _cms_cfg(url)
        bid = _cms_book_id(url, cfg)
        if not bid:
            print(f"CMS({key}): cannot parse book id from {url[:80]}")
            return None
        book_url = _cms_book_url(url, cfg)
        target = book_url or url
        r = _cjk_get(target, timeout=30)
        if r is None:
            print(f"CMS({key}) metadata: page fetch failed ({bid})")
            return None
        soup = parse_html(r)
        page_text = soup.get_text('\n', strip=True)

        # العنوان: h1 (يحمل لاحقة (1-622) أحياناً) ← وسم title أول جزء
        title = ''
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(' ', strip=True)
        if not title:
            raw_title = soup.title.get_text() if soup.title else ''
            title = re.split(r'[|_]', raw_title)[0].strip()
        title = re.sub(r'\(\d+-\d+\)\s*$', '', title).strip()
        title = re.sub(r'全文阅读|免费阅读|免費閱讀', '', title).strip()

        # المؤلف
        author = ''
        m = re.search(r'作者[：:]\s*([^\s<|，,]{1,25})', page_text)
        if m:
            author = m.group(1)
        author = re.sub(r'_[^_]{1,8}$', '', author).strip()  # لاحقة اسم الموقع (笔仙阁)

        # الغلاف
        cover = ''
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('src') or ''
            if src and any(h in src for h in cfg['cover_hints']):
                cover = urljoin(cfg['base'] + '/', src)
                break

        # الوصف
        description = ''
        if cfg['desc_from'] == 'meta':
            desc_meta = get_meta(soup, name='description')
            if desc_meta:
                m = re.search(r'简介[：:]\s*(.+)$', desc_meta, re.S)
                description = m.group(1).strip() if m else desc_meta.strip()
        else:  # block — فقرة 作品简介
            lines = page_text.split('\n')
            for i, l in enumerate(lines):
                if '作品简介' in l:
                    rest = [x.strip() for x in lines[i + 1:i + 12] if x.strip()]
                    description = '\n'.join(rest[:8])
                    break
            if not description:
                m = re.search(r'简介[：:]\s*(.+)', page_text, re.S)
                description = (m.group(1)[:600].strip() if m else '')

        # التصنيف من مسار الرابط أو القائمة
        category = ''
        cat_m = re.search(r'^/([a-z]+)/', urlparse(target).path or '')
        if cat_m:
            cat_slug = cat_m.group(1)
            for a in soup.select('a[href="/' + cat_slug + '/"]'):
                t = a.get_text(strip=True)
                if t and len(t) <= 6:
                    category = t
                    break

        tags = []
        if 'jpxs123' in url:
            kw = get_meta(soup, name='keywords')
            if kw:
                tags = [t.strip() for t in kw.split(',') if t.strip()]
            # تنقية وسوم SEO: حذف ما يحمل اسم الرواية نفسها أو كلمات الترويج
            tags = [t for t in tags
                    if title[:6] not in t and not re.search(r'免费|免費|全集|下载|下載|最新|在线|在線', t)][:6]

        return {
            'title': title, 'description': description,
            'cover': fix_image_url(cover, base_url=cfg['base']),
            'status': 'مستمرة', 'category': category or 'عام', 'tags': tags,
            'sourceUrl': target, 'lastUpdate': None,
        }
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error CMS Meta: {e}")
        return None


def _cms_link_title(raw_title, n):
    """تصحيح عناوين روابط الفهرس: روابط «اقرأ الآن» تحمل نصها بدل عنوان الفصل"""
    t = (raw_title or '').strip()
    if re.fullmatch(r'(?:在线|線上|线上|全文|开始|開始|点击|點擊)?(?:阅读|閱讀)', t):
        return f'第{n}节'
    return t or f'第{n}节'


def fetch_chapter_list_cms(url):
    try:
        key, cfg = _cms_cfg(url)
        bid = _cms_book_id(url, cfg)
        if not bid:
            print(f"CMS({key}): cannot parse book id from {url[:80]}")
            return []
        book_url = _cms_book_url(url, cfg)
        target = book_url or url
        r = _cjk_get(target, timeout=30,
                     validate=lambda t: re.search(cfg['chapter_in_book_page'], t) is not None)
        if r is None:
            print(f"CMS({key}) chapters: page fetch failed ({bid})")
            return []
        soup = parse_html(r)
        chapters = []
        seen = set()
        for a in soup.find_all('a'):
            href = a.get('href') or ''
            m = re.search(cfg['chapter_in_book_page'], href)
            if not m or m.group(1) != bid:
                continue
            n = int(m.group(2))
            if n in seen:
                continue
            seen.add(n)
            link_title = a.get_text(' ', strip=True)
            full = urljoin(cfg['base'] + '/', href.strip())
            chapters.append({'number': n, 'url': full,
                             'title': _cms_link_title(link_title, n)})
        chapters.sort(key=lambda c: c['number'])
        print(f"✅ CMS({key}) chapters ({bid}): {len(chapters)}")
        return chapters
    except ValueError as e:
        print(str(e))
        return []
    except Exception as e:
        print(f"Error CMS List: {e}")
        return []


def scrape_chapter_cms(url):
    try:
        key, cfg = _cms_cfg(url)
        bid = _cms_book_id(url, cfg)
        chapter_no = 0
        m = re.search(cfg['chapter_re'], urlparse(url).path or '')
        if m:
            chapter_no = int(m.group(2))
        r = _cjk_get(url, referer=cfg['base'] + '/', timeout=30,
                     validate=lambda t: _CHAPTER_HEAD_RE.search(t) is not None or '正文' in t)
        if r is None:
            return None
        soup = parse_html(r)
        content_div = None
        for sel in cfg['content_sel']:
            content_div = soup.select_one(sel)
            if content_div:
                break
        if not content_div:
            print(f"CMS({key}): content container not found in {url[:80]}")
            return None
        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()
        text = content_div.get_text('\n')
        lines = [l.strip() for l in text.split('\n')]
        lines = _strip_book_intro(lines, chapter_no, soup.h1.get_text(' ', strip=True) if soup.h1 else '')
        return _clean_chapter_text('\n'.join(lines))
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error CMS Chapter: {e}")
        return None


def _make_cms_functions(key):
    cfg = _CMS_SITES[key]

    def metadata(url):
        return fetch_metadata_cms(url)

    def chapters(url):
        return fetch_chapter_list_cms(url)

    def content(url):
        return scrape_chapter_cms(url)

    def worker(url, admin_email, meta):
        generic_worker(url, admin_email, meta, chapters, content, site_name=cfg['name'])

    return metadata, chapters, content, worker


_bixiange_meta, _bixiange_chapters, _bixiange_content, _bixiange_worker = _make_cms_functions('bixiange')
_ffxs8_meta, _ffxs8_chapters, _ffxs8_content, _ffxs8_worker = _make_cms_functions('ffxs8')
_jpxs_meta, _jpxs_chapters, _jpxs_content, _jpxs_worker = _make_cms_functions('jpxs123')


# ==========================================
# 🟦 5. TAOBAO JH (jhbook.taobao.com — 淘宝阅读)
# ==========================================
# نسخة تاوباو لكتب Tadu:
# - صفحة الكتاب فيها SSR JSON مضمّن: BookVO (name/introduction/bookTags/cover/
#   totalChapters/status) + catalogData (أول 100 فصل بمعرفات حقيقية، hasMore=true
#   — البقية بلا واجهة ظاهرة، والمجاني فعلياً هو أول 100).
# - صفحة الفصل: {رابط الكتاب}/{chapterId}.html وفيها novelData مضمّن:
#     type=success   → المحتوى كامل
#     type=copyright → معاينة محجوبة (حقوق) — نرفض بصدق
#     novelData={}   → فشل SSR لأن الجلسة مجهولة (userId=0) — القراءة تحتاج
#                      كوكيز حساب تاوباو (مؤكد حياً: فشل من كل الطرق بلا جلسة)
# - الكوكيز: إعداد ← خادم التطبيق (jhbookCookies) ← بيئة JHBOOK_COOKIES ← زائر

_JH_BASE = 'https://jhbook.taobao.com'
_JH_CHECK_BOOK = 'novel-20260214100375480400341'
_JH_RUNTIME = {'cookies': '', 'app_cookies': '', 'last_app_pull': 0.0}
_JH_LOCK = threading.Lock()
_JH_WARNED = set()


class JhBookError(Exception):
    pass


def set_jhbook_runtime_cookies(value):
    """ضبط كوكيز Taobao JH من واجهة الإعدادات (فارغ = وضع الزائر)"""
    with _JH_LOCK:
        _JH_RUNTIME['cookies'] = str(value or '').strip()
    print(f"🟦 TaobaoJH cookies {'فُرِّغت (وضع الزائر)' if not str(value or '').strip() else 'حُدِّثت'}")


def _pull_jhbook_cookies_from_app():
    """سحب كوكيز Taobao JH من خادم التطبيق (حقل jhbookCookies) — كل 5 دقائق"""
    now = time.time()
    with _JH_LOCK:
        if now - _JH_RUNTIME['last_app_pull'] < 300:
            return
        _JH_RUNTIME['last_app_pull'] = now
    try:
        from core.config import API_SECRET, NODE_BACKEND_URL
        import requests
        r = requests.get(f"{NODE_BACKEND_URL}/api/admin/scraper-keys",
                         headers={'x-api-secret': API_SECRET}, timeout=20)
        if r.status_code == 200:
            val = str((r.json() or {}).get('jhbookCookies') or '').strip()
            with _JH_LOCK:
                _JH_RUNTIME['app_cookies'] = val
            if val:
                print("🟦 Pulled TaobaoJH cookies from app server settings")
    except Exception as e:
        print(f"   TaobaoJH app-pull failed: {str(e)[:70]}")


def _jh_cookie_header():
    with _JH_LOCK:
        runtime = _JH_RUNTIME['cookies']
    if runtime:
        return runtime
    with _JH_LOCK:
        app_val = _JH_RUNTIME['app_cookies']
        should_pull = not app_val
    if should_pull:
        _pull_jhbook_cookies_from_app()
        with _JH_LOCK:
            app_val = _JH_RUNTIME['app_cookies']
    if app_val:
        return app_val
    return os.environ.get('JHBOOK_COOKIES', '').strip()


def jhbook_cookie_summary():
    """ملخص مخفى لحالة كوكيز Taobao JH (للواجهة)"""
    header = _jh_cookie_header()
    parts = {}
    for part in str(header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        if sep and re.fullmatch(r'[A-Za-z0-9_\-]+', name):
            parts[name] = value
    masked = [f"{n}={(v[:6] + '…' + v[-4:]) if len(v) > 12 else '…'}" for n, v in parts.items()]
    if not parts:
        return {'source': 'guest', 'count': 0, 'cookies': [], 'has_session': False,
                'message': 'وضع الزائر — بيانات الكتاب وفهرسه يعملان، وقراءة الفصول ستُرفض (جلسة مطلوبة).'}
    return {'source': 'settings', 'count': len(parts), 'cookies': masked, 'has_session': True,
            'message': 'الكوكيز مضبوطة — ستُستخدم في قراءة الفصول.'}


def _jh_book_slug(url):
    m = re.search(r'/book/(novel-\d+)(?:\.html)?', urlparse(url).path or '')
    return m.group(1) if m else None


def _jh_chapter_id(url):
    m = re.search(r'/book/(novel-\d+)\.html/(\d+)\.html', urlparse(url).path or '')
    return m.group(2) if m else None


def _extract_json_object(text, anchor):
    """استخراج كائن JSON مضمّن بوعي للنصوص (اقتباسات/مهرّبات).
    إذا كان الـ anchor مفتاحاً يليه ":{" فالبداية من قوسه هو (مثل "catalogData"),
    وإلا نرجع لأول '{' قبله (مثل anchor داخل الكائن مثل "class":"...BookVO")."""
    idx = text.find(anchor)
    if idx < 0:
        return None
    after = text[idx + len(anchor):idx + len(anchor) + 6]
    m = re.match(r'\s*:\s*\{', after)
    if m:
        start = idx + len(anchor) + m.end() - 1
    else:
        start = text.rfind('{', 0, idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, min(len(text), start + 400000)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def fetch_metadata_jhbook(url):
    try:
        slug = _jh_book_slug(url)
        if not slug:
            raise JhBookError('TaobaoJH: الرابط المدعوم /book/novel-{id}.html')
        book_url = f'{_JH_BASE}/book/{slug}.html'
        r = _cjk_get(book_url, timeout=30, validate=lambda t: 'BookVO' in t or 'catalogData' in t)
        if r is None:
            print(f"TaobaoJH metadata: page fetch failed ({slug})")
            return None
        book = _extract_json_object(r.text, '"class":"com.taobao.newbbs.ssr.vo.jhbook.vo.BookVO"')
        if not book:
            print("TaobaoJH: BookVO not found in page JSON")
            return None
        title = book.get('name') or 'Unknown Title'
        description = book.get('introduction') or ''
        tags = [t.strip() for t in str(book.get('bookTags') or '').split(',') if t.strip()]
        cover = book.get('coverUrl') or ''
        if cover and cover.startswith('//'):
            cover = 'https:' + cover
        # الحالة: completed=true يعني مكتملة
        status = 'مكتملة' if book.get('completed') else 'مستمرة'
        cat = book.get('secondCategoryName') or book.get('firstCateCode') or ''
        tags_out = list(tags)
        author = str(book.get('author') or '').strip()
        if author and author not in tags_out:
            tags_out.append(author)
        return {
            'title': title, 'description': description,
            'cover': fix_image_url(cover, base_url=_JH_BASE),
            'status': status, 'category': str(cat) or 'عام', 'tags': tags_out,
            'sourceUrl': book_url, 'lastUpdate': None,
        }
    except JhBookError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error TaobaoJH Meta: {e}")
        return None


def fetch_chapter_list_jhbook(url):
    try:
        slug = _jh_book_slug(url)
        if not slug:
            raise JhBookError('TaobaoJH: الرابط المدعوم /book/novel-{id}.html')
        book_url = f'{_JH_BASE}/book/{slug}.html'
        r = _cjk_get(book_url, timeout=30, validate=lambda t: 'catalogData' in t)
        if r is None:
            print(f"TaobaoJH chapters: page fetch failed ({slug})")
            return []
        catalog = _extract_json_object(r.text, '"catalogData"')
        if not catalog:
            print("TaobaoJH: catalogData not found")
            return []
        items = catalog.get('list') or []
        chapters = []
        for item in items:
            cid = str(item.get('chapterId') or '')
            if not cid:
                continue
            n = int(item.get('sortNumber') or (len(chapters) + 1))
            chapters.append({
                'number': n,
                'url': f'{book_url}/{cid}.html',
                'title': item.get('name') or f'第{n}章',
            })
        chapters.sort(key=lambda c: c['number'])
        total = catalog.get('totalCount')
        if catalog.get('hasMore'):
            print(f"TaobaoJH: catalogue shows first {len(chapters)} chapters"
                  + (f" of {total}" if total else "")
                  + " (hasMore=true — no public API for the rest; free reading is the first 100 anyway)")
        return chapters
    except JhBookError as e:
        print(str(e))
        return []
    except Exception as e:
        print(f"Error TaobaoJH List: {e}")
        return []


def _jh_warn_once(key, message):
    if key in _JH_WARNED:
        return
    _JH_WARNED.add(key)
    try:
        from core.backend import push_log
        push_log(message, 'warning')
    except Exception:
        pass


def scrape_chapter_jhbook(url):
    """محتوى فصل Taobao: novelData مضمّن — كشف صادق لكل الحالات"""
    try:
        slug = _jh_book_slug(url)
        cid = _jh_chapter_id(url)
        if not slug or not cid:
            raise JhBookError('TaobaoJH: رابط الفصل يجب أن يكون /book/novel-{id}.html/{chapterId}.html')
        book_url = f'{_JH_BASE}/book/{slug}.html'
        cookies = _jh_cookie_header()
        extra = {'Referer': book_url}
        if cookies:
            extra['Cookie'] = cookies
        r = _cjk_get(f'{book_url}/{cid}.html', referer=book_url,
                     extra_headers=extra, timeout=30,
                     validate=lambda t: 'novelData' in t or 'catalogData' in t)
        if r is None:
            print(f"TaobaoJH: chapter page fetch failed ({cid})")
            return None
        data = _extract_json_object(r.text, '"novelData"')
        # novelData فارغة {} = SSR رفض الجلسة المجهولة (hsf请求失败 / userId=0)
        if not data or not (data.get('type') or data.get('content')):
            _jh_warn_once(
                f'jh:{slug}',
                '🟦 [TaobaoJH] قراءة الفصول من تاوباو تتطلب جلسة تسجيل دخول — الطلبات المجهولة '
                'ترفض من خادم الموقع نفسه. الصق كوكيز حساب تاوباو من واجهة السكرابر '
                '(أو متغير البيئة JHBOOK_COOKIES) ثم استأنف بنفس الرابط. '
                'بيانات الكتاب وفهرسه (أول 100 فصل) تعمل بلا جلسة.')
            print(f"TaobaoJH: novelData empty for {cid} — session required")
            return None
        if data.get('type') == 'copyright':
            print(f"TaobaoJH: chapter {cid} is copyright-blocked (paid preview)")
            return None
        content = data.get('content') or ''
        text = _html_to_text(content) if '<' in content else str(content)
        if len(re.sub(r'\s', '', text)) < 100:
            print(f"TaobaoJH: chapter {cid} content too short ({len(text)} chars)")
            return None
        return _clean_chapter_text(text)
    except JhBookError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error TaobaoJH Chapter: {e}")
        return None


def worker_jhbook(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_jhbook, scrape_chapter_jhbook,
                   site_name='TaobaoJH')


def jhbook_quick_session_check():
    """فحص حي: جلسة تاوباو تعمل أم لا؟ (بيانات الكتاب مجانية — الفصول بجلسة)"""
    header = _jh_cookie_header()
    try:
        book_url = f'{_JH_BASE}/book/{_JH_CHECK_BOOK}.html'
        r = _cjk_get(book_url, timeout=25, validate=lambda t: 'catalogData' in t)
        if r is None:
            return {'ok': False, 'guest': None, 'message': 'تعذر الوصول لـ jhbook.taobao.com — '
                    'جرّب الفحص لاحقاً أو أضف مفاتيح ScraperAPI.'}
        catalog = _extract_json_object(r.text, '"catalogData"')
        items = (catalog or {}).get('list') or []
        if not items:
            return {'ok': False, 'guest': None, 'message': 'لم يُعثر على فهرس الفصول في صفحة الكتاب — ربما تغير القالب.'}
        cid = str(items[0].get('chapterId'))
        extra = {'Referer': book_url}
        if header:
            extra['Cookie'] = header
        rc = _cjk_get(f'{book_url}/{cid}.html', referer=book_url,
                      extra_headers=extra, timeout=25,
                      validate=lambda t: 'novelData' in t)
        if rc is None:
            return {'ok': False, 'guest': None, 'message': 'صفحة الفصل لم تُجلب — تحقق من الاتصال أو المفاتيح.'}
        data = _extract_json_object(rc.text, '"novelData"')
        if data and data.get('type') == 'success':
            return {'ok': True, 'guest': not header, 'source': 'settings' if header else 'env',
                    'message': 'قراءة الفصول تعمل — novelData يرجع المحتوى كاملاً.'}
        if data and data.get('type') == 'copyright':
            return {'ok': True, 'guest': False, 'source': 'settings' if header else 'env',
                    'message': 'الجلسة تعمل لكن هذا الفصل محجوب بحقوق (مدفوع) — جرّب فصلاً مجانياً.'}
        if not header:
            return {'ok': False, 'guest': True,
                    'message': 'وضع الزائر: خادم تاوباو يرفض قراءة الفصول مجهولاً (مؤكد). '
                               'الصق كوكيز حساب تاوباو في الإعدادات — بيانات الكتاب وفهرسه يعملان بلا جلسة.'}
        return {'ok': False, 'guest': True, 'source': 'settings',
                'message': 'الكوكيز موجودة لكن الجلسة لا تعمل — انتهت صلاحيتها أو غير صالحة. '
                           'انسخ ترويسة Cookie جديدة بعد تسجيل الدخول والصقها في الإعدادات.'}
    except Exception as e:
        return {'ok': False, 'guest': None, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}


# ==========================================
# 📚 التسجيل في السجل العام
# ==========================================
register_site(
    domain_patterns=['tadu.com', 'www.tadu.com'],
    name='Tadu (塔读文学)',
    language='chinese',
    fetch_metadata=fetch_metadata_tadu,
    fetch_chapters=fetch_chapter_list_tadu,
    fetch_content=scrape_chapter_tadu,
    worker=worker_tadu,
    status='active',
    notes='جديد (v3.0)! بيانات og:novel:* + فهرس /book/catalogue/{id} + محتوى JSONP '
          'بترتيب الفصل (seq). الزائر أول 30 فصلاً كاملة والباقي معاينات مرفوضة بصدق؛ '
          'كوكيز حساب اختيارية من واجهة السكرابر أو TADU_COOKIES توسّع القراءة.'
)


register_site(
    domain_patterns=['bixiange.top', 'www.bixiange.top'],
    name='Bixiange (笔仙阁)',
    language='chinese',
    fetch_metadata=_bixiange_meta,
    fetch_chapters=_bixiange_chapters,
    fetch_content=_bixiange_content,
    worker=_bixiange_worker,
    status='active',
    notes='جديد (v3.0)! قالب Empire CMS بترميز GBK — فهرس كامل بصفحة الكتاب '
          '(/ك/{id}/{N}.html) + محتوى div#mycontent + غلاف /d/file/. '
          'مقدمة الكتاب الملحقة بالفصل الأول تُنزع تلقائياً.'
)


register_site(
    domain_patterns=['ffxs8.com', 'www.ffxs8.com'],
    name='FFXS8 (饭饭小说)',
    language='chinese',
    fetch_metadata=_ffxs8_meta,
    fetch_chapters=_ffxs8_chapters,
    fetch_content=_ffxs8_content,
    worker=_ffxs8_worker,
    status='active',
    notes='جديد (v3.0)! نفس قالب بيكسينج — فهرس /book/{cls}-{id}-{N}.html بصفحة '
          'الكتاب + محتوى div.content (H1 يذكر عدداً مضللاً أحياناً — نعتمد الموجود فعلاً). '
          'بلا غلاف (الموقع لا يعرض صورة). ملاحظة: بعض بايتات «——» تالفة بالمصدر وتُنزع.'
)


register_site(
    domain_patterns=['jpxs123.com', 'www.jpxs123.com'],
    name='JPXS123 (精校小说网)',
    language='chinese',
    fetch_metadata=_jpxs_meta,
    fetch_chapters=_jpxs_chapters,
    fetch_content=_jpxs_content,
    worker=_jpxs_worker,
    status='active',
    notes='جديد (v3.0)! نفس قالب بيكسينج — فهرس /{تصنيف}/{id}/{N}.html + محتوى '
          'div.read_chapterDetail + غلاف /d/file/. المؤلف من وسوم الصفحة والوصف من '
          'meta description (源名/别名/标签 تُفكك إلى وسوم).'
)


register_site(
    domain_patterns=['jhbook.taobao.com'],
    name='TaobaoJH (淘宝阅读)',
    language='chinese',
    fetch_metadata=fetch_metadata_jhbook,
    fetch_chapters=fetch_chapter_list_jhbook,
    fetch_content=scrape_chapter_jhbook,
    worker=worker_jhbook,
    status='active',
    notes='جديد (v3.0)! بيانات الكتاب (BookVO) وفهرسه (أول 100 فصل بمعرفات حقيقية) '
          'مجانيان من SSR JSON المضمّن؛ قراءة الفصول تتطلب جلسة تاوباو — الكوكيز من '
          'واجهة السكرابر أو JHBOOK_COOKIES. type=copyright (مدفوع) يُرفض بصدق.'
)
