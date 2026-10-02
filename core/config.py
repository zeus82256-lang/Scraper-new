# -*- coding: utf-8 -*-
"""
==========================================
⚙️ الإعدادات العامة للسكرابر (Shared Config)
==========================================
يحتوي على كل الإعدادات التي تحتاجها بقية الوحدات:
- مفاتيح الحماية
- روابط الخادم الرئيسي
- الكوكيز الخاصة
- حالة الجدولة التلقائية
"""

import os

# ==========================================
# 🔐 مفتاح سري لحماية الروابط (نفس القيمة القديمة تماماً)
# ==========================================
API_SECRET = os.environ.get(
    'API_SECRET',
    'Zeusndndjddnejdjdjdejekk29393838msmskxcm9239484jdndjdnddjj99292938338zeuslojdnejxxmejj82283849'
)

# ==========================================
# 🌐 رابط الخادم الرئيسي (Node.js backend)
# ==========================================
NODE_BACKEND_URL = os.environ.get('NODE_BACKEND_URL', 'https://c-production-6948.up.railway.app')

# ==========================================
# 🍪 إعدادات الكوكيز (تجاوز حماية تسجيل الدخول لمركز الروايات القديم)
# ==========================================
MARKAZ_COOKIES = os.environ.get(
    'MARKAZ_COOKIES',
    'wordpress_sec_198f6e9e82ba200a53325105f201ddc5=mikey%7C1771590380%7CKJphcZkhBFCpXyLUDrDcGPi9XmNOC47IPCSEHAPyfXS%7C5e8e596c5389b65f91a30668be6f16c7134b98b3ae55a007ed360594dd035527; cf_clearance=qYXkJIaj1IiaBKgi561_IQ.9oWgJ3fx10itfVR20lXY-1765278736-1.2.1.1-soYoRwUhDSq_.2cCoaJ22MPadmCmaQ0cW3AkfA1L97BJIbxQQro5hvpmuJxhQaT57TxfEW10l9gQYsmy5QgrwLsiWHScUWVvqYzZufRRYs9LIDPAhyxiOnL2Byevi12fb8iAZWttVNlqYWeKjH06tTp8bNhPx4dsmudPpIh0qzijEZhRk8lK6nWip1SeDFO2Of35W2rBKDEtjidGFyIj1RU3B7Xt.4CVoQbE9pGFaS8gFTMOp.0qmMMiz1UmHoFc; wpmanga-body-contrast=light; wpmanga-reading-history=W3siaWQiOjEyODE3LCJjIjoiMzEzMDgiLCJwIjoxLCJpIjoiIiwidCI6MTc2ODEwMTY3MH1d; sbjs_migrations=1418474375998%3D1; sbjs_current_add=fd%3D2026-02-06%2012%3A25%3A57%7C%7C%7Cep%3Dhttps%3A%2F%2Fmarkazriwayat.com%2F%7C%7C%7Crf%3Dhttps%3A%2F%2Fwww.bing.com%2F; sbjs_first_add=fd%3D2026-02-06%2012%3A25%3A57%7C%7C%7Cep%3Dhttps%3A%2F%2Fmarkazriwayat.com%2F%7C%7C%7Crf%3Dhttps%3A%2F%2Fwww.bing.com%2F; sbjs_current=typ%3Dreferral%7C%7C%7Csrc%3Dbing.com%7C%7C%7Cmdm%3Dreferral%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%2F%7C%7C%7Ctrm%3D%28none%29%7C%7Cid%3D%28none%29%7C%7Cplt%3D%28none%29%7C%7Cfmt%3D%28none%29%7C%7Ctct%3D%28none%29; sbjs_first=typ%3Dreferral%7C%7C%7Csrc%3Dbing.com%7C%7C%7Cmdm%3Dreferral%7C%7C%7Ccmp%3D%28none%29%7C%7Ccnt%3D%2F%7C%7C%7Ctrm%3D%28none%29%7C%7Cid%3D%28none%29%7C%7Cplt%3D%28none%29%7C%7Cfmt%3D%28none%29%7C%7Ctct%3D%28none%29; sbjs_udata=vst%3D1%7C%7C%7Cuip%3D%28none%29%7C%7C%7Cuag%3DMozilla%2F5.0%20%28Windows%20NT%206.2%3B%20Win64%3B%20x64%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F109.0.0.0%20Safari%2F537.36%20Edg%2F109.0.1518.140; wordpress_test_cookie=WP%20Cookie%20check; _lscache_vary=8d8d3777c370b0211addc5b0a9411cd9; wordpress_logged_in_198f6e9e82ba200a53325105f201ddc5=mikey%7C1771590380%7CKJphcZkhBFCpXyLUDrDcGPi9XmNOC47IPCSEHAPyfXS%7Cb7d906dce3f0b160d5c2f585bfec331fe7d0cc3e4640a74945cc619df837e5c9; sbjs_session=pgs%3D2%7C%7C%7Ccpg%3Dhttps%3A%2F%2Fmarkazriwayat.com%2F%3Fnsl_bypass_cache%3D74d71305203b9ce18787813c87e33f8c'
)

# ==========================================
# 🍪 كوكيز TomatoMTL الثابتة (tomatomtl.com — حساب قارئ)
# ==========================================
# المستخدم طلب وضعها مباشرة في الكود لأن الجزء المهم منها طويل الأمد:
#   remember_*  = كوكي «تذكرني» (Laravel) يصلح ≈ 5 سنوات — هو الأساس
#   PHPSESSID   = جلسة قصيرة العمر (ساعات) — remember_ يجدد الدخول تلقائياً
#   cf_clearance= حماية Cloudflare قصيرة ومرتبطة بـ IP/UA المتصفح الذي أنشأها
#                 (لا تعمل من عنوان سيرفر مختلف — مجرد قيمة احتياطية هنا)
# لتحديثها لاحقاً بدون نشر جديد: حقل «كوكيز TomatoMTL» في واجهة السكرابر
# (الموقع والتطبيق بنفس الواجهة) — الحقل الفارغ يعني: استخدم هذه الثابتة.
DEFAULT_TOMATOMTL_COOKIES = os.environ.get(
    'TOMATOMTL_COOKIES',
    'cf_clearance=alvbHRPkSSaWrtoOVhRFGrz8P_tbInkpDGYghdal00w-1790935815-1.2.1.1-P0Igsp3EJhUG94kDQrmQeVNw28aQdWQ1gKBOOWoPojqZtyXDb25i12M00zuttCOSB2nFZ.D4b8sJuCwiJdDRQ4YSwBAHYU0LkpzwrpwcIw7qiWxOChm1SFrT3I0kURJJa14BXe9gsnAid42Ciuw4YSM2pYmSh0ZuyixNdhnbKTuFJaacnemyG2ak2OHwqL3gftow7sVIuOcTnospQV00kQD93S4Psz5NULSuDGj1.ZPCrwasUHxn4Tzq4SLX.oE4pnuKtUXnwU8Wt0OclCpVNBmSPJpBXc3KXmlLGqQNuzFVqAK7zUsWOkXb4smRvDG0T3Fh.hfOn9YXZC_LQxnKmHtzeowGP5efg3JSAtNdtxo; _ga_RCS34C198F=GS2.1.s1790935815$o1$g1$t1790936075$j13$l0$h0; _ga=GA1.1.1632139315.1790935815; __gads=ID=dd86b5f3935831a7:T=1790935816:RT=1790935816:S=ALNI_Mb8o6J02fnecKf2sEIH7GaZma__Hg; __gpi=UID=000015513a14839f:T=1790935816:RT=1790935816:S=ALNI_MYPw3ITP6oXPQRupPazBaYCSXWXcw; __eoi=ID=29c5e103f5eb3c6e:T=1790935816:RT=1790935816:S=AA-Afja4SOhjoQaaDDdyLlFvBcBO; FCCDCF=%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2C%5B%5B32%2C%22%5B%5C%220292b987-58f8-4819-ad3c-64dfa2251659%5C%22%2C%5B1790935816%2C501000000%5D%5D%22%5D%5D%5D; FCNEC=%5B%5B%22AKsRol_8Thwc9hst6OPNP9QOWoerJh-eDKJJNnhXuzMiYxRaE772t8C3foR3GkmD0mhhTwW0DJkXPLY77nfkWXyEpbIKCeyizgg7FTsgMvSg4kq6Y7BdLC2smPkZ1SxVY5PpCbDQ_bTlFwyx6A1Fu2kck0E0ZVs1eQ%3D%3D%22%5D%5D; translator_button=en; remember_6TpGq1xR_F05q3tke-JkBw=wJwdY-taHOAxK15ymm9RarLW%7E5pnIX134L0vGDX5N3ROrYxcV_4xWJFLS; PHPSESSID=t349n0dhnsm74n6mqasln6rvne'
)

# ==========================================
# 🔄 حالة الجدولة التلقائية العامة (Scheduler)
# ==========================================
SCHEDULER_CONFIG = {
    'active': False,
    'interval_seconds': 86400,  # الافتراضي 24 ساعة
    'next_run': 0,
    'last_run': 0,
    'status': 'idle',
    'admin_email': 'system@auto'
}
