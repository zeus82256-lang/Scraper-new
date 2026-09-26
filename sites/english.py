# -*- coding: utf-8 -*-
"""
==========================================
🟦 المواقع الإنجليزية (English Novel Sites)
==========================================
المواقع المسجلة في هذا الملف:
1.  Novel Fire       - novelfire.net                 ✅ يعمل
2.  NovelMTL         - novelmtl.com                  ✅ يعمل (منصة MTLNation الجديدة)
3.  FanMTL           - fanmtl.com                    ✅ (نفس منصة NovelMTL + قالب قديم)
4.  WuxiaWorld.Site  - wuxiaworld.site               ✅ يعمل (قالب Madara)
5.  WuxiaBox/Spot    - wuxiabox.com / wuxiaspot.com  ⚠️ يعمل (محجوب عن IP السيرفرات فقط)
6.  FreeWebNovel     - freewebnovel.com              ✅ عبر SCRAPERAPI_KEY (v2.4: قالب جديد + ترقيم ?page=N)
7.  Royal Road       - royalroad.com                 ⚠️ يعمل (محجوب عن IP السيرفرات فقط)
8.  Scribble Hub     - scribblehub.com               ⚠️ يعمل (محجوب عن IP السيرفرات فقط)
9.  NovelBin         - novelbin.net                  ⚠️ يعمل (حماية JS تُحل تلقائياً)
10. LNMTL            - lnmtl.com                     ✅ يعمل
"""

import re
import time
import json
import requests
from urllib.parse import urljoin, urlparse

from core.registry import register_site
from core.utils import (
    http_get, smart_get, parse_html, get_headers, get_base_url, fix_image_url,
    parse_relative_date, extract_chapter_number, clean_text, get_meta,
    UA_CHROME, UA_FIREFOX, UA_MOBILE,
    madara_fetch_metadata, madara_worker,
    generic_worker,
)


# ==========================================
# 🔵 1. Novel Fire (novelfire.net)
# ==========================================

def fetch_metadata_novelfire(url):
    try:
        response = http_get(url, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('h1.novel-title')
        if not title_tag:
            meta_title = soup.find("meta", property="og:title")
            title = meta_title["content"] if meta_title else "Unknown Title"
        else:
            title = title_tag.get_text(strip=True)
        title = title.replace(' - Novel Fire', '').strip()

        cover = ""
        img_tag = soup.select_one('figure.cover img')
        if img_tag:
            cover = img_tag.get('src')
        if not cover:
            og_img = soup.find("meta", property="og:image")
            if og_img:
                cover = og_img["content"]
        cover = fix_image_url(cover, base_url='https://novelfire.net')

        desc_div = soup.select_one('.summary .content')
        if not desc_div:
            desc_div = soup.find('div', class_='description') or soup.find('div', id='novel-summary')
        description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""

        tags = []
        genre_links = soup.select('.categories ul li a')
        if not genre_links:
            genre_links = soup.select('.novel-genres a')
        for link in genre_links:
            tags.append(link.get_text(strip=True))
        category = tags[0] if tags else "عام"

        status = "مستمرة"
        completed_tag = soup.find('strong', class_='completed')
        if completed_tag and 'Completed' in completed_tag.get_text(strip=True):
            status = "مكتملة"

        # تاريخ آخر تحديث: من أول فصل في قائمة الفصول (datetime attribute)
        last_update = None
        update_node = soup.select_one('.chapter-latest-container .update')
        if update_node:
            last_update = parse_relative_date(update_node.get_text(strip=True))
        if not last_update:
            time_tag = soup.select_one('time.chapter-update[datetime]')
            if time_tag and time_tag.get('datetime'):
                last_update = parse_relative_date(time_tag['datetime'])

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags, 'sourceUrl': url,
            'lastUpdate': last_update
        }
    except Exception as e:
        print(f"Error NovelFire Meta: {e}")
        return None


def fetch_chapter_list_novelfire(url):
    """سحب جميع الفصول من NovelFire مع دعم التنقل بين الصفحات (Pagination)"""
    chapters = []
    if not url.rstrip('/').endswith('/chapters'):
        list_url = url.rstrip('/') + '/chapters'
    else:
        list_url = url

    try:
        current_page = 1

        while True:
            page_url = f"{list_url}?page={current_page}"
            print(f"🔍 Fetching chapters from NovelFire Page: {current_page}")

            res = http_get(page_url, timeout=15)
            if res is None or res.status_code != 200:
                break

            soup = parse_html(res)

            items = soup.select('ul.chapter-list li')
            if not items:
                break

            for item in items:
                a = item.find('a')
                if not a:
                    continue
                href = a.get('href', '')
                link = 'https://novelfire.net' + href if href.startswith('/') else href

                # ✅ تحسين: استخراج العنوان النظيف من strong.chapter-title
                title_el = a.select_one('strong.chapter-title') or a.select_one('.chapter-title')
                if title_el:
                    raw_title = title_el.get_text(strip=True)
                else:
                    raw_title = a.get('title') or a.get_text(strip=True)
                    # إزالة التاريخ من نهاية النص كحل بديل
                    raw_title = re.sub(r'\s*\d+\s*(?:second|min|minute|hour|day|week|month|year)s?\s*ago\s*$', '', raw_title, flags=re.IGNORECASE)
                    raw_title = re.sub(r'^\d+\s*', '', raw_title)

                num_el = a.select_one('.chapter-no')
                number = 0
                if num_el:
                    try:
                        number = int(num_el.get_text(strip=True))
                    except ValueError:
                        number = 0
                if number == 0:
                    num_match = re.search(r'chapter-(\d+)', link)
                    if not num_match:
                        num_match = re.search(r'(\d+)', raw_title)
                    number = int(num_match.group(1)) if num_match else 0

                if number > 0:
                    chapters.append({'number': number, 'url': link, 'title': raw_title})

            # التحقق من وجود صفحة تالية
            next_btn = soup.select_one('li.page-item a[rel="next"]')
            if next_btn:
                current_page += 1
                time.sleep(0.5)
            else:
                break

        # إزالة التكرار وترتيب الفصول
        chapters = list({c['number']: c for c in chapters}.values())
        chapters.sort(key=lambda x: x['number'])
        print(f"✅ Total chapters found across all pages: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error list NovelFire with pagination: {e}")
        return []


def scrape_chapter_novelfire(url):
    try:
        res = http_get(url, timeout=15)
        if res is None or res.status_code != 200:
            return None
        soup = parse_html(res)

        container = soup.find('div', id='content') or soup.find('div', class_='chapter-content')
        if container:
            for bad in container.find_all(['div', 'script', 'style', 'ins', 'button']):
                if bad.get('class') and ('ads' in str(bad.get('class'))):
                    bad.decompose()

            text = container.get_text(separator="\n\n", strip=True)
            text = re.sub(r'Read.*online.*now!', '', text)
            text = clean_text(text)
            return text or None
        return None
    except Exception:
        return None


def worker_novelfire(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_novelfire, scrape_chapter_novelfire)


# ==========================================
# 🟪 2. NovelMTL (novelmtl.com - منصة MTLNation)
# ==========================================
# novelmtl.com يعمل مباشرة بالتصميم الجديد (Quasar).

MTLNATION_SITES = {
    'novelmtl.com': 'https://www.novelmtl.com',
}


def _mtlnation_base(url):
    for domain, base in MTLNATION_SITES.items():
        if domain in url:
            return base
    return 'https://www.novelmtl.com'


def fetch_metadata_mtlnation(url):
    try:
        base = _mtlnation_base(url)
        response = http_get(url, timeout=20)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        # العنوان: og:title هو الأدق في تصميم Quasar الجديد
        title = get_meta(soup, prop='og:title') or ""
        if not title:
            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else "Unknown Title"
        title = re.sub(r'\s*[-–|]\s*(Novel|FanMTL|NovelMTL).*$', '', title, flags=re.IGNORECASE).strip()

        # الغلاف: أول صورة كبيرة في صفحة الرواية وإلا og:image
        cover = ""
        img_candidates = soup.select('img[src*="cover"], .novel-thumbnail img, .q-avatar img')
        if img_candidates:
            cover = img_candidates[0].get('src') or ""
        if not cover:
            cover = get_meta(soup, prop='og:image')
        cover = fix_image_url(cover, base_url=base)

        # الوصف من meta description (موجود دائماً في القالب الجديد)
        description = get_meta(soup, name='description')
        if not description:
            og_desc = get_meta(soup, prop='og:description')
            description = og_desc

        # التصنيفات من شرائح المؤلف/النوع
        tags = []
        for el in soup.select('.chip-author, .chip-genre'):
            txt = el.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        # الحالة (مكتملة/مستمرة) من نص الصفحة
        status = "مستمرة"
        page_text = soup.get_text()[:6000]
        if re.search(r'\bcompleted\b', page_text, re.IGNORECASE):
            status = "مكتملة"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error MTLNation Meta: {e}")
        return None


def fetch_chapter_list_mtlnation(url):
    """
    قائمة صفحات القراءة من الأزرار المرقمة في صفحة الرواية:
    /read/1, /read/2 ... (كل رقم = فصل/صفحة، وتحتاج ?cont=1 للفتح)
    """
    chapters = []
    try:
        base = _mtlnation_base(url)
        response = http_get(url, timeout=20)
        if response is None or response.status_code != 200:
            return []
        soup = parse_html(response)

        slug_match = re.search(r'/novel/([^/?#]+)', url)
        slug = slug_match.group(1) if slug_match else ''

        page_numbers = set()
        for a in soup.find_all('a', href=True):
            m = re.search(rf'/novel/{re.escape(slug)}/read/(\d+)', a['href'])
            if m:
                # تجاهل روابط الاستكمال cont (تخص نفس الرقم)
                if 'cont=' in a['href']:
                    continue
                page_numbers.add(int(m.group(1)))

        for number in sorted(page_numbers):
            # ✅ كل صفحة تحتاج ?cont=1 لعرض المحتوى (بدونها 404)
            full_link = f"{base}/novel/{slug}/read/{number}?cont=1"
            chapters.append({'number': number, 'url': full_link, 'title': f"Chapter {number}"})

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ Total MTLNation pages found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error MTLNation List: {e}")
        return []


def scrape_chapter_mtlnation(url):
    """سحب محتوى صفحة قراءة MTLNation مع تنظيف أدوات الواجهة"""
    try:
        res = http_get(url, timeout=20)
        if res is None or res.status_code != 200:
            return None
        soup = parse_html(res)

        app_div = soup.find(id='q-app')
        if not app_div:
            app_div = soup.find('body')
        if not app_div:
            return None

        # إزالة عناصر الواجهة (الترويسة والتذييل والأزرار والقوائم)
        for junk in app_div.find_all(['header', 'footer', 'nav', 'script', 'style']):
            junk.decompose()
        for cls in ['app-header', 'app-footer', 'q-header', 'q-footer', 'q-drawer',
                    'fixed-bottom', 'fixed-top', 'q-btn', 'q-toolbar', 'q-pagination']:
            for el in app_div.find_all(class_=cls):
                el.decompose()

        text = app_div.get_text(separator="\n\n", strip=True)

        # إزالة نصوص أدوات القارئ من البداية (18px / Page N / أزرار القارئ)
        text = re.sub(r'^.*?Page\s+\d+\s*', '', text, count=1, flags=re.DOTALL)
        text = re.sub(r'\b(arrow_back|zoom_out|zoom_in|18px)\b', '', text)
        text = clean_text(text)

        return text if len(text) > 50 else None
    except Exception:
        return None


def worker_mtlnation(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_mtlnation, scrape_chapter_mtlnation)


# ==========================================
# 🟪 3. قالب EmpireCMS المشترك (FanMTL + WuxiaBox)
# ==========================================
# ⚠️ تحديث مهم (2025): fanmtl.com و wuxiabox.com يعملان بنفس القالب
# (Empire CMS) الذي ظهر في HTML الموقع الحالي:
#   - صفحة الرواية: /novel/{slug}.html تحتوي ul.chapter-list
#   - كل صفحة تعرض 100 فصل، والباقي عبر ترقيم AJAX:
#     /e/extend/fy.php?page={N}&wjm={slug}   (N يبدأ من 0)
#   - روابط الفصول: /novel/{slug}_{N}.html
#   - محتوى الفصل داخل div.chapter-content
# ⚠️ الموقعان يحجبان IP مراكز البيانات (403 Cloudflare) → نستخدم smart_get
# الذي ينتقل تلقائياً لبروكسي ترجمة جوجل عند الحجب.

EMPIRECMS_SITES = {
    'fanmtl.com': 'https://fanmtl.com',
    'wuxiabox.com': 'https://wuxiabox.com',
    'wuxiaspot.com': 'https://wuxiaspot.com',
}


def _empire_base(url):
    for domain, base in EMPIRECMS_SITES.items():
        if domain in url:
            return base
    return 'https://fanmtl.com'


def _empire_slug(url):
    m = re.search(r'/novel/([^/?#]+?)\.html', url)
    if m:
        slug = m.group(1)
    else:
        m = re.search(r'/novel/([^/?#_]+)', url)
        slug = m.group(1) if m else ''
    # إزالة لاحقة الفصل (_5) إن وُجدت
    slug = re.sub(r'_\d+$', '', slug)
    return slug


def _empire_parse_chapter_list(soup, base):
    """تحليل ul.chapter-list (روابط الفصول + الأرقام + العناوين + التواريخ)"""
    chapters = []
    for a in soup.select('ul.chapter-list li a'):
        href = a.get('href') or ''
        if not href:
            continue
        full_link = urljoin(base, href)
        raw_title = a.get('title') or a.get_text(' ', strip=True)

        number = 0
        chapter_no = a.select_one('.chapter-no')
        if chapter_no:
            try:
                number = int(chapter_no.get_text(strip=True))
            except ValueError:
                number = 0
        if number == 0:
            m = re.search(r'_([\d]+)\.html', full_link)
            if m:
                number = int(m.group(1))
        if number == 0:
            number = extract_chapter_number(raw_title, full_link)

        title_node = a.select_one('.chapter-title')
        chapter_title = title_node.get_text(strip=True) if title_node else raw_title

        if number > 0:
            chapters.append({'number': number, 'url': full_link, 'title': chapter_title})
    return chapters


def _empire_fetch_chapters(url, max_pages=300):
    """جلب كل الفصول: الصفحة الأولى من صفحة الرواية ثم ترقيم fy.php حتى النهاية"""
    chapters = []
    try:
        base = _empire_base(url)
        slug = _empire_slug(url)
        if not slug:
            print(f"EmpireCMS: cannot extract slug from {url}")
            return []

        response = smart_get(url, timeout=30)
        if response is None or response.status_code != 200:
            print(f"EmpireCMS: novel page failed ({getattr(response, 'status_code', 'None')})")
            return []
        soup = parse_html(response)
        chapters.extend(_empire_parse_chapter_list(soup, base))

        # اكتشاف عدد صفحات الترقيم من رابط ">>" (آخر صفحة)
        last_page = 0
        for a in soup.select('.pagination a, .pagination-container a'):
            href = a.get('href') or ''
            m = re.search(r'/e/extend/fy\.php\?page=(\d+)', href)
            if m:
                last_page = max(last_page, int(m.group(1)))

        print(f"EmpireCMS ({slug}): {len(chapters)} chapters on page 1, last AJAX page={last_page}")

        # جلب بقية الصفحات (ترقيم يبدأ من 0 = الصفحة الأولى)
        for page in range(0, last_page + 1):
            if page == 0 and chapters:
                continue  # الصفحة الأولى جُلبت من صفحة الرواية نفسها
            ajax_url = f"{base}/e/extend/fy.php?page={page}&wjm={slug}"
            resp = smart_get(ajax_url, timeout=30)
            if resp is None or resp.status_code != 200:
                print(f"EmpireCMS: AJAX page {page} failed, stopping.")
                break
            page_soup = parse_html(resp)
            found = _empire_parse_chapter_list(page_soup, base)
            if not found:
                break
            chapters.extend(found)
            time.sleep(0.6)
            if len(chapters) > 20000:
                break

        # إزالة التكرار (الموقع يعرض نفس الرقم بصيغتين 001 و 1) + ترتيب
        dedup = {}
        for c in chapters:
            if c['number'] not in dedup or len(c['url']) > len(dedup[c['number']]['url']):
                dedup[c['number']] = c
        chapters = sorted(dedup.values(), key=lambda x: x['number'])
        print(f"✅ Total EmpireCMS chapters ({slug}): {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error EmpireCMS List: {e}")
        return []


def _empire_scrape_content(url):
    """سحب محتوى فصل من div.chapter-content مع تنظيف الإعلانات وأدوات القارئ"""
    try:
        response = smart_get(url, timeout=30, referer=_empire_base(url) + '/')
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.select_one('div.chapter-content') or soup.select_one('article#chapter-article')
        if not content_div:
            return None

        # إزالة الإعلانات والعناصر غير النصية
        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe', 'button', 'input']):
            bad.decompose()
        for div in content_div.find_all('div'):
            cls = ' '.join(div.get('class') or [])
            _id = div.get('id') or ''
            # إعلانات PubFuture/القوائم العائمة وأدوات القارئ
            if ('PUBFUTURE' in cls or 'pf-' in _id or 'TPuhiHlg' in cls
                    or 'chapternav' in cls or 'guide-message' in cls
                    or div.find(['script', 'iframe'])):
                div.decompose()

        text = content_div.get_text(separator="\n\n", strip=True)

        # تنظيف بقايا HTML المفسّرة داخل النص مثل: <  p idx="6">
        text = re.sub(r'&lt;\s*p[^&]*&gt;', '', text)
        text = re.sub(r'<\s*p\s+idx="\d+"\s*>', '', text)
        # تنظيف أسطر الملاحة/الإعلانات
        text = re.sub(r'(Previous\s*Chapter\s*\|\s*Next\s*Chapter)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Tip:\s*You can use left and right keyboard keys.*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Tap the screen to use advanced tools', '', text, flags=re.IGNORECASE)
        text = clean_text(text)
        return text if len(text) > 50 else None
    except Exception:
        return None


def fetch_metadata_fanmtl(url):
    """بيانات الرواية من تصميم EmpireCMS الحالي (h1.novel-title و header-stats)"""
    try:
        base = _empire_base(url)
        response = smart_get(url, timeout=30)
        if response is None or response.status_code != 200:
            print(f"FanMTL metadata: page fetch failed ({getattr(response, 'status_code', 'None')})")
            return None
        soup = parse_html(response)

        # العنوان
        title = ""
        h1 = soup.select_one('h1.novel-title') or soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            title = get_meta(soup, name='description') or "Unknown Title"
        title = re.sub(r'\s*Novel\s*Read\s*Online.*$', '', title, flags=re.IGNORECASE).strip()

        # العنوان الأصلي (صيني) كوسم إضافي
        tags = []
        alt = soup.select_one('h2.alternative-title')
        if alt and alt.get_text(strip=True):
            tags.append(alt.get_text(strip=True))

        # الغلاف
        cover = ""
        img = soup.select_one('figure.cover img') or soup.select_one('.fixed-img img')
        if img:
            cover = img.get('data-src') or img.get('src') or ''
        if not cover:
            cover = get_meta(soup, prop='og:image')
        cover = fix_image_url(cover, base_url=base)

        # الوصف
        description = ""
        summary_div = soup.select_one('section#info div.summary div.content') or soup.select_one('div.summary .content')
        if summary_div:
            description = summary_div.get_text(separator="\n\n", strip=True)
        if not description:
            description = get_meta(soup, name='description') or ''

        # الحالة وعدد الفصول من header-stats
        status = "مستمرة"
        for strong in soup.select('.header-stats strong'):
            txt = strong.get_text(strip=True).lower()
            if 'completed' in txt or 'complete' in txt:
                status = "مكتملة"
                break

        # التصنيفات
        category = "عام"
        cat_links = soup.select('.categories a.property-item')
        if cat_links:
            category = cat_links[0].get_text(strip=True)
            for c in cat_links:
                t = c.get_text(strip=True)
                if t and t not in tags:
                    tags.append(t)

        # آخر تحديث من تاريخ أول فصل
        last_update = None
        first_time = soup.select_one('ul.chapter-list time.chapter-update')
        if first_time:
            last_update = parse_relative_date(first_time.get_text(strip=True))

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'sourceUrl': url, 'lastUpdate': last_update
        }
    except Exception as e:
        print(f"Error FanMTL Meta: {e}")
        return None


def worker_fanmtl(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, _empire_fetch_chapters, _empire_scrape_content)


def fetch_chapter_list_fanmtl(url):
    return _empire_fetch_chapters(url)


def scrape_chapter_fanmtl(url):
    return _empire_scrape_content(url)


# --- WuxiaBox: نفس قالب EmpireCMS بالضبط (novel_{N}.html + fy.php) ---

def _normalize_wuxiabox_url(url):
    """الروابط القديمة بدون .html أصبحت غير صالحة — نضيفها تلقائياً"""
    if re.search(r'/novel/[^/]+$', url):
        if not url.endswith('.html'):
            url = url.rstrip('/') + '.html'
    return url


def fetch_metadata_wuxiabox(url):
    url = _normalize_wuxiabox_url(url)
    meta = fetch_metadata_fanmtl(url)
    if meta:
        meta['sourceUrl'] = url
    return meta


def fetch_chapter_list_wuxiabox(url):
    return _empire_fetch_chapters(_normalize_wuxiabox_url(url))


def scrape_chapter_wuxiabox(url):
    return _empire_scrape_content(url)


def worker_wuxiabox(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_wuxiabox, scrape_chapter_wuxiabox)


# ==========================================
# 🟫 4. WuxiaWorld (wuxiaworld.site) - قالب Madara
# ==========================================
# الموقع الرسمي wuxiaworld.com تطبيق SPA بحماية gRPC ولا يمكن سحبه،
# لذا نستخدم المرآة الرسمية القديمة wuxiaworld.site (نفس المحتوى).

def fetch_metadata_wuxiaworld(url):
    return madara_fetch_metadata(url, use_cookies=False)


def worker_wuxiaworld(url, admin_email, metadata):
    madara_worker(url, admin_email, metadata, use_cookies=False)


# ==========================================
# 🔴 6. FreeWebNovel (freewebnovel.com)
# ==========================================
# ⚠️ الموقع يحجب IP مراكز البيانات (403) — نستخدم smart_get
# (مباشر ثم بروكسي ترجمة جوجل تلقائياً)

def fetch_metadata_freewebnovel(url):
    try:
        response = smart_get(url, timeout=25)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.find("meta", property="og:title")
        title = title_tag["content"] if title_tag else ""
        tit = soup.select_one('h1.tit')
        if not title and tit:
            title = tit.get_text(strip=True)
        title = (title or "Unknown Title").split(' - ')[0].strip()

        cover_tag = soup.find("meta", property="og:image")
        cover = cover_tag["content"] if cover_tag else ""

        desc_div = soup.select_one('.m-desc .txt .inner')
        if desc_div:
            description = desc_div.get_text(separator="\n\n", strip=True)
        else:
            desc_meta = soup.find("meta", property="og:description")
            description = desc_meta["content"] if desc_meta else ""

        status = "مستمرة"
        status_node = soup.select_one('.m-imgtxt .item span.s3 a')
        if status_node and 'Completed' in status_node.get_text():
            status = "مكتملة"

        tags = []
        genre_links = soup.select('.m-imgtxt .item a[href*="genre"]')
        for link in genre_links:
            tags.append(link.get_text(strip=True))
        category = tags[0] if tags else "عام"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags, 'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error Freewebnovel Meta: {e}")
        return None


def fetch_chapter_list_freewebnovel(url):
    """قائمة الفصول مع الترقيم الجديد للموقع:
    الصفحة الأولى تعرض دفعة فقط (30-40) والباقي عبر ?page=N
    (عدد الصفحات من خيارات #indexselect)"""
    chapters = []
    try:
        base_list_url = url.split('?')[0]
        seen = set()
        page = 1
        while page <= 400:  # شبكة أمان ضد الحلقات اللانهائية
            list_url = base_list_url if page == 1 else f"{base_list_url}?page={page}"
            response = smart_get(list_url, timeout=25)
            if response is None or response.status_code != 200:
                break
            soup = parse_html(response)

            new = 0
            items = soup.select('ul#idData li a')
            for a in items:
                href = a.get('href')
                if not href:
                    continue
                full_link = urljoin('https://freewebnovel.com', href)
                title = a.get('title') or a.get_text(strip=True)

                match = re.search(r'Chapter\s+(\d+)', title, re.IGNORECASE)
                if match:
                    num = int(match.group(1))
                    if num in seen:
                        continue
                    seen.add(num)
                    chapters.append({'number': num, 'url': full_link, 'title': title})
                    new += 1

            # لا فصول جديدة أو لا صفحات إضافية = انتهى الفهرس
            page_options = soup.select('#indexselect option')
            if new == 0 or len(page_options) <= page:
                break
            page += 1
            time.sleep(0.5)

        chapters.sort(key=lambda x: x['number'])
        return chapters
    except Exception as e:
        print(f"Error Freewebnovel List: {e}")
        return chapters


def scrape_chapter_freewebnovel(url):
    try:
        response = smart_get(url, timeout=25)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.select_one('.m-read .txt') or soup.find('div', id='chaptercontent')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'subtxt', 'center']):
            bad.decompose()
        # 🆕 الموقع الجديد يلفّ النص داخل divs فرعية — سابقاً كان حذف كل div
        # يمسح النص كله (0 حرف)؛ الآن: div يحمل نصاً يُفكّ ويُبقى محتواه،
        # وdiv فارغ (إعلان/فاصل) يُحذف
        for d in content_div.find_all('div'):
            if d.get_text(strip=True):
                d.unwrap()
            else:
                d.decompose()

        text = content_div.get_text(separator="\n\n", strip=True)
        text = re.sub(r'Find.*novels.*at.*freewebnovel.*', '', text, flags=re.IGNORECASE)
        return text or None
    except Exception:
        return None


def worker_freewebnovel(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_freewebnovel, scrape_chapter_freewebnovel)


# ==========================================
# 🏰 7. Royal Road (royalroad.com)
# ==========================================
# ⚠️ الموقع يحجب IP مراكز البيانات (صفحة Access Denied) — smart_get
# ينتقل تلقائياً لبروكسي ترجمة جوجل (تم التحقق أنه يعمل).
# قائمة الفصول تُقرأ من بيانات window.chapters المضمّنة في الصفحة.

def fetch_metadata_royalroad(url):
    try:
        response = smart_get(url, timeout=30)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('h1.fiction-title') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            # بديل: عنوان الصفحة بصيغة "Name | Royal Road"
            page_title = soup.find('title')
            if page_title:
                title = page_title.get_text(strip=True).split('|')[0].strip()
        title = title or "Unknown Title"

        cover = ""
        # og:image هو الغلاف الحقيقي في Royal Road
        cover = get_meta(soup, prop='og:image')
        if not cover:
            img_tag = soup.select_one('.cover-art-ego img, .fiction-info img')
            cover = img_tag.get('src') if img_tag else ""
        cover = fix_image_url(cover, base_url='https://www.royalroad.com')

        desc_div = soup.select_one('.description .hidden-content') or soup.select_one('.description')
        description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""
        description = re.sub(r'\[.*?\]', '', description).strip()

        tags = []
        for tag in soup.select('.fiction-tags a, .tags a'):
            txt = tag.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        status = "مستمرة"
        page_text = soup.get_text()[:8000].upper()
        if 'COMPLETED' in page_text:
            status = "مكتملة"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags, 'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error RoyalRoad Meta: {e}")
        return None


def fetch_chapter_list_royalroad(url):
    """قائمة الفصول من window.chapters JSON المضمّن في صفحة الرواية"""
    chapters = []
    try:
        response = smart_get(url, timeout=30)
        if response is None or response.status_code != 200:
            return []
        html = response.text

        match = re.search(r'window\.chapters\s*=\s*(\[.*?\]);', html, re.DOTALL)
        if not match:
            print("RoyalRoad: window.chapters not found, trying table fallback")
            return _royalroad_table_fallback(url)

        chapter_json = json.loads(match.group(1))

        for ch in chapter_json:
            try:
                number = int(ch.get('order', 0))
                chapter_url = urljoin('https://www.royalroad.com', ch.get('url', ''))
                title = ch.get('title', f"Chapter {number}")
                if number > 0 and chapter_url:
                    chapters.append({'number': number, 'url': chapter_url, 'title': title})
            except (ValueError, TypeError):
                continue

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ RoyalRoad chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error RoyalRoad List: {e}")
        return []


def _royalroad_table_fallback(url):
    """بديل: قراءة جدول الفصول مباشرة من HTML"""
    chapters = []
    try:
        response = smart_get(url, timeout=30)
        if response is None or response.status_code != 200:
            return []
        soup = parse_html(response)

        rows = soup.select('table#chapters tbody tr')
        for i, row in enumerate(rows, start=1):
            a = row.select_one('a[href*="/chapter/"]')
            if not a:
                continue
            link = urljoin('https://www.royalroad.com', a['href'])
            title = a.get_text(strip=True)
            chapters.append({'number': i, 'url': link, 'title': title})

        chapters.sort(key=lambda x: x['number'])
        return chapters
    except Exception:
        return []


def scrape_chapter_royalroad(url):
    try:
        res = smart_get(url, referer='https://www.royalroad.com/', timeout=30)
        if res is None or res.status_code != 200:
            return None
        soup = parse_html(res)

        container = soup.select_one('.chapter-content') or soup.select_one('.chapter-inner')
        if not container:
            return None

        for bad in container.find_all(['script', 'style', 'ins', 'iframe', 'button']):
            bad.decompose()

        text = container.get_text(separator="\n\n", strip=True)
        text = re.sub(r'(Follow|Support|Rate|Comment|Share).*?Royal Road.*?', '', text, flags=re.DOTALL)
        text = clean_text(text)
        return text if len(text) > 50 else None
    except Exception:
        return None


def worker_royalroad(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_royalroad, scrape_chapter_royalroad, delay=1.5)


# ==========================================
# ✏️ 8. Scribble Hub (scribblehub.com)
# ==========================================
# ⚠️ الموقع يعمل لكنه يحجب IP مراكز البيانات فقط (403).
# قائمة الفصول تُجلب عبر admin-ajax (نفس طريقة LNReader الرسمية).

def fetch_metadata_scribblehub(url):
    try:
        response = smart_get(url, timeout=30)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('.fic_title, h1') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover = ""
        img_tag = soup.select_one('.fic_image img, .seriestopimg')
        if img_tag:
            cover = img_tag.get('src') or ""
        if not cover:
            cover = get_meta(soup, prop='og:image')
        cover = fix_image_url(cover, base_url='https://www.scribblehub.com')

        description = get_meta(soup, prop='og:description')
        if not description:
            desc_div = soup.select_one('.fic_row .news_body, .story-details')
            description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""

        tags = []
        for g in soup.select('.fic_genre'):
            txt = g.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        status = "مستمرة"
        page_text = soup.get_text()[:10000]
        if re.search(r'Completed', page_text):
            status = "مكتملة"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags, 'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error ScribbleHub Meta: {e}")
        return None


def fetch_chapter_list_scribblehub(url):
    """قائمة الفصول عبر admin-ajax (wi_getreleases_pagination)
    ScribbleHub يحجب IP السيرفرات بحماية Cloudflare صرامة جداً (حتى بروكسي جوجل)،
    لذا نجرب بالترتيب: POST مباشر بانتحال بصمة كروم ← GET عبر smart_get
    (بروكسي جوجل/worker إن ضُبط) ← POST عبر smart_get (FlareSolverr/ScraperAPI
    مع دوران كل المفاتيح). عند الفشل: رسالة صريحة في كونسول التطبيق."""
    from core.utils import _direct_post
    from core.backend import push_log
    chapters = []
    try:
        # استخراج معرف الرواية من الرابط /series/{id}/{slug}/
        match = re.search(r'/series/(\d+)/', url)
        if not match:
            print("ScribbleHub: cannot extract series id")
            return []
        series_id = match.group(1)
        ajax_data = {
            'action': 'wi_getreleases_pagination',
            'pagenum': '-1',
            'mypostid': series_id,
        }
        ajax_url = ('https://www.scribblehub.com/wp-admin/admin-ajax.php'
                    f'?action=wi_getreleases_pagination&pagenum=-1&mypostid={series_id}')

        # 1) POST مباشر بانتحال بصمة متصفح كروم (curl_cffi)
        try:
            response = _direct_post(
                'https://www.scribblehub.com/wp-admin/admin-ajax.php',
                data=ajax_data,
                headers=get_headers(referer=url),
                timeout=30,
            )
            if response.status_code == 200 and 'toc_w' in response.text:
                soup = parse_html(response.content)
                return _scribblehub_parse_toc(soup)
            print(f"ScribbleHub direct POST blocked: HTTP {response.status_code}")
        except Exception as e:
            print(f"ScribbleHub direct POST failed: {str(e)[:60]}")

        # 2) GET عبر smart_get (بروكسي جوجل/worker إن نجحا)
        response = smart_get(ajax_url, timeout=35, referer=url)
        if response is not None and response.status_code == 200 and 'toc_w' in response.text:
            soup = parse_html(response.content)
            return _scribblehub_parse_toc(soup)

        # 3) POST عبر smart_get → FlareSolverr/ScraperAPI (دوران كل المفاتيح)
        response = smart_get('https://www.scribblehub.com/wp-admin/admin-ajax.php',
                             timeout=35, referer=url, post_data=ajax_data)
        if response is not None and response.status_code == 200 and 'toc_w' in response.text:
            soup = parse_html(response.content)
            return _scribblehub_parse_toc(soup)

        # 4) فرض مسار ScraperAPI بGET على رابط ajax (لو حُفظت طريقة فاشلة في الكاش)
        from core.utils import _scraperapi_get
        r = _scraperapi_get(ajax_url, referer=url,
                            validate=lambda b: 'toc_w' in b)
        if r is not None and 'toc_w' in r.text:
            soup = parse_html(r.content)
            return _scribblehub_parse_toc(soup)

        print("ScribbleHub: TOC blocked from this server (Cloudflare). "
              "أضف مفاتيح ScraperAPI صالحة من واجهة المفاتيح (SCRAPERAPI_KEYS) "
              "أو ضبط FLARESOLVR_URL.")
        push_log("❌ [ScribbleHub] قائمة الفصول محجوبة من خادم السكرابر (Cloudflare صارم). "
                 "الموقع يحتاج مفتاح ScraperAPI صالح — أضف مفاتيحك من شاشة "
                 "'مفاتيح ScraperAPI' ثم أعد المحاولة.", 'error')
        return []
    except Exception as e:
        print(f"Error ScribbleHub List: {e}")
        return []


def _scribblehub_parse_toc(soup):
    """تحليل قائمة الفصول من HTML الذي أعاده admin-ajax"""
    chapters = []
    rows = soup.select('.toc_w')
    for i, el in enumerate(rows, start=1):
        a = el.find('a')
        if not a or not a.get('href'):
            continue
        chapter_url = a['href']
        title = el.select_one('.toc_a')
        chapter_title = title.get_text(strip=True) if title else f"Chapter {i}"
        chapters.append({'number': i, 'url': chapter_url, 'title': chapter_title})

    # الفصول تأتي عكسية أحياناً
    if chapters and chapters[0]['number'] == 1:
        chapters.reverse()
    chapters.sort(key=lambda x: x['number'])
    print(f"✅ ScribbleHub chapters found: {len(chapters)}")
    return chapters


def scrape_chapter_scribblehub(url):
    try:
        res = smart_get(url, referer='https://www.scribblehub.com/', timeout=30)
        if res is None or res.status_code != 200:
            return None
        soup = parse_html(res)

        content_div = soup.select_one('div.chp_raw') or soup.select_one('#chp_content')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe', 'button']):
            bad.decompose()

        text = clean_text(content_div.get_text(separator="\n\n", strip=True))
        return text if len(text) > 50 else None
    except Exception:
        return None


def worker_scribblehub(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_scribblehub, scrape_chapter_scribblehub, delay=1.5, site_name='ScribbleHub')


# ==========================================
# 📦 9. NovelBin (novelbin.net)
# ==========================================
# ⚠️ الموقع يستخدم حماية JS (صفحة Loading... مع توكن JWT) ثم
# يحول أحياناً لمضيف ميت ww80.novelbin.net — نعيد كتابة المضيف.
# نستخدم smart_get كطبقة إضافية عند الحجب.

_NOVELBIN_HOSTS = ('ww80.novelbin.net', 'ww2.novelbin.net', 'ww10.novelbin.net')


def _rewrite_novelbin_url(url):
    """إعادة توجيه المضيفات الميتة إلى النطاق الرئيسي"""
    for host in _NOVELBIN_HOSTS:
        if host in url:
            return url.replace(f'http://{host}', 'https://novelbin.net').replace(f'https://{host}', 'https://novelbin.net')
    return url


def _novelbin_session_get(url, referer=None, max_retries=4):
    """طلب مع محاولة حل حماية JS الخاصة بـ NovelBin (توكن JWT + تحويلات)"""
    session = requests.Session()
    headers = get_headers(ua=UA_CHROME, referer=referer)

    try:
        r = session.get(url, headers=headers, timeout=25, allow_redirects=False)

        # متابعة التحويلات يدوياً مع إصلاح المضيفات الميتة
        hops = 0
        while r.status_code in (301, 302, 307, 308) and hops < 6:
            nxt = _rewrite_novelbin_url(r.headers.get('Location', ''))
            if not nxt:
                break
            r = session.get(nxt, headers=headers, timeout=25, allow_redirects=False)
            hops += 1

        # إذا كانت الصفحة صفحة التحدي "Loading..." نتابع إعادة التوجيه JS
        for _ in range(max_retries):
            if 'window.location.replace' in r.text and r.status_code == 200:
                m = re.search(r"window\.location\.replace\('([^']+)'\)", r.text)
                if not m:
                    break
                nxt = _rewrite_novelbin_url(m.group(1))
                r = session.get(nxt, headers=headers, timeout=25, allow_redirects=False)
                # متابعة أي تحويلات HTTP بعد التحويل JS
                hops = 0
                while r.status_code in (301, 302, 307, 308) and hops < 6:
                    nxt = _rewrite_novelbin_url(r.headers.get('Location', ''))
                    if not nxt:
                        break
                    r = session.get(nxt, headers=headers, timeout=25, allow_redirects=False)
                    hops += 1
            else:
                break

        # إن بقينا عالقين في التحدي، جرب عبر smart_get (بروكسي ترجمة)
        if 'window.location.replace' in r.text or r.status_code != 200:
            alt = smart_get(url, timeout=30)
            if alt is not None and alt.status_code == 200 and 'window.location.replace' not in alt.text:
                return alt
        return r
    except Exception as e:
        print(f"NovelBin session get failed: {e}")
        alt = smart_get(url, timeout=30)
        return alt


def fetch_metadata_novelbin(url):
    try:
        r = _novelbin_session_get(url)
        if r is None or r.status_code != 200:
            return None
        soup = parse_html(r.text)

        title = get_meta(soup, prop='og:title') or ""
        if not title:
            h1 = soup.select_one('h1')
            title = h1.get_text(strip=True) if h1 else "Unknown Title"
        title = re.sub(r'\s*[-–|]\s*NovelBin.*$', '', title, flags=re.IGNORECASE).strip()

        # إذا كانت الصفحة صفحة التحدي (بدون عنوان حقيقي) فشل الوصول — لا نجلب بيانات وهمية
        if not title or title.lower() in ('unknown title', 'loading...', 'just a moment...'):
            print("NovelBin: challenge page detected (title missing).")
            return None

        cover = get_meta(soup, prop='og:image')
        if not cover:
            img = soup.select_one('.books .book img, .cover img')
            cover = (img.get('data-src') or img.get('src') or '') if img else ""
        cover = fix_image_url(cover, base_url=get_base_url(url))

        desc_div = soup.select_one('.summary .content, #trungmvprl .cnten, div.description')
        description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""

        tags = []
        for a in soup.select('.genres-content a, .tag a'):
            txt = a.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        status = "مستمرة"
        page_text = soup.get_text()[:8000].lower()
        if 'completed' in page_text:
            status = "مكتملة"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags, 'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error NovelBin Meta: {e}")
        return None


def fetch_chapter_list_novelbin(url):
    """قائمة فصول NovelBin: تحاول عدة محددات معروفة للقالب"""
    chapters = []
    try:
        r = _novelbin_session_get(url)
        if r is None or r.status_code != 200:
            return []
        soup = parse_html(r.text)
        base_url = get_base_url(url)

        # محددات متعددة حسب إصدار القالب
        selectors = [
            'ul.list-chapter li a',
            'ul#chapter-list li a',
            'ul.list-1 li a',
            'div#chapter-list-chapters li a',
            '.list-chapter li a',
        ]

        items = []
        used_selector = None
        for sel in selectors:
            items = soup.select(sel)
            if items:
                used_selector = sel
                break

        # إذا لم نجد: جرّب واجهة API الخاصة بالقالب (تحميل الفصول دفعة واحدة)
        if not items:
            slug_match = re.search(r'/novel/([^/]+)', url)
            if slug_match:
                try:
                    api_resp = requests.post(
                        f"{base_url}/api/chapters/",
                        data={'novel_id': slug_match.group(1), 'page': '1'},
                        headers=get_headers(referer=url),
                        timeout=20,
                    )
                    if api_resp.status_code == 200:
                        soup_api = parse_html(api_resp.content)
                        items = soup_api.select('li a')
                except Exception:
                    pass

        for a in items:
            href = a.get('href')
            if not href:
                continue
            full_link = urljoin(base_url, href)
            title = a.get('title') or a.get_text(strip=True)
            number = extract_chapter_number(title, full_link)
            if number > 0:
                chapters.append({'number': number, 'url': full_link, 'title': title})

        chapters = list({c['number']: c for c in chapters}.values())
        chapters.sort(key=lambda x: x['number'])
        print(f"✅ NovelBin chapters found: {len(chapters)} (selector: {used_selector})")
        return chapters
    except Exception as e:
        print(f"Error NovelBin List: {e}")
        return []


def scrape_chapter_novelbin(url):
    try:
        r = _novelbin_session_get(url)
        if r is None or r.status_code != 200:
            return None
        soup = parse_html(r.text)

        content_div = soup.select_one('div#chapter-content') or soup.select_one('.chr-c')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe', 'button', 'div']):
            bad.decompose()

        text = clean_text(content_div.get_text(separator="\n\n", strip=True))
        return text if len(text) > 50 else None
    except Exception:
        return None


def worker_novelbin(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_novelbin, scrape_chapter_novelbin, delay=1.5)


# ==========================================
# 🈶 10. LNMTL (lnmtl.com) - ترجمة آلية للروايات
# ==========================================

def fetch_metadata_lnmtl(url):
    try:
        response = http_get(url, timeout=20)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        img_tag = soup.select_one('img.img-rounded')
        title = img_tag.get('title') if img_tag and img_tag.get('title') else ""
        if not title:
            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else "Unknown Title"

        cover = img_tag.get('src') if img_tag else ""
        cover = fix_image_url(cover, base_url='https://lnmtl.com')

        description = ""
        desc_div = soup.select_one('.novel-description, .panel-body .description')
        if desc_div:
            description = desc_div.get_text(separator="\n\n", strip=True)

        # استخراج البيانات من لوحة المعلومات (dt/dd)
        author = ""
        status = "مستمرة"
        tags = []
        dts = soup.select('dt')
        dds = soup.select('dd')
        for dt, dd in zip(dts, dds):
            key = dt.get_text(strip=True)
            val = dd.get_text(strip=True)
            if 'author' in key.lower():
                author = val
            elif 'status' in key.lower():
                if 'ongoing' in val.lower():
                    status = "مستمرة"
                elif 'complete' in val.lower() or 'dropped' in val.lower():
                    status = "مكتملة"
            elif 'tag' in key.lower() or 'genre' in key.lower():
                for a in dd.find_all('a'):
                    txt = a.get_text(strip=True)
                    if txt:
                        tags.append(txt)

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': tags[0] if tags else "عام", 'tags': tags,
            'author': author, 'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error LNMTL Meta: {e}")
        return None


def fetch_chapter_list_lnmtl(url):
    """قائمة الفصول عبر واجهة LNMTL JSON (لكل مجلد volumes)"""
    chapters = []
    try:
        response = http_get(url, timeout=20)
        if response is None or response.status_code != 200:
            return []
        html = response.text

        # استخراج قائمة المجلدات lnmtl.volumes = [...]
        match = re.search(r'lnmtl\.volumes\s*=\s*(\[.+?\])\s*;', html, re.DOTALL)
        if not match:
            # بديل: قراءة روابط الفصول من الصفحة مباشرة
            return _lnmtl_html_fallback(url, html)

        volumes = json.loads(match.group(1))
        print(f"LNMTL: found {len(volumes)} volumes")

        for volume in volumes:
            volume_id = volume.get('id')
            if not volume_id:
                continue

            # جلب فصول المجلد مع دعم الصفحات
            page = 1
            while True:
                api_url = f"https://lnmtl.com/chapter?volumeId={volume_id}&page={page}"
                r = http_get(api_url, referer=url, timeout=20)
                if r is None or r.status_code != 200:
                    break
                try:
                    data = r.json()
                except Exception:
                    break

                for ch in data.get('data', []):
                    number = ch.get('number', 0)
                    slug = ch.get('slug', '')
                    title = ch.get('title', f"Chapter {number}")
                    if number and slug:
                        chapters.append({
                            'number': number,
                            'url': f"https://lnmtl.com/chapter/{slug}",
                            'title': f"#{number} - {title}",
                        })

                last_page = data.get('last_page', 1)
                if page >= last_page:
                    break
                page += 1
                time.sleep(0.5)

        chapters = list({c['number']: c for c in chapters}.values())
        chapters.sort(key=lambda x: x['number'])
        print(f"✅ LNMTL chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error LNMTL List: {e}")
        return []


def _lnmtl_html_fallback(url, html=None):
    """بديل: قراءة روابط الفصول من HTML مباشرة"""
    chapters = []
    try:
        if html is None:
            response = http_get(url, timeout=20)
            if response is None or response.status_code != 200:
                return []
            html = response.text

        soup = parse_html(html)
        for a in soup.select('a[href*="/chapter/"]'):
            href = a.get('href', '')
            m = re.search(r'chapter-(\d+)', href)
            if m:
                number = int(m.group(1))
                title = a.get_text(strip=True) or f"Chapter {number}"
                chapters.append({'number': number, 'url': href, 'title': title})

        chapters = list({c['number']: c for c in chapters}.values())
        chapters.sort(key=lambda x: x['number'])
        return chapters
    except Exception:
        return []


def scrape_chapter_lnmtl(url):
    """سحب محتوى فصل LNMTL من عناصر sentence.translated"""
    try:
        res = http_get(url, timeout=20)
        if res is None or res.status_code != 200:
            return None
        soup = parse_html(res)

        sents = soup.select('sentence.translated')
        if not sents:
            return None

        paragraphs = []
        current = []
        for s in sents:
            txt = s.get_text(strip=True)
            if txt:
                current.append(txt)
            # كل بضع جمل تشكل فقرة (الجملة الأخيرة في الفقرة تنتهي بعلامة)
            if txt and txt[-1] in '。"\'!?…':
                paragraphs.append(' '.join(current))
                current = []
        if current:
            paragraphs.append(' '.join(current))

        text = "\n\n".join(p for p in paragraphs if p)

        # إزالة نص الإعلان/الجدار
        text = re.sub(r'This\s*chapter\s*content\s*is.*?update.*?(if|through).*$', '', text, flags=re.DOTALL | re.IGNORECASE)

        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_lnmtl(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_lnmtl, scrape_chapter_lnmtl, delay=1.5)


# ==========================================
# 📋 تسجيل المواقع الإنجليزية
# ==========================================

register_site(
    domain_patterns=['novelfire.net'],
    name='Novel Fire',
    language='english',
    fetch_metadata=fetch_metadata_novelfire,
    fetch_chapters=fetch_chapter_list_novelfire,
    fetch_content=scrape_chapter_novelfire,
    worker=worker_novelfire,
    status='active',
    notes='يعمل بالكامل. تم تحسين استخراج عناوين الفصول وتاريخ التحديث.'
)

register_site(
    domain_patterns=['novelmtl.com'],
    name='NovelMTL',
    language='english',
    fetch_metadata=fetch_metadata_mtlnation,
    fetch_chapters=fetch_chapter_list_mtlnation,
    fetch_content=scrape_chapter_mtlnation,
    worker=worker_mtlnation,
    status='active',
    notes='جديد! منصة MTLNation بالتصميم الجديد - يعمل بالكامل.'
)

register_site(
    domain_patterns=['fanmtl.com'],
    name='FanMTL',
    language='english',
    fetch_metadata=fetch_metadata_fanmtl,
    fetch_chapters=fetch_chapter_list_fanmtl,
    fetch_content=scrape_chapter_fanmtl,
    worker=worker_fanmtl,
    status='active',
    notes='أعيد بناؤه كلياً لقالب الموقع الحالي (Empire CMS + ترقيم fy.php). يعمل حتى مع حجب IP السيرفرات عبر التوجيه الذكي (smart_get).'
)

register_site(
    domain_patterns=['wuxiaworld.site'],
    name='WuxiaWorld (Mirror)',
    language='english',
    fetch_metadata=fetch_metadata_wuxiaworld,
    fetch_chapters=lambda url: None,
    fetch_content=None,
    worker=worker_wuxiaworld,
    status='active',
    notes='جديد! مرآة WuxiaWorld بقالب Madara. الموقع الرسمي wuxiaworld.com تطبيق SPA غير قابل للسحب.'
)

register_site(
    domain_patterns=['wuxiabox.com', 'wuxiaspot.com'],
    name='WuxiaBox / WuxiaSpot',
    language='english',
    fetch_metadata=fetch_metadata_wuxiabox,
    fetch_chapters=fetch_chapter_list_wuxiabox,
    fetch_content=scrape_chapter_wuxiabox,
    worker=worker_wuxiabox,
    status='active',
    notes='نفس قالب FanMTL (Empire CMS). الروابط الجديدة تنتهي بـ .html (تُضاف تلقائياً). يعمل عبر التوجيه الذكي رغم حجب IP السيرفرات.'
)

register_site(
    domain_patterns=['freewebnovel.com'],
    name='FreeWebNovel',
    language='english',
    fetch_metadata=fetch_metadata_freewebnovel,
    fetch_chapters=fetch_chapter_list_freewebnovel,
    fetch_content=scrape_chapter_freewebnovel,
    worker=worker_freewebnovel,
    status='blocked',
    notes='يحجب IP السيرفرات وحتى بروكسي جوجل (403 صارم). يحتاج FLARESOLVR_URL أو SCRAPERAPI_KEY. بديل بنفس المحتوى: NovelFire.'
)

register_site(
    domain_patterns=['royalroad.com'],
    name='Royal Road',
    language='english',
    fetch_metadata=fetch_metadata_royalroad,
    fetch_chapters=fetch_chapter_list_royalroad,
    fetch_content=scrape_chapter_royalroad,
    worker=worker_royalroad,
    status='active',
    notes='يعمل عبر التوجيه الذكي (بروكسي ترجمة جوجل) رغم حجب IP السيرفرات. الفصول من window.chapters JSON.'
)

register_site(
    domain_patterns=['scribblehub.com'],
    name='Scribble Hub',
    language='english',
    fetch_metadata=fetch_metadata_scribblehub,
    fetch_chapters=fetch_chapter_list_scribblehub,
    fetch_content=scrape_chapter_scribblehub,
    worker=worker_scribblehub,
    status='blocked',
    notes='حماية Cloudflare صارمة على كل المسارات (حتى بروكسي جوجل محجوب). يحتاج FLARESOLVR_URL أو SCRAPERAPI_KEY.'
)

register_site(
    domain_patterns=['novelbin.net', 'novelbin.com'],
    name='NovelBin',
    language='english',
    fetch_metadata=fetch_metadata_novelbin,
    fetch_chapters=fetch_chapter_list_novelbin,
    fetch_content=scrape_chapter_novelbin,
    worker=worker_novelbin,
    status='blocked',
    notes='متحي تحدي JS (توكن JWT + تحويلات لمضيفات ميتة — يُعالج تلقائياً). من IP السيرفرات يحتاج FLARESOLVR_URL أو SCRAPERAPI_KEY.'
)

register_site(
    domain_patterns=['lnmtl.com'],
    name='LNMTL',
    language='english',
    fetch_metadata=fetch_metadata_lnmtl,
    fetch_chapters=fetch_chapter_list_lnmtl,
    fetch_content=scrape_chapter_lnmtl,
    worker=worker_lnmtl,
    status='active',
    notes='جديد! موقع الترجمة الآلية MTL. قائمة الفصول عبر واجهة JSON (مجلدات + صفحات). يعمل بالكامل.'
)
