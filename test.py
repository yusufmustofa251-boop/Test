import requests
import sys

# Link Platoboost (pake link asli lo kalo mau tes full, atau link dummy ini)
URL = "https://auth.platorelay.com/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print(f"Mencoba nembak: {URL}")
try:
    # Tes koneksi basic
    res = requests.get(URL, headers=headers, timeout=15)
    print(f"Status Code: {res.status_code}")
    print("Response Headers:")
    for k, v in res.headers.items():
        print(f"  {k}: {v}")
        
    # Kalo Cloudflare nge-block, biasanya muncul challenge HTML atau 403/503
    if res.status_code in [403, 503]:
        print("\n❌ KESIMPULAN: IP Datacenter DIBLOKIR Cloudflare (WAF/Challenge).")
    elif "cf-mitigated" in res.headers:
        print("\n❌ KESIMPULAN: IP Datacenter DIBLOKIR Cloudflare (cf-mitigated).")
    else:
        print("\n✅ KESIMPULAN: Koneksi tembus! (Cek response text di bawah)")
        print(res.text[:500])

except Exception as e:
    print(f"\n❌ ERROR JARINGAN: {e}")
