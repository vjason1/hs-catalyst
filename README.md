# Hammerspace C.A.T.A.L.Y.S.T.

**Continuous Assimilation Tracker And Logic for Yield, Storage, & Targeted Analysis**

Live monitor and replay tool for Hammerspace assimilation logs (`HS_root.log`). It shows a full-screen dashboard with the status of each log, a count of every error type, highlights of likely problems, and a live feed of items of concern. You can save what it finds and upload it to Hammerspace.

- Single file: [`catalyst.py`](catalyst.py)
- Python 3.7+, standard library only (nothing to install)
- Runs on a Hammerspace Anvil, Linux, or macOS
- Full guide: [`docs/Hammerspace_CATALYST.docx`](docs/Hammerspace_CATALYST.docx) (also importable into Confluence)

## Quick start

```bash
python3 catalyst.py              # live: watch /pd/assimilation-logs on the Anvil
python3 catalyst.py replay       # replay a finished log with its original timing
python3 catalyst.py -h           # all options
```

Press **Enter** at the prompts to accept the defaults, then **q** to stop and see the summary.

## Where the logs are

While an assimilation runs, its log is at:

```
/pd/assimilation-logs/<date-time stamp>/HS_root.log
```

When the assimilation finishes, the log is moved into the destination share as `<share>_<epoch>_HS_root.log`. C.A.T.A.L.Y.S.T. watches `/pd/assimilation-logs` by default and picks up new runs as they start. It keeps each log open so the final lines are still read after the move.

| Status | Meaning |
|---|---|
| `ACTIVE` | Log is still growing |
| `COMPLETE` | Log contains `Assimilation complete` |
| `MOVED` | Completed and moved into the destination share (normal) |
| `STALLED` | No growth for `--stall-secs` and no completion line |
| `VANISHED` | Log disappeared before completing |
| `INCOMPLETE` | Replay: log ended without `Assimilation complete` |

## What to monitor

The `-d` option, or the **Monitor** prompt, accepts any of these. Folders are always searched recursively.

| Input | Example |
|---|---|
| Nothing (default) | `/pd/assimilation-logs` |
| A folder | `-d /shares/finance` |
| A log file | `-d /shares/finance/COM.X_1724094740_HS_root.log` |
| A file name, or part of one | `-d HS_root.log`, `-d ONCOR` |
| A folder plus a name | `-d /shares/finance/ONCOR` |

## Watch items

At startup, choose which items feed the live list of items of concern (`--select all`, `none`, `default`, or `1-5,8`). Error types are always counted.

| # | Item | Severity | Default |
|---|---|---|---|
| 1–5 | `error= `, `err= `, `Skipped `, `Issues - A1 `, `Failed ` (original grep) | mixed | on |
| 6 | `error="..."` error detail line | ERROR | on |
| 7 | `err=<n>` error number (e.g. `err=13`) | ERROR | on |
| 8 | Issues during import of | ISSUE | on |
| 9 | Error importing directory contents | ERROR | on |
| 10 | Permission denied | ERROR | on |
| 11 | Alternate data stream(s) not assimilated | WARN | off |
| 12 | Unmapped SID, ACE dropped | WARN | off |
| 13 | Unmapped user/group SID, owner fallback | WARN | off |
| 14 | Owner mapped to nobody (uid 65534) | WARN | off |
| 15 | `Skipped "…" because file not seen on the SMB side` | ISSUE | on |
| 16 | `Skipped "…" because existence denied by SMB server` | ISSUE | on |

Add your own with `--add` (repeatable). Use plain text or `re:<regex>`, optionally starting with `E:` / `I:` / `W:` / `N:` to set the severity:

```bash
python3 catalyst.py --add 'E:re:err=(5|28)' --add 'W:Stale file handle'
```

Text inside imported file and folder names is ignored unless you pass `--match-paths`.

Skipped lines are counted by reason (for example *Skipped - file not seen on the SMB side*), the skipped file's path is shown in the feed, and each reason gets a highlight. New items in an upgrade start at their default, even if you saved a selection with an earlier version.

## Keys

| Key | Action |
|---|---|
| `q` | Quit and show the summary (Ctrl-C also works) |
| `f` | Change the feed filter: all, errors and issues, errors only |
| `c` | Clear the feed |
| `p` | Pause |
| `+` / `-` | Replay speed |
| `s` | Replay: skip to the next entry |

## Saving and uploading

- `-o` saves the summary and all matched lines to `/tmp/catalyst_<host>_<timestamp>_report.txt` and `_matches.csv`. When you stop, it asks whether to upload them.
- `-u` saves, and uploads when stopped without asking.

The upload bundles both files as a `.tar.gz` and POSTs them to the Hammerspace endpoint the same way as `dme-watch.sh`. It uses `curl` if installed, or a built-in HTTP upload otherwise. Override the endpoint with `--upload-url` or `CATALYST_UPLOAD_URL`.

## Examples

```bash
python3 catalyst.py -o                                    # watch, save, ask about upload at the end
python3 catalyst.py -y -u                                 # unattended, upload on exit
python3 catalyst.py -d /shares/finance                    # watch a share with finished logs
python3 catalyst.py replay -d ./logs --speed 20           # replay at 20x
python3 catalyst.py replay -y -d ./logs --speed max \
    --plain --report report.txt --matches-csv hits.csv    # analyze all logs fast, grep-style
python3 catalyst.py simulate old_HS_root.log test/HS_root.log   # write a log out gradually to test live mode
```

## Environment variables

| Variable | Purpose |
|---|---|
| `CATALYST_DIR` | Default folder (default `/pd/assimilation-logs`) |
| `CATALYST_GLOB` | Default file name pattern (default `*HS_root.log`) |
| `CATALYST_UPLOAD_URL` | Upload endpoint |
| `NO_COLOR` | Turn colors off |

## Version history

| Version | Changes |
|---|---|
| 2.4.3 | Watch items 15–16 for files skipped by SMB (not seen on the SMB side / existence denied), on by default, with counts by reason and highlights. |
| 2.4.2 | Live mode watches `/pd/assimilation-logs` by default. Accepts a folder, log file, or file name. Handles logs moved at completion (`MOVED`) or removed early (`VANISHED`). |
| 2.4.1 | Initial release |
