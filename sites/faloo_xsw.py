# -*- coding: utf-8 -*-
"""
==========================================
🟥 موقعان صينيان إضافيان (v3.2) — Faloo + XSW
==========================================
موقعان جديدان (v3.2) — كلهما بدعم كامل: بيانات + فهرس بعناوين حقيقية +
محتوى نظيف + أغلفة، مع رفض صادق للمحتوى المحجوب بدل إرسال نص ناقص:

1.  Faloo (飞卢小说网)  - wap.faloo.com    ✅ ترميز GBK/GB2312
    صفحة الكتاب: حقول مخفية (hidNovelID/hidNovelName/hidCoverUrl) + h1.name +
    المؤلف من رابط search?t=2&k= + التصنيف من رابط /y_ + الحالة i.tag (完結).
    الوصف الكامل من meta description بعد نزع غلاف «【飞卢小说网独家签约小说：…】».
    الفهرس الكامل بصفحة booklist_{id}.html (روابط {id}_{N}.html بترقيم حقيقي).
    المحتوى div.nodeContent بفقرات <p>.
    🔒 فصول الاشتراك: nodeContent فارغ + «您还没有登录» → رفض صادق.
       كوكيز حساب (اختيارية) تفتح الفصول المشتراة — تُدار من واجهة السكرابر
       (فارغ = وضع الزائر) أو البيئة FALOO_COOKIES.

2.  XSW (台灣小說網)     - m.xsw.tw         ✅ صينية تقليدية UTF-8
    ⚠️ شهادة SSL ناقصة السلسلة (CertificateVerifyError) — الجالب يجرب
       verify=True ثم False تلقائياً.
    بيانات الكتاب الأغنى من سطح المكتب www.xsw.tw/book/{id}.html:
    غلاف img.xsw.tw/{id//1000}/{id}/{id}s.jpg + div.intro كاملة +
    صفوف 小說分類/小說狀態/小說作者.
    الفهرس بترقيم صفحات m.xsw.tw/{id}/page-N.html (20 فصلاً/صفحة،
    الروابط بعلامات اقتباس مفردة href='…' ونصها يحمل <span></span>).
    المحتوى div#nr1 من الجوال.
    🚧 قيود الموقع الحقيقية (رفض صادق):
       - فصول بخادمهم فاشل: «章節內容獲取超時» دائماً (مؤكد حتى بـ5 محاولات)
       - فصول محتواها صور فقط: وسوم <img مكتوبة بـ&nbsp; داخل الوسم فلا
         يلتقطها BeautifulSoup — تُكشف من HTML الخام بـ regex.
    بلا كوكيز (الموقع لا يوفّر تسجيل حساب أصلاً).
"""

import os
import re
import time
import threading
import requests
from urllib.parse import urljoin, urlparse

from core.registry import register_site
from core.utils import (
    parse_html, get_headers, fix_image_url,
    clean_text, UA_MOBILE,
    SmartResponse,
    generic_worker,
)

# استيراد جالب CJK الآمن للترميز من cnextra (نفس آلية فك GBK)
from sites.cnextra import _cjk_get, _html_to_text

# ==========================================
# 🟥 1) FALOO 飞卢小说网 (wap.faloo.com)
# ==========================================

_FALOO_BASE = 'https://wap.faloo.com'
_FALOO_IMG_HTTPS_OK = {'img.faloo.com'}   # نطاقات أغلفة جرّب https لها

_FALOO_RUNTIME = {'cookies': '', 'app_cookies': '', 'last_app_pull': 0.0}
_FALOO_LOCK = threading.Lock()

# كتاب/فصل الفحص الحي للجلسة: الفصل 100 من كتاب 944651 خلف تسجيل الدخول
_FALOO_CHECK_BOOK = '944651'
_FALOO_CHECK_CHAPTER = '100'

# أسطر ترويجية تتكرر نهاية/بداية فصول Faloo — تُنزع من سطر كامل فقط
_FALOO_JUNK_LINE_RE = re.compile(
    r'读书三件事|手机用户请浏览|飞卢首发|飞要你好看|飞卢小说|飞卢中文网|'
    r'(?:请记住本书|本书来自|更多精彩).{0,30}(?:域名|网址|首发)')


def set_faloo_runtime_cookies(value):
    """ضبط كوكيز Faloo من واجهة الإعدادات (فارغ = وضع الزائر)"""
    with _FALOO_LOCK:
        _FALOO_RUNTIME['cookies'] = str(value or '').strip()
    print(f"📕 Faloo cookies {'فُرِّغت (وضع الزائر)' if not str(value or '').strip() else 'حُدِّثت'}")


def _pull_faloo_cookies_from_app():
    """سحب كوكيز Faloo من خادم التطبيق (حقل falooCookies) — كل 5 دقائق كحد أقصى"""
    now = time.time()
    with _FALOO_LOCK:
        if now - _FALOO_RUNTIME['last_app_pull'] < 300:
            return
        _FALOO_RUNTIME['last_app_pull'] = now
    try:
        from core.config import API_SECRET, NODE_BACKEND_URL
        r = requests.get(f"{NODE_BACKEND_URL}/api/admin/scraper-keys",
                         headers={'x-api-secret': API_SECRET}, timeout=20)
        if r.status_code == 200:
            val = str((r.json() or {}).get('falooCookies') or '').strip()
            with _FALOO_LOCK:
                _FALOO_RUNTIME['app_cookies'] = val
            if val:
                print("📕 Pulled Faloo cookies from app server settings")
    except Exception as e:
        print(f"   Faloo app-pull failed: {str(e)[:70]}")


def _faloo_cookie_header():
    """ترويسة Cookie حسب سلسلة الأولوية: إعداد ← خادم التطبيق ← بيئة ← فارغ (زائر)"""
    with _FALOO_LOCK:
        runtime = _FALOO_RUNTIME['cookies']
    if runtime:
        return runtime
    with _FALOO_LOCK:
        app_val = _FALOO_RUNTIME['app_cookies']
        should_pull = not app_val
    if should_pull:
        _pull_faloo_cookies_from_app()
        with _FALOO_LOCK:
            app_val = _FALOO_RUNTIME['app_cookies']
    if app_val:
        return app_val
    return os.environ.get('FALOO_COOKIES', '').strip()


def faloo_cookie_summary():
    """ملخص مخفى لحالة كوكيز Faloo (للواجهة — بلا قيم كاملة)"""
    header = _faloo_cookie_header()
    parts = {}
    for part in str(header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        if sep and re.fullmatch(r'[A-Za-z0-9_\-]+', name):
            parts[name] = value
    masked = [f"{n}={(v[:6] + '…' + v[-4:]) if len(v) > 12 else '…'}" for n, v in parts.items()]
    if not parts:
        return {'source': 'guest', 'count': 0, 'cookies': [], 'has_session': False,
                'message': 'وضع الزائر — الفصول المجانية فقط؛ فصول الاشتراك خلف تسجيل الدخول. '
                           'الكوكيز اختيارية لقراءة الفصول المشتراة.'}
    return {'source': 'settings', 'count': len(parts), 'cookies': masked, 'has_session': True,
            'message': 'الكوكيز مضبوطة — ستفتح الفصول المشتراة إن كان الحساب صالحاً.'}


def _faloo_ids(url):
    """تحليل رابط Faloo: صفحة الكتاب أو فصل.
    الصيغ المقبولة: /{id}.html (كتاب) — /{id}_{N}.html (فصل) —
    booklist_{id}.html / vol_{id}.html / buy_{id}.html / d_{id}.html / look_1_{id}_1.html (كتاب)."""
    p = urlparse(url)
    host = p.netloc.lower()
    if 'faloo.com' not in host:
        raise ValueError('Faloo: استخدم رابطاً على faloo.com فقط.')
    path = p.path or ''
    # فصل: 944651_100.html
    m = re.search(r'/(\d+)_(\d+)\.html', path)
    if m:
        return m.group(1), m.group(2)
    # صفحات الكتاب بأي صيغة
    for pat in (r'/(\d+)\.html', r'/booklist_(\d+)\.html', r'/vol_(\d+)\.html',
                r'/buy_(\d+)\.html', r'/d_(\d+)\.html', r'/look_1_(\d+)_\d+\.html',
                r'/p/(\d+)'):
        m = re.search(pat, path)
        if m:
            return m.group(1), None
    raise ValueError('Faloo: الرابط المدعوم https://wap.faloo.com/{book_id}.html '
                     'أو رابط فصل https://wap.faloo.com/{book_id}_{N}.html.')


def _faloo_upgrade_cover_https(cover):
    """غلاف Faloo يُخدم http — img.faloo.com يدعم https (مؤكد) — نقيس قبل الاعتماد"""
    if not cover.startswith('http://'):
        return cover
    host = urlparse(cover).netloc.lower()
    if host not in _FALOO_IMG_HTTPS_OK:
        return cover
    https_url = 'https://' + cover[len('http://'):]
    try:
        chk = requests.head(https_url, timeout=10, stream=True, allow_redirects=True,
                            headers={'User-Agent': UA_MOBILE})
        if chk.status_code < 400 and (chk.headers.get('Content-Type', '') or '').lower().startswith('image'):
            return https_url
    except Exception:
        pass  # فشل فحص https → نُبقي http الأصلي
    return cover


def fetch_metadata_faloo(url):
    """بيانات الرواية من صفحة الكتاب (حقول مخفية + عناصر الولاية) — تقبل رابط فصل أيضاً"""
    try:
        bid, _chap = _faloo_ids(url)
        book_url = f'{_FALOO_BASE}/{bid}.html'
        r = _cjk_get(book_url, timeout=30,
                     validate=lambda t: 'hidNovelName' in t or 'nodeContent' in t)
        if r is None:
            print(f"Faloo metadata: page fetch failed for {bid}")
            return None
        raw = r.text

        def _hidden(name):
            m = (re.search(r'id="' + name + r'"[^>]*value="([^"]*)"', raw)
                 or re.search(r'value="([^"]*)"[^>]*id="' + name + r'"', raw)
                 or re.search(r'name="' + name + r'"[^>]*value="([^"]*)"', raw))
            return m.group(1).strip() if m else ''

        title = _hidden('hidNovelName')
        cover = _hidden('hidCoverUrl')
        if not title:
            m = re.search(r'<h1[^>]*class="name"[^>]*>([^<]+)</h1>', raw)
            title = m.group(1).strip() if m else ''
        if not title:
            m = re.search(r'<title>([^<]+)</title>', raw)
            title = re.split(r'[_|]', m.group(1).strip())[0].strip() if m else ''
        if not title:
            print(f"Faloo metadata: no title found for {bid}")
            return None

        # المؤلف: رابط بحث الكاتب search?t=2&k= (h2 داخل شريط الصفحة أيضاً)
        author = ''
        m = re.search(r'<a[^>]*href="[^"]*search[^"]*\?t=2&k=[^"]*"[^>]*>([^<]{1,25})</a>', raw)
        if m:
            author = m.group(1).strip()
        if not author:
            m = re.search(r'<h2><a[^>]*>([^<]{1,25})</a></h2>', raw)
            author = m.group(1).strip() if m else ''

        # التصنيف: رابط /y_
        category = ''
        m = re.search(r'<a[^>]*href="[^"]*/y_\d+(?:_\d+)*\.html"[^>]*>([^<]{1,12})</a>', raw)
        if m:
            category = m.group(1).strip()

        # الحالة: i.tag (完结 / 連載)
        status_txt = ''
        m = re.search(r'<i[^>]*class="[^"]*tag[^"]*"[^>]*>([^<]{1,8})</i>', raw)
        if m:
            status_txt = m.group(1).strip()
        status = 'مكتملة' if '完' in status_txt else 'مستمرة'

        # الوصف الكامل: meta description بعد نزع غلاف «【飞卢小说网独家签约小说：…】»
        description = ''
        m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', raw)
        if not m:
            m = re.search(r'<meta[^>]*content="([^"]*)"[^>]*name="description"', raw)
        if m:
            description = m.group(1).strip()
            description = re.sub(r'^【[^】]*独家签约小说[^】]*】\s*', '', description)
            description = description.strip()
        if not description:
            m = re.search(r'<p[^>]*class="jj"[^>]*>(.*?)</p>', raw, re.S)
            if m:
                description = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        # وسوم: روابط tag_{n}.html
        tags = []
        for tm in re.finditer(r'<a[^>]*href="[^"]*tag_\d+\.html"[^>]*>([^<]{1,10})</a>', raw):
            t = tm.group(1).strip()
            if t and t not in tags and t != title:
                tags.append(t)
        tags = tags[:6]

        return {
            'title': title, 'author': author, 'description': description,
            'cover': fix_image_url(_faloo_upgrade_cover_https(cover), base_url=_FALOO_BASE),
            'status': status, 'category': category or 'عام', 'tags': tags,
            'sourceUrl': book_url, 'lastUpdate': None,
        }
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error Faloo Meta: {e}")
        return None


def fetch_chapter_list_faloo(url):
    """فهرس كامل بصفحة واحدة booklist_{id}.html — روابط {id}_{N}.html بترقيم حقيقي"""
    bid, _ = _faloo_ids(url)
    index_url = f'{_FALOO_BASE}/booklist_{bid}.html'
    r = _cjk_get(index_url, referer=f'{_FALOO_BASE}/{bid}.html', timeout=30,
                 validate=lambda t: f'_{bid}.html' in t)
    if r is None:
        print(f"Faloo chapters: index fetch failed for {bid}")
        return []
    raw = r.text
    # الروابط بروتوكول نسبي //wap.faloo.com/944651_1.html (أو مطلقة) — نصها عنوان الفصل
    link_re = re.compile(
        r'<a[^>]*href="(?:https?:)?' + re.escape('//wap.faloo.com/') + r'(\d+)_(\d+)\.html"[^>]*>([^<]{2,120})</a>')
    chapters = {}
    for m in link_re.finditer(raw):
        link_bid, n, title = m.group(1), int(m.group(2)), m.group(3).strip()
        if link_bid != bid:
            continue  # روابط كتب أخرى (توصيات)
        title = re.sub(r'\s+', ' ', title).strip()
        if not title:
            title = f'第{n}章'
        chapters[n] = {'number': n, 'url': f'{_FALOO_BASE}/{bid}_{n}.html', 'title': title}
    out = [chapters[k] for k in sorted(chapters)]
    print(f"Faloo: {len(out)} chapters for book {bid}")
    return out


def _faloo_extract_text(raw):
    """استخراج نص الفصل من div.nodeContent (فقرات <p>) + كشف البوابة"""
    m = re.search(r'<div[^>]*class="[^"]*nodeContent[^"]*"[^>]*>(.*?)</div>', raw, re.S)
    if not m:
        return None, 'no_nodeContent'
    body = m.group(1)
    paras = []
    for pm in re.finditer(r'<p[^>]*>(.*?)</p>', body, re.S):
        t = re.sub(r'<[^>]+>', '', pm.group(1))
        t = re.sub(r'&nbsp;?', ' ', t).strip()
        if t:
            paras.append(t)
    text = '\n'.join(paras)
    return text, 'ok'


def scrape_chapter_faloo(url):
    """محتوى فصل Faloo — فصول الاشتراك بلا جلسة تُرفض بصدق"""
    try:
        bid, n = _faloo_ids(url)
        extra = {}
        header = _faloo_cookie_header()
        if header:
            extra['Cookie'] = header
        r = _cjk_get(url, referer=f'{_FALOO_BASE}/booklist_{bid}.html',
                     timeout=30, extra_headers=extra or None,
                     validate=lambda t: 'wap.faloo.com' in t)
        if r is None:
            print(f"Faloo: chapter page fetch failed {url}")
            return None
        raw = r.text
        text, why = _faloo_extract_text(raw)
        if why != 'ok':
            print(f"Faloo: nodeContent not found in {url} — template changed?")
            return None
        if '您还没有登录' in raw and len(re.sub(r'\s', '', text)) < 50:
            print(f"Faloo: chapter {n} of {bid} is behind login (subscription) — "
                  "paste account cookies from the scraper UI to read it")
            return None
        # تنظيف: أسطر ترويجية + أسطر فارغة زائدة
        lines = []
        for line in text.split('\n'):
            l = line.strip()
            if not l:
                lines.append('')
                continue
            if len(l) <= 60 and _FALOO_JUNK_LINE_RE.search(l):
                continue
            lines.append(l)
        out = clean_text('\n'.join(lines))
        if len(re.sub(r'\s', '', out)) < 100:
            print(f"Faloo: chapter {n} content too short ({len(out)} chars)")
            return None
        return out
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error Faloo Chapter: {e}")
        return None


def worker_faloo(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_faloo, scrape_chapter_faloo,
                   site_name='Faloo')


def faloo_quick_session_check():
    """فحص حي: هل كوكيز Faloo تفتح الفصول المشتراة؟
    يقرأ فصلاً معروفاً خلف تسجيل الدخول (944651/100) ويقيس النتيجة."""
    header = _faloo_cookie_header()
    try:
        chap_url = f'{_FALOO_BASE}/{_FALOO_CHECK_BOOK}_{_FALOO_CHECK_CHAPTER}.html'
        extra = {'Cookie': header} if header else None
        r = _cjk_get(chap_url, referer=f'{_FALOO_BASE}/booklist_{_FALOO_CHECK_BOOK}.html',
                     timeout=30, extra_headers=extra,
                     validate=lambda t: 'wap.faloo.com' in t)
        if r is None:
            return {'ok': False, 'guest': None, 'message': 'تعذر الوصول لـ wap.faloo.com من السيرفر — '
                    'جرّب الفحص لاحقاً أو أضف مفاتيح ScraperAPI.'}
        text, why = _faloo_extract_text(r.text)
        if why != 'ok':
            return {'ok': False, 'guest': None, 'message': 'لم يُعثر على div.nodeContent — ربما تغيّر قالب الموقع.'}
        plain = len(re.sub(r'\s', '', text))
        if plain >= 300:
            return {'ok': True, 'guest': not header, 'source': 'settings' if header else 'env',
                    'message': 'قراءة الفصول تعمل — الفصل المختبئي (خلف تسجيل الدخول) أُعيد كاملاً. '
                               'الفصول المشتراة ستُقرأ بالكوكيز الحالية.' if header else
                               'الفصل المختبئي مفتوح حالياً من هذا العنوان (عرض مؤقت؟) — السحب سيمر.'}
        if '您还没有登录' in r.text or not text:
            if not header:
                return {'ok': False, 'guest': True,
                        'message': 'وضع الزائر (مؤكد): الفصل المختبئي خلف تسجيل الدخول — الفصول المجانية تعمل، '
                                   'وفصول الاشتراك تُرفض بصدق. الصق كوكيز حساب Faloo في الإعدادات لقراءتها.'}
            return {'ok': False, 'guest': True, 'source': 'settings',
                    'message': 'الكوكيز موجودة لكنها لا تفتح الفصل المختبئ — انتهت صلاحيتها أو الحساب '
                               'لم يشترِ هذا الفصل. انسخ ترويسة Cookie جديدة بعد تسجيل الدخول.'}
        return {'ok': False, 'guest': None,
                'message': f'رد غير مفهوم من صفحة الفصل ({plain} محرفاً) — راجع السجلات.'}
    except Exception as e:
        return {'ok': False, 'guest': None, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}


# ==========================================
# 🟩 2) XSW 台灣小說網 (m.xsw.tw / www.xsw.tw)
# ==========================================

_XSW_BASE_M = 'https://m.xsw.tw'
_XSW_BASE_D = 'https://www.xsw.tw'

# شهادة SSL ناقصة السلسلة (CertificateVerifyError) — تجرب verify=True ثم False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # المسار الاحتياطي مقصود
_XSW_SESSION = requests.Session()
_XSW_SESSION.headers.update({
    'User-Agent': UA_MOBILE,
    'Accept-Language': 'zh-TW,zh;q=0.9,zh-CN;q=0.8',
})

# إعلان ثابت أول كل فصل تقريباً — يُنزع من سطر كامل
_XSW_JUNK_LINE_RE = re.compile(
    r'書海閣|您可以在百度裏搜索|查找最新章節|請記住本站|本站最新網址|'
    r'(?:一秒記住|精彩東方文學|筆下文學)\S{0,20}')

_XSW_TIMEOUT_MARK = '章節內容獲取超時'


def _xsw_get(url, referer=None, timeout=25, attempts=2):
    """جالب XSW المتسامح مع SSL: verify=True ثم False — يعيد نصاً أو None"""
    headers = {'Referer': referer} if referer else None
    for attempt in range(attempts):
        for verify in (True, False):
            try:
                r = _XSW_SESSION.get(url, headers=headers, timeout=timeout, verify=verify)
                if r.status_code == 200 and r.text and len(r.text) > 200:
                    return r.text
                if r.status_code == 404:
                    return None
            except requests.exceptions.SSLError:
                continue  # جرّب بلا تحقق
            except Exception as e:
                print(f"   xsw get failed {url[:70]}: {type(e).__name__}: {str(e)[:60]}")
        if attempt < attempts - 1:
            time.sleep(1.5)
    return None


def _xsw_ids(url):
    """تحليل رابط XSW (جوال أو سطح مكتب): يعيد (book_id, chap_id أو None)"""
    p = urlparse(url)
    host = p.netloc.lower()
    if 'xsw.tw' not in host:
        raise ValueError('XSW: استخدم رابطاً على xsw.tw فقط.')
    path = p.path or ''
    # جوال فصل: /{book}/{chap}.html
    m = re.fullmatch(r'/(\d+)/(\d+)\.html/?', path)
    if m:
        return m.group(1), m.group(2)
    # جوال كتاب: /{book}/ (أو /{book})
    m = re.fullmatch(r'/(\d+)/?', path)
    if m:
        return m.group(1), None
    # سطح مكتب: /book/{book}.html أو /book/{book}/page-N.html أو /book/{book}/{chap}.html
    m = re.search(r'/book/(\d+)(?:/(\d+)(?:\.html)?)?', path)
    if m:
        return m.group(1), m.group(2)
    raise ValueError('XSW: الرابط المدعوم https://m.xsw.tw/{book_id}/ '
                     'أو https://www.xsw.tw/book/{book_id}.html.')


def _xsw_mobile_url(book_id, chap_id=None):
    """توحيد أي رابط (سطح مكتب/جوال) إلى صيغة الجوال للسحب"""
    if chap_id:
        return f'{_XSW_BASE_M}/{book_id}/{chap_id}.html'
    return f'{_XSW_BASE_M}/{book_id}/'


def fetch_metadata_xsw(url):
    """بيانات الرواية من صفحة سطح المكتب (الأغنى: غلاف + intro كاملة + صفوف معلومات)"""
    try:
        bid, _chap = _xsw_ids(url)
        desk_url = f'{_XSW_BASE_D}/book/{bid}.html'
        raw = _xsw_get(desk_url, referer=f'{_XSW_BASE_M}/{bid}/', timeout=30)
        if raw is None:
            print(f"XSW metadata: desktop page fetch failed for {bid}")
            return None
        soup = parse_html(raw)
        page_text = soup.get_text('\n', strip=True)

        # العنوان + المؤلف: h1 يحمل «العنوان作者：المؤلف» — نفصل عند 作者：
        title, author = '', ''
        h1 = soup.find('h1')
        if h1:
            h1_txt = h1.get_text(' ', strip=True)
            m = re.match(r'(.+?)\s*作者[：:]\s*(\S{1,25})', h1_txt)
            if m:
                title, author = m.group(1).strip(), m.group(2).strip()
            else:
                title = h1_txt.strip()
        if not title:
            raw_title = soup.title.get_text() if soup.title else ''
            title = re.split(r'[-（(]', raw_title)[0].strip()
        if not title:
            print(f"XSW metadata: no title found for {bid}")
            return None
        if not author:
            m = re.search(r'小說作者\s*[：:]?\s*\n?([^\n<]{1,25})', page_text)
            if m:
                author = m.group(1).strip()

        # الغلاف: صورة تحمل معرف الكتاب — واحتياطاً الصيغة القياسية للموقع
        cover = ''
        for img in soup.find_all('img'):
            src = img.get('src') or ''
            if f'/{bid}/' in src or f'{bid}s.jpg' in src:
                cover = urljoin(desk_url + '/', src)
                break
        if not cover:
            cover = f'https://img.xsw.tw/{int(bid) // 1000}/{bid}/{bid}s.jpg'
        cover = cover.replace('http://', 'https://')

        # الوصف: أطول div.intro (قد توجد عدة — بعضها يحمل عدادات)
        description = ''
        for div in soup.select('div.intro'):
            t = div.get_text('\n', strip=True)
            t = re.sub(r'總點擊數[^\n]*', '', t).strip()
            t = re.sub(r'\n{2,}', '\n', t)
            if len(t) > len(description):
                description = t
        if not description:
            m = re.search(r'(?:內容簡介|内容简介)[：:]?\s*\n?([^\n]{30,})', page_text)
            description = m.group(1).strip() if m else ''

        # صفوف المعلومات
        category = ''
        m = re.search(r'小說分類\s*[：:]?\s*\n?([^\n<]{1,20})', page_text)
        if m:
            category = m.group(1).strip()
        status_txt = ''
        m = re.search(r'小說狀態\s*[：:]?\s*\n?([^\n<]{1,12})', page_text)
        if m:
            status_txt = m.group(1).strip()
        status = 'مكتملة' if ('完' in status_txt or '完結' in status_txt) else 'مستمرة'

        return {
            'title': title, 'author': author, 'description': description,
            'cover': fix_image_url(cover, base_url=_XSW_BASE_D),
            'status': status, 'category': category or 'عام', 'tags': [],
            'sourceUrl': _xsw_mobile_url(bid), 'lastUpdate': None,
        }
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error XSW Meta: {e}")
        return None


def fetch_chapter_list_xsw(url):
    """فهرس مرقّم بالصفحات: m.xsw.tw/{id}/page-N.html — 20 فصلاً/صفحة.
    الروابط بعلامات اقتباس مفردة داخل ul.chapter ونصها ينتهي بـ<span></span>."""
    bid, _ = _xsw_ids(url)
    first_url = f'{_XSW_BASE_M}/{bid}/page-1.html'
    first = _xsw_get(first_url, referer=_xsw_mobile_url(bid), timeout=30)
    if first is None:
        print(f"XSW chapters: index page-1 fetch failed for {bid}")
        return []
    # أقصى صفحة من روابط الترقيم (استبعد صيغة page-N-M.html للترتيب العكسي)
    max_page = None
    for mp in re.findall(r'page-(\d+)\.html', first):
        v = int(mp)
        if max_page is None or v > max_page:
            max_page = v
    if max_page:
        max_page = min(max_page, 1000)  # سقف أمان
    print(f"XSW: index pages for {bid}: max={max_page or '?'}")

    chapters = []
    seen_ids = set()

    def _collect(html):
        added = 0
        for m in re.finditer(
                r"href=['\"]/" + re.escape(bid) + r'/(\d+)\.html["\'][^>]*>(.*?)</a>', html, re.S):
            cid, inner = m.group(1), m.group(2)
            if cid in seen_ids:
                continue
            title = re.sub(r'<[^>]+>', '', inner)      # ينزع <span></span> وما شابه
            title = re.sub(r'\s+', ' ', title).strip()
            if not title:
                title = f'第{len(chapters) + 1}章'
            seen_ids.add(cid)
            chapters.append({
                'number': len(chapters) + 1,
                'url': f'{_XSW_BASE_M}/{bid}/{cid}.html',
                'title': title,
            })
            added += 1
        return added

    _collect(first)
    page = 2
    while True:
        if max_page and page > max_page:
            break
        html = _xsw_get(f'{_XSW_BASE_M}/{bid}/page-{page}.html',
                        referer=first_url, timeout=30)
        if html is None:
            # صفحة فاشلة — محاولة أخيرة ثم توقف (لا نضلل الترقيم)
            html = _xsw_get(f'{_XSW_BASE_M}/{bid}/page-{page}.html',
                            referer=first_url, timeout=30)
            if html is None:
                print(f"XSW: index page-{page} failed — stopping at {len(chapters)} chapters")
                break
        if _collect(html) == 0:
            break
        page += 1
        time.sleep(0.3)  # مهذب مع الموقع (عشرات الصفحات)

    print(f"XSW: {len(chapters)} chapters for book {bid}")
    return chapters


def scrape_chapter_xsw(url):
    """محتوى فصل XSW من div#nr1 (الجوال) — رفض صادق لفصول الخادم الفاشلة وفصول الصور"""
    try:
        bid, chap_id = _xsw_ids(url)
        if not chap_id:
            print(f"XSW: ليس رابط فصل: {url}")
            return None
        page_url = _xsw_mobile_url(bid, chap_id)
        raw = _xsw_get(page_url, referer=f'{_XSW_BASE_M}/{bid}/page-1.html', timeout=25)
        if raw is None:
            print(f"XSW: chapter page fetch failed {page_url}")
            return None
        m = re.search(r'<div[^>]*id="nr1"[^>]*>(.*?)</div>', raw, re.S)
        if not m:
            print(f"XSW: div#nr1 not found — template changed? {page_url}")
            return None
        body = m.group(1)
        # 1) فصول خادمهم الفاشلة: رسالة «章節內容獲取超時» (دائمة حتى بإعادات المحاولة)
        if _XSW_TIMEOUT_MARK in body:
            print(f"XSW: chapter {chap_id} — site server timeout (章節內容獲取超時، دائم لهذا الفصل) — تخطٍّ صادق")
            return None
        # 2) تنظيف نصي
        txt = re.sub(r'<br\s*/?>', '\n', body)
        txt = re.sub(r'<[^>]+>', '', txt)
        txt = txt.replace('&nbsp;', ' ').replace('&nbsp', ' ')
        lines = [l.strip() for l in txt.split('\n') if l.strip()]
        lines = [l for l in lines if not (len(l) <= 60 and _XSW_JUNK_LINE_RE.search(l))]
        text = '\n'.join(lines)
        # 3) فصول الصور فقط: وسوم <img مكتوبة بـ&nbsp; داخلها فلا يفكّها المحلل —
        #    تُكشف من HTML الخام، والنص النظيف بعدها أقصر من الحد الأدنى
        if len(re.sub(r'\s', '', text)) < 100:
            if re.search(r'<img[\s&nbsp;]', body, re.I) or '&nbsp;<img' in body:
                print(f"XSW: chapter {chap_id} is images-only (وسوم img بخادم الموقع) — تخطٍّ صادق")
                return None
            print(f"XSW: chapter {chap_id} content too short ({len(text)} chars)")
            return None
        return clean_text(text)
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error XSW Chapter: {e}")
        return None


def worker_xsw(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_xsw, scrape_chapter_xsw,
                   site_name='XSW')


# ==========================================
# 📚 التسجيل في السجل العام
# ==========================================
register_site(
    domain_patterns=['faloo.com', 'wap.faloo.com', 'b.faloo.com'],
    name='Faloo (飞卢小说网)',
    language='chinese',
    fetch_metadata=fetch_metadata_faloo,
    fetch_chapters=fetch_chapter_list_faloo,
    fetch_content=scrape_chapter_faloo,
    worker=worker_faloo,
    status='active',
    notes='جديد (v3.2)! ترميز GBK — بيانات من حقول مخفية (hidNovelName/hidCoverUrl) + '
          'وصف كامل من meta بعد نزع غلاف الترويج + فهرس كامل booklist_{id}.html بترقيم '
          'حقيقي + محتوى div.nodeContent. الفصول المجانية للزائر وفصول الاشتراك خلف '
          'تسجيل الدخول (رفض صادق) — كوكيز حساب اختيارية من واجهة السكرابر أو FALOO_COOKIES.'
)


register_site(
    domain_patterns=['xsw.tw', 'm.xsw.tw', 'www.xsw.tw'],
    name='XSW (台灣小說網)',
    language='chinese',
    fetch_metadata=fetch_metadata_xsw,
    fetch_chapters=fetch_chapter_list_xsw,
    fetch_content=scrape_chapter_xsw,
    worker=worker_xsw,
    status='active',
    notes='جديد (v3.2)! صينية تقليدية — شهادة SSL ناقصة (تدار تلقائياً verify=True→False) '
          '+ بيانات سطح المكتب (غلاف/intro/صفوف) + فهرس مرقّم 20/صفحة بروابط اقتباس مفردة '
          '+ محتوى div#nr1 من الجوال. فصول خادمهم الفاشلة (章節內容獲取超時) وفصول الصور '
          'تُرفض بصدق وتُتخطى. بلا كوكيز (لا تسجيل بالموقع).'
)
