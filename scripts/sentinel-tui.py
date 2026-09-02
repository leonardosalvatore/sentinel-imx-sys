#!/usr/bin/env python3
"""sentinel-tui - a retro-'80s "hacker" dashboard for the sentinel-imx demo.

Runs ON the i.MX 8M Plus board (over SSH). Dependency-free: only the Python 3
standard library. Renders a full-screen, neon/synthwave dashboard showing:

  * animated title banner
  * per-core CPU load bars + history sparkline
  * Vivante GPU/NPU load (from /sys/kernel/debug/gc/load) + sparklines
  * memory + SoC temperature + uptime
  * the sentinel-imx daemon's live vitals (CPU%, RSS, events, alerts)
  * a colorized live stream of the daemon's kernel/D-Bus detections

Keys:  q = quit   a / SPACE = inject a synthetic anomaly into /dev/kmsg

Usage (record this over SSH with a TTY):
    ssh -t root@<board> 'python3 /usr/local/bin/sentinel-tui.py'
"""
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from collections import deque

SERVICE = os.environ.get("SENTINEL_SERVICE", "sentinel-imx.service")
CAPTURE = os.environ.get("SENTINEL_CAPTURE_PATH", "/var/lib/sentinel-imx/capture.jsonl")
GC_LOAD = "/sys/kernel/debug/gc/load"

# ---------------------------------------------------------------- palette ----
def fg(r, g, b): return f"\033[38;2;{r};{g};{b}m"
def bgc(r, g, b): return f"\033[48;2;{r};{g};{b}m"

RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
PINK = fg(255, 45, 149); CYAN = fg(0, 255, 231); PURPLE = fg(179, 0, 255)
GREEN = fg(57, 255, 20); YELLOW = fg(255, 214, 0); ORANGE = fg(255, 111, 0)
BLUE = fg(80, 140, 255); WHITE = fg(235, 235, 245); GREY = fg(110, 110, 140)
BG = bgc(10, 6, 20)  # deep near-black purple

GRAD = [fg(255, 45, 149), fg(214, 60, 200), fg(179, 0, 255),
        fg(120, 90, 255), fg(0, 200, 255), fg(0, 255, 231)]
SPARK = " ▁▂▃▄▅▆▇█"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")

ANOMALIES = [
    "kernel BUG: unable to handle kernel paging request at 00000000",
    "Out of memory: Killed process 4242 (rogue) total-vm:900000kB",
    "EXT4-fs error (device mmcblk0p2): ext4_find_entry: reading directory lblock",
    "usb 1-1: device descriptor read/64, error -110",
    "watchdog: BUG: soft lockup - CPU#2 stuck for 22s!",
    "audit: type=1400 avc: denied { execute } for pid=1337 comm=\"suspicious\"",
]


def vlen(s):
    return len(ANSI_RE.sub("", s))


def bar(frac, width, lo=GREEN, mid=YELLOW, hi=PINK):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    color = lo if frac < 0.5 else (mid if frac < 0.8 else hi)
    return color + "█" * filled + GREY + "░" * (width - filled) + RESET


def spark(hist, width):
    vals = list(hist)[-width:]
    out = []
    for v in vals:
        idx = int(max(0.0, min(1.0, v)) * (len(SPARK) - 1))
        c = GREEN if v < 0.5 else (YELLOW if v < 0.8 else PINK)
        out.append(c + SPARK[idx])
    s = "".join(out) + RESET
    pad = width - len(vals)
    return (GREY + "·" * pad + RESET + s) if pad > 0 else s


# ---------------------------------------------------------------- sources ----
class Cpu:
    def __init__(self):
        self.prev = {}

    def read(self):
        out = {}
        try:
            with open("/proc/stat") as f:
                for line in f:
                    if not line.startswith("cpu"):
                        break
                    parts = line.split()
                    name = parts[0]
                    if name == "cpu" or (name.startswith("cpu") and name[3:].isdigit()):
                        vals = list(map(int, parts[1:]))
                        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                        total = sum(vals)
                        p = self.prev.get(name)
                        if p:
                            dt = total - p[1]
                            di = idle - p[0]
                            out[name] = 1.0 - (di / dt) if dt > 0 else 0.0
                        else:
                            out[name] = 0.0
                        self.prev[name] = (idle, total)
        except OSError:
            pass
        return out


def read_gc_load():
    try:
        with open(GC_LOAD) as f:
            txt = f.read()
        pairs = re.findall(r"core\s*:\s*(\d+)\s*load\s*:\s*(\d+)\s*%", txt)
        return [(int(c), int(v) / 100.0) for c, v in pairs]
    except OSError:
        return []


def read_mem():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = int(v.split()[0])
        total = info.get("MemTotal", 1)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        return 1.0 - avail / total, total // 1024, (total - avail) // 1024
    except OSError:
        return 0.0, 0, 0


def read_temp():
    best = None
    try:
        base = "/sys/class/thermal"
        for z in os.listdir(base):
            if z.startswith("thermal_zone"):
                try:
                    with open(f"{base}/{z}/temp") as f:
                        t = int(f.read().strip()) / 1000.0
                    best = t if best is None else max(best, t)
                except OSError:
                    pass
    except OSError:
        pass
    return best


def read_uptime():
    try:
        with open("/proc/uptime") as f:
            s = int(float(f.read().split()[0]))
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    except OSError:
        return "--:--:--"


class Daemon:
    def __init__(self):
        self.prev = None
        self.clk = os.sysconf("SC_CLK_TCK")

    def pid(self):
        try:
            out = subprocess.check_output(
                ["systemctl", "show", "-p", "MainPID", "--value", SERVICE],
                text=True).strip()
            return int(out) if out and out != "0" else None
        except Exception:
            return None

    def read(self):
        pid = self.pid()
        if not pid:
            self.prev = None
            return None
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().split()
            ticks = int(parts[13]) + int(parts[14])
            now = time.monotonic()
            cpu = 0.0
            if self.prev:
                dt = now - self.prev[1]
                cpu = ((ticks - self.prev[0]) / self.clk) / dt * 100.0 if dt > 0 else 0.0
            self.prev = (ticks, now)
            rss = 0
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS"):
                        rss = int(line.split()[1]) // 1024
                        break
            return {"pid": pid, "cpu": cpu, "rss": rss}
        except OSError:
            self.prev = None
            return None


def count_lines(path):
    n = 0
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(1 << 16)
                if not b:
                    break
                n += b.count(b"\n")
    except OSError:
        return 0
    return n


class Journal:
    def __init__(self):
        self.lines = deque(maxlen=500)
        self.alerts = 0
        cmd = ["journalctl", "-u", SERVICE, "-f", "-n", "40",
               "-o", "short-precise", "--no-hostname"]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True)
        except Exception:
            self.proc = None
            return
        os.set_blocking(self.proc.stdout.fileno(), False)

    def poll(self):
        if not self.proc:
            return
        try:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break
                line = line.rstrip("\n")
                if line:
                    if "alert fired" in line:
                        self.alerts += 1
                    self.lines.append(line)
        except Exception:
            pass

    def close(self):
        if self.proc:
            self.proc.terminate()


def colorize_log(line):
    low = line.lower()
    if "alert fired" in low or "bug" in low or "error" in low or "denied" in low:
        c = PINK + BOLD
    elif "suppressed" in low or "warn" in low or "unavailable" in low:
        c = YELLOW
    elif "ready" in low or "running" in low or "enabled" in low or "delegate" in low:
        c = GREEN
    elif "dbus" in low:
        c = CYAN
    elif "kmsg" in low or "kernel" in low:
        c = BLUE
    else:
        c = GREY
    return c + line + RESET


# ---------------------------------------------------------------- drawing ----
def panel(title, content, width, border):
    cw = width - 4
    head = f"{border}╔═[ {WHITE}{BOLD}{title}{RESET}{border} ]"
    fill = width - vlen(head) - 1
    rows = [head + "═" * max(0, fill) + "╗" + RESET]
    for c in content:
        v = vlen(c)
        if v > cw:
            c = c + RESET
            v = cw  # assume caller sized it
        rows.append(f"{border}║{RESET} " + c + " " * (cw - v) + f" {border}║{RESET}")
    rows.append(border + "╚" + "═" * (width - 2) + "╝" + RESET)
    return rows


def cell(*parts):
    """parts: (visible_width, rendered_string). Returns (total_width, string)."""
    w = sum(p[0] for p in parts)
    return w, "".join(p[1] for p in parts)


def banner(width, frame):
    text = "SENTINEL-IMX"
    fw = "".join(chr(ord(ch) + 0xFEE0) if "A" <= ch <= "Z" else
                 ("－" if ch == "-" else ch) for ch in text)
    bw = len(text) * 2
    if bw + 2 > width:
        line = f"{BOLD}{PINK}// {text} //{RESET}"
        return [" " * max(0, (width - vlen(line)) // 2) + line]
    coled = "".join(GRAD[(i + frame) % len(GRAD)] + ch for i, ch in enumerate(fw)) + RESET
    pad = (width - bw) // 2
    sub = f"{DIM}{CYAN}on-device log-anomaly detection · NXP i.MX 8M Plus · NPU{RESET}"
    return [
        " " * pad + coled,
        " " * max(0, (width - vlen(sub)) // 2) + sub,
    ]


def main():
    isatty = sys.stdin.isatty()
    old = None
    if isatty:
        old = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
    sys.stdout.write("\033[?25l\033[2J")  # hide cursor, clear

    cpu = Cpu(); daemon = Daemon(); jr = Journal()
    cpu_hist = deque(maxlen=120)
    gc_hist = {}
    ev_cache = (0.0, 0)
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    frame = 0
    try:
        while running:
            frame += 1
            size = shutil.get_terminal_size((100, 30))
            W = max(60, size.columns)
            H = max(20, size.lines)
            iw = W - 4  # panel interior width

            jr.poll()
            cores = cpu.read()
            total = cores.get("cpu", 0.0)
            cpu_hist.append(total)
            gc = read_gc_load()
            memf, memtot, memused = read_mem()
            temp = read_temp()
            up = read_uptime()
            dstat = daemon.read()
            now = time.monotonic()
            if now - ev_cache[0] > 2.0:
                ev_cache = (now, count_lines(CAPTURE))
            events = ev_cache[1]

            out = [BG + "\033[H"]
            for ln in banner(W, frame):
                out.append(ln + "\033[K\n")
            out.append("\033[K\n")

            # ---- SYSTEM panel ----
            sysc = []
            lbl_w = 8; val_w = 5
            barw = iw - lbl_w - val_w - 2
            _, r = cell((lbl_w, f"{WHITE}{'CPU tot':<{lbl_w}}{RESET}"),
                        (barw, bar(total, barw)),
                        (1, " "),
                        (val_w, f"{WHITE}{int(total*100):3d}% {RESET}"))
            sysc.append(r)
            sysc.append(spark(cpu_hist, iw))
            ncore = sorted(k for k in cores if k != "cpu")
            for name in ncore:
                f = cores[name]
                _, r = cell((lbl_w, f"{CYAN}{name:<{lbl_w}}{RESET}"),
                            (barw, bar(f, barw)),
                            (1, " "),
                            (val_w, f"{WHITE}{int(f*100):3d}% {RESET}"))
                sysc.append(r)
            _, r = cell((lbl_w, f"{WHITE}{'MEM':<{lbl_w}}{RESET}"),
                        (barw, bar(memf, barw, lo=BLUE, mid=PURPLE, hi=PINK)),
                        (1, " "),
                        (val_w, f"{WHITE}{int(memf*100):3d}% {RESET}"))
            sysc.append(r)
            tstr = f"{temp:.0f}°C" if temp is not None else "n/a"
            tcol = GREEN if (temp or 0) < 70 else (YELLOW if (temp or 0) < 85 else PINK)
            info = f"{WHITE}TEMP {tcol}{tstr}{RESET}   {WHITE}MEM {memused}/{memtot} MB   UPTIME {CYAN}{up}{RESET}"
            sysc.append(info + " " * max(0, iw - vlen(info)))

            # ---- ACCELERATOR panel ----
            accc = []
            names = {0: "GPU  c0", 1: "NPU  c1"}
            if not gc:
                accc.append(f"{GREY}(/sys/kernel/debug/gc/load not readable){RESET}")
            for core, val in gc:
                gc_hist.setdefault(core, deque(maxlen=120)).append(val)
                lbl = names.get(core, f"core{core}")
                _, r = cell((lbl_w, f"{PINK}{lbl:<{lbl_w}}{RESET}"),
                            (barw, bar(val, barw, lo=PURPLE, mid=PINK, hi=PINK)),
                            (1, " "),
                            (val_w, f"{WHITE}{int(val*100):3d}% {RESET}"))
                accc.append(r)
                accc.append(spark(gc_hist[core], iw))
            note = f"{DIM}{GREY}tiny INT8 model → NPU finishes instantly; load stays low by design{RESET}"
            accc.append(note + " " * max(0, iw - vlen(note)))

            # ---- DAEMON panel ----
            if dstat:
                status = f"{GREEN}● ONLINE{RESET}"
                d = (f"{status}   {WHITE}PID {CYAN}{dstat['pid']}{RESET}   "
                     f"{WHITE}CPU {CYAN}{dstat['cpu']:.1f}%{RESET}   "
                     f"{WHITE}RSS {CYAN}{dstat['rss']} MB{RESET}   "
                     f"{WHITE}EVENTS {GREEN}{events}{RESET}   "
                     f"{WHITE}ALERTS {PINK}{jr.alerts}{RESET}")
            else:
                d = f"{PINK}● OFFLINE{RESET}   {GREY}systemctl start {SERVICE}{RESET}"
            dcon = [d + " " * max(0, iw - vlen(d))]

            # assemble top panels
            for ln in panel("SYSTEM VITALS", sysc, W, CYAN):
                out.append(ln + "\033[K\n")
            for ln in panel("ACCELERATOR · Vivante GC", accc, W, PINK):
                out.append(ln + "\033[K\n")
            for ln in panel("DAEMON", dcon, W, GREEN):
                out.append(ln + "\033[K\n")

            # ---- EVENT STREAM (fills remaining height) ----
            # count rows rendered above so the stream fills the rest of the screen
            rendered = len(banner(W, frame)) + 1  # banner + blank
            rendered += len(sysc) + 2 + len(accc) + 2 + len(dcon) + 2
            stream_h = max(3, H - rendered - 3)
            logs = list(jr.lines)[-stream_h:]
            scon = []
            for ln in logs:
                s = colorize_log(ln)
                if vlen(s) > iw:
                    # truncate on visible width
                    plain = ANSI_RE.sub("", ln)[:iw - 1]
                    s = colorize_log(plain) + "…"
                scon.append(s + " " * max(0, iw - vlen(s)))
            while len(scon) < stream_h:
                scon.append(" " * iw)
            for ln in panel("LIVE KERNEL / D-BUS EVENT STREAM", scon, W, PURPLE):
                out.append(ln + "\033[K\n")

            foot = (f"{DIM}{WHITE}[q]{RESET}{GREY} quit   "
                    f"{DIM}{WHITE}[a]/[space]{RESET}{GREY} inject anomaly   "
                    f"{PURPLE}sentinel-imx{GREY} demo dashboard{RESET}")
            out.append(foot + "\033[K")
            out.append("\033[J")  # clear below
            sys.stdout.write("".join(out))
            sys.stdout.flush()

            # input (non-blocking) up to ~0.25s
            if isatty:
                r, _, _ = select.select([sys.stdin], [], [], 0.25)
                if r:
                    ch = sys.stdin.read(1)
                    if ch in ("q", "Q"):
                        running = False
                    elif ch in ("a", "A", " "):
                        try:
                            msg = ANOMALIES[frame % len(ANOMALIES)]
                            with open("/dev/kmsg", "w") as k:
                                k.write("sentinel-demo-inject: " + msg + "\n")
                        except OSError:
                            pass
            else:
                time.sleep(0.25)
    finally:
        jr.close()
        sys.stdout.write(RESET + "\033[?25h\033[2J\033[H")
        sys.stdout.flush()
        if isatty and old:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
