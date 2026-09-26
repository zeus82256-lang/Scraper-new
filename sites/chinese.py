# -*- coding: utf-8 -*-
"""
==========================================
🟥 المواقع الصينية (Chinese Novel Sites)
==========================================
المواقع المسجلة في هذا الملف:
1.  Quanben      - quanben.io            ⚠️ يعمل (محجوب عن IP السيرفرات فقط)
2.  52shuku      - 52shuku.net           ✅ يعمل (تم إعادة كتابته للتصميم الجديد)
3.  ErCiYuan     - erciyan.com           ⚠️ يعمل (WAF كابتشا من IP السيرفرات فقط)
4.  69shu        - 69shu.xyz / 69shuba.com   ✅ جديد (Cloudflare أحياناً)
5.  ixdzs8       - ixdzs8.com            ✅ جديد ويعمل بالكامل (爱下电子书)
6.  Linovel      - linovel.net           ✅ جديد ويعمل بالكامل
7.  Linovelib TW - tw.linovelib.com      ✅ جديد ويعمل بالكامل (繁體)
8.  Novel543     - novel543.com          ✅ جديد (Cloudflare متقلب أحياناً)
"""

import os
import re
import time
import json
import random
import requests
from urllib.parse import urljoin, urlparse

from core.registry import register_site
from core.utils import (
    http_get, smart_get, parse_html, get_headers, get_base_url, fix_image_url,
    parse_relative_date, extract_chapter_number, clean_text, get_meta,
    UA_FIREFOX,
    generic_worker,
)


# ==========================================
# 🔵 1. Quanben.io (全本网)
# ==========================================
# ⚠️ الموقع يحجب IP مراكز البيانات (403 Apache) — نستخدم smart_get
# (مباشر ثم بروكسي ترجمة جوجل تلقائياً — تم التحقق أنه يعمل).

def fetch_metadata_quanben(url):
    try:
        # إذا كان رابط فصل، حوّله لصفحة الكتاب
        if '/n/' in url:
            match = re.search(r'/n/([^/]+)/', url)
            if match:
                slug = match.group(1)
            else:
                parsed = urlparse(url)
                path_parts = parsed.path.strip('/').split('/')
                if 'n' in path_parts:
                    idx = path_parts.index('n')
                    if idx + 1 < len(path_parts):
                        slug = path_parts[idx + 1]
                    else:
                        return None
                else:
                    return None
            info_url = f"https://www.quanben.io/n/{slug}/"
        else:
            info_url = url

        response = smart_get(info_url, sl='zh-CN', timeout=30)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title = ""
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            title_span = soup.select_one('.list2 h3 span')
            if title_span:
                title = title_span.get_text(strip=True)
        if not title:
            title = "Unknown Title"

        cover = ""
        img = soup.select_one('.list2 img')
        if img:
            cover = img.get('src')
            if cover:
                if cover.startswith('//'):
                    cover = 'https:' + cover
                elif cover.startswith('/'):
                    cover = 'https://www.quanben.io' + cover

        description = ""
        desc_p = soup.select_one('.description p')
        if desc_p:
            description = desc_p.get_text(strip=True)
        else:
            description = get_meta(soup, name='description')

        status = "مستمرة"
        page_text = soup.get_text()
        if '完结' in page_text:
            status = "مكتملة"

        category = "عام"
        cat_span = soup.select_one('.list2 p:-soup-contains("类别") span')
        if cat_span:
            category = cat_span.get_text(strip=True)

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': [],
            'sourceUrl': info_url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error quanben metadata: {e}")
        return None


def fetch_chapter_list_quanben(url):
    chapters = []
    try:
        if '/n/' in url and url.endswith('.html'):
            list_url = url.rsplit('/', 1)[0] + '/list.html'
        elif '/n/' in url and not url.endswith('/list.html'):
            if url.endswith('/'):
                list_url = url + 'list.html'
            else:
                list_url = url + '/list.html'
        else:
            list_url = url

        response = smart_get(list_url, sl='zh-CN', timeout=30)
        if response is None or response.status_code != 200:
            return chapters
        soup = parse_html(response)

        links = soup.select('ul.list3 li a')
        for a in links:
            href = a.get('href')
            if not href:
                continue
            full_url = urljoin('https://www.quanben.io', href)
            text = a.get_text(strip=True)
            num_match = re.search(r'/(\d+)\.html', href)
            if not num_match:
                num_match = re.search(r'第(\d+)章', text)
            number = int(num_match.group(1)) if num_match else 0
            if number > 0:
                chapters.append({'number': number, 'url': full_url, 'title': text.strip()})

        # ملء الفصول الناقصة بالتخمين المباشر (الترقيم متسلسل)
        if chapters:
            max_num = max(c['number'] for c in chapters)
            existing_nums = {c['number'] for c in chapters}
            base_url = re.sub(r'\d+\.html$', '', chapters[0]['url'])
            for i in range(1, max_num + 1):
                if i not in existing_nums:
                    chapters.append({'number': i, 'url': f"{base_url}{i}.html", 'title': f'第{i}章'})
            chapters.sort(key=lambda x: x['number'])

        return chapters
    except Exception as e:
        print(f"Error quanben chapter list: {e}")
        return chapters


def scrape_chapter_quanben(url):
    try:
        response = smart_get(url, sl='zh-CN', timeout=30)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.find('div', id='content')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()

        paragraphs = content_div.find_all('p')
        if paragraphs:
            text = '\n\n'.join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        else:
            text = content_div.get_text(separator='\n\n', strip=True)

        text = re.sub(r'<!--PAGE \d+-->', '', text)
        text = clean_text(text)

        if len(text.strip()) < 50:
            return None
        return text
    except Exception as e:
        print(f"Error scraping quanben chapter: {e}")
        return None


def worker_quanben(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_quanben, scrape_chapter_quanben)


# ==========================================
# ⚪ 2. 52shuku.net (52书库) - التصميم الجديد بالكامل
# ==========================================
# الموقع غيّر بنيته: الكتاب الآن /{تصنيف}/{id}.html والفصول
# صفحات متتابعة /{تصنيف}/{id}_{صفحة}.html

def fetch_metadata_52shuku(url):
    try:
        response = http_get(url, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        # العنوان من h1 بصيغة: 书名_作者【状态】
        title = "Unknown Title"
        author = ""
        h1 = soup.select_one('h1.article-title') or soup.find('h1') or soup.find('title')
        if h1:
            title = h1.get_text(strip=True).split('_')[0].strip()
            full = h1.get_text(strip=True)
            parts = full.split('_')
            if len(parts) > 1:
                author = parts[1].strip()

        status = "مستمرة"
        if '完结' in title or '完本' in title:
            status = "مكتملة"

        # الوصف من الفقرة بعد "小说简介："
        description = ""
        article = soup.find('article', class_='article-content') or soup.find('div', class_='article-content')
        if article:
            for p in article.find_all('p'):
                txt = p.get_text(strip=True)
                if '小说简介' in txt:
                    # الوصف داخل نفس الفقرة بعد النقطتين أو الفقرة التالية
                    after = txt.split('小说简介：')[-1].strip()
                    if after:
                        description = after
                    else:
                        next_p = p.find_next_sibling('p')
                        if next_p:
                            description = next_p.get_text(strip=True)
                    break
            if not description:
                # خذ أول فقرة معتبرة
                for p in article.find_all('p'):
                    txt = p.get_text(strip=True)
                    if len(txt) > 40 and '传送门' not in txt:
                        description = txt
                        break

        # الغلاف من og:image إن وجد
        cover = get_meta(soup, prop='og:image')

        # معرف الكتاب للتسلسل
        book_match = re.search(r'/(\w+)/(\d+)\.html', url)

        return {
            'title': title, 'description': description, 'cover': cover,
            'author': author, 'status': status, 'category': "عام", 'tags': [],
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error 52shuku metadata: {e}")
        return None


def fetch_chapter_list_52shuku(url):
    """
    قائمة "الفصول" = صفحات الكتاب المتتابعة:
    صفحة 2، 3، 4... إلى آخر صفحة (نتبع رابط الصفحة التالية)
    """
    chapters = []
    try:
        m = re.match(r'(https?://[^/]+/.+?)/(\d+)\.html', url)
        if not m:
            return chapters
        base_path, book_id = m.group(1), m.group(2)

        current_page = 2  # الصفحة الأولى هي صفحة الكتاب نفسها (مقدمة)
        while current_page and current_page < 5000:
            page_url = f"{base_path}/{book_id}_{current_page}.html"
            res = http_get(page_url, timeout=15)
            if res is None or res.status_code != 200:
                break
            soup = parse_html(res)

            chapters.append({
                'number': current_page - 1,  # نبدأ الترقيم من 1
                'url': page_url,
                'title': f"صفحة {current_page - 1}",
            })

            # البحث عن رابط الصفحة التالية
            next_page = None
            for a in soup.find_all('a', href=True):
                hm = re.search(rf'/{book_id}_(\d+)\.html', a['href'])
                if hm and int(hm.group(1)) == current_page + 1:
                    next_page = int(hm.group(1))
                    break

            # إن لم يوجد رابط تالٍ مباشر، جرّب الأعلى المذكور
            if not next_page:
                all_nums = [
                    int(x) for x in re.findall(rf'/{book_id}_(\d+)\.html', str(soup))
                    if int(x) > current_page
                ]
                if all_nums:
                    next_page = min(all_nums)

            if not next_page:
                break
            current_page = next_page
            time.sleep(0.4)

        print(f"✅ Total 52shuku pages found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error 52shuku page list: {e}")
        return chapters


def scrape_chapter_52shuku(url):
    try:
        response = http_get(url, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.find('article', class_='article-content') or soup.find('div', id='nr1')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe', 'button']):
            bad.decompose()
        for div in content_div.find_all('div'):
            if div.get('id') and div.get('id').startswith('pf-'):
                div.decompose()
            elif div.get('class') and any(c in ['pagination2', 'breadcrumbs', 'nr_set', 'meta', 'article-nav', 'related_top'] for c in div.get('class', [])):
                div.decompose()

        paragraphs = content_div.find_all('p')
        if paragraphs:
            text_parts = []
            for p in paragraphs:
                pt = p.get_text(strip=True)
                if pt and not re.match(r'^Tips：|^传送门：|^哦豁，小伙伴们', pt):
                    text_parts.append(pt)
            text = '\n\n'.join(text_parts)
        else:
            text = content_div.get_text(separator='\n\n', strip=True)

        text = clean_text(text)
        if len(text.strip()) < 20:
            return None
        return text
    except Exception as e:
        print(f"Error scraping 52shuku page: {e}")
        return None


def worker_52shuku(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_52shuku, scrape_chapter_52shuku)


# ==========================================
# 🟤 3. ErCiYuan (二次元小说网 - erciyan.com)
# ==========================================
# ⚠️ الموقع يعرض WAF كابتشا لعناوين مراكز البيانات — نستخدم smart_get
# (تم التحقق أن بروكسي الترجمة يجلب الصفحة الحقيقية بدون كابتشا).
# ملاحظة: روابط الفصول في صفحة الكتاب تشير لموقع الشقيق 2cyxsw.net
# لذلك مسجلان معاً بنفس الدوال.

ZH_HEADERS_LANG = 'zh-CN,zh;q=0.9'


def fetch_metadata_erciyuan(url):
    try:
        response = smart_get(url, sl='zh-CN', lang=ZH_HEADERS_LANG, timeout=30)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('div.info h1') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover = ""
        img_tag = soup.select_one('div.imgbox img')
        if img_tag:
            cover = img_tag.get('src')
        if not cover:
            cover = get_meta(soup, prop='og:image')
        if cover and cover.startswith('/'):
            cover = get_base_url(url) + cover

        desc_div = soup.select_one('div.desc') or soup.select_one('div.m-desc')
        description = desc_div.get_text(separator="\n\n", strip=True) if desc_div else ""

        status = "مستمرة"
        category = "عام"
        tags = []
        info_div = soup.select_one('div.info')
        if info_div:
            info_text = info_div.get_text()
            status_match = re.search(r'状态[：:]\s*([^\s]+)', info_text)
            if status_match and ('完结' in status_match.group(1)):
                status = "مكتملة"
            cat_match = re.search(r'类[：:]\s*([^\s]+)', info_text)
            if cat_match:
                category = cat_match.group(1)
            tags = [category] if category != "عام" else []

        last_update = None
        update_match = re.search(r'最后更新[：:]\s*(\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{1,2}:\d{1,2})', soup.get_text())
        if update_match:
            try:
                from datetime import datetime
                dt = datetime.strptime(update_match.group(1), '%Y-%m-%d %H:%M:%S')
                last_update = dt.isoformat()
            except Exception:
                pass

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'sourceUrl': url, 'lastUpdate': last_update
        }
    except Exception as e:
        print(f"Error ErCiYuan metadata: {e}")
        return None


def _erciyuan_book_id(url):
    m = re.search(r'/book/(\d+)', url)
    return m.group(1) if m else None


def _erciyuan_chapter_number(title, href):
    """رقم الفصل: من العنوان (435:xxx / 第435章) ثم من الرابط كاحتياط"""
    m = re.match(r'^\s*(\d+)\s*[:：.、]', title)
    if m:
        return int(m.group(1))
    m = re.search(r'第(\d+)[章回节]', title)
    if m:
        return int(m.group(1))
    return extract_chapter_number(title, href)


def fetch_chapter_list_erciyuan(url):
    """
    قائمة الفصول الكاملة عبر فهرس موقع الشقيق 2cyxsw.net:
    - الفهرس: /book/{id}/{صفحة}/ (صفحات من select options)
    - كل صفحة فيها روابط بصيغة /book/{id}/{chapterid}.html وعنوان "N:اسم الفصل"
    """
    chapters = []
    try:
        book_id = _erciyuan_book_id(url)
        if not book_id:
            print("ErCiYuan: cannot extract book id")
            return []

        tocs_seen = set()
        page = 1
        while page and page < 100:
            toc_url = f'https://www.2cyxsw.net/book/{book_id}/{page}/'
            if toc_url in tocs_seen:
                break
            tocs_seen.add(toc_url)

            response = smart_get(toc_url, sl='zh-CN', lang=ZH_HEADERS_LANG, timeout=30)
            if response is None or response.status_code != 200:
                break
            soup = parse_html(response)

            found = 0
            next_page = None
            for a in soup.select(f'a[href*="/book/{book_id}/"]'):
                href = a.get('href') or ''
                m = re.search(rf'/book/{book_id}/(\d+)\.html$', href)
                if m:
                    raw_title = a.get_text(strip=True)
                    # تجاهل روابط التنقل الثابتة
                    if raw_title in ('开始阅读', '直达底部', '加入书架', '投推荐票'):
                        continue
                    number = _erciyuan_chapter_number(raw_title, href)
                    # تجاهل الأرقام غير المنطقية (مثل معرف الكتاب نفسه)
                    if number > 0 and number != int(book_id):
                        chapters.append({
                            'number': number,
                            'url': f'https://www.2cyxsw.net/book/{book_id}/{m.group(1)}.html',
                            'title': raw_title,
                        })
                        found += 1
                        continue
                    # روابط ترقيم الفهرس: /book/{id}/{N}/
                    m2 = re.search(rf'/book/{book_id}/(\d+)/$', href)
                    if m2 and a.get_text(strip=True) in ('下一页', '下页', 'next', '下一頁'):
                        next_page = max(next_page or 0, int(m2.group(1)))

            print(f"ErCiYuan TOC page {page}: {found} chapters")

            # اكتشاف آخر صفحة فهرس من قائمة select
            max_opt = 0
            for option in soup.select('option'):
                val = option.get('value') or ''
                m3 = re.search(rf'/book/{book_id}/(\d+)/$', val)
                if m3:
                    max_opt = max(max_opt, int(m3.group(1)))

            if next_page and next_page > page:
                page = next_page
            elif max_opt and page < max_opt:
                page += 1
            else:
                break
            time.sleep(0.5)

        if not chapters:
            return []

        # إزالة التكرار بالرقم + ترتيب
        dedup = {}
        for c in chapters:
            dedup.setdefault(c['number'], c)
        chapters = sorted(dedup.values(), key=lambda x: x['number'])
        print(f"✅ ErCiYuan chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error ErCiYuan chapter list: {e}")
        return chapters


def scrape_chapter_erciyuan(url):
    try:
        response = smart_get(url, sl='zh-CN', lang=ZH_HEADERS_LANG, timeout=30)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.find('div', id='content') or soup.find('div', class_='content')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()

        paragraphs = content_div.find_all('p')
        if paragraphs:
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        else:
            text = content_div.get_text(separator="\n\n", strip=True)

        text = re.sub(r'本章未完，点击下一页继续阅读', '', text)
        text = re.sub(r'请收藏本站：https?://\S+', '', text)
        text = re.sub(r'最新章节请.*', '', text, flags=re.IGNORECASE)
        # تنظيف أسطر الإعلانات المتنقلة (完♂本♂神♂立占 وروابط m.xxx)
        text = re.sub(r'[↘↙↑]\s*完[♂♀]本[♂♀]神[♂♀]立占\s*[↗↖↑↙↘]?', '', text)
        text = re.sub(r'手机用户输入地址[:：]?\s*m\.\S+', '', text)
        text = re.sub(r'天才一秒记住本站地址.*', '', text)
        text = re.sub(r'\b(m|www)\.\w+\.(com|net|cc|org)\b.*', '', text)
        text = clean_text(text)

        return text if len(text.strip()) > 50 else None
    except Exception as e:
        print(f"Error scraping ErCiYuan chapter: {e}")
        return None


def worker_erciyuan(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_erciyuan, scrape_chapter_erciyuan)


# ==========================================
# 🐉 4. 69shu / 69shuba (69书吧)
# ==========================================
# جديد! المصدر من LNReader. الدومين يتغير بين:
# 69shu.xyz / 69shu.com / 69shuba.com / 69shuba.cx
# الموقع يستخدم ترميز GBK!

SHU69_DOMAINS = ['www.69shu.xyz', 'www.69shu.com', 'www.69shuba.com', '69shuba.com', '69shu.xyz']


def _shu69_base(url=''):
    """تحديد الدومين الأساسي: من الرابط نفسه أو أول دومين يعمل"""
    if url:
        parsed = urlparse(url)
        if parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    for domain in SHU69_DOMAINS:
        base = f"https://{domain}"
        r = http_get(base, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=12)
        if r is not None and r.status_code == 200 and 'just a moment' not in r.text[:3000].lower():
            return base
    return 'https://www.69shu.xyz'


def _shu69_get(url, timeout=15):
    """طلب مع ترميز GBK الصحيح"""
    r = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=timeout)
    if r is not None:
        r.encoding = 'gbk'
    return r


def fetch_metadata_69shu(url):
    try:
        r = _shu69_get(url)
        if r is None or r.status_code != 200:
            return None
        soup = parse_html(r.text)

        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover = ""
        cover_img = soup.select_one('div.cover > img, .book-img img')
        if cover_img:
            cover = cover_img.get('src') or cover_img.get('data-src') or ""
        cover = fix_image_url(cover, base_url=get_base_url(url))

        summary_div = soup.select_one('#bookIntro, .book-intro')
        description = summary_div.get_text("\n", strip=True) if summary_div else ""
        description = re.sub(r'^简介[:：]?\s*', '', description)

        author = ""
        status = "مستمرة"
        info_p = soup.select_one('div.caption-bookinfo p, .book-info')
        if info_p:
            a_tag = info_p.find('a')
            if a_tag:
                author = a_tag.get('title') or a_tag.get_text(strip=True)
            if '连载' not in info_p.get_text():
                status = "مكتملة"

        # معرف الكتاب لقائمة الفصول
        book_id_match = re.search(r'/txt/(\d+)', url)

        return {
            'title': title, 'description': description, 'cover': cover,
            'author': author, 'status': status, 'category': "عام", 'tags': [],
            'book_id': book_id_match.group(1) if book_id_match else None,
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error 69shu metadata: {e}")
        return None


def fetch_chapter_list_69shu(url):
    """قائمة الفصول: من صفحة الفهرس الكامل (مع ترقيم صفحات داخلي)"""
    chapters = []
    try:
        base = get_base_url(url)

        # 1. إيجاد رابط الفهرس الكامل (dd.all > a)
        r = _shu69_get(url)
        if r is None or r.status_code != 200:
            return []
        soup = parse_html(r.text)

        all_link = soup.select_one('dd.all > a')
        if not all_link or not all_link.get('href'):
            # جرّب مباشرة نمط /txt/{id}/all.html أو /txt/{id}.html
            m = re.search(r'/txt/(\d+)', url)
            if m:
                catalog_url = f"{base}/txt/{m.group(1)}/all.html"
            else:
                return []
        else:
            catalog_url = urljoin(base, all_link['href'])

        # 2. التنقل بين صفحات الفهرس
        current_url = catalog_url
        visited = set()
        while current_url and current_url not in visited:
            visited.add(current_url)
            rc = _shu69_get(current_url)
            if rc is None or rc.status_code != 200:
                break
            csoup = parse_html(rc.text)

            for dd in csoup.select('dl.panel-chapterlist dd'):
                a = dd.find('a')
                if not a or not a.get('href'):
                    continue
                href = a['href']
                full_link = href if href.startswith('http') else urljoin(base, href)
                title = a.get_text(strip=True)
                number = extract_chapter_number(title, full_link)
                if number > 0 and not any(c['number'] == number for c in chapters):
                    chapters.append({'number': number, 'url': full_link, 'title': title})

            # رابط الصفحة التالية (下一页)
            next_link = None
            for a in csoup.select('div.listpage a'):
                if '下一页' in a.get_text() and a.get('href') and 'javascript' not in a['href']:
                    next_link = urljoin(base, a['href'])
                    break
            current_url = next_link
            if current_url:
                time.sleep(0.5)

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ Total 69shu chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error 69shu chapter list: {e}")
        return chapters


def scrape_chapter_69shu(url):
    try:
        r = _shu69_get(url)
        if r is None or r.status_code != 200:
            return None
        soup = parse_html(r.text)

        content_div = soup.select_one('#chaptercontent') or soup.select_one('.txtnav')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()

        ps = content_div.find_all('p')
        if ps:
            lines = [p.get_text(strip=True) for p in ps]
        else:
            lines = content_div.get_text('\n').split('\n')

        lines = [ln.strip() for ln in lines]
        lines = [ln for ln in lines if ln and '69书吧' not in ln and '69書吧' not in ln]
        text = '\n\n'.join(lines)
        text = clean_text(text)

        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_69shu(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_69shu, scrape_chapter_69shu)


# ==========================================
# 📖 5. ixdzs8 (爱下电子书 - ixdzs8.com)
# ==========================================
# جديد ويعمل بالكامل! واجهة API للفصول + معالجة تحدي الأمان.

def fetch_metadata_ixdzs8(url):
    try:
        response = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('.n-text h1') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover = ""
        img_tag = soup.select_one('.n-img img')
        if img_tag:
            cover = img_tag.get('src') or ""
        cover = fix_image_url(cover, base_url='https://ixdzs8.com')

        intro = soup.select_one('p#intro')
        description = intro.get_text('\n', strip=True) if intro else ""

        status = "مستمرة"
        if soup.select_one('.n-text p span.end'):
            status = "مكتملة"

        tags = []
        for a in soup.select('div.panel div.tags a, .n-text .n-tag a'):
            txt = a.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        # معرف الكتاب من الرابط /read/{id}/ أو /baidu/{id}/
        book_match = re.search(r'/(?:read|baidu)/(\d+)', url)

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'book_id': book_match.group(1) if book_match else None,
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error ixdzs8 metadata: {e}")
        return None


def fetch_chapter_list_ixdzs8(url):
    """قائمة الفصول عبر POST /novel/clist/ (JSON)"""
    chapters = []
    try:
        book_match = re.search(r'/(?:read|baidu)/(\d+)', url)
        if not book_match:
            print("ixdzs8: cannot extract book id")
            return []
        book_id = book_match.group(1)

        resp = requests.post(
            'https://ixdzs8.com/novel/clist/',
            data=f'bid={book_id}',
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': UA_FIREFOX,
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"ixdzs8 clist failed: HTTP {resp.status_code}")
            return []

        data = resp.json()
        if data.get('rs') != 200 or not isinstance(data.get('data'), list):
            print("ixdzs8: invalid clist response")
            return []

        for ch in data['data']:
            try:
                order = int(ch.get('ordernum', 0))
            except (ValueError, TypeError):
                continue
            # فقط الفصول العادية (ctype=0)
            if str(ch.get('ctype', '0')) != '0':
                continue
            title = ch.get('title', f"第{order}章")
            chapters.append({
                'number': order,
                'url': f"https://ixdzs8.com/read/{book_id}/p{order}.html",
                'title': title,
            })

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ ixdzs8 chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error ixdzs8 chapter list: {e}")
        return chapters


def scrape_chapter_ixdzs8(url):
    """سحب فصل مع معالجة تحدي الأمان (?challenge=token)"""
    try:
        res = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=20)
        if res is None or res.status_code != 200:
            return None
        html = res.text

        # فحص صفحة التحدي
        if '正在進行安全驗證' in html or 'challenge' in html[:3000]:
            token_match = re.search(r'let token\s*=\s*"([^"]+)"', html)
            if token_match:
                challenge_url = url + '?challenge=' + token_match.group(1)
                res = http_get(challenge_url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=20)
                if res is None or res.status_code != 200:
                    return None
                html = res.text

        soup = parse_html(html)
        content = soup.select_one('article section')
        if not content:
            return None

        # تنظيف الإعلانات والعناصر الزائدة
        for bad in content.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()
        for p in content.find_all('p'):
            if not p.get_text(strip=True):
                p.decompose()

        text = content.get_text(separator='\n\n', strip=True)
        text = re.sub(r'推薦本書.*', '', text)
        text = clean_text(text)

        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_ixdzs8(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_ixdzs8, scrape_chapter_ixdzs8)


# ==========================================
# 🌸 6. Linovel (轻小说文库 - linovel.net)
# ==========================================
# جديد ويعمل بالكامل!

def fetch_metadata_linovel(url):
    try:
        response = http_get(url, lang=ZH_HEADERS_LANG, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('h1.book-title') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover = ""
        img_tag = soup.select_one('.book-cover img, div.cover img')
        if img_tag:
            cover = img_tag.get('src') or ""
        if not cover:
            cover = get_meta(soup, prop='og:image')
        cover = fix_image_url(cover, base_url='https://www.linovel.net')

        description = ""
        desc_div = soup.select_one('#bookSummary, .book-summary, .book-information .summary')
        if desc_div:
            description = desc_div.get_text('\n', strip=True)
        else:
            description = get_meta(soup, name='description')

        status = "مستمرة"
        page_text = soup.get_text()[:5000]
        if '完结' in page_text:
            status = "مكتملة"

        tags = []
        for a in soup.select('.book-info a[href*="/tags/"], .book-meta a[href*="tag"]'):
            txt = a.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error linovel metadata: {e}")
        return None


def fetch_chapter_list_linovel(url):
    chapters = []
    try:
        response = http_get(url, lang=ZH_HEADERS_LANG, timeout=15)
        if response is None or response.status_code != 200:
            return chapters
        soup = parse_html(response)

        base_url = get_base_url(url)
        seen = set()
        index = 0

        # قائمة الفصول داخل #chapter-list أو .chapter-list
        chapter_links = soup.select('#chapter-list a, .chapter-list a, .cate-item a')
        for a in chapter_links:
            href = a.get('href')
            if not href or not re.search(r'/book/\d+/\d+\.html', href):
                continue
            full_url = href if href.startswith('http') else urljoin(base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            index += 1
            raw_title = a.get_text(strip=True)
            clean_title = re.sub(r'^第\d+[章节]\s*', '', raw_title).strip() or raw_title

            # ✅ روابط linovel تستخدم معرفات غير متسلسلة - نعتمد الترتيب
            chapters.append({'number': index, 'url': full_url, 'title': clean_title})

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ linovel chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error linovel chapter list: {e}")
        return chapters


def scrape_chapter_linovel(url):
    try:
        response = http_get(url, lang=ZH_HEADERS_LANG, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.select_one('#aContent') or soup.select_one('.read-content')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()

        text = content_div.get_text(separator='\n\n', strip=True)
        text = re.sub(r'本章未完.*', '', text)
        text = clean_text(text)

        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_linovel(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_linovel, scrape_chapter_linovel)


# ==========================================
# 🇹🇼 7. Linovelib TW (轻小说文库繁体 - tw.linovelib.com)
# ==========================================
# جديد ويعمل بالكامل!

def fetch_metadata_linovelib_tw(url):
    try:
        response = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=15)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        title_tag = soup.select_one('h1.book-title') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"

        cover = ""
        img_tag = soup.select_one('.book-info img, .cover img')
        if img_tag:
            cover = img_tag.get('src') or img_tag.get('data-src') or ""
        if not cover:
            cover = get_meta(soup, prop='og:image')
        cover = fix_image_url(cover, base_url='https://tw.linovelib.com')

        description = ""
        desc_div = soup.select_one('.book-info .intro, #bookIntro, .book-intro')
        if desc_div:
            description = desc_div.get_text('\n', strip=True)
        else:
            description = get_meta(soup, name='description')

        status = "مستمرة"
        page_text = soup.get_text()[:5000]
        if '完結' in page_text or '完结' in page_text:
            status = "مكتملة"

        tags = []
        for a in soup.select('.book-info a[href*="/tags/"], .book-info a[href*="wenku"]'):
            txt = a.get_text(strip=True)
            if txt and len(txt) < 20:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        return {
            'title': title, 'description': description, 'cover': cover,
            'status': status, 'category': category, 'tags': tags,
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error linovelib_tw metadata: {e}")
        return None


def fetch_chapter_list_linovelib_tw(url):
    """قائمة الفصول من صفحة الفهرس /novel/{id}/catalog (بترقيم تسلسلي)"""
    chapters = []
    try:
        base_url = get_base_url(url)
        book_match = re.search(r'/novel/(\d+)', url)
        if not book_match:
            return []
        book_id = book_match.group(1)

        catalog_url = f"{base_url}/novel/{book_id}/catalog"
        response = http_get(catalog_url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=15)
        if response is None or response.status_code != 200:
            # جرّب صفحة الكتاب نفسها
            response = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=15)
            if response is None or response.status_code != 200:
                return []
        soup = parse_html(response)

        seen = set()
        index = 0
        for a in soup.find_all('a', href=True):
            href = a['href']
            # روابط الفصول: /novel/{id}/{cid}.html (نستثني vol_ و _N.html)
            if not re.search(rf'/novel/{book_id}/\d+\.html$', href):
                continue
            full_url = href if href.startswith('http') else urljoin(base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            index += 1
            raw_title = a.get_text(strip=True)
            clean_title = re.sub(r'^第\d+[章节][\s　]*', '', raw_title).strip() or raw_title

            # ✅ المعرف في الرابط غير متسلسل - نعتمد ترتيب الفهرس
            chapters.append({'number': index, 'url': full_url, 'title': clean_title})

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ linovelib_tw chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error linovelib_tw chapter list: {e}")
        return chapters


def scrape_chapter_linovelib_tw(url):
    """سحب فصل من linovelib TW مع دعم الفصول متعددة الصفحات (_2.html ...)"""
    try:
        all_text = []
        current_url = url
        visited = set()

        while current_url and current_url not in visited:
            visited.add(current_url)
            response = http_get(current_url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=15)
            if response is None or response.status_code != 200:
                break
            soup = parse_html(response)

            # ✅ الحاوية الصحيحة هي #acontent
            content_div = soup.select_one('#acontent') or soup.select_one('#cContent') or soup.select_one('#content')
            if content_div:
                for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
                    bad.decompose()
                txt = content_div.get_text(separator='\n\n', strip=True)
                if txt:
                    all_text.append(txt)

            # البحث عن صفحة تالية للفصل الواحد (chapter_2.html)
            next_url = None
            for a in soup.find_all('a', href=True):
                href = a['href']
                if re.search(r'_\d+\.html', href) and ('下一頁' in a.get_text() or '下一页' in a.get_text() or 'next' in a.get_text().lower()):
                    next_url = urljoin(current_url, href)
                    break
            current_url = next_url
            if current_url:
                time.sleep(0.5)

        text = clean_text('\n\n'.join(all_text))
        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_linovelib_tw(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_linovelib_tw, scrape_chapter_linovelib_tw)


# ==========================================
# 📚 8. Novel543 (novel543.com) - 稷下書院
# ==========================================
# جديد! الموقع من عائلة MTLNation بالتصميم البوليسار (Quasar).

def fetch_metadata_novel543(url):
    try:
        response = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=20)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        # العنوان من قسم التفاصيل
        title = ""
        info_h1 = soup.select_one('section#detail div.media-content.info h1.title') or soup.find('h1')
        if info_h1:
            title = info_h1.get_text(strip=True)
        if not title:
            title = get_meta(soup, prop='og:title') or "Unknown Title"

        cover = ""
        cover_img = soup.select_one('section#detail div.cover img')
        if cover_img:
            cover = cover_img.get('src') or ""
        if not cover:
            cover = get_meta(soup, prop='og:image')
        cover = fix_image_url(cover, base_url='https://www.novel543.com')

        description = ""
        intro_div = soup.select_one('section#detail div.mod div.intro')
        if intro_div:
            description = intro_div.get_text('\n', strip=True)
        else:
            description = get_meta(soup, name='description')

        author = ""
        author_span = soup.select_one('section#detail p.meta span.author')
        if author_span:
            author = author_span.get_text(strip=True)

        tags = []
        for a in soup.select('section#detail p.meta a[href*="/bookstack/"]'):
            txt = a.get_text(strip=True)
            if txt:
                tags.append(txt)
        category = tags[0] if tags else "عام"

        status = "مستمرة"
        page_text = soup.get_text()[:6000]
        if '完結' in page_text or '完结' in page_text:
            status = "مكتملة"

        return {
            'title': title, 'description': description, 'cover': cover,
            'author': author, 'status': status, 'category': category, 'tags': tags,
            'sourceUrl': url,
            'lastUpdate': None
        }
    except Exception as e:
        print(f"Error novel543 metadata: {e}")
        return None


def fetch_chapter_list_novel543(url):
    """قائمة الفصول: من رابط الفهرس ({id}/dir) داخل صفحة الرواية"""
    chapters = []
    try:
        base_url = get_base_url(url)
        response = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=20)
        if response is None or response.status_code != 200:
            return []
        soup = parse_html(response)

        # البحث عن رابط الفهرس (ينتهي بـ /dir)
        catalog_link = None
        for a in soup.select('a[href]'):
            href = a['href']
            if href.rstrip('/').endswith('/dir'):
                catalog_link = urljoin(base_url, href)
                break

        if not catalog_link:
            # بناء الرابط مباشرة من معرف الرواية /{id}/
            m = re.search(r'novel543\.com/(\d+)/?', url)
            if m:
                catalog_link = f"{base_url}/{m.group(1)}/dir"
            else:
                return []

        # جلب صفحة الفهرس
        r2 = http_get(catalog_link, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=20)
        if r2 is None or r2.status_code != 200:
            return []
        csoup = parse_html(r2.text)

        index = 0
        for a in csoup.select('div.chaplist ul.all li a'):
            href = a.get('href')
            if not href:
                continue
            index += 1
            full_url = href if href.startswith('http') else urljoin(base_url, href)
            title = a.get_text(strip=True) or f"第{index}章"
            chapters.append({'number': index, 'url': full_url, 'title': title})

        # فحص ترتيب القائمة (倒序 = عكسي)
        sort_btn = csoup.select_one('div.chaplist .header button.reverse span:last-child')
        if sort_btn and sort_btn.get_text(strip=True) == '倒序' and chapters:
            # القائمة معروضة من الأحدث؛ نرتّبها تصاعدياً حسب الرقم
            chapters.reverse()

        chapters.sort(key=lambda x: x['number'])
        print(f"✅ novel543 chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error novel543 chapter list: {e}")
        return chapters


def scrape_chapter_novel543(url):
    try:
        response = http_get(url, ua=UA_FIREFOX, lang=ZH_HEADERS_LANG, timeout=20)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        content_div = soup.select_one('div.content.py-5') or soup.select_one('.chap-content')
        if not content_div:
            return None

        for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
            bad.decompose()

        lines = []
        for p in content_div.find_all('p'):
            txt = p.get_text(strip=True)
            if not txt:
                continue
            if any(k in txt for k in ['請記住本站域名', '手機版閱讀網址', 'novel543', '稷下書院']):
                continue
            lines.append(txt)

        text = '\n\n'.join(lines)
        text = clean_text(text)

        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_novel543(url, admin_email, metadata):
    generic_worker(url, admin_email, metadata, fetch_chapter_list_novel543, scrape_chapter_novel543)


# ==========================================
# 📋 تسجيل المواقع الصينية
# ==========================================

register_site(
    domain_patterns=['quanben.io'],
    name='Quanben (全本网)',
    language='chinese',
    fetch_metadata=fetch_metadata_quanben,
    fetch_chapters=fetch_chapter_list_quanben,
    fetch_content=scrape_chapter_quanben,
    worker=worker_quanben,
    status='active',
    notes='يعمل عبر التوجيه الذكي (بروكسي ترجمة جوجل) رغم حجب IP السيرفرات. قائمة الفصول في /n/{slug}/list.html.'
)

register_site(
    domain_patterns=['52shuku.net'],
    name='52shuku (52书库)',
    language='chinese',
    fetch_metadata=fetch_metadata_52shuku,
    fetch_chapters=fetch_chapter_list_52shuku,
    fetch_content=scrape_chapter_52shuku,
    worker=worker_52shuku,
    status='active',
    notes='تم إعادة كتابته بالكامل للتصميم الجديد: الكتاب /{تصنيف}/{id}.html والفصول صفحات متتابعة.'
)

register_site(
    domain_patterns=['erciyan.com', '2cyxsw.net'],
    name='ErCiYuan (二次元小说网)',
    language='chinese',
    fetch_metadata=fetch_metadata_erciyuan,
    fetch_chapters=fetch_chapter_list_erciyuan,
    fetch_content=scrape_chapter_erciyuan,
    worker=worker_erciyuan,
    status='active',
    notes='WAF كابتشا من IP السيرفرات — يعمل عبر التوجيه الذكي. روابط الفصول تشير لموقع الشقيق 2cyxsw.net (مسجل أيضاً).'
)

register_site(
    domain_patterns=['69shu.xyz', '69shu.com', '69shuba.com', '69shuba.cx'],
    name='69shu / 69shuba (69书吧)',
    language='chinese',
    fetch_metadata=fetch_metadata_69shu,
    fetch_chapters=fetch_chapter_list_69shu,
    fetch_content=scrape_chapter_69shu,
    worker=worker_69shu,
    status='active',
    notes='جديد (من LNReader)! دعم الدومينات المتعددة + ترميز GBK. Cloudflare يظهر أحياناً من IP السيرفرات.'
)

register_site(
    domain_patterns=['ixdzs8.com'],
    name='ixdzs8 (爱下电子书)',
    language='chinese',
    fetch_metadata=fetch_metadata_ixdzs8,
    fetch_chapters=fetch_chapter_list_ixdzs8,
    fetch_content=scrape_chapter_ixdzs8,
    worker=worker_ixdzs8,
    status='active',
    notes='جديد (من LNReader)! يعمل بالكامل - واجهة API للفصول + معالجة تحدي الأمان.'
)

register_site(
    domain_patterns=['linovel.net'],
    name='Linovel (轻小说文库)',
    language='chinese',
    fetch_metadata=fetch_metadata_linovel,
    fetch_chapters=fetch_chapter_list_linovel,
    fetch_content=scrape_chapter_linovel,
    worker=worker_linovel,
    status='active',
    notes='جديد (من LNReader)! يعمل بالكامل - بيانات + فصول + محتوى.'
)

register_site(
    domain_patterns=['tw.linovelib.com', 'linovelib.com', 'bilinovel.com'],
    name='Linovelib TW (轻小说文库繁體)',
    language='chinese',
    fetch_metadata=fetch_metadata_linovelib_tw,
    fetch_chapters=fetch_chapter_list_linovelib_tw,
    fetch_content=scrape_chapter_linovelib_tw,
    worker=worker_linovelib_tw,
    status='active',
    notes='جديد (من LNReader)! النسخة التقليدية (繁體) تعمل بالكامل عبر صفحة catalog.'
)

register_site(
    domain_patterns=['novel543.com'],
    name='Novel543 (稷下書院)',
    language='chinese',
    fetch_metadata=fetch_metadata_novel543,
    fetch_chapters=fetch_chapter_list_novel543,
    fetch_content=scrape_chapter_novel543,
    worker=worker_novel543,
    status='active',
    notes='جديد (من LNReader)! فهرس عبر /{id}/dir. Cloudflare متقلب أحياناً من IP السيرفرات.'
)


# ==========================================
# 📖 9. Twkan (twkan.com / twkan.cc) - 台灣小說網
# ==========================================
# نطاقان لنفس قاعدة البيانات لكن بقالبين مختلفين تماماً:
#
#   twkan.cc (قالب جديد) — مفتوح حالياً ويعمل مباشرة (موصى به):
#     كتاب /book/{نص}.html | فهرس /chapter/{id}.html + ترقيم /{صفحة}.html
#     فصل /chapter/{id}/{ch}.html | المحتوى div#content بفقرات <p>
#     المحددات: h1.booktitle، p.booktag (a.red مؤلف / a.blue تصنيف / span.red حالة)،
#               p.bookintro، img.thumbnail
#
#   twkan.com (قالب جيتشي القديم) — خلف Cloudflare صارم: تحدي مُدار + صفحات خداع
#     تُرجع محتوى 200 مزيف حتى لبروكسي ترجمة جوجل ("Leap of Faith...") → كل
#     الطلبات عبر smart_get مع كاشف الخداع؛ من IP مراكز البيانات يحتاج
#     FLARESOLVR_URL أو SCRAPERAPI_KEY:
#     كتاب /book/{رقم}.html (h1>a، المؤلف /author/..، التصنيف /novels/class/..،
#               الغلاف og:image، الوصف og:description)
#     الفهرس الكامل: /ajax_novels/chapterlist/{id}.html (li data-num > a مطلقة /txt/{id}/{ch})
#     الفصل /txt/{id}/{ch} — المحتوى div#txtcontent0 بنص <br> (لا يوجد تقسيم داخلي)

TWKAN_MAX_LIST_PAGES = 120  # شبكة أمان لترقيم فهرس twkan.cc (501 فصلاً/صفحة)


def _twkan_true_number(title, fallback):
    """الرقم الحقيقي للفصل من عنوانه (第N章) بدل الترقيم التسلسلي.
    يلغي انحراف الترقيم بين قائمة twkan.com وتوأمها twkan.cc:
    القائمتان تختلفان في عدد الانقسامات (1144 مقابل 1147 مدخلاً لنفس الرواية)
    فكان الاستئناف يقفز/يكرر فصولاً. الفصول بلا رقم في العنوان (خاتمة/خارجية)
    تأخذ الترقيم التسلسلي كاحتياط."""
    try:
        m = re.search(r'第\s*(\d+)\s*[章回节節]', title or '')
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return fallback


def _twkan_validate(body):
    """كاشف صفحات الخداع/التحدي — يقبل القالبين ويرفض أي صفحة بلا بصمة الموقع"""
    if not body:
        return False
    if '台灣小說網' not in body:
        return False
    # صفحات القالب الجديد: صفحة كتاب (booktitle/readcontent) أو فصل (id="content")
    # أو صفحات فهرس الفصول (روابط /chapter/) أو قالب جيتشي القديم (روابط /txt/ ...)
    if any(m in body for m in ('/chapter/', 'booktitle', 'readcontent', 'id="content"')):
        return True
    return any(m in body for m in ('txtcontent', '/txt/', 'novels/class',
                                   'ajax_novels', 'files/article'))


def _twkan_get(url, timeout=30):
    """طلب موحّد عبر التوجيه الذكي مع كاشف الخداع (عناوين تقليدية zh-TW)"""
    return smart_get(url, sl='zh-TW', tl='en', lang='zh-TW,zh;q=0.9,en;q=0.5',
                     timeout=timeout, validate=_twkan_validate, ua=UA_FIREFOX)


def _twkan_is_new_style(url):
    """twkan.cc = القالب الجديد، ما عدا ذلك = قالب جيتشي القديم"""
    return 'twkan.cc' in (urlparse(url).netloc.lower())


def _twkan_book_id(url):
    """معرف الكتاب من أي رابط (كتاب/فصل/فهرس) — يدعم الصيغتين"""
    m = re.search(r'/book/([0-9A-Za-z]+)\.html', url)
    if m:
        return m.group(1)
    m = re.search(r'/chapter/([0-9A-Za-z]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/txt/(\d+)/', url)
    if m:
        return m.group(1)
    return None


def _twkan_book_url(url):
    """تحويل أي رابط إلى رابط صفحة الكتاب على نفس النطاق"""
    bid = _twkan_book_id(url)
    if not bid:
        return url
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/book/{bid}.html"


def _twkan_meta_new(soup, book_url):
    """استخراج البيانات من قالب twkan.cc الجديد"""
    title_tag = soup.select_one('h1.booktitle') or soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        return None

    cover = ""
    img_tag = soup.select_one('img.thumbnail') or soup.select_one('.book img')
    if img_tag:
        cover = img_tag.get('src') or img_tag.get('data-src') or ""
    if not cover:
        cover = get_meta(soup, prop='og:image') or ""
    cover = fix_image_url(cover, base_url=book_url)

    author, category, status = "", "عام", "مستمرة"
    tag_p = soup.select_one('p.booktag')
    if tag_p:
        a_red = tag_p.select_one('a.red')
        if a_red:
            author = a_red.get_text(strip=True)
        a_blue = tag_p.select_one('a.blue')
        if a_blue and a_blue.get_text(strip=True):
            category = a_blue.get_text(strip=True)
        for sp in tag_p.find_all('span'):
            st = sp.get_text(strip=True)
            if '完結' in st or '完结' in st:
                status = "مكتملة"
                break

    desc_p = soup.select_one('p.bookintro')
    description = desc_p.get_text('\n', strip=True) if desc_p \
        else (get_meta(soup, name='description') or "")
    # إزالة جُمل الدعاية الختامية المضافة من الموقع نفسه
    description = re.sub(r'本書由[^。]*呈現[^。]*。?', '', description).strip()
    description = re.sub(r'《[^》]+》是作家「[^」]*」傾力打造[^。]*。?', '', description).strip()

    tags = [category] if category and category != "عام" else []
    return {'title': title, 'description': description, 'cover': cover,
            'author': author, 'status': status, 'category': category, 'tags': tags}


def _twkan_meta_old(soup, book_url):
    """استخراج البيانات من قالب twkan.com (جيتشي)"""
    h1 = soup.find('h1')
    title = h1.get_text(strip=True) if h1 else ""
    if not title:
        return None

    cover = get_meta(soup, prop='og:image') or ""
    cover = fix_image_url(cover, base_url=book_url)

    author = ""
    a_author = soup.select_one('a[href*="/author/"]')
    if a_author:
        author = a_author.get_text(strip=True)

    category = "عام"
    a_cat = soup.select_one('a[href*="/novels/class/"]')
    if a_cat and a_cat.get_text(strip=True):
        category = a_cat.get_text(strip=True)

    # الحالة من فقرة المعلومات نفسها (تحتوي 萬字) — لا من الصفحة كلها
    # (الشريط الجانبي يعرض كتباً مكتملة فيلوّث الفحص الشامل)
    status = "مستمرة"
    for p in soup.find_all('p'):
        pt = p.get_text()
        if '萬字' in pt or '万字' in pt:
            if '完結' in pt or '完结' in pt or '完本' in pt:
                status = "مكتملة"
            break

    # الوصف الحقيقي في og:description (بفواصل <br />)
    description = get_meta(soup, prop='og:description') or ""
    description = description.replace('<br />', '\n').replace('<br>', '\n').strip()
    if not description:
        description = get_meta(soup, name='description') or ""

    tags = [category] if category and category != "عام" else []
    return {'title': title, 'description': description, 'cover': cover,
            'author': author, 'status': status, 'category': category, 'tags': tags}


def _twkan_cover_via_twin(title, book_url):
    """غلاف بديل من التوأم twkan.cc — غلاف twkan.com محجوب بـ Cloudflare
    (403 حتى للسيرفر وCloudinary) بينما CDN التوأم img.cuoceng.com مفتوح"""
    try:
        host = (urlparse(book_url).netloc or '').lower()
        if 'twkan.cc' in host:
            return ""  # غلاف .cc يعمل مباشرة — لا حاجة للتوأم
        twin = _twkan_find_cc_twin(title or '')
        if not twin:
            return ""
        r = _twkan_get(twin)
        if r is None or r.status_code != 200:
            return ""
        soup = parse_html(r)
        img = soup.select_one('div.bookcover img') or soup.select_one('img.thumbnail')
        if img:
            return (img.get('src') or img.get('data-src') or '').strip()
    except Exception:
        return ""
    return ""


def fetch_metadata_twkan(url):
    try:
        book_url = _twkan_book_url(url)
        response = _twkan_get(book_url)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)
        # كشف القالب صراحةً: booktag/booktitle = قالب .cc الجديد، وإلا جرّب جيتشي
        meta = None
        if soup.select_one('p.booktag') or soup.select_one('h1.booktitle'):
            meta = _twkan_meta_new(soup, book_url)
        if meta is None:
            meta = _twkan_meta_old(soup, book_url)
        if meta:
            meta['sourceUrl'] = book_url
            meta['lastUpdate'] = None
            # 🔥 غلاف twkan.com محجوب بـ Cloudflare (403 للسيرفر والتطبيق معاً)
            # → استبدله بغلاف التوأم من CDN twkan.cc المفتوح
            if meta.get('cover') and 'twkan.com' in str(meta.get('cover', '')):
                twin_cover = _twkan_cover_via_twin(meta.get('title', ''), book_url)
                if twin_cover:
                    print("   🖼️ cover blocked by Cloudflare — using twin CDN cover")
                    meta['cover'] = twin_cover
        return meta
    except Exception as e:
        print(f"Error twkan metadata: {e}")
        return None


def _twkan_chapters_new(url, bid):
    """فهرس twkan.cc: صفحات متتابعة /chapter/{id}[/{صفحة}].html"""
    base = get_base_url(url)
    bid_q = re.escape(bid)
    chapters, seen, used_nums = [], set(), set()
    index = 0
    page_no = 1
    while page_no <= TWKAN_MAX_LIST_PAGES:
        list_url = f"{base}/chapter/{bid}.html" if page_no == 1 \
            else f"{base}/chapter/{bid}/{page_no}.html"
        response = _twkan_get(list_url)
        if response is None or response.status_code != 200:
            break
        soup = parse_html(response)

        page_new = 0
        for a in soup.find_all('a', href=True):
            href = a['href']
            m = re.search(rf'/chapter/{bid_q}/([0-9A-Za-z]+)\.html$', href)
            if not m:
                continue
            full = urljoin(base, href)
            if full in seen:
                continue
            seen.add(full)
            title = a.get_text(strip=True)
            index += 1
            page_new += 1
            # الرقم الحقيقي من العنوان — يوحّد الترقيم مع twkan.com
            num = _twkan_true_number(title, index)
            while num in used_nums:
                num += 1
            used_nums.add(num)
            chapters.append({'number': num, 'url': full, 'title': title})

        if page_new == 0:
            break  # لا فصول جديدة = آخر صفحة
        page_no += 1
        time.sleep(0.4)  # مهلة أدب بين صفحات الفهرس

    return chapters


def _twkan_chapters_old(url, bid):
    """فهرس twkan.com الكامل: /ajax_novels/chapterlist/{id}.html (روابط مطلقة)"""
    base = get_base_url(url)
    list_url = f"{base}/ajax_novels/chapterlist/{bid}.html"
    response = _twkan_get(list_url, timeout=40)
    if response is None or response.status_code != 200:
        print(f"   ⚠️ twkan.com AJAX list failed ({list_url})")
        return []
    soup = parse_html(response)

    chapters, seen, used_nums = [], set(), set()
    index = 0
    for a in soup.find_all('a', href=True):
        href = a['href']
        m = re.search(rf'/txt/{re.escape(bid)}/(\d+)$', href)
        if not m:
            continue
        full = urljoin(base, href)
        if full in seen:
            continue
        seen.add(full)
        title = a.get_text(strip=True)
        index += 1
        # الرقم الحقيقي من العنوان — يوحّد الترقيم مع التوأم ويمنع فجوات الاستئناف
        num = _twkan_true_number(title, index)
        while num in used_nums:
            num += 1
        used_nums.add(num)
        chapters.append({'number': num, 'url': full, 'title': title})

    print(f"   📋 twkan.com AJAX list parsed: {len(chapters)} chapters")
    return chapters


def _twkan_find_cc_twin(title):
    """البحث عن توأم الكتاب على twkan.cc (نفس قاعدة البيانات، بدون حماية)
    يُستخدم عندما يمنع خداع Cloudflare فهرس twkan.com — يعيد رابط .cc أو None"""
    try:
        from urllib.parse import quote
        q = quote((title or '').strip())
        if not q:
            return None
        r = _twkan_get(f"https://twkan.cc/search/{q}.html")
        if r is None or r.status_code != 200:
            return None
        soup = parse_html(r)
        target = re.sub(r'\s+', '', title)
        for a in soup.find_all('a', href=True):
            m = re.search(r'/book/([0-9A-Za-z]+)\.html$', a['href'])
            if not m:
                continue
            t = re.sub(r'\s+', '', a.get_text(strip=True))
            if t and t == target:
                return f"https://twkan.cc/book/{m.group(1)}.html"
        return None
    except Exception:
        return None


def fetch_chapter_list_twkan(url):
    try:
        bid = _twkan_book_id(url)
        if not bid:
            return []
        chapters = _twkan_chapters_new(url, bid) if _twkan_is_new_style(url) \
            else _twkan_chapters_old(url, bid)
        print(f"✅ twkan chapters found: {len(chapters)}")
        return chapters
    except Exception as e:
        print(f"Error twkan chapter list: {e}")
        return []


def scrape_chapter_twkan(url):
    """سحب محتوى فصل — يدعم القالبين (div#content أو div#txtcontent*)"""
    try:
        base = get_base_url(url)
        response = _twkan_get(url)
        if response is None or response.status_code != 200:
            return None
        soup = parse_html(response)

        parts = []
        # القالب الجديد: حاوية واحدة
        content_div = soup.select_one('div#content') or soup.select_one('div.readcontent')
        if content_div is not None:
            for bad in content_div.find_all(['script', 'style', 'ins', 'iframe']):
                bad.decompose()
            for a in content_div.find_all('a'):
                a.unwrap()
            txt = content_div.get_text(separator='\n\n', strip=True)
            if txt:
                parts.append(txt)
        else:
            # قالب جيتشي: txtcontent0 (+ أي أجزاء إضافية نظرياً) بنص <br>
            for div in soup.select('div[id^="txtcontent"]'):
                for bad in div.find_all(['script', 'style', 'ins', 'iframe']):
                    bad.decompose()
                for a in div.find_all('a'):
                    a.unwrap()
                txt = div.get_text(separator='\n', strip=True)
                if txt:
                    parts.append(txt)

        text = clean_text('\n\n'.join(parts))
        if len(text.strip()) < 50:
            return None
        return text
    except Exception:
        return None


def worker_twkan(url, admin_email, metadata):
    """عامل مخصص: منطق generic_worker + ذكاء إضافي —
    إذا حجب خداع Cloudflare فهرس twkan.com، يبحث عن توأم الكتاب على twkan.cc
    (نفس قاعدة البيانات، مفتوح بدون حماية) ويسحب الفصول والمحتوى منه مباشرة.
    مقاوم للأعطال: إيقاع بشري بين الفصول (يمنع تشغيل تحديات Cloudflare)،
    تهدئة متصاعدة عند التعثر، إعادة محاولة الإرسال، سجل صريح لكل فشل،
    توقف آمن بدل التسريب الصامت للحزم — الفصول غير المرسلة يعيد السكرابر
    سحبها في الجولة القادمة."""
    from core.backend import send_data_to_backend, check_existing_chapters

    BATCH_SIZE = 5

    def _send_batch(payload, first_num, last_num, attempts=3):
        """إرسال حزمة مع إعادة محاولة وتراجع زمني — فشل صامت = فصول ضائعة للأبد"""
        delays = [5, 15]
        for attempt in range(1, attempts + 1):
            try:
                if send_data_to_backend(payload):
                    return True
                print(f"   ⚠️ backend refused batch [{first_num}-{last_num}] "
                      f"(attempt {attempt}/{attempts}) — HTTP not 200")
            except Exception as e:
                print(f"   ⚠️ backend send error [{first_num}-{last_num}] "
                      f"(attempt {attempt}/{attempts}): {e}")
            if attempt < attempts:
                time.sleep(delays[min(attempt - 1, len(delays) - 1)])
        print(f"   🛑 BACKEND UNREACHABLE after {attempts} attempts — chapters "
              f"[{first_num}-{last_num}] NOT saved. Stopping worker safely; "
              f"these chapters will be re-scraped on the next run.")
        return False

    try:
        existing_chapters = check_existing_chapters(metadata['title'])
    except Exception:
        existing_chapters = []
    existing_set = set(existing_chapters)
    skip_meta = len(existing_chapters) > 0

    if existing_chapters:
        print(f"📚 Novel exists in app DB: {len(existing_chapters)} chapters "
              f"(max #{max(existing_chapters)}) — skipping them, resuming the gaps")

    send_data_to_backend({'adminEmail': admin_email, 'novelData': metadata,
                          'chapters': [], 'skipMetadataUpdate': skip_meta})

    bid = _twkan_book_id(url)
    all_chapters = []
    if _twkan_is_new_style(url):
        all_chapters = _twkan_chapters_new(url, bid)
    else:
        all_chapters = _twkan_chapters_old(url, bid)
        if not all_chapters and bid:
            print("   ↪️ twkan.com index blocked/decoyed — trying twkan.cc twin ...")
            twin = _twkan_find_cc_twin(metadata.get('title', ''))
            if twin:
                print(f"   ✅ twin found: {twin}")
                all_chapters = _twkan_chapters_new(twin, _twkan_book_id(twin))

    if not all_chapters:
        print(f"No chapters found for {metadata['title']}")
        return

    to_scrape = [c for c in all_chapters if c['number'] not in existing_set]
    skipped = len(all_chapters) - len(to_scrape)
    print(f"Processing {len(all_chapters)} chapters — "
          f"{skipped} already in DB, {len(to_scrape)} to scrape now.")

    stats = {'scraped': 0, 'failed': 0, 'sent': 0, 'batches': 0}
    batch = []
    consec_fail = 0

    # ⏱️ إيقاع بشري: السرعة الآلية (5 فصول/ثانية) هي ما يشغّل تحديات
    # Cloudflare بعد ~20 طلباً من IP مراكز البيانات (مؤكد بالفحص الحي:
    # بصمة python مكشوفة تُقابل بصفحات challenge-platform 200 مزيفة).
    # مهلة عشوائية بين الفصول تخفي الطبيعة الآلية للطلبات.
    delay_min = float(os.environ.get('TWKAN_DELAY_MIN', '1.2') or 1.2)
    delay_max = float(os.environ.get('TWKAN_DELAY_MAX', '2.5') or 2.5)
    slow_left = 0  # فصول متبقية بالأداء البطيء بعد أي تعثر (استشفاء لطيف)
    print(f"⏱️ twkan pacing: {delay_min}-{delay_max}s between chapters "
          f"(tune via env: TWKAN_DELAY_MIN / TWKAN_DELAY_MAX)")

    def _flush():
        """إرسال الحزمة الحالية؛ عند فشل مستمر يتوقف العامل بأمان بدل مواصلة السحب بلا فائدة"""
        if not batch:
            return True
        nums = [c['number'] for c in batch]
        payload = {'adminEmail': admin_email, 'novelData': metadata,
                   'chapters': list(batch), 'skipMetadataUpdate': True}
        if _send_batch(payload, min(nums), max(nums)):
            stats['sent'] += len(batch)
            stats['batches'] += 1
            batch.clear()
            time.sleep(1.0)
            return True
        return False

    for idx, chap in enumerate(to_scrape):
        if idx:
            mult = 2.5 if slow_left > 0 else 1.0
            if slow_left > 0:
                slow_left -= 1
            time.sleep(random.uniform(delay_min, delay_max) * mult)
        print(f"Scraping {metadata.get('title', '?')}: Ch {chap['number']}...")
        try:
            content = scrape_chapter_twkan(chap['url'])
        except Exception as e:
            print(f"   ❌ content exception: {e}")
            content = None

        # إعادة محاولة واحدة بعد مهلة قصيرة (أخطاء عابرة/خداع متقطع)
        if not content:
            time.sleep(2)
            try:
                content = scrape_chapter_twkan(chap['url'])
            except Exception:
                content = None

        if content:
            if consec_fail >= 3:
                print(f"   💚 recovered at Ch {chap['number']} after {consec_fail} "
                      f"consecutive failures — keeping a slow pace for a while")
            stats['scraped'] += 1
            consec_fail = 0
            batch.append({'number': chap['number'], 'title': chap['title'],
                          'content': content})
            if len(batch) >= BATCH_SIZE and not _flush():
                return
        else:
            stats['failed'] += 1
            consec_fail += 1
            slow_left = 10
            print(f"   ❌ Ch {chap['number']}: content failed "
                  f"(consecutive: {consec_fail}) — chapter skipped this run")
            if consec_fail >= 3:
                # تهدئة متصاعدة 20/40/80/160/160... — نوافذ تحديد المعدل في
                # Cloudflare عادةً دقائق، فالصبر الطويل هنا ينقذ الجولة
                # بدل قطعها مبكراً بينما الاستئناف سيكرر نفس العائق لاحقاً
                cd = min(20 * (2 ** (consec_fail - 3)), 160)
                print(f"   😴 cooling down {cd}s (possible rate-limit) ...")
                time.sleep(cd)
            if consec_fail >= 8:
                print(f"🛑 8 consecutive content failures — aborting. "
                      f"scraped={stats['scraped']}, failed={stats['failed']}. "
                      f"Next run resumes the gaps. "
                      f"(للحجب العنيد: FLARESOLVR_URL أو SCRAPERAPI_KEY أو CF_WORKER_URL)")
                _flush()  # لا نرمي الفصول الناجحة المتراكمة — نرسلها قبل التوقف
                return

    _flush()
    print(f"✅ twkan worker finished: scraped={stats['scraped']} "
          f"sent={stats['sent']} failed={stats['failed']} "
          f"skipped(existing)={skipped} batches={stats['batches']}")


register_site(
    domain_patterns=['twkan.com', 'twkan.cc'],
    name='Twkan (台灣小說網)',
    language='chinese',
    fetch_metadata=fetch_metadata_twkan,
    fetch_chapters=fetch_chapter_list_twkan,
    fetch_content=scrape_chapter_twkan,
    worker=worker_twkan,
    status='active',
    notes='نطاقان لقاعدة بيانات واحدة بقالبين: twkan.cc (جديد، يعمل مباشرة — موصى به) '
          'وtwkan.com (جيتشي قديم، خلف Cloudflare صارم بتحدي مُدار وصفحات خداع 200 مزيفة) '
          'يُتعامل معه عبر smart_get (انتحال بصمة curl_cffi + كاشف الخداع)، ومن IP مراكز '
          'البيانات يحتاج FLARESOLVR_URL أو SCRAPERAPI_KEY أو CF_WORKER_URL. الفهرس الكامل '
          'على .com عبر /ajax_novels/chapterlist/{id}.html. السحب بإيقاع بشري '
          '(TWKAN_DELAY_MIN/MAX) + تهدئة متصاعدة لمقاومة تحديد المعدل.'
)
