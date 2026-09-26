# -*- coding: utf-8 -*-
"""
==========================================
📡 الاتصال بالخادم الرئيسي (Backend Bridge)
==========================================
دوال إرسال البيانات إلى خادم Node.js الخاص بتطبيق C:
- send_data_to_backend: إرسال بيانات رواية + فصول
- check_existing_chapters: منع تكرار الفصول الموجودة
"""

import requests

from .config import API_SECRET, NODE_BACKEND_URL


def _headers():
    return {
        'Content-Type': 'application/json',
        'Authorization': API_SECRET,
        'x-api-secret': API_SECRET,
    }


def send_data_to_backend(payload):
    """إرسال البيانات إلى الخادم الرئيسي"""
    try:
        endpoint = f"{NODE_BACKEND_URL}/api/scraper/receive"
        response = requests.post(endpoint, json=payload, headers=_headers(), timeout=60)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Failed to send data: {e}")
        return False


def check_existing_chapters(title):
    """التحقق من الفصول الموجودة في الباك إند لمنع التكرار"""
    try:
        endpoint = f"{NODE_BACKEND_URL}/api/scraper/check-chapters"
        response = requests.post(endpoint, json={'title': title}, headers=_headers(), timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get('exists'):
                return data['chapters']
            return []
        return []
    except Exception as e:
        print(f"❌ Error checking existence: {e}")
        return []


def push_log(message, log_type='info'):
    """🔔 إرسال سجل مرئي إلى كونسول السكرابر في واجهة التطبيق
    (يظهر فوراً للمشرف في شاشة المراقبة) — لا يرفع استثناءات أبداً"""
    try:
        endpoint = f"{NODE_BACKEND_URL}/api/scraper/log"
        requests.post(endpoint, json={'message': message, 'type': log_type},
                      headers=_headers(), timeout=15)
    except Exception as e:
        print(f"   (log push failed: {str(e)[:60]})")
