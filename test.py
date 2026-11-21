import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import solve_chain
import auth_client as AUTH

# MASUKIN LINK PLATOBOOST FRESH LO DI SINI (Yang ada ?d=...)
TEST_URL = "https://auth.platorelay.com/a?d=ISI_TICKET_FRESH_LO_DISINI"

print("[*] Mencoba nge-bypass dari IP GitHub Actions...")
try:
    ticket = AUTH.extract_ticket(TEST_URL)
    key, timer = solve_chain(ticket, verbose=True)
    
    if key:
        print(f"\n✅ BERHASIL! Key: {key}")
        print("Artinya IP GitHub GAK DIBLOKIR dan kita bisa pindah ke sini!")
    else:
        print("\n❌ GAGAL. IP GitHub diblokir sama API Platoboost atau link expired.")
        print(f"Alasan: {getattr(timer, 'invalid_reason', 'Unknown')}")
except Exception as e:
    print(f"\n❌ ERROR: {e}")
