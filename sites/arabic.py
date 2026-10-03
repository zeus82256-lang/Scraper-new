# -*- coding: utf-8 -*-
"""
==========================================
🟩 المواقع العربية (Arabic Novel Sites)
==========================================
المواقع المسجلة في هذا الملف:
1. Rewayat Club      - rewayat.club          ✅ يعمل
2. Ar-Novel          - ar-no.com             ✅ يعمل (قالب Madara)
3. Markaz Riwayat    - markazriwayat.com     ⚠️ الموقع أُغلق (صفحة Coming Soon)

ملاحظة: مركز الروايات انتقل إلى galaxynovels.com لكن الموقع الجديد
يمنع صراحة السحب الآلي في صفحاته (تم حجب السحب من قِبل الناشر).
"""

import re
import time
import threading

from bs4 import BeautifulSoup
from urllib.parse import urlparse

from core.config import API_SECRET
from core.registry import register_site
from core.backend import send_data_to_backend, check_existing_chapters
from core.utils import (
    http_get, parse_html, get_headers, get_base_url, fix_image_url,
    parse_relative_date, clean_text,
    madara_fetch_metadata, madara_worker,
    get_current_chapter_spec, parse_chapter_spec_tokens,
)


# ==========================================
# 🟣 1. Rewayat Club (rewayat.club) - Nuxt
# ==========================================

def _extract_from_nuxt(soup):
    """استخراج رابط الغلاف من بيانات window.__NUXT__"""
    try:
        for script in soup.find_all('script'):
            if script.string and 'window.__NUXT__' in script.string:
                content = script.string
                match = re.search(r'poster_url:"(.*?)"', content)
                if not match:
                    match = re.search(r'poster:"(.*?)"', content)
                if match:
                    return match.group(1).encode('utf-8').decode('unicode_escape')
    except Exception:
        pass
    return None


def fetch_metadata_rewayat(url):
    """جلب بيانات رواية من نادي الروايات"""
    try:
        response = http_get(url, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover_url = _extract_from_nuxt(soup) or ""
        if not cover_url:
            og_image = soup.find("meta", property="og:image")
            if og_image:
                cover_url = og_image["content"]
        cover_url = fix_image_url(cover_url)

        desc_div = soup.find(class_='text-pre-line') or soup.find('div', class_='v-card__text')
        description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""

        # 🔥 فحص حالة الرواية (مكتملة/مستمرة)
        status = "مستمرة"
        for chip in soup.find_all(class_='v-chip__content'):
            txt = chip.get_text(strip=True)
            if "مكتملة" in txt or "Completed" in txt:
                status = "مكتملة"
                break
        if status == "مستمرة" and "مكتملة" in soup.get_text():
            status = "مكتملة"

        # 🔥 استخراج تاريخ آخر تحديث من قوائم الصفحة
        last_update = None
        for sub in soup.find_all(class_='v-list-item__subtitle'):
            txt = sub.get_text(strip=True)
            date_match = re.search(r'(\d{4}/\d{1,2}/\d{1,2})', txt)
            if date_match:
                last_update = parse_relative_date(date_match.group(1))
                if last_update:
                    break

        return {
            'title': title, 'description': description, 'cover': cover_url,
            'status': status, 'category': "عام", 'tags': [], 'sourceUrl': url,
            'lastUpdate': last_update
        }
    except Exception as e:
        print(f"Error rewayat metadata: {e}")
        return None


def scrape_chapter_rewayat(novel_url, chapter_num):
    """سحب فصل محدد بالرقم من نادي الروايات (الموقع يستخدم ترقيم مباشر)"""
    url = f"{novel_url.rstrip('/')}/{chapter_num}"
    try:
        response = http_get(url, timeout=12)
        if response is None or response.status_code != 200:
            return None, None
        soup = parse_html(response)
        paragraphs = soup.find_all('p')
        clean_paragraphs = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
        if clean_paragraphs:
            text = "\n\n".join(clean_paragraphs)
        else:
            div = soup.find('div', class_='pre-formatted') or soup.find('div', class_='v-card__text')
            text = div.get_text(separator="\n\n", strip=True) if div else ""

        if len(text.strip()) < 2:
            return None, None

        title_tag = soup.find(class_='v-card__subtitle') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else f"الفصل {chapter_num}"
        title = re.sub(r'^\d+\s*-\s*', '', title)
        return title, text
    except Exception:
        return None, None


def worker_rewayat_probe(url, admin_email, metadata):
    """عامل نادي الروايات: يجرّب الفصول بالترتيب 1..5000 حتى 15 خطأ متتاليا"""
    existing_chapters = check_existing_chapters(metadata['title'])
    skip_meta = len(existing_chapters) > 0

    send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': [], 'skipMetadataUpdate': skip_meta})

    # 🎯 سحب انتقائي: فلتر أرقام الفصول إن وُضع من /scrape ("10-20" / "12,50" / "10-!")
    spec = get_current_chapter_spec()
    tokens = parse_chapter_spec_tokens(spec) if spec else None

    def _allowed(n):
        if not tokens:
            return True
        for tok in tokens:
            if tok[0] == 'single' and tok[1] == n:
                return True
            if tok[0] == 'range' and tok[1] <= n <= tok[2]:
                return True
            if tok[0] == 'open' and n >= tok[1]:
                return True
        return False

    if tokens:
        closed_max = [t[2] for t in tokens if t[0] == 'range'] + [t[1] for t in tokens if t[0] == 'single']
        hard_max = max(closed_max + [5000]) if any(t[0] == 'open' for t in tokens) else max(closed_max)
        start_at = min(t[1] for t in tokens)
        print(f"🎯 فلتر الفصول '{spec}' على نادي الروايات: يفحص من {start_at} حتى {hard_max}")
    else:
        hard_max = 5000
        start_at = 1

    current_chapter = start_at
    errors = 0
    batch = []

    while current_chapter <= hard_max and errors < 15:
        if not _allowed(current_chapter):
            current_chapter += 1
            continue

        if current_chapter in existing_chapters:
            current_chapter += 1
            errors = 0
            continue

        chap_title, content = scrape_chapter_rewayat(url, current_chapter)
        if content:
            errors = 0
            batch.append({'number': current_chapter, 'title': chap_title, 'content': content})
            print(f"Fetched Ch {current_chapter}")
            if len(batch) >= 5:
                send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': batch, 'skipMetadataUpdate': True})
                batch = []
                time.sleep(1)
        else:
            errors += 1
            print(f"Failed Ch {current_chapter} ({errors}/15)")
        current_chapter += 1

    if batch:
        send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata, 'chapters': batch, 'skipMetadataUpdate': True})


# ==========================================
# 🟢 2. Ar-Novel (ar-no.com) + 3. Markaz Riwayat
#          (قالب Madara المشترك في core/utils.py)
# ==========================================

def fetch_metadata_ar_novel(url):
    return madara_fetch_metadata(url, use_cookies=False)


def fetch_metadata_markaz(url):
    return madara_fetch_metadata(url, use_cookies=True)


def worker_ar_novel(url, admin_email, metadata):
    madara_worker(url, admin_email, metadata, use_cookies=False)


def worker_markaz(url, admin_email, metadata):
    madara_worker(url, admin_email, metadata, use_cookies=True)


# ==========================================
# 📋 تسجيل المواقع العربية
# ==========================================

register_site(
    domain_patterns=['rewayat.club'],
    name='Rewayat Club (نادي الروايات)',
    language='arabic',
    fetch_metadata=fetch_metadata_rewayat,
    worker=worker_rewayat_probe,
    status='active',
    notes='موقع نادي الروايات - يعمل بالكامل (بيانات + فصول). يستخدم الترقيم المباشر للفصول.'
)

register_site(
    domain_patterns=['ar-no.com'],
    name='Ar-Novel (الرواية العربية)',
    language='arabic',
    fetch_metadata=fetch_metadata_ar_novel,
    fetch_chapters=lambda url: None,  # عبر worker الخاص بـ Madara
    fetch_content=None,
    worker=worker_ar_novel,
    status='active',
    notes='قالب WordPress Madara - يعمل بالكامل (بيانات + قائمة فصول + محتوى).'
)

register_site(
    domain_patterns=['markazriwayat.com'],
    name='Markaz Riwayat (مركز الروايات)',
    language='arabic',
    fetch_metadata=fetch_metadata_markaz,
    fetch_chapters=lambda url: None,
    fetch_content=None,
    worker=worker_markaz,
    status='dead',
    notes='⚠️ الموقع مغلق حالياً ويعرض صفحة Coming Soon. الناشر انتقل إلى galaxynovels.com '
          'والذي يمنع صراحة السحب الآلي. تم الإبقاء على الكود في حال عودة الموقع.'
)
