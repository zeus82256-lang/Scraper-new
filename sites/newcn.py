# -*- coding: utf-8 -*-
"""
==========================================
🟥 ثلاثة مواقع صينية إضافية (v3.3) — 85Novel + Shuqi + UUread
==========================================
ثلاثة مواقع جديدة (v3.3) — كلها بدعم كامل: بيانات + فهرس بعناوين حقيقية +
محتوى نظيف + أغلفة، مع رفض صادق للمحتوى الفاشل بدل إرسال نص ناقص:

1.  85Novel (85小說網)      - www.85novel.com   ✅ صينية تقليدية UTF-8
    قالب DaisyUI/Alpine.js — الفهرس يُجلب من واجهة POST داخلية:
      - GET صفحة الكتاب أولًا (كوكيز جلسة + كوكي _xsrf إلزامية)
      - POST ?_xsrf={token}  {action:'auth'}     → عدد الفصول الكلي
      - POST ?_xsrf={token}  {action:'chapters', slice:[a,b]} (دفعة 200 فصل)
    ⚠️ محتوى الفصل مشوَّش بالترتيب (data-content-order-mode/strategy):
       القالب يخلط الفقرات داخل كتل data-chapter-content-block ثم يعيدها
       الجافاسكربت — نُنفِّذ نفس خوارزمية الاستعادة (restoreSplitChapterItems)
       بايثونيًا: عكس اختياري + تقسيم زوجي/فردي + تشابك. مؤكدة حرفيًا من common.js.
    البيانات: h1 + مؤلف من span قبل em(著) + صف معلومات (تصنيف/حالة/طول) +
    وصف من فقرات div max-h-64 + وسوم bg-base-300 + غلاف /cover/{id}.jpg.

2.  Shuqi (书旗小说)        - t.shuqi.com       ✅ صينية مبسطة UTF-8
    منصة علي بابا — تطبيق Vue SPA بواجهات موقّعة md5 (مؤكدة من app.js):
      - بيانات الصفحة من وسوم og:novel:* + JSON مضمّن __INITIAL_STATE__
        (وصف كامل بأسطر جديدة + وسوم + تصنيف + حالة + وقت تحديث).
      - فهرس: GET /reader/{id} → commonParams (توكن ضيف مضمّن) →
        GET content.shuqireader.com/openapi/book/chapterlist
        مع توقيع sign = md5(قيم المفاتيح مرتبة مدمجة + مفتاح walden)
        (مفاتيح التشفير: bookId + user_id، ضيف = 8000000).
      - المحتوى: رابط موقّع جاهز لكل فصل (contUrlSuffix) من الفهرس →
        /openapi/chapter/contentfree/{suffix} → ChapterContent →
        🔐 فك التشويش المؤكد من الكود: rot13 ثم base64 ثم تقسيم <br>
        (encrypt: "rot13, base64, trim" من app.js).
    ⚠️ payStatus=0 للفصول المجانية فقط (20 فصلًا)، لكن نهاية contentfree
       مع لاحقة contUrlSuffix الموقعة تعيد نص الفصل الكامل حتى للفصول
       المدفوعة (مؤكد: الفصل 21 و 922 — طول النص = wordCount المعلن حرفيًا).
    بلا كوكيز — توكن الضيف يأتي مضمّنًا في HTML كل طلب.

3.  UUread (uu看書)         - www.uuread.tw    ✅ صينية تقليدية UTF-8
    ⚠️ يحجب بصمة Chrome (403) — الجالب يستخدم بصمة Firefox مباشرة.
    البيانات من وسوم og:novel:* + div#bookintro (كيانات &lt;BR/&gt; تُحوَّل
    لأسطر، والوصف مبتور من الموقع نفسه — نأخذه كما هو بصدق).
    الفهرس: قائمة كاملة مرتّبة داخل div#newlist (روابط /chapter/{bid}/{cid}.html).
    المحتوى: div#nr بفقرات <p> + ⚠️ فصول مقسّمة صفحات {cid}_2.html، {cid}_3.html…
    (نتبع سلسلة «الصفحة التالية» حتى نفادها ثم نجمع الفقرات بالترتيب).
    بلا كوكيز (لا فصول مقفلة أصلاً — الفهرس كله مجاني).
"""

import base64
import codecs
import hashlib
import json
import re
import threading
import time

from urllib.parse import urljoin, urlparse, unquote

from core.registry import register_site
from core.utils import (
    fix_image_url,
    clean_text,
    generic_worker,
)

# جالب CJK الآمن للترميز (uuread فقط — بقية المواقع بجوالات خاصة بها)
from sites.cnextra import _cjk_get
from curl_cffi import requests as _cffi

_UA_PC = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
_UA_FF = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) '
          'Gecko/20100101 Firefox/133.0')


# ==========================================
# 🟥 1) 85NOVEL 85小說網 (www.85novel.com)
# ==========================================

_85_BASE = 'https://www.85novel.com'
_85_SLICE = 200          # الدفعة القصوى بفهرس الموقع (مؤكدة من common.js)
_85_LOCK = threading.Lock()


def _85_ids(url):
    """تحليل رابط 85novel: صفحة كتاب /book/{id}.html أو فصل /book/{id}/{cid}.html"""
    p = urlparse(url)
    host = p.netloc.lower()
    if '85novel.com' not in host:
        raise ValueError('85Novel: استخدم رابطاً على 85novel.com فقط.')
    m = re.search(r'/book/(\d+)(?:/(\d+))?\.html', p.path or '')
    if m:
        return m.group(1), m.group(2)
    m = re.search(r'/book/(\d+)', p.path or '')
    if m:
        return m.group(1), None
    raise ValueError('85Novel: الرابط المدعوم https://www.85novel.com/book/{book_id}.html '
                     'أو رابط فصل https://www.85novel.com/book/{book_id}/{chapter_id}.html.')


def _85_session_get(s, url, referer=None, timeout=30):
    """GET عبر جلسة curl_cffi ببصمة Chrome — نص UTF-8 أو None.
    الموقع يقيّد الطلبات المتتالية (403 مؤقت قصير) — تراجع متزايد حتى 4 محاولات."""
    headers = {
        'User-Agent': _UA_PC,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.5',
    }
    if referer:
        headers['Referer'] = referer
    waits = [2, 45, 90]   # الموقع يفرض حصة زمنية ضيقة على سحب الفصول (403 حتى تتجدد
    for attempt in range(4):   # الحصة) — الانتظار الطويل أجدى من الطلبات المتلاحقة
        try:
            r = s.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.content.decode('utf-8', errors='replace')
            if r.status_code in (403, 429) and attempt < 3:
                print(f"85Novel: GET {url[-40:]} → {r.status_code} — retry in {waits[attempt]}s")
                time.sleep(waits[attempt])
                continue
            print(f"85Novel: GET {url[:80]} → {r.status_code}")
            return None
        except Exception as e:
            if attempt >= 3:
                print(f"   85Novel GET failed {url[:70]}: {str(e)[:70]}")
                return None
            time.sleep(2)
    return None


def _85_post_api(s, page_url, payload, xsrf, timeout=20):
    """POST واجهة Alpine الداخلية ?_xsrf= مع جسم JSON — يعيد dict أو None.
    الموقع يقيّد الطلبات المتتالية (403 مؤقت) — إعادة محاولة بتراجع متزايد."""
    headers = {
        'User-Agent': _UA_PC,
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': _85_BASE,
        'Referer': page_url,
    }
    for attempt in range(3):
        try:
            r = s.post(f'{page_url}?_xsrf={xsrf}', data=json.dumps(payload),
                       headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 429) and attempt < 2:
                wait = 6 + attempt * 8   # 6ث ثم 14ث — الحجب المؤقت يزول
                print(f"85Novel: API {payload.get('action')} → {r.status_code} — إعادة محاولة بعد {wait}ث")
                time.sleep(wait)
                continue
            print(f"85Novel: API {payload.get('action')} → {r.status_code}")
            return None
        except Exception as e:
            if attempt >= 2:
                print(f"   85Novel API {payload.get('action')} failed: {str(e)[:80]}")
                return None
            time.sleep(3)
    return None


def fetch_metadata_85novel(url):
    """بيانات الرواية من صفحة الكتاب (h1 + صف المعلومات + فقرات الوصف)"""
    try:
        bid, _cid = _85_ids(url)
        book_url = f'{_85_BASE}/book/{bid}.html'
        s = _cffi.Session(impersonate='chrome131')
        raw = _85_session_get(s, book_url, timeout=30)
        if raw is None or 'bookintro' not in raw and '<h1' not in raw:
            print(f"85Novel metadata: page fetch failed for {bid}")
            return None

        title = ''
        m = re.search(r'<h1[^>]*class="[^"]*text-2xl[^"]*"[^>]*>([^<]+)</h1>', raw)
        if m:
            title = m.group(1).strip()
        if not title:
            m = re.search(r'<title>([^<]+)</title>', raw)
            title = m.group(1).split('(')[0].strip() if m else ''
        if not title:
            print(f"85Novel metadata: no title for {bid}")
            return None

        # المؤلف: <span class="ms-2">{مؤلف}<em ...>著</em></span>
        author = ''
        m = re.search(r'<span class="ms-2">([^<]{1,30})<em', raw)
        if m:
            author = m.group(1).strip()

        # صف المعلومات: تصنيفات + طول + حالة + أزمنة
        category, status = '', ''
        m = re.search(r'<div class="text-base-700">(.*?)</div>', raw, re.S)
        if m:
            spans = [re.sub(r'<[^>]+>', '', x).strip()
                     for x in re.findall(r'<span>([^<]*)</span>', m.group(1))]
            spans = [x for x in spans if x]
            if spans:
                category = spans[0]
                for x in spans:
                    if re.search(r'連載|完結|完本', x):
                        status = x
                        break
        status = 'مكتملة' if ('完' in status) else 'مستمرة'

        # الوصف: فقرات div max-h-64
        description = ''
        m = re.search(r'<div class="overscroll-contain[^"]*max-h-64[^"]*">(.*?)</div>', raw, re.S)
        if m:
            paras = [re.sub(r'<[^>]+>', '', p).strip()
                     for p in re.findall(r'<p[^>]*>(.*?)</p>', m.group(1), re.S)]
            description = '\n'.join(p for p in paras if p)
        if not description:
            m = re.search(r'<meta property="og:description" content="([^"]*)"', raw)
            description = m.group(1).strip() if m else ''

        # الوسوم: spans بخلفية bg-base-300
        tags = []
        for tm in re.finditer(r'<span class="text-sm bg-base-300[^"]*">([^<]{1,12})</span>', raw):
            t = tm.group(1).strip()
            if t and t not in tags:
                tags.append(t)
        tags = tags[:6]

        # الغلاف: src مباشر (og:image بالموقع مكسور — https:https://)
        cover = ''
        m = re.search(r'<img class="w-\[180px\][^"]*"[^>]*src="([^"]+)"', raw)
        if m:
            cover = urljoin(book_url, m.group(1))
        if not cover:
            m = re.search(r'/cover/(\d+)\.jpg', raw)
            if m:
                cover = f'{_85_BASE}/cover/{m.group(1)}.jpg'

        return {
            'title': title, 'author': author, 'description': description,
            'cover': fix_image_url(cover, base_url=_85_BASE),
            'status': status, 'category': category or 'عام', 'tags': tags,
            'sourceUrl': book_url, 'lastUpdate': None,
        }
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error 85Novel Meta: {e}")
        return None


def _85_auth(s, book_url, xsrf):
    """استدعاء action=auth — يعيد (total_chapters, nID) أو (0, None)"""
    j = _85_post_api(s, book_url, {'action': 'auth'}, xsrf)
    if not j:
        return 0, None
    res = j.get('result') or {}
    try:
        total = int(res.get('chapters') or 0)
    except (TypeError, ValueError):
        total = 0
    return total, res.get('nID')


def _85_fetch_all_chapters(s, bid, book_url, xsrf, total):
    """سحب كل دفعات الفهرس action=chapters بترتيبها — قائمة (cid, title).
    تجميع بلا تكرار حسب ChapterID مع وقوف مبكر عند بلوغ العدد الكلي."""
    out = []
    seen = set()
    start = 1
    while start <= total:
        end = min(start + _85_SLICE - 1, total)
        j = _85_post_api(s, book_url,
                         {'action': 'chapters', 'slice': [start, end]}, xsrf)
        chs = ((j or {}).get('result') or {}).get('chapters') or []
        if not chs:
            print(f"85Novel: slice [{start},{end}] returned empty — stop at {len(out)}")
            break
        for ch in chs:
            cu = str(ch.get('ChapterUrl') or '')
            cm = re.match(r'(\d+)/(\d+)\.html', cu)
            if not cm or cm.group(1) != bid:
                continue
            cid = cm.group(2)
            if cid in seen:
                continue
            seen.add(cid)
            title = re.sub(r'\s+', ' ', str(ch.get('ChapterName') or '')).strip()
            out.append((cid, title))
            if len(seen) >= total:
                break
        if len(seen) >= total:
            break
        start = end + 1
        time.sleep(0.8)   # مهلة بين الدفعات — الموقع يقيّد الطلبات المتتالية
    return out


def fetch_chapter_list_85novel(url):
    """فهرس كامل عبر واجهة POST الداخلية (جلسة + _xsrf + دفعات 200)"""
    try:
        bid, _ = _85_ids(url)
        book_url = f'{_85_BASE}/book/{bid}.html'
        s = _cffi.Session(impersonate='chrome131')
        raw = _85_session_get(s, book_url, timeout=30)
        if raw is None:
            print(f"85Novel chapters: book page fetch failed for {bid}")
            return []
        xsrf = s.cookies.get('_xsrf') or ''
        if not xsrf:
            print("85Novel chapters: no _xsrf cookie — POST API will fail")
            return []
        total, _nid = _85_auth(s, book_url, xsrf)
        if total <= 0:
            print(f"85Novel chapters: auth returned no count for {bid}")
            return []
        pairs = _85_fetch_all_chapters(s, bid, book_url, xsrf, total)
        chapters = []
        for idx, (cid, title) in enumerate(pairs, start=1):
            if not title:
                title = f'第{idx}章'
            chapters.append({'number': idx,
                             'url': f'{_85_BASE}/book/{bid}/{cid}.html',
                             'title': title})
        print(f"85Novel: {len(chapters)} chapters for book {bid}")
        return chapters
    except ValueError as e:
        print(str(e))
        return []
    except Exception as e:
        print(f"Error 85Novel Chapters: {e}")
        return []


def _85_restore_split(items, mode):
    """نسخة بايثونية حرفية من restoreSplitChapterItems في common.js:
    عكس اختياري ثم تقسيم نصفي حتى/فرد حسب الوضع ثم تشابكهم."""
    grouped = list(items)
    if mode in (1, 2):
        grouped.reverse()
    even_first = mode in (1, 3)
    first_count = -(-len(grouped) // 2) if even_first else len(grouped) // 2
    first = grouped[:first_count]
    second = grouped[first_count:]
    even, odd = (first, second) if even_first else (second, first)
    restored = []
    for i in range(max(len(even), len(odd))):
        if i < len(even):
            restored.append(even[i])
        if i < len(odd):
            restored.append(odd[i])
    return restored


def _85_extract_paragraphs(raw):
    """استخراج فقرات الفصل مع استعادة الترتيب من attrs الحاوية. None إن لم تُوجد."""
    mcont = re.search(r'<div[^>]*data-chapter-content[^>]*>', raw)
    if not mcont:
        return None
    open_tag = mcont.group(0)
    mmode = re.search(r'data-content-order-mode="(-?\d+)"', open_tag)
    mstrat = re.search(r'data-content-order-strategy="(\w+)"', open_tag)
    mode = int(mmode.group(1)) if mmode else 0
    strategy = mstrat.group(1) if mstrat else 'split'

    start = raw.find(open_tag)
    rest = raw[start:]
    blocks = re.findall(r'<div[^>]*data-chapter-content-block[^>]*>(.*?)</div>', rest, re.S)
    if not blocks:
        return []

    per_block = []
    for b in blocks:
        paras = []
        for p in re.findall(r'<p[^>]*>(.*?)</p>', b, re.S):
            t = re.sub(r'<[^>]+>', '', p)
            t = t.replace('&nbsp;', ' ').strip()
            if t:
                paras.append(t)
        if strategy == 'split':
            paras = _85_restore_split(paras, mode)
        elif mode in (1, 2):
            paras.reverse()
        per_block.append(paras)

    reverse_blocks = (mode in (1, 2)) if strategy == 'split' else (mode in (1, 3))
    if reverse_blocks:
        per_block.reverse()
    return [p for blk in per_block for p in blk]


def scrape_chapter_85novel(url):
    """محتوى فصل 85novel — استعادة ترتيب الفقرات + تنظيف نهائي"""
    try:
        bid, cid = _85_ids(url)
        if not cid:
            print(f"85Novel: ليس رابط فصل: {url}")
            return None
        s = _cffi.Session(impersonate='chrome131')
        raw = _85_session_get(s, url, referer=f'{_85_BASE}/book/{bid}.html', timeout=30)
        if raw is None:
            print(f"85Novel: chapter page fetch failed {url}")
            return None
        if '您还没有登录' in raw or '尚未登录' in raw:
            print(f"85Novel: chapter {cid} of {bid} behind login — تخطٍّ صادق")
            return None
        paras = _85_extract_paragraphs(raw)
        if paras is None:
            print(f"85Novel: data-chapter-content not found — template changed? {url}")
            return None
        text = '\n'.join(paras)
        out = clean_text(text)
        if len(re.sub(r'\s', '', out)) < 100:
            print(f"85Novel: chapter {cid} content too short ({len(out)} chars)")
            return None
        return out
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error 85Novel Chapter: {e}")
        return None


def worker_85novel(url, admin_email, metadata):
    # الموقع يقيّد الطلبات المتتالية بعنف (403 مؤقت) — مهلة 15ث بين الفصول
    # + تراجع إعادة المحاولة الداخلي. الفصول الفاشلة تُرفض بصدق وتُتخطى.
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_85novel, scrape_chapter_85novel,
                   delay=15.0, site_name='85Novel')


# ==========================================
# 🟥 2) SHUQI 书旗小说 (t.shuqi.com)
# ==========================================

_SHUQI_BASE = 'https://t.shuqi.com'
_SHUQI_CONTENT_HOST = 'https://content.shuqireader.com'
_SHUQI_WALDEN_KEY = '37e81a9d8f02596e1b895d07c171d5c9'   # من __INITIAL_STATE__.apis.walden (ثابت)
_SHUQI_GUEST_UID = '8000000'
# روابط الفصول تحمل لاحقة موقّعة من الفهرس — تُخبَّأ هنا ليعمل سحب المحتوى لاحقاً
_SHUQI_RUNTIME = {'suffixes': {}, 'order': []}
_SHUQI_LOCK = threading.Lock()
_SHUQI_IMG_HTTPS_OK = {'img-tailor.11222.cn'}


def _shuqi_ids(url):
    """تحليل رابط شوقي: /book/{id} أو /reader/{id} (+?chapterId=) — ورفع .html"""
    p = urlparse(url)
    host = p.netloc.lower()
    if 'shuqi.com' not in host:
        raise ValueError('Shuqi: استخدم رابطاً على t.shuqi.com فقط.')
    path = p.path or ''
    m = re.match(r'/(?:book|reader)/(\d+?)(?:\.html)?/?$', path)
    if m:
        bid = m.group(1)
        q = re.search(r'chapterId=(\d+)', p.query or '')
        return bid, (q.group(1) if q else None)
    raise ValueError('Shuqi: الرابط المدعوم https://t.shuqi.com/book/{book_id} '
                     'أو رابط قارئ https://t.shuqi.com/reader/{book_id}?chapterId={cid}.')


def _shuqi_get(url, referer=None, timeout=25, firefox=False):
    """GET بسيط ببصمة Chrome (أو Firefox) — نص UTF-8 أو None"""
    headers = {'User-Agent': _UA_FF if firefox else _UA_PC,
               'Accept': 'text/html,application/json,*/*;q=0.8',
               'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.5'}
    if referer:
        headers['Referer'] = referer
    for attempt in range(3):
        try:
            r = _cffi.get(url, headers=headers, timeout=timeout,
                          impersonate='firefox133' if firefox else 'chrome131')
            if r.status_code == 200:
                return r.content.decode('utf-8', errors='replace')
            if r.status_code in (403, 429) and attempt < 2:
                time.sleep(2 + attempt * 2)
                continue
            print(f"Shuqi: GET {url[:80]} → {r.status_code}")
            return None
        except Exception as e:
            if attempt >= 2:
                print(f"   Shuqi GET failed {url[:70]}: {str(e)[:70]}")
                return None
            time.sleep(2)
    return None


def _shuqi_initial_state(raw):
    """فك JSON المضمّن window.__INITIAL_STATE__={...} — dict أو {}"""
    i = raw.find('__INITIAL_STATE__=')
    if i < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[i + len('__INITIAL_STATE__='):].lstrip())
        return data or {}
    except Exception as e:
        print(f"   Shuqi: INITIAL_STATE parse failed: {str(e)[:70]}")
        return {}


def _shuqi_og(raw, prop):
    """قراءة وسم og:novel:{prop} بأي ترتيب سمات"""
    m = (re.search(r'<meta[^>]*property="og:' + prop + r'"[^>]*content="([^"]*)"', raw)
         or re.search(r'<meta[^>]*content="([^"]*)"[^>]*property="og:' + prop + r'"', raw))
    return m.group(1).strip() if m else ''


def _shuqi_upgrade_cover_https(cover):
    """غلاف شوقي يُخدم http — img-tailor.11222.cn يدعم https (نقيس قبل الاعتماد)"""
    if not cover.startswith('http://'):
        return cover
    host = urlparse(cover).netloc.lower()
    if host not in _SHUQI_IMG_HTTPS_OK:
        return cover
    https_url = 'https://' + cover[len('http://'):]
    try:
        chk = _cffi.head(https_url, timeout=10, impersonate='chrome131',
                         headers={'User-Agent': _UA_PC})
        ct = (chk.headers.get('Content-Type') or '').lower()
        if chk.status_code < 400 and ct.startswith('image'):
            return https_url
    except Exception:
        pass
    return cover


def _shuqi_signed_params(params, encrypt_keys, key):
    """توقيع شوقي المؤكد من app.js:
    sign = md5(قيم مفاتيح (encryptKeys+timestamp) مرتبة مدمجة + المفتاح)"""
    e = {'timestamp': int(time.time())}
    for k in encrypt_keys:
        v = params.get(k, e.get(k))
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(',', ':'))
        e[k] = v
    joined = ''.join(str(e[k]) for k in sorted(e.keys())) + key
    out = dict(params)
    out.update(e)
    out['sign'] = hashlib.md5(joined.encode('utf-8')).hexdigest()
    return out


def _shuqi_chapterlist_api(bid):
    """واجهة فهرس شوقي: GET /reader/{bid} → commonParams → chapterlist موقّع.
    يعيد (chapters_flat, prefixes) أو ([], None)"""
    raw = _shuqi_get(f'{_SHUQI_BASE}/reader/{bid}', referer=f'{_SHUQI_BASE}/book/{bid}')
    if raw is None:
        print(f"Shuqi chapters: reader page fetch failed for {bid}")
        return [], None
    state = _shuqi_initial_state(raw)
    cp = state.get('commonParams') or {}
    params = _shuqi_signed_params({**cp, 'bookId': str(bid), 'user_id': _SHUQI_GUEST_UID},
                                  ['bookId', 'user_id'], _SHUQI_WALDEN_KEY)
    try:
        from curl_cffi import requests as _c2
        r = _c2.get(f'{_SHUQI_CONTENT_HOST}/openapi/book/chapterlist', params=params,
                    timeout=25, impersonate='chrome131',
                    headers={'User-Agent': _UA_PC, 'Referer': f'{_SHUQI_BASE}/'})
        j = r.json()
    except Exception as e:
        print(f"   Shuqi chapterlist API failed: {str(e)[:80]}")
        return [], None
    d = j.get('data') or {}
    vols = d.get('chapterList') or []
    flat = [c for v in vols for c in (v.get('volumeList') or [])]
    prefixes = {
        'free': d.get('freeContUrlPrefix') or 'https://c-100.11222.cn/openapi/chapter/contentfree/',
        'charge': d.get('chargeContUrlPrefix') or 'https://content.shuqireader.com/openapi/chapter/contentcharge/',
    }
    # توحيد بروتوكول البادئات إلى https (نسخ http بالموقع تفشل من السيرفر)
    for k in prefixes:
        prefixes[k] = re.sub(r'^http://', 'https://', prefixes[k])
    return flat, prefixes


def _shuqi_cache_store(bid, flat):
    """تخزين لاحقات محتوى الفصول (chapterId → contUrlSuffix) بحد أقصى 8 كتب"""
    with _SHUQI_LOCK:
        _SHUQI_RUNTIME['suffixes'][bid] = {
            str(c.get('chapterId')): (c.get('contUrlSuffix') or c.get('shortContUrlSuffix') or '')
            for c in flat}
        if bid in _SHUQI_RUNTIME['order']:
            _SHUQI_RUNTIME['order'].remove(bid)
        _SHUQI_RUNTIME['order'].append(bid)
        while len(_SHUQI_RUNTIME['order']) > 8:
            old = _SHUQI_RUNTIME['order'].pop(0)
            _SHUQI_RUNTIME['suffixes'].pop(old, None)


def _shuqi_suffix_for(bid, cid):
    """لاحقة contUrlSuffix لفصل معروف — من الخبيئة أو بإعادة جلب الفهرس"""
    with _SHUQI_LOCK:
        sfx = _SHUQI_RUNTIME['suffixes'].get(bid, {}).get(cid)
    if sfx:
        return sfx
    print(f"Shuqi: suffix cache miss for {bid}/{cid} — refetching chapter list")
    flat, _ = _shuqi_chapterlist_api(bid)
    if flat:
        _shuqi_cache_store(bid, flat)
        with _SHUQI_LOCK:
            sfx = _SHUQI_RUNTIME['suffixes'].get(bid, {}).get(cid)
    return sfx


def fetch_metadata_shuqi(url):
    """بيانات شوقي من وسوم og:novel:* + __INITIAL_STATE__ (وصف كامل + وسوم)"""
    try:
        bid, _cid = _shuqi_ids(url)
        book_url = f'{_SHUQI_BASE}/book/{bid}'
        raw = _shuqi_get(book_url, timeout=25)
        if raw is None:
            print(f"Shuqi metadata: page fetch failed for {bid}")
            return None
        state = _shuqi_initial_state(raw)
        info = ((state.get('cover') or {}).get('bookInfo') or {}).get('data') or {}

        title = _shuqi_og(raw, 'novel:book_name') or info.get('bookName') or ''
        if not title:
            m = re.search(r'<title>([^<]+)</title>', raw)
            title = m.group(1).split('(')[0].strip() if m else ''
        if not title:
            print(f"Shuqi metadata: no title for {bid}")
            return None
        author = _shuqi_og(raw, 'novel:author') or info.get('authorName') or ''
        category = _shuqi_og(raw, 'novel:category') or info.get('className') or ''
        status_txt = _shuqi_og(raw, 'novel:status') or ''
        status = 'مكتملة' if '完' in status_txt else 'مستمرة'
        update_time = _shuqi_og(raw, 'novel:update_time') or ''

        # الوصف الكامل من INITIAL_STATE (بأسطر \n حقيقية) وإلا og:description
        description = str(info.get('desc') or '').strip()
        if not description:
            description = _shuqi_og(raw, 'description')

        # الوسوم من مصفوفة tag
        tags = []
        for t in (info.get('tag') or [])[:6]:
            name = str(t.get('tagName') or '').strip()
            if name and name not in tags:
                tags.append(name)

        cover = _shuqi_og(raw, 'image') or info.get('imgUrl') or ''

        return {
            'title': title, 'author': author, 'description': description,
            'cover': fix_image_url(_shuqi_upgrade_cover_https(cover), base_url=_SHUQI_BASE),
            'status': status, 'category': category or 'عام', 'tags': tags,
            'sourceUrl': book_url, 'lastUpdate': (update_time or None),
        }
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error Shuqi Meta: {e}")
        return None


def fetch_chapter_list_shuqi(url):
    """فهرس شوقي عبر واجهة chapterlist الموقّعة — قوائم مجلدات مسطّحة بالترتيب"""
    try:
        bid, _ = _shuqi_ids(url)
        flat, _prefixes = _shuqi_chapterlist_api(bid)
        if not flat:
            print(f"Shuqi chapters: no chapters returned for {bid}")
            return []
        _shuqi_cache_store(bid, flat)
        chapters = []
        for idx, c in enumerate(flat, start=1):
            cid = str(c.get('chapterId') or '')
            if not cid:
                continue
            title = re.sub(r'\s+', ' ', str(c.get('chapterName') or '')).strip()
            if not title:
                title = f'第{idx}章'
            chapters.append({'number': len(chapters) + 1,
                             'url': f'{_SHUQI_BASE}/reader/{bid}?chapterId={cid}',
                             'title': title})
        print(f"Shuqi: {len(chapters)} chapters for book {bid} "
              f"(مدفوعة: {sum(1 for c in flat if str(c.get('payStatus')) != '0')})")
        return chapters
    except ValueError as e:
        print(str(e))
        return []
    except Exception as e:
        print(f"Error Shuqi Chapters: {e}")
        return []


def _shuqi_decode_content(enc):
    """فك تشويش محتوى شوقي (مؤكد من app.js): rot13 ← base64 ← نص UTF-8"""
    if not enc:
        return ''
    rot = codecs.encode(enc, 'rot13')
    return base64.b64decode(rot + '===').decode('utf-8', errors='replace')


def scrape_chapter_shuqi(url):
    """محتوى فصل شوقي: رابط موقّع contentfree + فك rot13/base64 + تقسيم <br>"""
    try:
        bid, cid = _shuqi_ids(url)
        if not cid:
            print(f"Shuqi: ليس رابط فصل: {url}")
            return None
        suffix = _shuqi_suffix_for(bid, cid)
        if not suffix:
            print(f"Shuqi: no content suffix for {bid}/{cid} — تخطٍّ صادق")
            return None
        api_url = f'{_SHUQI_CONTENT_HOST}/openapi/chapter/contentfree/{suffix}'
        raw = _shuqi_get(api_url, referer=f'{_SHUQI_BASE}/reader/{bid}')
        if raw is None:
            print(f"Shuqi: content API fetch failed {bid}/{cid}")
            return None
        try:
            j = json.loads(raw)
        except Exception:
            print(f"Shuqi: content API non-JSON for {bid}/{cid}")
            return None
        enc = j.get('ChapterContent')
        if str(j.get('state')) != '200' or not enc:
            print(f"Shuqi: chapter {cid} rejected by API "
                  f"(state={j.get('state')}, msg={j.get('message')}) — تخطٍّ صادق")
            return None
        text = _shuqi_decode_content(enc)
        # فصل الأسطر: <br> فواصل + إزاحة مسافات جانبية كاملة
        text = re.sub(r'(?i)<br\s*/?>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        lines = []
        for line in text.split('\n'):
            l = line.strip().strip('\u3000').strip()
            if l:
                lines.append(l)
        out = clean_text('\n'.join(lines))
        if len(re.sub(r'\s', '', out)) < 100:
            print(f"Shuqi: chapter {cid} content too short ({len(out)} chars)")
            return None
        return out
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error Shuqi Chapter: {e}")
        return None


def worker_shuqi(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_shuqi, scrape_chapter_shuqi,
                   site_name='Shuqi')


# ==========================================
# 🟥 3) UUREAD uu看書 (www.uuread.tw)
# ==========================================

_UU_BASE = 'https://www.uuread.tw'
# الموقع يحجب بصمة Chrome (403) — Firefox يعمل مباشرة (مؤكد بالفحص)
_UU_IMPERSONATE = 'firefox133'


def _uu_ids(url):
    """تحليل رابط uuread: كتاب /{id} أو فصل /chapter/{id}/{cid}[_N].html"""
    p = urlparse(url)
    host = p.netloc.lower()
    if 'uuread.tw' not in host:
        raise ValueError('UUread: استخدم رابطاً على uuread.tw فقط.')
    path = p.path or ''
    m = re.search(r'/chapter/(\d+)/(\d+)(?:_(\d+))?\.html', path)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r'/(?:book/)?(\d{3,})(?:\.html)?/?$', path)
    if m:
        return m.group(1), None
    raise ValueError('UUread: الرابط المدعوم https://www.uuread.tw/{book_id} '
                     'أو رابط فصل https://www.uuread.tw/chapter/{book_id}/{chapter_id}.html.')


def _uu_get(url, referer=None, timeout=30, validate=None):
    """جالب uuread عبر _cjk_get (بصمة Firefox مباشرة + توجيه ذكي عند الحجب)"""
    headers = {'User-Agent': _UA_FF}
    if referer:
        headers['Referer'] = referer
    return _cjk_get(url, referer=referer, timeout=timeout, validate=validate,
                    extra_headers=headers)


def _uu_og(raw, prop):
    """قراءة وسم og:novel:{prop} بأي ترتيب سمات"""
    m = (re.search(r'<meta[^>]*property="og:' + prop + r'"[^>]*content="([^"]*)"', raw)
         or re.search(r'<meta[^>]*content="([^"]*)"[^>]*property="og:' + prop + r'"', raw))
    return m.group(1).strip() if m else ''


def fetch_metadata_uuread(url):
    """بيانات uu看書 من og:novel:* + div#bookintro (كيانات BR تُحوَّل لأسطر)"""
    try:
        bid, _cid = _uu_ids(url)
        book_url = f'{_UU_BASE}/{bid}'
        r = _uu_get(book_url, timeout=30, validate=lambda t: 'og:novel' in t or 'bookintro' in t)
        if r is None:
            print(f"UUread metadata: page fetch failed for {bid}")
            return None
        raw = r.text

        title = _uu_og(raw, 'novel:book_name') or _uu_og(raw, 'title') or ''
        if not title:
            m = re.search(r'<title>([^<]+)</title>', raw)
            title = m.group(1).split('(')[0].strip() if m else ''
        if not title:
            print(f"UUread metadata: no title for {bid}")
            return None
        author = _uu_og(raw, 'novel:author') or ''
        category = _uu_og(raw, 'novel:category') or ''
        status_txt = _uu_og(raw, 'novel:status') or ''
        status = 'مكتملة' if '完' in status_txt else 'مستمرة'
        update_time = _uu_og(raw, 'novel:update_time') or ''

        # الوصف من div#bookintro — كيانات &lt;BR/&gt; → أسطر (مبتور من الموقع نفسه)
        import html as _html
        description = ''
        m = re.search(r'<div[^>]*id="bookintro"[^>]*>(.*?)</div>', raw, re.S)
        if m:
            description = m.group(1).strip()
            description = _html.unescape(description)
            description = re.sub(r'(?i)<br\s*/?>', '\n', description)
            description = re.sub(r'<[^>]+>', '', description).strip()
        if not description:
            description = _uu_og(raw, 'description')

        # الغلاف من og:image أو أول صورة غلاف بالصفحة
        cover = _uu_og(raw, 'image') or ''
        if not cover:
            m = re.search(r'<img[^>]*src="([^"]*/images/\d+/[^"]+\.jpg)"', raw)
            if m:
                cover = urljoin(book_url, m.group(1))

        return {
            'title': title, 'author': author, 'description': description,
            'cover': fix_image_url(cover, base_url=_UU_BASE),
            'status': status, 'category': category or 'عام', 'tags': [],
            'sourceUrl': book_url, 'lastUpdate': (update_time or None),
        }
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error UUread Meta: {e}")
        return None


def fetch_chapter_list_uuread(url):
    """فهرس uu看書 من div#newlist بصفحة الكتاب — روابط مرتبة بلا تكرار"""
    try:
        bid, _ = _uu_ids(url)
        book_url = f'{_UU_BASE}/{bid}'
        r = _uu_get(book_url, timeout=30,
                    validate=lambda t: 'newlist' in t or f'/chapter/{bid}/' in t)
        if r is None:
            print(f"UUread chapters: book page fetch failed for {bid}")
            return []
        raw = r.text

        # قصّ المقطع من بداية قائمة الفصول حتى قسم التوصيات (إن وجد)
        i = raw.find('id="newlist"')
        seg = raw[i:] if i >= 0 else raw
        for stop_mark in ('newzjlist', '相關推薦', '相关推荐'):
            j = seg.find(stop_mark)
            if j >= 0:
                seg = seg[:j]

        chapters = []
        seen = set()
        for m in re.finditer(
                r'<a[^>]*href="(?:https?://www\.uuread\.tw)?(/chapter/' + bid + r'/(\d+)\.html)"'
                r'[^>]*title="([^"]*)"', seg):
            cid, title = m.group(2), m.group(3).strip()
            if cid in seen:
                continue
            seen.add(cid)
            title = re.sub(r'\s+', ' ', _clean_uu_title(title))
            chapters.append({'number': len(chapters) + 1,
                             'url': f'{_UU_BASE}/chapter/{bid}/{cid}.html',
                             'title': title})
        print(f"UUread: {len(chapters)} chapters for book {bid}")
        return chapters
    except ValueError as e:
        print(str(e))
        return []
    except Exception as e:
        print(f"Error UUread Chapters: {e}")
        return []


def _clean_uu_title(title):
    """عنوان فصل uuread قد يأتي بكيانات HTML — تنظيف بسيط"""
    import html as _html
    return _html.unescape(title or '')


def _uu_extract_page(raw):
    """استخراج فقرات div#nr من صفحة فصل — قائمة نصوص أو None إن لم تُوجد الحاوية"""
    m = re.search(r'<div[^>]*id="nr"[^>]*>(.*?)</div>', raw, re.S)
    if not m:
        return None
    paras = []
    for p in re.findall(r'<p[^>]*>(.*?)</p>', m.group(1), re.S):
        t = re.sub(r'<[^>]+>', '', p).strip()
        if t:
            paras.append(t)
    if not paras:
        # بعض الصفحات قد تضع نصاً مباشرة بلا <p>
        t = re.sub(r'(?i)<br\s*/?>', '\n', m.group(1))
        t = re.sub(r'<[^>]+>', '', t).strip()
        paras = [x.strip() for x in t.split('\n') if x.strip()]
    return paras


def scrape_chapter_uuread(url):
    """محتوى فصل uuread + متابعة صفحات التقسيم {cid}_2.html… حتى نفادها"""
    try:
        bid, cid = _uu_ids(url)
        if not cid:
            print(f"UUread: ليس رابط فصل: {url}")
            return None
        all_paras = []
        page_url = f'{_UU_BASE}/chapter/{bid}/{cid}.html'
        page = 1
        while page_url and page <= 30:   # سقف أمان لعدد الصفحات
            r = _uu_get(page_url, referer=f'{_UU_BASE}/{bid}',
                        validate=lambda t: 'id="nr"' in t or 'txt_tcontent' in t)
            if r is None:
                print(f"UUread: chapter page fetch failed {page_url}")
                return None
            raw = r.text
            paras = _uu_extract_page(raw)
            if paras is None:
                if not all_paras:
                    print(f"UUread: div#nr not found — template changed? {page_url}")
                    return None
                break
            all_paras.extend(paras)
            # هل توجد «صفحة تالية» لنفس الفصل؟ {cid}_{page+1}.html
            nxt = f'/chapter/{bid}/{cid}_{page + 1}.html'
            page_url = (f'{_UU_BASE}{nxt}' if f'href="{nxt}"' in raw else None)
            page += 1
            if page_url:
                time.sleep(0.4)
        text = '\n'.join(all_paras)
        out = clean_text(text)
        if len(re.sub(r'\s', '', out)) < 100:
            print(f"UUread: chapter {cid} content too short ({len(out)} chars)")
            return None
        return out
    except ValueError as e:
        print(str(e))
        return None
    except Exception as e:
        print(f"Error UUread Chapter: {e}")
        return None


def worker_uuread(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata,
                   fetch_chapter_list_uuread, scrape_chapter_uuread,
                   site_name='UUread')


# ==========================================
# 📚 التسجيل في السجل العام
# ==========================================
register_site(
    domain_patterns=['85novel.com', 'www.85novel.com'],
    name='85Novel (85小說網)',
    language='chinese',
    fetch_metadata=fetch_metadata_85novel,
    fetch_chapters=fetch_chapter_list_85novel,
    fetch_content=scrape_chapter_85novel,
    worker=worker_85novel,
    status='active',
    notes='جديد (v3.3)! صينية تقليدية — فهرس عبر واجهة POST داخلية (جلسة + _xsrf + '
          'دفعات 200 فصل بـ action=auth/chapters) + محتوى data-chapter-content مع '
          'استعادة ترتيب الفقرات المشوَّشة (restoreSplitChapterItems من common.js '
          'منفَّذة بايثونيًا) + غلاف /cover/{id}.jpg. بلا كوكيز.'
)


register_site(
    domain_patterns=['t.shuqi.com', 'shuqi.com', 'www.shuqi.com'],
    name='Shuqi (书旗小说)',
    language='chinese',
    fetch_metadata=fetch_metadata_shuqi,
    fetch_chapters=fetch_chapter_list_shuqi,
    fetch_content=scrape_chapter_shuqi,
    worker=worker_shuqi,
    status='active',
    notes='جديد (v3.3)! منصة علي بابا — بيانات من og:novel:* و __INITIAL_STATE__ '
          '(وصف كامل + وسوم) + فهرس عبر واجهة content.shuqireader.com الموقّعة md5 '
          '(توقيع مفاتيح مرتبة + مفتاح walden، توكن ضيف مضمّن) + محتوى بروابط موقّعة '
          'جاهزة تُفكّ بـ rot13→base64 (مؤكد من app.js). الفصول المدفوعة تعيد نصها '
          'الكامل بلاحقة contentfree الموقعة (مؤكد بالفحص). بلا كوكيز.'
)


register_site(
    domain_patterns=['uuread.tw', 'www.uuread.tw', 'm.uuread.tw'],
    name='UUread (uu看書)',
    language='chinese',
    fetch_metadata=fetch_metadata_uuread,
    fetch_chapters=fetch_chapter_list_uuread,
    fetch_content=scrape_chapter_uuread,
    worker=worker_uuread,
    status='active',
    notes='جديد (v3.3)! صينية تقليدية — يحجب بصمة Chrome (403) فالجالب ببصمة Firefox. '
          'بيانات og:novel:* + #bookintro + فهرس كامل div#newlist + محتوى div#nr مع '
          'متابعة صفحات التقسيم {cid}_N.html. بلا كوكيز.'
)
