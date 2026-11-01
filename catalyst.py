#!/usr/bin/env python3
"""
Hammerspace C.A.T.A.L.Y.S.T.
(Continuous Assimilation Tracker And Logic for Yield, Storage, & Targeted Analysis)

==============================================================================
  Name     : Hammerspace C.A.T.A.L.Y.S.T. - Continuous Assimilation Tracker
             And Logic for Yield, Storage, & Targeted Analysis
  File     : catalyst.py
  Version  : 2.4.3
  Author   : Jason Ventresco
  Created  : 2026-10-29
  Requires : Python 3.7+ (standard library only; uses curl for upload when
             present, otherwise a built-in HTTP upload)

  Changelog
    2.4.3  2026-10-31  New watch items 15-16 (on by default):
                         Skipped "..." because file not seen on the SMB side
                         Skipped "..." because existence denied by SMB server
                       Skipped lines are counted by reason, show the skipped
                       path in the feed, and raise highlights. Saved
                       selections from older versions get new items at their
                       default. --speed accepts max / 20x.
    2.4.2  2026-10-29  Live default is the Anvil's /pd/assimilation-logs (one
                       <date-time>/HS_root.log per running assimilation).
                       Target may be a folder, a log file, or a log file name;
                       folders are always searched recursively. Log files are
                       held open so the final lines are still read after the
                       log is moved into the destination share at completion.
                       Author name removed from the on-screen output.
    2.4.1  2026-10-29  Initial release: live monitor (recursive discovery,
                       tailing, stall detection), replay with original timing,
                       watch-item selection + custom items, count by type,
                       highlights, CSV/text reports, simulate mode, save to
                       /tmp and optional Hammerspace upload (same method as
                       dme-watch.sh / HS_Tier-0_HW_NUMA_Report.sh).

  When making future changes, please bump __version__ below and add a new
  Changelog entry describing what changed and why.
==============================================================================

Saving / uploading:
  With -o (or answering "y" at startup) the captured items of concern and the
  summary are saved to
      /tmp/catalyst_<host>_<timestamp>_report.txt
      /tmp/catalyst_<host>_<timestamp>_matches.csv
  When you stop (q or Ctrl-C) you're asked whether to upload them. If yes,
  they're bundled as /tmp/catalyst_bundle_<host>_<timestamp>.tar.gz and POSTed
  to the Hammerspace endpoint. Nothing is uploaded unless you answer "y" or
  pass -u.

Live monitor and replay tool for Hammerspace assimilation logs.

Where the logs are:
  While an assimilation runs, its log is on the Anvil at
      /pd/assimilation-logs/<date-time stamp>/HS_root.log
  When it finishes, the log is moved into the destination share, so that folder
  normally holds only the folder for the run in progress. Live mode watches it
  by default and picks up new runs as they start. You can instead give:
      a folder      searched recursively for assimilation logs
      a log file    e.g. /shares/foo/COM.X_1724094740_HS_root.log
      a file name   e.g. HS_root.log, or part of one such as ONCOR; searched
                    for recursively under the default folder (or the folder
                    in front of it, e.g. /shares/foo/ONCOR)

  python3 catalyst.py                 # live monitor of /pd/assimilation-logs (prompts first)
  python3 catalyst.py -d /some/share  # live monitor of another folder / file / file name
  python3 catalyst.py replay          # replay one or more logs with original timing
  python3 catalyst.py simulate SRC DST  # write SRC into DST gradually (to test live mode)
  python3 catalyst.py -h              # all options

Pure Python 3.7+ standard library. No installs needed.
"""

import argparse
import calendar
import collections
import fnmatch
import heapq
import json
import os
import re
import shutil
import sys
import time

# ---------------------------------------------------------------------------
# Defaults you may want to edit
# ---------------------------------------------------------------------------
DEFAULT_LIVE_DIR = os.environ.get("CATALYST_DIR", "/pd/assimilation-logs")
# Matches the running log (HS_root.log) and logs already moved into shares (<share>_<epoch>_HS_root.log)
DEFAULT_FILE_GLOB = os.environ.get("CATALYST_GLOB", "*HS_root.log")
CONFIG_PATH = os.path.expanduser("~/.catalyst.json")

__title__ = "Hammerspace C.A.T.A.L.Y.S.T."
__expansion__ = "Continuous Assimilation Tracker And Logic for Yield, Storage, & Targeted Analysis"
__fullname__ = f"{__title__} - {__expansion__}"
__version__ = "2.4.3"
__date__ = "2026-10-29"
VERSION = __version__

# Upload (same request as dme-watch.sh). Note: like curl --insecure, TLS verification is skipped.
UPLOAD_URL = os.environ.get("CATALYST_UPLOAD_URL", "https://v1proto.sc.hammerspace.com/upload/")
UPLOAD_FIELDS = {"payload": "prosvcs", "cluster_id": "manual", "payload_type": "prosvcs"}
HOST = __import__("socket").gethostname().split(".")[0] or "host"
RUN_STAMP = time.strftime("%Y-%m-%d_%H%M%S")
SAVE_DIR = "/tmp" if os.path.isdir("/tmp") else __import__("tempfile").gettempdir()

# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
if os.name == "nt":
    os.system("")  # enables ANSI escape handling in Windows 10+ consoles


def _c(code):
    return code if USE_COLOR else ""


CYAN = _c("\033[36m")
BLUE = _c("\033[94m")
BRIGHT_CYAN = _c("\033[1;96m")
WHITE = _c("\033[1;37m")
GRAY = _c("\033[90m")
RED = _c("\033[1;91m")
YELLOW = _c("\033[93m")
MAGENTA = _c("\033[95m")
GREEN = _c("\033[92m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
RESET = _c("\033[0m")

SEV_COLOR = {"ERROR": RED, "ISSUE": YELLOW, "WARN": CYAN, "NOTE": MAGENTA, "INFO": GRAY}
SEV_RANK = {"ERROR": 0, "ISSUE": 1, "NOTE": 2, "WARN": 3, "INFO": 4}

BANNER_ART = r"""
  ____    _  _____    _    _   ___   ______   _____ _____ 
 / ___|  / \|_   _|  / \  | | | \ \ / / ___| |_   _|_   _|
| |     / _ \ | |   / _ \ | | | |\ V /\___ \   | |   | |  
| |___ / ___ \| |  / ___ \| |_| | | |  ___) |  | |   | |  
 \____/_/   \_\_| /_/   \_\\___/|_| |_| |____/   |_|   |_|  """


def print_banner(status="Assimilation & Analysis Engine Active"):
    print(f"{BRIGHT_CYAN}{BANNER_ART}{RESET}")
    print(f"{BLUE} [::] {WHITE}SYSTEM:{CYAN} {__title__} {GRAY}v{VERSION}{RESET}")
    print(f"{BLUE} [::] {WHITE}NAME:  {CYAN} {__expansion__}{RESET}")
    print(f"{BLUE} [::] {WHITE}STATUS:{CYAN} {status}{RESET}")
    print(f"{GRAY}{'=' * 61}{RESET}")


# ---------------------------------------------------------------------------
# Watch items
# ---------------------------------------------------------------------------
# (label, kind 'sub'|'re', pattern, severity, on-by-default, origin)
PRESETS = [
    ("error= ", "sub", "error= ", "ERROR", True, "your grep"),
    ("err= ", "sub", "err= ", "ERROR", True, "your grep"),
    ("Skipped ", "sub", "Skipped ", "ISSUE", True, "your grep"),
    ("Issues - A1 ", "sub", "Issues - A1 ", "ISSUE", True, "your grep"),
    ("Failed ", "sub", "Failed ", "ERROR", True, "your grep"),
    ('error="..."  (error detail line)', "re", r'^\s+error="', "ERROR", True, "samples"),
    ("err=<n>  (errno, e.g. err=13)", "re", r"\berr=\d+", "ERROR", True, "samples"),
    ("Issues during import of", "sub", "Issues during import of", "ISSUE", True, "samples"),
    ("Error importing directory contents", "sub", "Error importing directory contents", "ERROR", True, "samples"),
    ("Permission denied", "sub", "Permission denied", "ERROR", True, "samples"),
    ("Alternate data stream(s) not assimilated", "re", r"alternate streams? and (?:it was|they were) not assimilated", "WARN", False, "samples"),
    ("Unmapped SID -> ACE dropped", "sub", "so ACE dropped", "WARN", False, "samples"),
    ("Unmapped User/Group SID -> owner fallback", "re", r"Could not map (?:User|Group) SID", "WARN", False, "samples"),
    ("Owner mapped to nobody (uid 65534)", "sub", "uid=65534(", "WARN", False, "samples"),
    ('Skipped "..." because file not seen on the SMB side', "re",
     r'Skipped ".*" because file not seen on the SMB side', "ISSUE", True, "requested"),
    ('Skipped "..." because existence denied by SMB server', "re",
     r'Skipped ".*" because existence denied by SMB server', "ISSUE", True, "requested"),
]


class Watch:
    __slots__ = ("label", "kind", "pattern", "sev", "rx", "hits", "origin")

    def __init__(self, label, kind, pattern, sev, origin="custom"):
        self.label, self.kind, self.pattern, self.sev, self.origin = label, kind, pattern, sev, origin
        self.rx = re.compile(pattern) if kind == "re" else None
        self.hits = 0

    def match(self, text):
        return (self.rx.search(text) is not None) if self.rx else (self.pattern in text)


def parse_custom(spec):
    """'re:<regex>' or plain text; optional severity prefix E:/I:/W:/N:."""
    sev = "ISSUE"
    m = re.match(r"^([EIWN]):(.*)$", spec)
    if m:
        sev = {"E": "ERROR", "I": "ISSUE", "W": "WARN", "N": "NOTE"}[m.group(1)]
        spec = m.group(2)
    if spec.startswith("re:"):
        re.compile(spec[3:])  # validate
        return Watch(spec, "re", spec[3:], sev)
    return Watch(spec, "sub", spec, sev)


def parse_selection(text, n):
    try:
        return _parse_selection(text, n)
    except ValueError:
        return None


def ask_selection(prompt, default, n):
    while True:
        sel = parse_selection(ask(prompt, default), n)
        if sel is not None:
            return sel
        print(f"  {RED}Use numbers and ranges like 1,3-5 or 'all'.{RESET}")


def _parse_selection(text, n):
    text = text.strip().lower()
    if text in ("all", "a", "*"):
        return list(range(n))
    if text in ("none", "0", "-"):
        return []
    out = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return sorted({i for i in out if 0 <= i < n})


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def choose_watches(args, cfg):
    saved_sel = cfg.get("selected")
    known = cfg.get("known")  # preset labels that existed when the selection was saved
    if saved_sel is not None and known is None:
        known = [p[0] for p in PRESETS[:14]]  # configs saved by v2.4.2 or earlier
    defaults = [i for i, p in enumerate(PRESETS)
                if (p[0] in saved_sel if (saved_sel is not None and p[0] in known) else p[4])]
    customs = list(cfg.get("custom", []))

    if args.select is not None:
        sel = defaults if args.select == "default" else parse_selection(args.select, len(PRESETS))
        if sel is None:
            sys.exit(f"Bad --select value: {args.select}")
    elif args.no_prompt:
        sel = defaults
    else:
        print(f"\n{WHITE}WATCH ITEMS{RESET}  {GRAY}(* = requested by you, + = found in the sample logs){RESET}")
        for i, (label, kind, pat, sev, _on, origin) in enumerate(PRESETS):
            mark = f"{GREEN}[x]{RESET}" if i in defaults else "[ ]"
            tag = "+" if origin == "samples" else "*"
            print(f"  {mark} {i + 1:2d} {tag} {SEV_COLOR[sev]}{sev:5s}{RESET}  {label}")
        print(f"{GRAY}  Note: your grep items use 'error= ' / 'err= ' with a space; the sample logs write"
              f" error=\"...\" and err=13,\n  so items 6-7 catch those. Text inside imported file names is ignored"
              f" (e.g. a file called '...Failed Login...').{RESET}")
        while True:
            ans = input(f"Select numbers/ranges (e.g. 1-5,8), 'all', 'none' [Enter = marked]: ").strip()
            sel = defaults if not ans else parse_selection(ans, len(PRESETS))
            if sel is not None:
                break
            print(f"  {RED}Use numbers and ranges like 1-5,8 or 'all'.{RESET}")

        if customs:
            print(f"Saved custom items: {', '.join(customs)}")
            keep = input("Keep saved custom items? [Y/n]: ").strip().lower()
            if keep.startswith("n"):
                customs = []
        print(f"{GRAY}Add custom items: plain text or re:<regex>. Prefix E: I: W: N: for severity"
              f" (default ISSUE). Blank line to finish.{RESET}")
        while True:
            s = input("  custom> ").rstrip("\n")
            if not s.strip():
                break
            try:
                parse_custom(s)
                customs.append(s)
            except re.error as e:
                print(f"  {RED}bad regex: {e}{RESET}")

    for s in args.add or []:
        if s not in customs:
            customs.append(s)

    watches = [Watch(PRESETS[i][0], PRESETS[i][1], PRESETS[i][2], PRESETS[i][3], PRESETS[i][5]) for i in sel]
    watches += [parse_custom(s) for s in customs]
    cfg["selected"] = [PRESETS[i][0] for i in sel]
    cfg["known"] = [p[0] for p in PRESETS]
    cfg["custom"] = customs
    return watches


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------
TS_RX = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.(\d+):")
HDR_TIME_RX = re.compile(r'(?:start|end) time="(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.(\d+))?"')
PATH_RX = re.compile(r'^(\S+ \S+:(?:Imported|Issues during import of) )"(.*)"( into dir )')
NUM_RX = re.compile(r"\d+")
HEX_RX = re.compile(r"0x[0-9a-fA-F]+")
QUOTE_RX = re.compile(r'"[^"]*"')
_sec_cache = {}


def _epoch(sec_str):
    v = _sec_cache.get(sec_str)
    if v is None:
        if len(_sec_cache) > 4096:
            _sec_cache.clear()
        v = calendar.timegm(time.strptime(sec_str, "%Y-%m-%d %H:%M:%S"))
        _sec_cache[sec_str] = v
    return v


def line_ts(line):
    """Timestamp in seconds. Note: the fractional part in these logs is an
    *unpadded nanosecond count* (".5158979" = 5,158,979 ns, which is earlier than
    ".10752551"), so it is NOT a decimal fraction."""
    m = TS_RX.match(line)
    if m:
        return _epoch(m.group(1)) + int(m.group(2)) / 1e9
    m = HDR_TIME_RX.search(line)
    if m:
        frac = m.group(2) or "0"
        return _epoch(m.group(1)) + int(frac) / (10 ** len(frac))
    return None


def normalize(s, width=60):
    s = QUOTE_RX.sub('"…"', s)
    s = HEX_RX.sub("0x…", s)
    s = NUM_RX.sub("N", s)
    return s.strip()[:width]


def short_name(path, width=34):
    b = os.path.basename(path)
    if b == "HS_root.log":  # running logs all share this name; show the <date-time> folder too
        b = os.path.basename(os.path.dirname(path)) + "/" + b
    return b if len(b) <= width else "…" + b[-(width - 1):]


class FileState:
    def __init__(self, path, idx):
        self.path, self.idx = path, idx
        self.name = short_name(path)
        self.offset = 0
        self.partial = b""
        self.ino = None
        self.lineno = 0
        self.started = None
        self.completed = None
        self.first_ts = None
        self.last_ts = None
        self.imported = collections.Counter()
        self.issues = 0
        self.errors = 0
        self.warns = 0
        self.types = collections.Counter()  # error-type -> count (this file)
        self.cur_path = ""
        self.cur_dir_ino = None
        self.dir_paths = {}  # ino -> directory path (to resolve "Error importing ... dir ino=N")
        self.last_growth = time.time()
        self.eof = False
        self.truncated_tail = False
        self.alerted_stall = False
        self.rotations = 0
        self.sids = collections.Counter()
        self.nobody = 0
        self.ads = 0
        self.skips = collections.Counter()  # skip reason -> count
        self.fh = None        # kept open so we can finish reading after the log is moved/deleted
        self.gone = False     # path no longer points at this log (moved into share / deleted)

    @property
    def items(self):
        return sum(self.imported.values()) + self.issues

    def status(self, live, stall_secs):
        if self.completed:
            return "MOVED" if (live and self.gone) else "COMPLETE"
        if live and self.gone:
            return "VANISHED"
        if live:
            if time.time() - self.last_growth > stall_secs:
                return "STALLED"
            return "ACTIVE"
        return "INCOMPLETE" if self.eof else "ACTIVE"


class Engine:
    """Classifies every line, counts error types, matches watch items, keeps the feed."""

    def __init__(self, watches, match_paths=False, feed_size=3000, matches_csv=None, plain=False):
        self.watches = watches
        self.match_paths = match_paths
        self.files = []
        self.by_path = {}
        self.types = collections.Counter()  # (sev, type) -> count
        self.type_files = collections.defaultdict(set)
        self.sids = collections.Counter()
        self.sid_perm = collections.Counter()
        self.nobody = 0
        self.ads = 0
        self.feed = collections.deque(maxlen=feed_size)
        self.total_lines = 0
        self.total_bytes = 0
        self.plain = plain
        self.csv = None
        if matches_csv:
            import csv
            fh = open(matches_csv, "w", newline="", encoding="utf-8")
            self.csv = (fh, csv.writer(fh))
            self.csv[1].writerow(["file", "line", "timestamp", "severity", "type", "watch_items", "path", "text"])

    def add_file(self, path):
        fs = FileState(path, len(self.files))
        self.files.append(fs)
        self.by_path[path] = fs
        return fs

    # -- classification --------------------------------------------------
    SKIP_REASONS = {
        "file not seen on the SMB side": "Skipped - file not seen on the SMB side",
        "existence denied by SMB server": "Skipped - existence denied by SMB server",
    }

    def _skipped(self, fs, text):
        """'Skipped "<path>" because <reason>' -> ISSUE typed by reason; None if not a skip line."""
        if not text.startswith('Skipped "'):
            return None
        end = text.rfind('" because ')
        if end < 0:
            fs.issues += 1
            return ("ISSUE", "Skipped: " + normalize(text[8:], 45))
        fs.cur_path = text[9:end]
        reason = text[end + 10:].strip().rstrip(".")
        fs.issues += 1
        fs.skips[reason] += 1
        return ("ISSUE", self.SKIP_REASONS.get(reason, "Skipped - " + normalize(reason, 50)))

    def _classify(self, fs, line):
        """Return (severity, type) or None for routine lines; updates per-file context."""
        c0 = line[:1]
        if c0 == " " or c0 == "\t":
            s = line.lstrip()
            if s.startswith('Skipped "'):
                return self._skipped(fs, s)
            if s.startswith('warning msg="'):
                fs.warns += 1
                if s.endswith('so ACE dropped."'):
                    i = s.find('SID="')
                    if i >= 0:
                        j = s.find('"', i + 5)
                        sid = s[i + 5:j]
                        self.sids[sid] += 1
                        fs.sids[sid] += 1
                        k = s.find("perm=", j)
                        if k >= 0:
                            self.sid_perm[(sid, s[k + 5:s.find(" ", k)])] += 1
                    return ("WARN", "Unmapped SID - ACE dropped")
                if s.startswith('warning msg="Could not map User SID'):
                    return ("WARN", "Unmapped user SID - owner id fallback")
                if s.startswith('warning msg="Could not map Group SID'):
                    return ("WARN", "Unmapped group SID - group id fallback")
                if "alternate stream" in s:
                    self.ads += 1
                    fs.ads += 1
                    return ("WARN", "Alternate data stream(s) not assimilated")
                return ("WARN", "warning: " + normalize(s[13:]))
            if s.startswith('error="'):
                fs.errors += 1
                j = s.find('"', 7)
                err = s[7:j]
                op = ""
                k = s.find('msg="', j)
                if k >= 0:
                    op = s[k + 5:].split(" ", 1)[0].rstrip('",')
                m = re.search(r"\berr=(\d+)", s)
                t = f"{err}" + (f" (err={m.group(1)})" if m else "") + (f" [{op}]" if op else "")
                return ("ERROR", t)
            key = s.split("=", 1)[0].lower()
            if "err" in key or "fail" in key:
                fs.errors += 1
                return ("ERROR", f"{key}: " + normalize(s))
            return ("NOTE", "Unrecognised detail: " + normalize(s, 50))

        m = TS_RX.match(line)
        if m:
            fs.last_ts = _epoch(m.group(1)) + int(m.group(2)) / 1e9
            if fs.first_ts is None:
                fs.first_ts = fs.last_ts
            body = line[m.end():]
            if body.startswith('Imported "'):
                end = body.find('" into dir ')
                fs.cur_path = body[10:end] if end > 0 else body[10:80]
                t = body.rfind(" type=")
                if t >= 0:
                    r = body.find(' ReadOnly="', t)
                    if r < 0:
                        r = body.find(' readonly="', t)
                    typ = body[t + 6:r] if r > 0 else body[t + 6:]
                else:
                    typ = "?"
                fs.imported[typ] += 1
                if "uid=65534(" in body:
                    self.nobody += 1
                    fs.nobody += 1
                if typ == "Directory":
                    u = body.find(" used=", end)
                    i = body.find(" ino=", u if u > 0 else end + 10)
                    if i > 0:
                        fs.dir_paths[body[i + 5:body.find(" ", i + 5)]] = fs.cur_path
                return None
            if body.startswith('Skipped "'):
                return self._skipped(fs, body)
            if body.startswith('Issues during import of "'):
                fs.issues += 1
                end = body.find('" into dir ')
                fs.cur_path = body[25:end] if end > 0 else body[25:80]
                t = body.rfind(" type=")
                typ = body[t + 6:].split(" ", 1)[0] if t >= 0 else "?"
                return ("ISSUE", f"Issues during import (type={typ})")
            low = body.lower()
            if "error" in low or "fail" in low:
                fs.errors += 1
                return ("ERROR", normalize(body, 55))
            return ("NOTE", "Unrecognised line: " + normalize(body, 45))

        if line.startswith("Assimilation started"):
            fs.started = line
            ts = line_ts(line)
            if ts and fs.first_ts is None:
                fs.first_ts = ts
            return None
        if line.startswith("Assimilation complete"):
            fs.completed = line
            ts = line_ts(line)
            if ts:
                fs.last_ts = ts
            return None
        if line.startswith('Skipped "'):
            return self._skipped(fs, line)
        if line.startswith("Error importing directory contents"):
            fs.errors += 1
            ino = line.rsplit("=", 1)[-1].strip()
            fs.cur_path = fs.dir_paths.get(ino, f"(dir ino={ino}, path not seen)")
            return ("ERROR", "Error importing directory contents")
        if not line.strip():
            return None
        low = line.lower()
        if "error" in low or "fail" in low:
            fs.errors += 1
            return ("ERROR", normalize(line, 55))
        return ("NOTE", "Unrecognised line: " + normalize(line, 45))

    def process_line(self, fs, line):
        fs.lineno += 1
        self.total_lines += 1
        cls = self._classify(fs, line)
        if cls:
            self.types[cls] += 1
            fs.types[cls] += 1
            self.type_files[cls].add(fs.idx)

        hits = None
        if self.watches:
            target = line
            stripped = None
            for w in self.watches:
                if w.match(target):
                    if not self.match_paths and line[:1] != " ":
                        if stripped is None:
                            stripped = PATH_RX.sub(r'\1"…"\3', line, count=1)
                        if not w.match(stripped):
                            continue
                    w.hits += 1
                    if hits is None:
                        hits = [w]
                    else:
                        hits.append(w)
        if hits:
            sev = min((w.sev for w in hits), key=lambda s: SEV_RANK[s])
            if cls and SEV_RANK[cls[0]] < SEV_RANK[sev]:
                sev = cls[0]
            typ = cls[1] if cls else hits[0].label
            ts = fs.last_ts
            tstr = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) if ts else ""
            labels = ", ".join(w.label.strip() for w in hits)
            entry = (tstr, fs.name, sev, typ, fs.cur_path, line.strip(), labels, fs.lineno, fs.path)
            self.feed.append(entry)
            if self.csv:
                self.csv[1].writerow([fs.path, fs.lineno, tstr, sev, typ, labels, fs.cur_path, line.rstrip()])
            if self.plain:
                self._say(f"{tstr} {SEV_COLOR[sev]}{sev:5s}{RESET} {fs.name}:{fs.lineno} {typ} | {fs.cur_path} | {line.strip()[:200]}")

    def event(self, sev, typ, fs, text):
        tstr = time.strftime("%Y-%m-%d %H:%M:%S")
        self.feed.append((tstr, fs.name, sev, typ, fs.path, text, "monitor", fs.lineno, fs.path))
        if self.plain:
            self._say(f"{tstr} {SEV_COLOR[sev]}{sev:5s}{RESET} {fs.name} {typ} | {text}")

    def _say(self, text):
        """Print a feed line; if the reader went away (e.g. piped into head), stop printing but keep counting."""
        try:
            print(text, flush=True)
        except BrokenPipeError:
            self.plain = False
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
            except OSError:
                pass

    def close(self):
        if self.csv:
            self.csv[0].close()

    # -- highlights --------------------------------------------------------
    def highlights(self, live, stall_secs):
        out = []
        for fs in self.files:
            st = fs.status(live, stall_secs)
            if st == "VANISHED":
                out.append(("ERROR", f"{fs.name}: log disappeared before 'Assimilation complete' -"
                                     f" assimilation aborted/removed, or log moved early"))
            elif st == "STALLED":
                out.append(("ERROR", f"{fs.name}: no growth for {int(time.time() - fs.last_growth)}s and no"
                                     f" 'Assimilation complete' - job stalled, killed, or log moved"))
            elif st == "INCOMPLETE":
                out.append(("ERROR", f"{fs.name}: ended without 'Assimilation complete' - run did not finish"
                                     f" (or log was copied mid-run)"))
            if fs.truncated_tail:
                out.append(("ISSUE", f"{fs.name}: last line is cut off mid-write"))
            if fs.started is None and fs.lineno > 0:
                out.append(("NOTE", f"{fs.name}: no 'Assimilation started' header (log may be partial)"))
            items = fs.items
            if items >= 10 and fs.issues / items > 0.10:
                out.append(("ERROR", f"{fs.name}: {fs.issues}/{items} items ({fs.issues * 100 // items}%) had"
                                     f" 'Issues during import' - most of this share is not coming across"))
            pd = sum(c for (sev, t), c in fs.types.items() if t.startswith("Permission denied"))
            if pd:
                out.append(("ERROR", f"{fs.name}: {pd} x Permission denied reading source attrs (err=13) -"
                                     f" check export permissions / root squash for the assimilation host"))
            ed = sum(c for (sev, t), c in fs.types.items() if t == "Error importing directory contents")
            if ed:
                out.append(("ERROR", f"{fs.name}: {ed} directories reported 'Error importing directory contents'"
                                     f" - their contents may be incomplete (see feed for paths)"))
            fi = fs.items or 1
            if fs.sids and fs.items >= 10:
                sid, c = fs.sids.most_common(1)[0]
                pct = min(100, c * 100 // fi)
                if pct >= 5:
                    full = self.sid_perm.get((sid, "0x1f01ff"), 0)
                    msg = (f"{fs.name}: SID {sid} unmapped on {c:,} entries (~{pct}% of items), ACE dropped"
                           + (" (Full Control ACEs among them)" if full else "")
                           + " - add an ID mapping or these ACLs will not survive")
                    out.append(("ISSUE" if pct >= 25 else "WARN", msg))
            if fs.nobody and fs.items >= 10:
                pct = fs.nobody * 100 // fi
                if pct >= 5:
                    out.append(("ISSUE" if pct >= 25 else "WARN",
                                f"{fs.name}: {fs.nobody:,} items (~{pct}%) now owned by uid 65534 (nobody)"))
            for reason, n in fs.skips.most_common():
                if reason == "file not seen on the SMB side":
                    out.append(("ISSUE", f"{fs.name}: {n:,} file{'s' if n != 1 else ''} skipped - not seen on the SMB side (present over NFS"
                                         f" but not visible through SMB; check SMB share path, vetoed/hidden files, name"
                                         f" characters SMB can't show)"))
                elif reason == "existence denied by SMB server":
                    out.append(("ISSUE", f"{fs.name}: {n:,} file{'s' if n != 1 else ''} skipped - existence denied by SMB server (check SMB"
                                         f" share/ACL permissions for the account used by the assimilation)"))
                else:
                    out.append(("ISSUE", f"{fs.name}: {n:,} file{'s' if n != 1 else ''} skipped - {reason}"))
            if fs.ads:
                out.append(("WARN", f"{fs.name}: {fs.ads:,} files had alternate data streams that were NOT"
                                    f" assimilated (macOS resource forks / Windows ADS lost)"))
        unk = sum(c for (sev, t), c in self.types.items() if sev == "NOTE")
        if unk:
            out.append(("NOTE", f"{unk} line(s) in a format not seen in the samples - see feed"))
        out.sort(key=lambda x: SEV_RANK[x[0]])
        return out


# ---------------------------------------------------------------------------
# File discovery & tailing
# ---------------------------------------------------------------------------
def discover(root, pattern):
    root = os.path.expanduser(root)
    if os.path.isfile(root):
        return [os.path.abspath(root)]
    pats = [p.strip() for p in pattern.split(",") if p.strip()]
    found = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != "__MACOSX" and not d.startswith(".")]
        for fn in fns:
            if fn.startswith("._"):
                continue
            if any(fnmatch.fnmatch(fn, p) for p in pats):
                found.append(os.path.abspath(os.path.join(dp, fn)))
    return sorted(found)


def resolve_target(text, pattern, bases):
    """Turn what the user typed into (root, pattern, description).

    text may be a folder (searched recursively), a log file, or a log file name / part of one
    (searched recursively under `bases`, or under the folder in front of it)."""
    t = os.path.expanduser(text.strip().strip('"').strip("'"))
    if os.path.isdir(t):
        root = os.path.abspath(t)
        return root, pattern, f"{root} (recursive, {pattern})"
    if os.path.isfile(t):
        root = os.path.abspath(t)
        return root, os.path.basename(root), root
    head, name = os.path.split(t.rstrip("/\\"))
    if not name:
        return os.path.abspath(t), pattern, t
    if os.path.abspath(t) == os.path.abspath(DEFAULT_LIVE_DIR):  # default log folder not created yet
        return os.path.abspath(t), pattern, f"{os.path.abspath(t)} (recursive, {pattern})"
    if head and not os.path.isdir(head):  # a path whose folder doesn't exist
        return os.path.abspath(t), pattern, t
    pat = name if any(ch in name for ch in "*?[") else f"*{name}*"
    cands = [head] if head else bases
    cands = [os.path.abspath(c) for c in cands if c and os.path.isdir(c)]
    for c in cands:
        if discover(c, pat):
            return c, pat, f"{c} (recursive, name {pat})"
    root = cands[0] if cands else os.path.abspath(head or (bases[0] if bases else "."))
    return root, pat, f"{root} (recursive, name {pat})"


def _open_log(engine, fs):
    try:
        fs.fh = open(fs.path, "rb")
    except OSError:
        return False
    st = os.fstat(fs.fh.fileno())
    if fs.ino is not None and st.st_ino != fs.ino:
        fs.offset, fs.partial = 0, b""  # a different file now lives at this path
    if st.st_size < fs.offset:
        fs.offset, fs.partial = 0, b""
    fs.ino = st.st_ino
    fs.fh.seek(fs.offset)
    return True


def read_new(engine, fs, budget):
    """Read up to `budget` bytes of new data from fs; returns bytes consumed.

    The file handle is kept open, so when Hammerspace moves the finished log into the
    destination share we still read whatever was written right before the move."""
    if fs.gone:
        return 0
    if fs.fh is None and not _open_log(engine, fs):
        return 0
    try:
        pst = os.stat(fs.path)
        same = pst.st_ino == fs.ino
    except OSError:
        pst, same = None, False
    hst = os.fstat(fs.fh.fileno())
    if hst.st_size < fs.offset:  # truncated in place
        fs.rotations += 1
        engine.event("NOTE", "Log truncated - re-reading from start", fs, fs.path)
        fs.offset, fs.partial = 0, b""
        fs.fh.seek(0)
    data = fs.fh.read(budget)
    if not data:
        if not same:  # drained the old file and the path no longer points at it
            fs.fh.close()
            fs.fh = None
            if fs.partial:
                engine.process_line(fs, fs.partial.decode("utf-8", "replace").rstrip("\r"))
                fs.truncated_tail = not fs.completed
                fs.partial = b""
            if pst is None:
                fs.gone = True
                if fs.completed:
                    engine.event("NOTE", "Assimilation finished - log moved into destination share", fs, fs.path)
                else:
                    engine.event("ERROR", "Log disappeared before 'Assimilation complete'", fs, fs.path)
            else:
                fs.rotations += 1
                engine.event("NOTE", "Log replaced at same path - reading new file", fs, fs.path)
                fs.offset, fs.ino = 0, None
        return 0
    fs.offset += len(data)
    fs.last_growth = time.time()
    fs.alerted_stall = False
    fs.truncated_tail = False
    engine.total_bytes += len(data)
    data = fs.partial + data
    lines = data.split(b"\n")
    fs.partial = lines.pop()
    for b in lines:
        engine.process_line(fs, b.decode("utf-8", "replace").rstrip("\r"))
    return len(data)


# ---------------------------------------------------------------------------
# Keyboard (non-blocking)
# ---------------------------------------------------------------------------
class Keys:
    def __init__(self):
        self.ok = sys.stdin.isatty()
        self.old = None

    def __enter__(self):
        if self.ok and os.name != "nt":
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *a):
        if self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)

    def get(self, timeout):
        if not self.ok:
            time.sleep(timeout)
            return None
        if os.name == "nt":
            import msvcrt
            end = time.time() + timeout
            while time.time() < end:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.02)
            return None
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def fmt_dur(sec):
    if sec is None:
        return "-"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ansi_len(s):
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def fit(s, width):
    """Truncate a string containing ANSI codes to `width` visible chars."""
    out, vis, i = [], 0, 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            out.append(s[i:j + 1])
            i = j + 1
            continue
        if vis >= width:
            break
        out.append(s[i])
        vis += 1
        i += 1
    return "".join(out) + RESET


class Dashboard:
    def __init__(self, engine, mode, root, live, stall_secs):
        self.e, self.mode, self.root, self.live, self.stall = engine, mode, root, live, stall_secs
        self.feed_filter = 0  # 0 all, 1 errors+issues, 2 errors only
        self.paused = False
        self.msg = ""
        self.started = time.time()

    def render(self, extra=""):
        e = self.e
        cols, rows = shutil.get_terminal_size((120, 40))
        cols = max(cols, 60)
        L = []
        act = sum(1 for f in e.files if f.status(self.live, self.stall) == "ACTIVE")
        head = (f"{BRIGHT_CYAN}{__title__}{RESET} {GRAY}v{VERSION}{RESET}  {WHITE}{self.mode}{RESET}  "
                f"{GRAY}{('…' + self.root[-40:]) if len(self.root) > 41 else self.root}{RESET}  files {len(e.files)} (active {act})  lines {e.total_lines:,}  "
                f"{time.strftime('%H:%M:%S')}")
        L.append(head)
        L.append(f"{GRAY}{__expansion__}{RESET}")
        keys = "[q]uit [f]eed filter [c]lear feed [p]ause"
        if self.mode.startswith("REPLAY"):
            keys += " [+/-] speed [s]kip gap"
        L.append(f"{GRAY}{keys}{RESET}  {extra}  {YELLOW}{self.msg}{RESET}")

        # files
        L.append(f"{WHITE}FILES{RESET}")
        if not e.files and getattr(self, "waiting", None):
            L.append(f"  {YELLOW}{self.waiting}{RESET}")
        L.append(f"{GRAY}  {'status':10s} {'file':34s} {'items':>10s} {'issues':>7s} {'errors':>7s} "
                 f"{'warns':>9s} {'elapsed':>8s}  last log time{RESET}")
        stc = {"COMPLETE": GREEN, "MOVED": GREEN, "ACTIVE": CYAN, "STALLED": RED, "INCOMPLETE": RED,
               "VANISHED": RED}
        max_files = max(3, min(len(e.files), rows // 5))
        shown = sorted(e.files, key=lambda f: (f.status(self.live, self.stall) == "COMPLETE", -f.last_growth))
        for f in shown[:max_files]:
            st = f.status(self.live, self.stall)
            el = (f.last_ts - f.first_ts) if (f.first_ts and f.last_ts) else None
            lt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(f.last_ts)) if f.last_ts else "-"
            L.append(f"  {stc.get(st, '')}{st:10s}{RESET} {f.name:34s} {f.items:>10,} "
                     f"{(YELLOW if f.issues else '')}{f.issues:>7,}{RESET} {(RED if f.errors else '')}{f.errors:>7,}{RESET} "
                     f"{f.warns:>9,} {fmt_dur(el):>8s}  {lt}")
        if len(e.files) > max_files:
            L.append(f"{GRAY}  … {len(e.files) - max_files} more files{RESET}")

        # summary by type
        L.append(f"{WHITE}COUNT BY TYPE{RESET}")
        items = sorted(e.types.items(), key=lambda kv: (SEV_RANK[kv[0][0]], -kv[1]))
        max_types = max(4, rows // 4)
        if not items:
            L.append(f"{GRAY}  (nothing yet){RESET}")
        for (sev, t), c in items[:max_types]:
            nf = len(e.type_files[(sev, t)])
            L.append(f"  {SEV_COLOR[sev]}{sev:5s}{RESET} {c:>11,}  {t}  {GRAY}({nf} file{'s' if nf != 1 else ''}){RESET}")
        if len(items) > max_types:
            L.append(f"{GRAY}  … {len(items) - max_types} more types (full list in final summary){RESET}")

        # watch items
        if e.watches:
            L.append(f"{WHITE}WATCH ITEMS{RESET}")
            line, vis = "  ", 2
            for w in e.watches:
                lab = re.sub(r"\s+\(.*\)$", "", w.label.strip())[:30]
                part = f"{SEV_COLOR[w.sev]}{lab}{RESET} {BOLD}{w.hits:,}{RESET}   "
                plen = len(lab) + len(f"{w.hits:,}") + 4
                if vis + plen > cols and vis > 2:
                    L.append(line)
                    line, vis = "  ", 2
                line += part
                vis += plen
            L.append(line)

        # highlights
        hl = e.highlights(self.live, self.stall)
        if hl:
            L.append(f"{WHITE}HIGHLIGHTS{RESET}")
            for sev, text in hl[:max(3, rows // 6)]:
                L.append(f"  {SEV_COLOR[sev]}!{RESET} {text}")

        # live feed
        flt = ["all", "errors+issues", "errors only"][self.feed_filter]
        L.append(f"{WHITE}LIVE ITEMS OF CONCERN{RESET} {GRAY}(filter: {flt}){RESET}")
        room = rows - len(L) - 1
        if room > 0:
            want = []
            for ent in reversed(e.feed):
                sev = ent[2]
                if self.feed_filter == 1 and sev not in ("ERROR", "ISSUE"):
                    continue
                if self.feed_filter == 2 and sev != "ERROR":
                    continue
                want.append(ent)
                if len(want) >= room:
                    break
            for tstr, fname, sev, typ, path, text, labels, ln, _ in reversed(want):
                L.append(f"  {GRAY}{tstr[5:]}{RESET} {SEV_COLOR[sev]}{sev:5s}{RESET} {GRAY}{fname[:22]}{RESET} "
                         f"{typ[:38]} {WHITE}{path}{RESET}")
        out = "\033[H" + "".join(fit(l, cols) + "\033[K\n" for l in L[:rows - 1]) + "\033[J"
        sys.stdout.write(out)
        sys.stdout.flush()

    def handle_key(self, k):
        if k == "f":
            self.feed_filter = (self.feed_filter + 1) % 3
        elif k == "c":
            self.e.feed.clear()
        elif k == "p":
            self.paused = not self.paused
            self.msg = "PAUSED" if self.paused else ""


def enter_screen():
    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()


def leave_screen():
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
def summary_text(engine, live, stall, color=True):
    c = (lambda x: x) if color else (lambda x: "")
    R = c(RESET)
    out = []
    out.append(f"{c(WHITE)}=== {__title__} v{VERSION} SUMMARY  ({time.strftime('%Y-%m-%d %H:%M:%S')}) ==={R}")
    out.append(f"{c(GRAY)}{__expansion__}{R}")
    out.append(f"Files: {len(engine.files)}   Lines: {engine.total_lines:,}")
    for f in engine.files:
        el = (f.last_ts - f.first_ts) if (f.first_ts and f.last_ts) else None
        imp = ", ".join(f"{k}={v:,}" for k, v in f.imported.most_common())
        out.append(f"\n{c(WHITE)}{f.path}{R}")
        out.append(f"  status={f.status(live, stall)}  items={f.items:,}  issues={f.issues:,}  errors={f.errors:,}"
                   f"  warnings={f.warns:,}  elapsed={fmt_dur(el)}")
        out.append(f"  imported by type: {imp or '-'}")
        for (sev, t), n in sorted(f.types.items(), key=lambda kv: (SEV_RANK[kv[0][0]], -kv[1])):
            out.append(f"    {c(SEV_COLOR[sev])}{sev:5s}{R} {n:>11,}  {t}")
    out.append(f"\n{c(WHITE)}COUNT BY TYPE (all files){R}")
    for (sev, t), n in sorted(engine.types.items(), key=lambda kv: (SEV_RANK[kv[0][0]], -kv[1])):
        out.append(f"  {c(SEV_COLOR[sev])}{sev:5s}{R} {n:>11,}  {t}  ({len(engine.type_files[(sev, t)])} files)")
    if engine.watches:
        out.append(f"\n{c(WHITE)}WATCH ITEMS{R}")
        for w in engine.watches:
            out.append(f"  {c(SEV_COLOR[w.sev])}{w.sev:5s}{R} {w.hits:>11,}  {w.label}")
    if engine.sids:
        out.append(f"\n{c(WHITE)}TOP UNMAPPED SIDs (ACE dropped){R}")
        for sid, n in engine.sids.most_common(8):
            out.append(f"  {n:>11,}  {sid}")
    hl = engine.highlights(live, stall)
    if hl:
        out.append(f"\n{c(WHITE)}HIGHLIGHTS{R}")
        for sev, t in hl:
            out.append(f"  {c(SEV_COLOR[sev])}{sev:5s}{R} {t}")
    return "\n".join(out)


def capture_paths():
    base = f"catalyst_{HOST}_{RUN_STAMP}"
    return (os.path.join(SAVE_DIR, base + "_report.txt"),
            os.path.join(SAVE_DIR, base + "_matches.csv"),
            os.path.join(SAVE_DIR, f"catalyst_bundle_{HOST}_{RUN_STAMP}.tar.gz"))


def setup_save(args):
    """Ask (interactive) or honour -o/-u; point report + CSV at /tmp when saving."""
    if not args.save and not args.no_prompt and sys.stdin.isatty():
        a = ask("Save captured errors + summary to " + SAVE_DIR + " (for upload when you stop)? (y/n)", "n")
        args.save = a.lower().startswith("y")
    if args.save:
        rep, csvp, _ = capture_paths()
        args.report = args.report or rep
        args.matches_csv = args.matches_csv or csvp
        args.started_at = time.strftime("%a %b %d %H:%M:%S %Z %Y")


def do_upload(files, url):
    import tarfile
    _, _, tarball = capture_paths()
    files = [f for f in files if f and os.path.exists(f)]
    print("Compressing files...")
    try:
        with tarfile.open(tarball, "w:gz") as tf:
            for f in files:
                tf.add(f, arcname=os.path.basename(f))  # relative paths inside the bundle
    except Exception as e:
        print(f"{RED}Error: Failed to create compression bundle: {e}{RESET}")
        return False
    print(f"Created bundle: {tarball}")
    print("Uploading to Hammerspace...")
    t0 = time.time()
    curl = shutil.which("curl")
    if curl:
        import subprocess
        cmd = [curl, "--insecure", "-i", "-X", "POST", "-H", "Content-Type: multipart/form-data"]
        for k, v in UPLOAD_FIELDS.items():
            cmd += ["-F", f"{k}={v}"]
        cmd += ["-F", f"file=@{tarball}", url]
        rc = subprocess.call(cmd)
        ok = rc == 0
    else:
        import ssl
        import urllib.request
        import uuid
        boundary = "----catalyst" + uuid.uuid4().hex
        body = bytearray()
        for k, v in UPLOAD_FIELDS.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        with open(tarball, "rb") as f:
            data = f.read()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f"filename=\"{os.path.basename(tarball)}\"\r\nContent-Type: application/gzip\r\n\r\n").encode()
        body += data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=bytes(body), method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        ctx = ssl._create_unverified_context()  # mirrors curl --insecure in dme-watch.sh
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=300) as r:
                print(f"HTTP {r.status} {r.reason}")
                print(r.read(2000).decode("utf-8", "replace"))
                ok = 200 <= r.status < 300
        except Exception as e:
            print(f"{RED}Upload failed: {e}{RESET}")
            ok = False
    print(f"\nUpload attempt complete. ({time.time() - t0:.1f}s)")
    return ok


def finish(engine, args, live):
    engine.close()
    txt = summary_text(engine, live, args.stall_secs, color=USE_COLOR)
    print(txt)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            if args.save:
                f.write(f"# {__fullname__}\n# Capture v{__version__}\n# Host:    {HOST}\n"
                        f"# Mode:    {'live' if live else 'replay'}\n# Source:  {args.source_root}\n"
                        f"# Started: {getattr(args, 'started_at', '')}\n"
                        f"# Stopped: {time.strftime('%a %b %d %H:%M:%S %Z %Y')}\n"
                        f"# Watch:   {', '.join(w.label.strip() for w in engine.watches) or '(none)'}\n#\n")
            f.write(summary_text(engine, live, args.stall_secs, color=False) + "\n")
            f.write("\nFILES\n" + "".join(f"  {fs.path}\n" for fs in engine.files))
        print(f"\nReport written to {args.report}")
    if args.matches_csv:
        print(f"Matched lines written to {args.matches_csv}")
    if not args.save:
        return

    entries = len(engine.feed) if engine.csv is None else sum(w.hits for w in engine.watches)
    concerns = sum(c for (sev, t), c in engine.types.items() if sev in ("ERROR", "ISSUE"))
    print(f"Saved {entries:,} matched entries ({concerns:,} errors/issues seen) to {SAVE_DIR}")
    if entries == 0 and concerns == 0:
        print("No errors were captured, so there's nothing to upload.")
        return
    upload = args.upload
    if not upload and sys.stdin.isatty():
        print("-" * 69)
        upload = ask("Do you want to upload this capture to Hammerspace? (y/n)", "n").lower().startswith("y")
    if upload:
        do_upload([args.report, args.matches_csv], args.upload_url)
    else:
        print(f"Upload skipped. Files remain at {args.report}" + (f" and {args.matches_csv}" if args.matches_csv else ""))


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
def ask(prompt, default):
    try:
        v = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        v = ""
    return v or default


def _ino(p):
    try:
        return os.stat(p).st_ino
    except OSError:
        return None


def run_live(args, cfg):
    target = args.dir or DEFAULT_LIVE_DIR
    while True:
        if not args.no_prompt and not args.dir:
            print(f"{GRAY}Running assimilations log to {DEFAULT_LIVE_DIR}/<date-time>/HS_root.log on the Anvil."
                  f" Enter that, another folder (searched recursively), a log file, or a log file name.{RESET}")
            target = ask(f"{WHITE}Monitor{RESET}", target)
        root, pattern, desc = resolve_target(target, args.glob, [DEFAULT_LIVE_DIR, os.getcwd()])
        if os.path.isdir(root) and not args.glob_given and not args.no_prompt and pattern == args.glob \
                and os.path.abspath(os.path.expanduser(target)) == root:
            pattern = ask(f"{WHITE}File name pattern{RESET} (comma-separate several)", pattern)
            desc = f"{root} (recursive, {pattern})"
        if os.path.exists(root):
            break
        if root == os.path.abspath(DEFAULT_LIVE_DIR) and os.path.isdir(os.path.dirname(root)):
            break  # on an Anvil before any assimilation has created the folder: wait for it
        print(f"{RED}Not found: {root}{RESET}"
              + (" - this doesn't look like an Anvil; give a folder, log file, or file name." if root == DEFAULT_LIVE_DIR else ""))
        if args.no_prompt or args.dir:
            return 2
        target = DEFAULT_LIVE_DIR if target != DEFAULT_LIVE_DIR else os.getcwd()
    from_start = args.from_start
    if from_start is None:
        from_start = True
        if not args.no_prompt:
            a = ask("Existing files: read from [b]eginning (full counts) or only [n]ew lines", "b").lower()
            from_start = not a.startswith("n")
    watches = choose_watches(args, cfg)
    save_config(cfg)
    args.source_root = root
    setup_save(args)

    engine = Engine(watches, args.match_paths, matches_csv=args.matches_csv, plain=args.plain)
    files = discover(root, pattern)
    for p in files:
        fs = engine.add_file(p)
        try:
            st = os.stat(p)
            fs.last_growth = st.st_mtime
            if not from_start:
                fs.offset, fs.ino = st.st_size, st.st_ino
        except OSError:
            pass
    print(f"Monitoring {desc}")
    if files:
        print(f"Found {len(files)} log(s). Checking for new ones every {args.rescan:g}s…")
    else:
        print(f"{YELLOW}No assimilation log there yet - waiting for one to start (checking every {args.rescan:g}s).{RESET}")
    time.sleep(0.8)

    dash = None if args.plain else Dashboard(engine, "LIVE", root, True, args.stall_secs)
    if dash:
        dash.waiting = f"no assimilation log yet - waiting for a new run under {root}"
    last_scan = time.time()
    last_draw = 0
    if dash:
        enter_screen()
    try:
        with Keys() as keys:
            while True:
                t0 = time.time()
                busy = False
                for fs in list(engine.files):
                    if read_new(engine, fs, args.chunk_mb * 1024 * 1024):
                        busy = True
                    if time.time() - t0 > 0.3:
                        break
                    if (not fs.completed and not fs.gone and not fs.alerted_stall
                            and time.time() - fs.last_growth > args.stall_secs):
                        fs.alerted_stall = True
                        if fs.partial:
                            fs.truncated_tail = True
                        engine.event("ERROR", "Stalled: no growth, no completion line", fs,
                                     f"{fs.path} (idle {int(time.time() - fs.last_growth)}s)")
                if time.time() - last_scan > args.rescan:
                    last_scan = time.time()
                    for p in discover(root, pattern):
                        old = engine.by_path.get(p)
                        if old is None or (old.gone and _ino(p) != old.ino):
                            fs = engine.add_file(p)
                            engine.event("NOTE", "New assimilation log detected", fs, p)
                if dash and not dash.paused and time.time() - last_draw > args.refresh:
                    dash.render()
                    last_draw = time.time()
                k = keys.get(0 if busy else 0.2)
                if k:
                    if k in ("q", "Q"):
                        break
                    if dash:
                        dash.handle_key(k)
    except KeyboardInterrupt:
        pass
    finally:
        if dash:
            leave_screen()
    finish(engine, args, live=True)
    return 0


def record_stream(fs, engine):
    """Yield (ts, [lines]) records from a file; a record = one top-level line + its indented detail lines."""
    last = None
    rec = []
    rec_ts = None
    with open(fs.path, "rb") as f:
        for b in f:
            if not b.endswith(b"\n"):
                fs.truncated_tail = True
            line = b.decode("utf-8", "replace").rstrip("\r\n")
            if line[:1] in (" ", "\t") and rec:
                rec.append(line)
                continue
            if rec:
                yield rec_ts, rec
            ts = line_ts(line)
            if ts is not None:
                last = ts if last is None else max(last, ts)  # threads log slightly out of order
            rec_ts = last if last is not None else 0.0
            rec = [line]
    if rec:
        yield rec_ts, rec


def run_replay(args, cfg):
    target = args.dir or cfg.get("replay_dir") or os.getcwd()
    while True:
        if not args.no_prompt and not args.dir:
            target = ask(f"{WHITE}Replay{RESET} (folder searched recursively, log file, or log file name)", target)
        root, pattern, desc = resolve_target(target, args.glob, [os.getcwd(), DEFAULT_LIVE_DIR])
        if os.path.isdir(root) and not args.glob_given and not args.no_prompt and pattern == args.glob \
                and os.path.abspath(os.path.expanduser(target)) == root:
            pattern = ask(f"{WHITE}File name pattern{RESET}", pattern)
        files = discover(root, pattern) if os.path.exists(root) else []
        if files:
            break
        print(f"{RED}No assimilation logs matching {pattern} under {root}{RESET}")
        if args.no_prompt or args.dir:
            return 2
    cfg["replay_dir"] = target
    if len(files) > 1 and not args.no_prompt and args.files is None:
        print(f"\n{WHITE}Files found:{RESET}")
        for i, p in enumerate(files):
            sz = os.path.getsize(p) / 1e6
            print(f"  {i + 1:2d}  {sz:9.1f} MB  {os.path.relpath(p, root) if os.path.isdir(root) else p}")
        sel = ask_selection("Replay which (e.g. 1,3-4 or all)", "all", len(files))
        files = [files[i] for i in sel]
    elif args.files:
        files = [files[i] for i in (parse_selection(args.files, len(files)) or [])]
    if not files:
        return 0
    speed = args.speed
    if speed is None:
        while True:
            s = "1" if args.no_prompt else ask("Speed multiplier (1 = real time, 10, 100, max)", "1")
            s = s.lower().strip()
            try:
                speed = 0.0 if s in ("max", "0", "inf") else float(s[:-1] if s.endswith("x") else s)
                if speed >= 0:
                    break
            except ValueError:
                pass
            print(f"  {RED}Enter a number like 1, 10, 100, or 'max'.{RESET}")
    watches = choose_watches(args, cfg)
    save_config(cfg)
    args.source_root = ", ".join(files)
    setup_save(args)

    engine = Engine(watches, args.match_paths, matches_csv=args.matches_csv, plain=args.plain)
    states = [engine.add_file(p) for p in files]
    streams = [record_stream(fs, engine) for fs in states]
    heap = []
    seq = 0
    for i, s in enumerate(streams):
        nxt = next(s, None)
        if nxt:
            heapq.heappush(heap, (nxt[0], seq, i, nxt[1]))
            seq += 1
        else:
            states[i].eof = True

    dash = None if args.plain else Dashboard(engine, "REPLAY", root, False, args.stall_secs)
    vclock = heap[0][0] if heap else 0.0  # virtual log time "now"
    last_wall = time.time()
    last_log = vclock
    last_draw = 0
    if dash:
        enter_screen()
    try:
        with Keys() as keys:
            while True:
                now = time.time()
                dt = now - last_wall
                last_wall = now
                paused = dash.paused if dash else False
                if not paused and speed > 0:
                    vclock += dt * speed
                t0 = time.time()
                while heap and not paused:
                    ts = heap[0][0]
                    i, rec = heap[0][2], heap[0][3]
                    if ts - vclock > args.max_gap:  # compress long idle gaps (and jumps between files)
                        vclock = ts - args.max_gap
                    if speed > 0 and ts > vclock:
                        break
                    heapq.heappop(heap)
                    last_log = max(last_log, ts)
                    fs = states[i]
                    for line in rec:
                        engine.process_line(fs, line)
                    nxt = next(streams[i], None)
                    if nxt:
                        heapq.heappush(heap, (nxt[0], seq, i, nxt[1]))
                        seq += 1
                    else:
                        fs.eof = True
                    if time.time() - t0 > 0.25:
                        break
                if speed > 0 and vclock > last_log + 2:
                    vclock = max(vclock - 1, last_log)  # processing fell behind; don't let a backlog snowball
                if not heap and not paused:
                    if dash:
                        dash.msg = "REPLAY COMPLETE - press q to exit"
                    else:
                        break
                if dash and time.time() - last_draw > args.refresh:
                    sp = "max" if speed <= 0 else f"{speed:g}x"
                    lt = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last_log)) if last_log else "-"
                    dash.mode = f"REPLAY {sp}"
                    dash.render(extra=f"log clock {lt}")
                    last_draw = time.time()
                k = keys.get(0 if (heap and (speed <= 0)) else 0.05)
                if k:
                    if k in ("q", "Q"):
                        break
                    if k == "+":
                        speed = 2.0 if speed <= 0 else speed * 2
                        speed = 0.0 if speed > 1e6 else speed
                    elif k == "-":
                        speed = 1e5 if speed <= 0 else max(0.125, speed / 2)
                    elif k == "s" and heap:
                        vclock = heap[0][0]
                    elif dash:
                        dash.handle_key(k)
    except KeyboardInterrupt:
        pass
    finally:
        if dash:
            leave_screen()
    finish(engine, args, live=False)
    return 0


def run_simulate(args):
    """Write SRC into DST progressively with original timing, to exercise live mode."""
    src, dst = args.src, args.dst
    speed = args.speed or 1.0
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    print(f"Simulating {src} -> {dst} at {speed:g}x (Ctrl-C to stop)")
    fs = FileState(src, 0)
    first = None
    t_start = time.time()
    with open(dst, "w", encoding="utf-8") as out:
        for ts, rec in record_stream(fs, None):
            if first is None:
                first = ts
            due = t_start + (ts - first) / speed
            delay = due - time.time()
            if delay > 0:
                out.flush()
                time.sleep(min(delay, 5))
            out.write("\n".join(rec) + "\n")
    print("Done.")
    return 0


# ---------------------------------------------------------------------------
def _speed_arg(v):
    v = v.lower().strip()
    if v in ("max", "inf"):
        return 0.0
    f = float(v[:-1] if v.endswith("x") else v)
    if f < 0:
        raise argparse.ArgumentTypeError("speed must be 0 or more")
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="catalyst",
        description=f"{__fullname__}\nv{__version__} - live monitor & replay for Hammerspace assimilation logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Keys while running: q quit, f cycle feed filter, c clear feed, p pause, +/- replay speed, "
               "s skip to next record (replay).\nCustom watch items: plain text or re:<regex>; prefix "
               "E: I: W: N: to set severity, e.g.  --add 'E:re:err=(5|28)'")
    ap.add_argument("mode", nargs="?", default="live", choices=["live", "replay", "simulate"])
    ap.add_argument("src", nargs="?", help="(simulate) source log")
    ap.add_argument("dst", nargs="?", help="(simulate) destination log to grow")
    ap.add_argument("-d", "--dir", help=f"folder (searched recursively), log file, or log file name to monitor/replay; default {DEFAULT_LIVE_DIR}")
    ap.add_argument("-g", "--glob", default=None, help=f"file name pattern(s), comma-separated; default {DEFAULT_FILE_GLOB}")
    ap.add_argument("-s", "--select", help="watch items to enable: 'all', 'none', 'default', or e.g. 1-5,8")
    ap.add_argument("-a", "--add", action="append", help="custom watch item (repeatable)")
    ap.add_argument("-y", "--no-prompt", action="store_true", help="don't ask anything; use defaults/saved choices")
    ap.add_argument("--files", help="(replay) which discovered files, e.g. 1,3 or all")
    ap.add_argument("--speed", type=_speed_arg, help="(replay/simulate) speed multiplier; 0 or max = as fast as possible")
    ap.add_argument("--max-gap", type=float, default=5.0, help="(replay) compress idle gaps longer than this many seconds")
    beg = ap.add_mutually_exclusive_group()
    beg.add_argument("--from-start", dest="from_start", action="store_true", default=None,
                     help="(live) read existing content first (default)")
    beg.add_argument("--from-end", dest="from_start", action="store_false", help="(live) only new lines")
    ap.add_argument("--stall-secs", type=int, default=120, help="(live) flag a log as STALLED after this idle time")
    ap.add_argument("--rescan", type=float, default=5.0, help="(live) seconds between folder rescans for new files")
    ap.add_argument("--refresh", type=float, default=0.5, help="screen refresh interval (s)")
    ap.add_argument("--chunk-mb", type=int, default=8, help="max MB read per file per pass")
    ap.add_argument("--match-paths", action="store_true",
                    help="also match watch items inside imported file/dir names (off by default)")
    ap.add_argument("--plain", action="store_true", help="no dashboard; print matching lines like grep, summary at end")
    ap.add_argument("--report", help="write the final summary to this text file")
    ap.add_argument("--matches-csv", help="write every matched line to this CSV")
    ap.add_argument("-o", "--save", action="store_true",
                    help=f"save captured errors + summary to {SAVE_DIR}/catalyst_<host>_<timestamp>_*")
    ap.add_argument("-u", "--upload", action="store_true",
                    help="save, and upload to Hammerspace when stopped without asking (implies -o)")
    ap.add_argument("--upload-url", default=UPLOAD_URL, help=f"upload endpoint (default {UPLOAD_URL})")
    ap.add_argument("-q", "--no-banner", action="store_true", help="don't show the banner at startup")
    ap.add_argument("-v", "--version", action="version", version=f"{__fullname__}\nv{__version__}")
    args = ap.parse_args(argv)
    args.glob_given = args.glob is not None
    if args.upload:
        args.save = True
    args.source_root = args.dir or ""
    args.glob = args.glob or DEFAULT_FILE_GLOB
    if not sys.stdout.isatty():
        args.plain = True

    if not args.no_banner:
        print_banner()
    if args.mode == "simulate":
        if not (args.src and args.dst):
            ap.error("simulate needs SRC and DST")
        return run_simulate(args)
    cfg = load_config()
    if args.mode == "replay":
        return run_replay(args, cfg)
    return run_live(args, cfg)


if __name__ == "__main__":
    try:
        import signal
        signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    except Exception:
        pass
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
