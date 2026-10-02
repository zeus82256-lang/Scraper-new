# -*- coding: utf-8 -*-
"""
==========================================
🕷️ ZEUS Novel Scraper v2.0 (Restructured)
==========================================
نقطة الدخول الرئيسية للسكرابر (Flask).

البنية الجديدة:
├── main.py               ← أنت هنا (المدخل + الراوتر)
├── core/
│   ├── config.py         ← الإعدادات والمفاتيح والكوكيز
│   ├── utils.py          ← أدوات مشتركة + قالب Madara العام
│   ├── backend.py        ← الاتصال بخادم Node.js
│   └── registry.py       ← سجل المواقع (التوجيه حسب النطاق)
├── sites/
│   ├── arabic.py         ← المواقع العربية
│   ├── english.py        ← المواقع الإنجليزية
│   ├── chinese.py        ← المواقع الصينية
│   └── korean.py         ← المواقع الكورية

التوافق الكامل مع التطبيق:
- POST /scrape            {url, adminEmail}      (نفس العقد القديم)
- POST /scheduler/config  {active, interval, adminEmail}
- GET  /scheduler/status
- GET  /sites              (جديد: قائمة المواقع المدعومة)
- POST /scraperapi/keys   {keys: [...]}          (جديد: مفاتيح ScraperAPI متعددة)
- GET  /scraperapi/keys                          (جديد: ملخص حالة المفاتيح)
- POST /tomatomtl/cookies {cookies}              (جديد: كوكيز حساب TomatoMTL)
- GET  /tomatomtl/cookies                        (جديد: ملخص مخفى للكوكيز)
- POST /tomatomtl/check                          (جديد: فحص حي لجلسة الحساب)
- POST /wtrlab/cookies {cookies}                 (جديد: كوكيز حساب WTR-LAB)
- GET  /wtrlab/cookies                           (جديد: ملخص مخفى للكوكيز)
- POST /wtrlab/check                             (جديد: فحص حي لجلسة القراءة)
- POST /tadu/cookies {cookies}                   (جديد: كوكيز اختيارية لتوسيع قراءة Tadu)
- GET  /tadu/cookies                             (جديد: ملخص مخفى للكوكيز)
- POST /tadu/check                               (جديد: فحص حي — هل القراءة موسّعة؟)
- POST /jhbook/cookies {cookies}                 (جديد: كوكيز جلسة تاوباو لقراءة الفصول)
- GET  /jhbook/cookies                           (جديد: ملخص مخفى للكوكيز)
- POST /jhbook/check                             (جديد: فحص حي لجلسة القراءة)
"""

import time
import threading
import traceback

from flask import Flask, request, jsonify
from flask_cors import CORS

from core.config import API_SECRET, SCHEDULER_CONFIG
from core.registry import resolve_site, get_registry
from core.backend import send_data_to_backend, check_existing_chapters  # noqa: F401
from core.utils import generic_worker  # noqa: F401

# استيراد حزمة المواقع يسجّل كل المواقع في السجل
import sites  # noqa: F401

# ==========================================
# ⚙️ إعداد التطبيق
# ==========================================
app = Flask(__name__)
CORS(app)


# ==========================================
# 🩺 فحص الصحة
# ==========================================
@app.route('/', methods=['GET'])
def health_check():
    registry = get_registry()
    active = sum(1 for s in registry if s['status'] == 'active')
    return jsonify({
        'service': 'ZEUS Novel Scraper v2.0 (Multi-Language)',
        'status': 'running',
        'total_sites': len(registry),
        'active_sites': active,
        'languages': ['arabic', 'english', 'chinese', 'korean'],
    }), 200


@app.route('/health', methods=['GET'])
def health_check_plain():
    return "ZEUS Scraper Service is Running", 200


# ==========================================
# 📚 قائمة المواقع المدعومة (جديد)
# ==========================================
@app.route('/sites', methods=['GET'])
def list_sites():
    return jsonify(get_registry()), 200


# ==========================================
# 🛰️ مفاتيح ScraperAPI (من واجهة التطبيق)
# ==========================================
# POST /scraperapi/keys  {keys: [...]} أو {text: "k1\nk2\nk3"} — ضبط/تحديث المفاتيح
# GET  /scraperapi/keys                    — ملخص حالات المفاتيح (مخفاة)
@app.route('/scraperapi/keys', methods=['POST'])
def set_scraperapi_keys_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from core.utils import set_scraperapi_keys, get_scraperapi_status
        data = request.json or {}
        keys = data.get('keys') or data.get('text') or ''
        saved = set_scraperapi_keys(keys)
        return jsonify({
            'message': f'ScraperAPI keys updated: {len(saved)} valid key(s)',
            'status': get_scraperapi_status(),
        }), 200
    except Exception as e:
        return jsonify({'message': 'Internal Server Error', 'details': str(e)}), 500


@app.route('/scraperapi/keys', methods=['GET'])
def get_scraperapi_keys_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    from core.utils import get_scraperapi_status
    return jsonify(get_scraperapi_status()), 200


# ==========================================
# 🍪 كوكيز TomatoMTL (حساب قارئ tomatomtl.com — من واجهة الموقع/التطبيق)
# ==========================================
# POST /tomatomtl/cookies {cookies: "name=v; ..."} — ضبط/تحديث (فارغ = الرجوع للثابتة بالكود)
# GET  /tomatomtl/cookies                          — ملخص مخفى (مصدر الكوكيز + الأسماء)
# POST /tomatomtl/check                            — فحص حي: هل الجلسة مسجلة الدخول فعلاً؟
@app.route('/tomatomtl/cookies', methods=['POST'])
def set_tomatomtl_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.tomatomtl import set_runtime_cookies, cookie_summary
        data = request.json or {}
        set_runtime_cookies(str(data.get('cookies') or ''))
        return jsonify({'message': 'TomatoMTL cookies updated', 'status': cookie_summary()}), 200
    except Exception as e:
        return jsonify({'message': 'Internal Server Error', 'details': str(e)}), 500


@app.route('/tomatomtl/cookies', methods=['GET'])
def get_tomatomtl_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    from sites.tomatomtl import cookie_summary
    return jsonify(cookie_summary()), 200


@app.route('/tomatomtl/check', methods=['POST'])
def check_tomatomtl_session_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.tomatomtl import quick_session_check
        return jsonify(quick_session_check()), 200
    except Exception as e:
        return jsonify({'ok': False, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}), 500


# ==========================================
# 🍪 كوكيز WTR-LAB (حساب قارئ wtr-lab.com — من واجهة الموقع/التطبيق)
# ==========================================
# البيانات والفهرس تعمل بلا جلسة؛ محتوى الفصول يحتاج جلسة (Turnstile) —
# الكوكيز تُلصق من الواجهة (ترويسة Cookie من متصفح مسجل الدخول).
# POST /wtrlab/cookies {cookies: "name=v; ..."} — ضبط/تحديث (فارغ = تصفير)
# GET  /wtrlab/cookies                          — ملخص مخفى (أسماء الكوكيز)
# POST /wtrlab/check                            — فحص حي: هل قراءة الفصول تعمل؟
@app.route('/wtrlab/cookies', methods=['POST'])
def set_wtrlab_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.wtrlab import set_runtime_cookies, cookie_summary
        data = request.json or {}
        set_runtime_cookies(str(data.get('cookies') or ''))
        return jsonify({'message': 'WTR-LAB cookies updated', 'status': cookie_summary()}), 200
    except Exception as e:
        return jsonify({'message': 'Internal Server Error', 'details': str(e)}), 500


@app.route('/wtrlab/cookies', methods=['GET'])
def get_wtrlab_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    from sites.wtrlab import cookie_summary
    return jsonify(cookie_summary()), 200


@app.route('/wtrlab/check', methods=['POST'])
def check_wtrlab_session_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.wtrlab import quick_session_check
        return jsonify(quick_session_check()), 200
    except Exception as e:
        return jsonify({'ok': False, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}), 500


# ==========================================
# 🍊 كوكيز Tadu (اختيارية — توسّع القراءة بعد 30 فصلاً مجانياً للزائر)
# ==========================================
# POST /tadu/cookies {cookies: "name=v; ..."} — ضبط/تحديث (فارغ = وضع الزائر)
# GET  /tadu/cookies                       — ملخص مخفى (مصدر الكوكيز + الأسماء)
# POST /tadu/check                         — فحص حي: هل القراءة موسّعة فعلاً؟
@app.route('/tadu/cookies', methods=['POST'])
def set_tadu_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.cnextra import set_tadu_runtime_cookies, tadu_cookie_summary
        data = request.json or {}
        set_tadu_runtime_cookies(str(data.get('cookies') or ''))
        return jsonify({'message': 'Tadu cookies updated', 'status': tadu_cookie_summary()}), 200
    except Exception as e:
        return jsonify({'message': 'Internal Server Error', 'details': str(e)}), 500


@app.route('/tadu/cookies', methods=['GET'])
def get_tadu_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    from sites.cnextra import tadu_cookie_summary
    return jsonify(tadu_cookie_summary()), 200


@app.route('/tadu/check', methods=['POST'])
def check_tadu_session_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.cnextra import tadu_quick_session_check
        return jsonify(tadu_quick_session_check()), 200
    except Exception as e:
        return jsonify({'ok': False, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}), 500


# ==========================================
# 🟦 كوكيز Taobao JH (جلسة تاوباو — قراءة الفصول تتطلب تسجيل دخول مؤكد)
# ==========================================
# POST /jhbook/cookies {cookies: "name=v; ..."} — ضبط/تحديث (فارغ = وضع الزائر)
# GET  /jhbook/cookies                          — ملخص مخفى (أسماء الكوكيز)
# POST /jhbook/check                            — فحص حي: هل قراءة الفصول تعمل؟
@app.route('/jhbook/cookies', methods=['POST'])
def set_jhbook_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.cnextra import set_jhbook_runtime_cookies, jhbook_cookie_summary
        data = request.json or {}
        set_jhbook_runtime_cookies(str(data.get('cookies') or ''))
        return jsonify({'message': 'TaobaoJH cookies updated', 'status': jhbook_cookie_summary()}), 200
    except Exception as e:
        return jsonify({'message': 'Internal Server Error', 'details': str(e)}), 500


@app.route('/jhbook/cookies', methods=['GET'])
def get_jhbook_cookies_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    from sites.cnextra import jhbook_cookie_summary
    return jsonify(jhbook_cookie_summary()), 200


@app.route('/jhbook/check', methods=['POST'])
def check_jhbook_session_route():
    auth_header = request.headers.get('Authorization') or request.headers.get('x-api-secret')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401
    try:
        from sites.cnextra import jhbook_quick_session_check
        return jsonify(jhbook_quick_session_check()), 200
    except Exception as e:
        return jsonify({'ok': False, 'message': f'فحص داخلي فاشل: {str(e)[:120]}'}), 500


# ==========================================
# 🕷️ نقطة السحب الرئيسية (نفس عقد التطبيق القديم)
# ==========================================
@app.route('/scrape', methods=['POST'])
def trigger_scrape():
    auth_header = request.headers.get('Authorization')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401

    try:
        data = request.json
        url = data.get('url', '').strip()
        admin_email = data.get('adminEmail')

        if not url:
            return jsonify({'message': 'No URL provided'}), 400

        # البحث عن الموقع في السجل
        site = resolve_site(url)
        if not site:
            return jsonify({
                'message': 'Unsupported Domain',
                'hint': 'Check GET /sites for all supported domains',
            }), 400

        # جلب بيانات الرواية أولاً
        try:
            meta = site['fetch_metadata'](url)
        except Exception as meta_err:
            print(f"Metadata error for {site['name']}: {meta_err}")
            meta = None

        if not meta:
            return jsonify({
                'message': 'Failed metadata',
                'site': site['name'],
                'siteStatus': site['status'],
                'notes': site.get('notes', ''),
                'reason': ('الموقع يحجب IP السيرفر الحالي. المواقع المسجلة active تعمل عبر '
                           'التوجيه الذكي تلقائياً — إن فشل هذا الموقع أضف مفاتيح ScraperAPI '
                           'من واجهة التطبيق أو ضبط متغير البيئة SCRAPERAPI_KEYS '
                           '(مفاتيح مفصولة بفواصل) أو FLARESOLVR_URL. تفاصيل كل موقع في GET /sites'),
            }), 400

        # تشغيل العامل في خيط منفصل
        thread = threading.Thread(target=site['worker'], args=(url, admin_email, meta), daemon=True)
        thread.start()

        return jsonify({
            'message': f"Scraping started ({site['name']}).",
            'site': site['name'],
            'language': site['language'],
        }), 200

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Server Error: {error_trace}")
        return jsonify({'message': 'Internal Server Error', 'details': str(e), 'trace': error_trace}), 500


# ==========================================
# 🔄 الجدولة التلقائية (نفس الواجهة القديمة)
# ==========================================
@app.route('/scheduler/config', methods=['POST'])
def configure_scheduler():
    auth_header = request.headers.get('Authorization')
    if auth_header != API_SECRET:
        return jsonify({'message': 'Unauthorized'}), 401

    data = request.json
    SCHEDULER_CONFIG['active'] = data.get('active', False)
    SCHEDULER_CONFIG['interval_seconds'] = int(data.get('interval', 86400))
    SCHEDULER_CONFIG['admin_email'] = data.get('adminEmail', 'system@auto')

    # عند التفعيل، حدد موعد التنفيذ التالي فوراً
    if SCHEDULER_CONFIG['active'] and SCHEDULER_CONFIG['next_run'] < time.time():
        SCHEDULER_CONFIG['next_run'] = time.time() + 5

    return jsonify({
        'message': 'Scheduler Updated',
        'config': SCHEDULER_CONFIG
    })


@app.route('/scheduler/status', methods=['GET'])
def get_scheduler_status():
    return jsonify(SCHEDULER_CONFIG)


# ==========================================
# 🕐 التنفيذ الفردي للجدولة (متزامن)
# ==========================================
def perform_single_scrape(url, admin_email):
    """تنفيذ سحب لرابط واحد بشكل متزامن (للجدولة التلقائية)"""
    try:
        if not url:
            return
        print(f"⏰ Scheduler Checking: {url}")

        site = resolve_site(url)
        if not site:
            print(f"⚠️ Scheduler: unsupported domain {url[:80]}")
            return

        try:
            meta = site['fetch_metadata'](url)
        except Exception as meta_err:
            print(f"Scheduler metadata error for {site['name']}: {meta_err}")
            meta = None

        if meta:
            site['worker'](url, admin_email, meta)
        else:
            print(f"⚠️ Scheduler: metadata failed for {site['name']}")

    except Exception as e:
        print(f"⚠️ Scheduler Error for {url}: {e}")


def scheduler_loop():
    """خيط الخلفية الذي يعمل للأبد"""
    while True:
        try:
            now = time.time()
            if SCHEDULER_CONFIG['active'] and now >= SCHEDULER_CONFIG['next_run']:
                SCHEDULER_CONFIG['status'] = 'running'
                print("🚀 [Scheduler] Starting Auto Update Job...")

                # 1. جلب قائمة المراقبة من Node.js
                import requests
                try:
                    headers = {'x-api-secret': API_SECRET}
                    from core.config import NODE_BACKEND_URL
                    res = requests.get(f"{NODE_BACKEND_URL}/api/admin/watchlist", headers=headers, timeout=30)
                    if res.status_code == 200:
                        watchlist = res.json()
                        print(f"📋 [Scheduler] Found {len(watchlist)} novels.")

                        for item in watchlist:
                            if item.get('sourceUrl') and item.get('status') == 'ongoing':
                                perform_single_scrape(item['sourceUrl'], SCHEDULER_CONFIG['admin_email'])
                                time.sleep(2)  # مهلة تأدبة بين الروايات

                        print("✅ [Scheduler] Job Completed.")
                    else:
                        print(f"❌ [Scheduler] Failed to fetch watchlist: HTTP {res.status_code}")
                except Exception as req_err:
                    print(f"❌ [Scheduler] Connection Error: {req_err}")

                # تحديث موعد التنفيذ التالي
                SCHEDULER_CONFIG['last_run'] = now
                SCHEDULER_CONFIG['next_run'] = now + SCHEDULER_CONFIG['interval_seconds']
                SCHEDULER_CONFIG['status'] = 'idle'

            time.sleep(5)
        except Exception as e:
            print(f"🔥 [Scheduler] Critical Loop Error: {e}")
            time.sleep(60)


# بدء خيط الجدولة فوراً
scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()


if __name__ == "__main__":
    port = int(__import__('os').environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, threaded=True)


# ==========================================
# 🌐 جميع المواقع المدعومة (مفصلة في README.md):
# ==========================================
# عربي:
#   1.  Rewayat Club      - https://rewayat.club            ✅
#   2.  Ar-Novel          - https://ar-no.com               ✅
#   3.  Markaz Riwayat    - https://markazriwayat.com       ⚠️ مغلق
# إنجليزي:
#   4.  Novel Fire        - https://novelfire.net           ✅
#   5.  NovelMTL          - https://www.novelmtl.com        ✅ جديد
#   6.  FanMTL            - https://fanmtl.com              ✅
#   7.  WuxiaWorld        - https://wuxiaworld.site         ✅ جديد
#   8.  WuxiaBox/Spot     - https://wuxiabox.com            ✅*
#   9.  FreeWebNovel      - https://freewebnovel.com        ✅*
#   10. Royal Road        - https://www.royalroad.com       ✅* جديد
#   11. Scribble Hub      - https://www.scribblehub.com     ✅* جديد
#   12. NovelBin          - https://novelbin.net            ✅* جديد
#   13. LNMTL             - https://lnmtl.com               ✅ جديد
# صيني:
#   14. Quanben           - https://www.quanben.io          ✅*
#   15. 52shuku           - https://www.52shuku.net         ✅ (أُعيد بناؤه)
#   16. ErCiYuan          - https://www.erciyan.com         ✅*
#   17. 69shu/69shuba    - https://www.69shu.xyz           ✅ جديد
#   18. ixdzs8            - https://ixdzs8.com              ✅ جديد
#   19. Linovel           - https://www.linovel.net         ✅ جديد
#   20. Linovelib TW      - https://tw.linovelib.com        ✅ جديد
#   21. Novel543          - https://www.novel543.com        ✅ جديد
#   23. TomatoMTL         - https://tomatomtl.com           ✅ جديد (v2.8 — جلسة حساب، كوكيز من الواجهة)
#   24. WTR-LAB           - https://wtr-lab.com             ✅ جديد (v2.9 — بيانات/فهرس مجانيان، الفصول بجلسة)
#   25. Tadu              - https://www.tadu.com            ✅ جديد (v3.0 — 30 فصلاً مجاناً، كوكيز اختيارية)
#   26. Bixiange          - http://www.bixiange.top         ✅ جديد (v3.0 — Empire CMS / GBK)
#   27. FFXS8             - https://www.ffxs8.com           ✅ جديد (v3.0 — نفس القالب)
#   28. JPXS123           - http://jpxs123.com              ✅ جديد (v3.0 — نفس القالب)
#   29. TaobaoJH          - https://jhbook.taobao.com       ✅ جديد (v3.0 — بيانات/فهرس مجانيان، الفصول بجلسة)
# كوري:
#   22. Agitoon           - https://agit664.xyz (+ دوران)   ✅ جديد
#
# * = الموقع يعمل لكنه يحجب IP مراكز البيانات فقط (مثل سيرفرات الاختبار)؛
#     يعمل طبيعياً من Railway أو IP سكني. التفاصيل في README.md
# ==========================================
