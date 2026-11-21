import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import solve_chain
import auth_client as AUTH

# MASUKIN LINK PLATOBOOST FRESH LO DI SINI (Yang ada ?d=...)
TEST_URL = "https://auth.platorelay.com/a?d=5HgLwAzeAlRqwbQs5hTxIqE8kpR3g5xaUQ8tDTDc0SVgUF4Cw9OEfJYwZbBfIsYEsjN7WFuKFAM6JIDMZsxtAcXLq3An6BYpHksiNzFdZYJ0TjtyQof965RF05BxhnuwKSmuAwGB09lqcgUWW2WL1CnIt8rtCui3QFENt0f7GuvietH3DqkRQkJoZswq663EcLCXHIqsgXp6k5s9oBCAX71GfNkAmauuD9fZPpHDJpTLNykSiGVkCogXttkOXZ7PBtmrNW3UPP11OYiiraehFhkKI2Bgusq8JGH3WEMOldOuG8riYeMHs8tX86opXGalwFCImRXM4HIcQXlOitMZn6RSUVw7J1EboTNsU68hOnxc6NFYg09tMzc0bADmtSEbusJcHI3gWcCnugpQitNZaHGbzvNVLcXw763LrljzfRMb5CbUvtDs41C1LhFfvNSobzU0CMK1U1VapAxAxM1lrN39KnUb8K2tB9RnHau53CYYtOOMaQp"

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
