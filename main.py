#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
import json
import asyncio
import hashlib
import threading
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import auth_client as AUTH
import link_generator as LG

# ==========================================
# SETUP FASTAPI & LIFESPAN
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        AUTH.start_version_watcher()
    except Exception:
        pass
    yield

app = FastAPI(title="Delta Cardkey", default_response_class=JSONResponse, lifespan=lifespan)

# ==========================================
# SOLVER LOGIC (Dari kode asli lo)
# ==========================================
FALLBACK_SERVICES = [3]
MAX_ROUNDS = 3
MAX_ROUNDS_HARD_CAP = 12
POLL_MAX_ATTEMPTS = 10
POLL_INTERVAL = 0.1
POLL_OVERLAP_DELAY = 0.05
STEP_THROTTLE_RETRIES = 2
STEP_THROTTLE_SLEEP = 2.0
MIN_STEP_GAP = 5.0

class Timer:
    def __init__(self):
        self.phases = {}
        self.t0 = None
        self.current_phase = None
        self.invalid_reason = None

    def start(self, phase):
        if self.current_phase is not None:
            self.stop()
        self.current_phase = phase
        self.t0 = time.time()

    def stop(self):
        if self.current_phase is not None and self.t0 is not None:
            dt = time.time() - self.t0
            self.phases[self.current_phase] = self.phases.get(self.current_phase, 0.0) + dt
            self.current_phase = None
            self.t0 = None

    def add(self, name, seconds):
        self.phases[name] = self.phases.get(name, 0.0) + seconds

    def total(self):
        return sum(self.phases.values())

    def summary(self):
        parts = []
        for name, secs in sorted(self.phases.items(), key=lambda x: -x[1]):
            pct = secs / self.total() * 100 if self.total() > 0 else 0
            parts.append(f"    {name}: {secs:.1f}s ({pct:.0f}%)")
        return '\n'.join(parts)

def resolve_meta(ticket, session=None, verbose=True):
    cp = None
    try:
        meta = AUTH.get_session_metadata(ticket, session=session)
        if isinstance(meta, dict):
            if meta.get('success') is False and not meta.get('transient'):
                msg = str(meta.get('message') or meta.get('error') or '').lower()
                if any(m in msg for m in AUTH.INVALID_MARKERS):
                    reason = str(meta.get('message') or meta.get('error') or 'invalid link')
                    return None, cp, False, reason
            data = meta.get('data', meta)
            if isinstance(data, dict):
                profile = data.get('activeRevenueProfile', {})
                if isinstance(profile, dict) and 'service' in profile:
                    svc = int(profile['service'])
                    try:
                        cpn = profile.get('checkpointCount')
                        cp = int(cpn) if cpn else None
                    except (TypeError, ValueError):
                        cp = None
                    return svc, cp, True, None
    except Exception:
        pass
    return None, cp, True, None

def throttled(r):
    if not isinstance(r, dict):
        return False
    msg = ' '.join(str(r.get(k, '')) for k in ('message', 'error', 'detail')).lower()
    return ('too fast' in msg) or ('slow down' in msg) or ('too many' in msg)

def do_step_with_retry(ticket, service=None, session=None, verbose=True, timer=None, gap_state=None, overlap_poll=False, poll_session=None):
    services_to_try = []
    if service is not None:
        services_to_try.append(service)
    for svc in FALLBACK_SERVICES:
        if svc not in services_to_try:
            services_to_try.append(svc)

    if timer: timer.start('step')

    if gap_state is not None and gap_state.get('ts'):
        gap = time.time() - gap_state['ts']
        if gap < MIN_STEP_GAP:
            time.sleep(MIN_STEP_GAP - gap)

    overlap_box = {}
    overlap_thread = None

    def overlap_poll_worker():
        time.sleep(POLL_OVERLAP_DELAY)
        sess = poll_session if poll_session is not None else session
        for _ in range(POLL_MAX_ATTEMPTS):
            if overlap_box.get('stop'): return
            try:
                st = AUTH.get_session_status(ticket, session=sess)
                data = st.get('data', st) if isinstance(st, dict) else {}
                k = data.get('key', '')
                if k and k != 'KEY_NOT_FOUND':
                    overlap_box['key'] = k
                    return
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    for svc in services_to_try:
        for attempt in range(STEP_THROTTLE_RETRIES + 1):
            try:
                t0 = time.time()
                if overlap_poll and overlap_thread is None:
                    overlap_thread = threading.Thread(target=overlap_poll_worker, daemon=True)
                    overlap_thread.start()
                r = AUTH.do_step(ticket, service=svc, session=session)
                dt = time.time() - t0
                if gap_state is not None:
                    gap_state['ts'] = time.time()
                if isinstance(r, dict) and r.get('success'):
                    if timer: timer.stop()
                    return svc, r, overlap_box
                if throttled(r):
                    if attempt < STEP_THROTTLE_RETRIES:
                        time.sleep(STEP_THROTTLE_SLEEP)
                        continue
                break
            except Exception:
                break

    if timer: timer.stop()
    overlap_box['stop'] = True
    return None, {'success': False, 'error': 'all services failed'}, overlap_box

def check_key_in_response(ticket, session=None, verbose=True, timer=None):
    try:
        if timer: timer.start('poll')
        st = AUTH.get_session_status(ticket, session=session)
        if timer: timer.stop()
        st_data = st.get('data', st) if isinstance(st, dict) else {}
        key = st_data.get('key', '')
        if key and key != 'KEY_NOT_FOUND':
            return key
    except Exception:
        pass
    return None

def poll_for_key(ticket, session=None, max_attempts=3, interval=0, verbose=True, timer=None):
    for i in range(max_attempts):
        key = check_key_in_response(ticket, session=session, verbose=verbose, timer=timer)
        if key: return key
        if interval > 0 and i < max_attempts - 1:
            time.sleep(interval)
    return None

def solve_chain(ticket, verbose=True, max_rounds=MAX_ROUNDS, session=None):
    if session is None:
        session = AUTH.create_session()
    current_ticket = ticket
    current_service = None
    timer = Timer()
    round_cap = max(max_rounds, 1)
    round_idx = 0
    last_exit = ['round-exhausted']
    gap_state = {'ts': 0.0}

    while round_idx < round_cap:
        if timer: timer.start('meta')
        meta_session = AUTH.create_session()
        meta_future = None
        stat_future = None
        cpc = None
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                meta_future = pool.submit(resolve_meta, current_ticket, meta_session, verbose)
                if round_idx == 0:
                    stat_session = AUTH.create_session()
                    stat_future = pool.submit(check_key_in_response, current_ticket, stat_session, verbose, None)
                if stat_future is not None:
                    try:
                        early = stat_future.result(timeout=6)
                    except Exception:
                        early = None
                    if early:
                        return early, timer
                try:
                    svc, cpc, mvalid, mreason = meta_future.result(timeout=6)
                    current_service = svc
                    if not mvalid:
                        timer.invalid_reason = mreason
                        return None, timer
                except Exception:
                    current_service, cpc = None, None
        finally:
            meta_session.close()
            try:
                if stat_future is not None: stat_session.close()
            except Exception: pass
        if timer: timer.stop()

        if cpc is not None:
            need = cpc + 1
            if need > round_cap:
                round_cap = min(need, MAX_ROUNDS_HARD_CAP)

        last_step = round_idx > 0
        service, resp, overlap = do_step_with_retry(
            current_ticket, service=current_service, session=session,
            verbose=verbose, timer=timer, gap_state=gap_state,
            overlap_poll=last_step, poll_session=None
        )
        if overlap.get('key'): return overlap['key'], timer
        if service is None:
            last_exit[0] = 'step-failed'
            round_idx += 1
            continue

        current_service = service
        url = (resp.get('data') or {}).get('url', '')
        if not url:
            last_exit[0] = 'no-url'
            round_idx += 1
            continue

        if url == 'about:blank':
            key = poll_for_key(current_ticket, session=session, verbose=verbose, timer=timer, max_attempts=POLL_MAX_ATTEMPTS, interval=POLL_INTERVAL)
            if key: return key, timer
            last_exit[0] = 'poll-timeout'
            round_idx += 1
            continue

        callback = AUTH.decode_callback_url(url)
        if callback:
            next_ticket = AUTH.extract_ticket_from_callback(callback)
            if next_ticket and len(next_ticket) > 50:
                current_ticket = next_ticket
                round_idx += 1
                continue

        key = check_key_in_response(current_ticket, session=session, verbose=verbose, timer=timer)
        if key: return key, timer
        last_exit[0] = 'no-callback-no-key'
        break

    key = check_key_in_response(current_ticket, session=session, verbose=verbose, timer=timer)
    if key: return key, timer
    return None, timer

# ==========================================
# HTTP API SERVER LOGIC
# ==========================================
executor = ThreadPoolExecutor(max_workers=10)
lock = threading.Lock()

# CACHE (Di-disable agar aman di Wasmer)
key_cache = {}
CACHE_TTL = 24 * 3600

def cache_get(ticket, h=None):
    h = h or hashlib.md5(ticket.encode()).hexdigest()
    with lock:
        rec = key_cache.get(h)
        if rec:
            if time.time() - rec.get("ts", 0) < CACHE_TTL:
                return rec.get("key"), True, rec.get("solve_time", 0.0)
            key_cache.pop(h, None)
    return None, False, 0.0

def cache_put(ticket, key, solve_time, h=None):
    if not key: return
    h = h or hashlib.md5(ticket.encode()).hexdigest()
    with lock:
        key_cache[h] = {"key": key, "ts": time.time(), "solve_time": solve_time}

MADE_BY = "Hasl_Team"
QQ_GROUP = "277707901"
inflight = {}              

def fmt_t(secs):
    return f"{round(float(secs or 0.0), 12)}s"

def solo_pass(ticket):
    t0 = time.time()
    solved_timer = None
    try:
        key, solved_timer = solve_chain(ticket, False, 3)
        if key:
            err = None
        else:
            reason = getattr(solved_timer, 'invalid_reason', None)
            err = f"无效链接: {reason}" if reason else "solve failed"
    except Exception as e:
        key, err = None, f"solve exception: {type(e).__name__}"
    
    if solved_timer is not None and solved_timer.total() > 0:
        st = solved_timer.total()
    else:
        st = time.time() - t0
    return key, err, st

def run_solves(ticket):
    key, err, st = solo_pass(ticket)
    if key or err.startswith("solve exception") or err.startswith("无效链接"):
        return key, err, st
    time.sleep(0.3)
    return solo_pass(ticket)

@app.get("/delta")
async def delta(url: str):
    t0 = time.time()
    try:
        ticket = AUTH.extract_ticket(url)
    except Exception:
        return {"key": None, "error": "invalid url", "cached": False, "made_by": MADE_BY, "times": fmt_t(time.time() - t0)}
    
    if len(ticket) < AUTH.MIN_TICKET_LEN:
        return {"key": None, "error": "invalid url (no ticket)", "cached": False, "made_by": MADE_BY, "times": fmt_t(time.time() - t0)}

    h = hashlib.md5(ticket.encode()).hexdigest()
    cached, found, cached_solve_time = cache_get(ticket, h)
    if found:
        return {"key": cached, "cached": True, "error": None, "made_by": MADE_BY, "times": fmt_t(cached_solve_time)}

    loop = asyncio.get_running_loop()
    with lock:
        fut = inflight.get(h)
        if fut is None:
            fut = loop.create_future()
            inflight[h] = fut
            spawn = True
        else:
            spawn = False
    if spawn:
        loop.create_task(drive(h, fut, ticket))

    try:
        key, err, solve_time = await asyncio.shield(fut)
    except Exception as e:
        key, err, solve_time = None, f"internal: {type(e).__name__}", time.time() - t0

    return {"key": key, "cached": False, "error": err, "made_by": MADE_BY, "times": fmt_t(solve_time)}

async def drive(h, fut, ticket):
    try:
        key, err, st = await asyncio.get_running_loop().run_in_executor(executor, run_solves, ticket)
    except Exception as e:
        key, err, st = None, f"solve exception: {type(e).__name__}", 0.0
    if key:
        cache_put(ticket, key, st, h)
    with lock:
        inflight.pop(h, None)
    if not fut.done():
        fut.set_result((key, err, st))

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8080)