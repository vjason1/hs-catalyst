# Hammerspace C.A.T.A.L.Y.S.T.

**Continuous Assimilation Tracker And Logic for Yield, Storage, & Targeted Analysis**

Live monitor and replay tool for Hammerspace assimilation logs (`HS_root.log`). It shows a full-screen dashboard with the status of each log, a count of every error type, highlights of likely problems, and a live feed of items of concern. You can save what it finds and upload it to Hammerspace.

- Single file: [`catalyst.py`](https://github.com/vjason1/hs-catalyst/blob/main/catalyst.py)
- Python 3.7+, standard library only (nothing to install)
- Runs on **Linux**, the primary platform: the Hammerspace Anvil is Linux-based, and live monitoring of `/pd/assimilation-logs` happens there. Also runs on Windows 10/11 and macOS (see "Platforms" below)
- Full guide: [`docs/Hammerspace_CATALYST.docx`](https://github.com/vjason1/hs-catalyst/blob/main/docs/Hammerspace_CATALYST.docx) (also importable into Confluence)
- Source repository: <https://github.com/vjason1/hs-catalyst>
- Confluence copy of this README: [`docs/README_confluence.docx`](https://github.com/vjason1/hs-catalyst/blob/main/docs/README_confluence.docx) (Import → Word document) or [`docs/README_confluence.md`](https://github.com/vjason1/hs-catalyst/blob/main/docs/README_confluence.md) (Insert → Markup → Markdown)

> **Important:** **Running assimilations require Hammerspace support.** While an assimilation is underway, its log is only on the Anvil (`/pd/assimilation-logs`), which end users can't access. **End users can examine logs of completed assimilations**, which are stored in the `assimilation-logs` folder at the root of each Hammerspace share.

## Quick start

```bash
python3 catalyst.py replay -d /mnt/finance   # end users: completed logs in a share's assimilation-logs folder
python3 catalyst.py -d /mnt/finance          # end users: scan a share's logs, 5 at a time, renaming each to *-scanned
python3 catalyst.py                          # Hammerspace support, on the Anvil: watch running assimilations
python3 catalyst.py -h                       # all options
```

Press **Enter** at the prompts to accept the defaults, then **q** to stop and see the summary.

## Platforms

| Platform | Use | How to run |
|---|---|---|
| **Linux** (primary) | Completed logs from a share; on the Anvil, live monitoring of running assimilations (Hammerspace support) | `python3 catalyst.py` |
| Windows 10/11 | Completed logs from a mounted share, or copied logs | `py catalyst.py` (or `python catalyst.py`) |
| macOS | Completed logs from a mounted share, or copied logs | `python3 catalyst.py` |

Notes for Windows:

- Use Windows Terminal or the Windows 10/11 console for the full-screen dashboard. Older consoles automatically fall back to plain output.
- Output goes to `%TEMP%` by default; change it with `-O`.
- Logs aren't held open between reads, so the program writing a log can still move or rename it.
- Upload uses the `curl.exe` included with Windows 10/11.

## Where the logs are

| Assimilation | Log location | Who can access it |
|---|---|---|
| **Completed** | `<share>/assimilation-logs/<date-time stamp>/` (a folder for the day the assimilation ran, inside the `assimilation-logs` folder at the root of each Hammerspace share) | **End users** |
| **Running** | `/pd/assimilation-logs/<date-time stamp>/HS_root.log` on the Anvil | **Hammerspace support only** |

**End users:** completed logs are in a folder for the day the assimilation ran, for example:

```
/mnt/finance/assimilation-logs/<date-time stamp>/COM.X_1724094740_HS_root.log
```

Point the tool at the share, or at its `assimilation-logs` folder. Use `replay` to analyze completed logs, or live mode to watch for new logs as assimilations finish. Folders are searched recursively, so giving the share root finds `assimilation-logs` and every dated folder in it automatically.

**Hammerspace support (on the Anvil):** live mode watches `/pd/assimilation-logs` by default and picks up new runs as they start. When an assimilation finishes, Hammerspace moves its log to the share's `assimilation-logs` folder. On Linux the tool keeps each log open, so it still reads the final lines after the move.

| Status | Meaning |
|---|---|
| `ACTIVE` | Log is still growing |
| `COMPLETE` | Log contains `Assimilation complete` |
| `MOVED` | Completed and moved to the share's `assimilation-logs` folder (normal) |
| `STALLED` | No growth for `--stall-secs` and no completion line |
| `VANISHED` | Log disappeared before completing |
| `SCANNED` | Outside the Anvil folder: read to the end (and renamed to `*-scanned`) |
| `INCOMPLETE` | Log ended without `Assimilation complete` (replay, or a scanned log outside the Anvil folder) |

## Scanning completed logs: 5 at a time

Hammerspace runs at most **5 assimilations at once**, so the tool never needs to handle more than 5 logs together. When you scan anywhere **other than** the Anvil's `/pd/assimilation-logs` folder (for example a share's `assimilation-logs` folder):

- **At most 5 logs are scanned at a time,** oldest first. The rest wait in a queue, shown at the top of the dashboard (`scanning 3 of max 5 · queued 4 · done 2`).
- **Each finished log is renamed** to end in `-scanned` (for example `COM.X_1724094740_HS_root.log-scanned`) before the next one starts. A log counts as finished when it has been read to the end and contains `Assimilation complete`, or when it has sat unchanged at the end for 10 seconds without one; that log is marked `INCOMPLETE`.
- **Renamed logs aren't picked up again,** so running the tool on the same folder later only scans new logs.
- **To scan without renaming,** use `--no-rename`.
- Existing logs are always read from the beginning (`--from-end` is ignored here).

In the Anvil folder, logs are never renamed: Hammerspace moves them itself. **Replay** also plays at most 5 logs at a time (the next starts as one finishes) but never renames files.

## What to monitor

The `-d` option, or the **Monitor** prompt, accepts any of these. Folders are always searched recursively.

| Input | Example |
|---|---|
| Nothing (default) | `/pd/assimilation-logs` (Hammerspace support, on the Anvil) |
| A share, or its `assimilation-logs` folder | `-d /mnt/finance` or `-d /mnt/finance/assimilation-logs` |
| A log file | `-d /mnt/finance/assimilation-logs/<date-time stamp>/COM.X_1724094740_HS_root.log` |
| A file name, or part of one | `-d HS_root.log`, `-d ONCOR` |
| A folder plus a name | `-d /mnt/finance/ONCOR` |

## Telling logs apart: share ID

When several logs are scanned together, every result shows the **share ID** it came from. The ID is read from each log's first line (`Assimilation started for share=126 obsid=192 …`). That matters because running logs are all named `HS_root.log`. The share ID appears in:

- **FILES table:** a `share` column.
- **Count by type, error guide and summaries:** which shares each error type came from, for example `(shares 126, 301)`, or `(share 301 · 2 logs)` when one share has several logs.
- **Live feed, highlights and plain output:** each line is tagged, for example `[share 126]`.
- **Exports:** the error log, the matches CSV (`share` column), and the unknown-entry file. Summaries also give the obsid.

The ID is read as soon as a log is found, so it's known even with `--from-end`. A log without the header line shows `share ?`.

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
| `q` | Quit and show the summary (Ctrl-C also works). In the error guide, `q` returns to the scan instead. |
| `e` | Open the **error guide** while the scan keeps running (see below). `e` or `Esc` returns to the screen you came from. |
| `v` | When more than one log is being scanned: switch between the **file list** and the **shares view** (see below). |
| `f` | Change the feed filter: all, errors and issues, errors only |
| `c` | Clear the feed |
| `p` | Pause |
| `+` / `-` | Replay speed |
| `s` | Replay: skip to the next entry |

## Output directory

Everything the tool writes goes to one folder: reports, CSV, Markdown exports, the error log, the unrecognised-entry file, and upload bundles. The default is `/tmp`. Change it with `-O DIR` / `--output-dir DIR`, or set `CATALYST_OUT`. The folder is created if it doesn't exist. The path is shown at startup.

```bash
python3 catalyst.py -O ~/catalyst-reports -x     # export into ~/catalyst-reports on exit
```

## Saving and uploading

- `-o` saves the summary and all matched lines to `<output dir>/catalyst_<host>_<timestamp>_report.txt` and `_matches.csv`. When you stop, it asks whether to upload them.
- `-u` saves, and uploads when stopped without asking.

The upload bundles both files as a `.tar.gz` and POSTs them to the Hammerspace endpoint the same way as `dme-watch.sh`. It uses `curl` if installed, or a built-in HTTP upload otherwise. Override the endpoint with `--upload-url` or `CATALYST_UPLOAD_URL`.

## Shares view

When more than one log is being scanned, press **`v`** to swap the scrolling file list for a dashboard of errors **per share ID**, and `v` again to go back. There's a panel for each share, up to 5 (the most assimilations Hammerspace runs at once), with active shares first:

- Share ID, obsid(s), number of logs and their status
- Items, errors, issues and warnings for that share
- Its most frequent error types
- Its latest items of concern (log time, type, affected path)

If more than 5 shares are present, the rest are noted at the bottom and are still in the summary reports.

## Error guide (while scanning)

Press **`e`** at any time to swap the dashboard for the error guide. The scan or replay keeps running underneath, and a status line at the top shows live line, error, issue and warning counts.

- **Found in this scan:** every error type found so far, worst severity first, then by count. Each shows its live count, how many files it appeared in, and its explanation. For SID errors, the PowerShell lookups use the most frequent SIDs from the log. Types that first appear while the guide is open are tagged **NEW**. Types with no description yet, and log entries the tool doesn't recognise, are listed with a short note.
- **Other error types:** the remaining types the tool can explain, not seen in this scan.
- **Keys:** `Up`/`Down` or `j`/`k` scroll; `PgUp`/`PgDn` or `b`/`space` page; `Home`/`End`. In replay, `+`/`-` still change speed. Press `e`, `Esc` or `q` to return to the scan.

## What the errors mean

The exit summary, saved report, and Markdown export include a **What these errors mean** section for each error type found. For SID errors, it adds PowerShell Active Directory lookups filled in with the most frequent domain SIDs from the log.

### Unmapped SID - ACE dropped

A user/group SID could not be mapped to a current AD user/group, so that ACE was dropped. In most cases, it is because the user or group was deleted. To verify this, search AD with the PowerShell commands below.

If the SID maps to a user/group, verify that it was not deleted. If not, verify that the cluster is joined to an Active Directory domain, is not having any issues communicating with Active Directory, and (if applicable) can query the target domain using a trust from the domain the cluster is joined to.

```powershell
Import-Module ActiveDirectory
Get-ADUser -Identity <SID>
Get-ADGroup -Identity <SID>
```


### No such file or directory (err=2) [nfs3_get_attr_by_readdir_file_id]

Hammerspace was unable to read a file using the source NFS export. As a result, it was not assimilated. To resolve this issue, check the file on the source volume, and, if present and valid, copy it manually to Hammerspace. If a large number of files are impacted, then you may need to correct something on the source volume, and retry the assimilation into a new/empty destination.


### Error importing directory contents

Hammerspace experienced an unidentified error importing the contents of a directory using the source NFS export. Check that the directory can be read within the Hammerspace share, and that all the contents are present (if there were any on the source). If the directory is missing some or all of the contents, check it directly on the source volume, and, if unassimilated files are present, copy them manually to Hammerspace. If a large number of directories are impacted, then you may need to correct something on the source volume (possibly including SMB permissions), and retry the assimilation into a new/empty destination.


### Issues during import (type=Regular)

Hammerspace experienced an unidentified error importing a file using the source NFS export. Check that it can be read within the Hammerspace share, and that the contents are intact (if there were any on the source). If the file cannot be read, or is empty, check it directly on the source volume, and, if present, copy it manually to Hammerspace. If a large number of files are impacted, then you may need to correct something on the source volume (possibly including SMB permissions), and retry the assimilation into a new/empty destination.


### Issues during import (type=Directory)

Hammerspace experienced an unidentified error importing a directory using the source NFS export. Check that it can be read within the Hammerspace share, and that the contents are present (if there were any on the source). If the directory cannot be read, or is missing some or all of the contents, check it directly on the source volume, and, if present, copy it manually to Hammerspace. If a large number of directories are impacted, then you may need to correct something on the source volume (possibly including SMB permissions), and retry the assimilation into a new/empty destination.


### Skipped - file not seen on the SMB side

This usually indicates that Hammerspace can see the file fine from the source NFS export, but is denied when trying to import the ACEs using the source SMB share. As a result, this file is skipped. Check this file directly on the source, and, if present, copy it manually to Hammerspace. If a large number of files are impacted, then you may need to correct something on the source volume (such as granting the assimilation service account access to the denied files), and retry the assimilation into a new/empty destination.

A less common reason for this error is that the file was deleted from the source before the SMB ACEs could be read.


### Skipped - existence denied by SMB server

Hammerspace can see the file fine from the NFS export, but cannot see it from the SMB share. As a result, this file is skipped. Check this file directly on the source, and, if present, copy it manually to Hammerspace. If a large number of files are impacted, then you may need to correct something on the source volume, and retry the assimilation into a new/empty destination.

One possible reason for this error is that the file was deleted from the source before the SMB ACEs could be read.


### Unmapped user SID - owner id fallback

A user SID could not be mapped to a current AD user, so the owning user was set to the fallback (if specified in the assimilation options). In most cases, it is because the user was deleted. To verify this, search AD with the PowerShell commands below.

```powershell
Import-Module ActiveDirectory
Get-ADUser -Identity <SID>
```


### Unmapped group SID - group id fallback

A group SID could not be mapped to a current AD group, so the owning group was set to the fallback (if specified in the assimilation options). In most cases, it is because the group was deleted. To verify this, search AD with the PowerShell commands below.

```powershell
Import-Module ActiveDirectory
Get-ADGroup -Identity <SID>
```


### Alternate data stream(s) not assimilated

Hammerspace does not currently support alternate data streams, so these are not imported during the assimilation process. This is expected.


## Exporting a report

When you quit, the summary is printed on screen and you're asked:

```
Export Markdown summary reports and full error logs (N errors/issues), one per share (S)? (y/N)
```

If you answer **y**, it asks for a folder (default: the output directory, `/tmp` unless changed with `-O`) and writes:

| File | Contents |
|---|---|
| `catalyst_<host>_<timestamp>_share<ID>_summary.md` | **One per share.** That share's summary in Markdown: highlights, files, count by type, watch items, top unmapped SIDs, what the errors mean, per-file breakdown, and any log entries not recognised |
| `catalyst_<host>_<timestamp>_share<ID>_errors.log` | **One per share.** Every ERROR, ISSUE and NOTE line found in that share's logs, each with log time, severity, type, share ID, log file and line number, affected path, and the original log line. Warnings are counted in the summary but not listed, since logs can have millions of them. |
| `catalyst_<host>_<timestamp>_summary.md` | When more than one share was scanned: an overview of all shares together |

Use `-x [DIR]` to export without being asked (default folder: the output directory). If you're also saving with `-o` / `-u`, the exported files are included in the upload bundle.

## Log entries the tool doesn't recognise

If a log contains an entry C.A.T.A.L.Y.S.T. doesn't recognise, it appears in the feed as a NOTE and in the highlights. Each one is kept with every line of its log entry (the timestamp line plus its indented detail lines). Up to 3 examples of each kind are kept.

When you quit, the tool lists these entries, saves them to `<output dir>/catalyst_<host>_<timestamp>_unknown.txt`, and asks:

```
Send these entries to Hammerspace so the tool can learn them? (y/N)
```

- **y**: the file is bundled as `<output dir>/catalyst_unknown_<host>_<timestamp>.tar.gz` and uploaded the same way as other captures.
- **N** (the default), or no terminal: you're asked to email the log entry text to **jason.ventresco@hammerspace.com**, and given the file to copy or attach.

## Examples

```bash
python3 catalyst.py -o                                    # watch, save, ask about upload at the end
python3 catalyst.py -y -u                                 # unattended, upload on exit
python3 catalyst.py -x ~/reports                          # export Markdown summary + error log on exit
python3 catalyst.py -d /mnt/finance                       # scan a share's completed logs (5 at a time, renamed to *-scanned)
python3 catalyst.py -d /mnt/finance --no-rename           # same, without renaming the logs
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
| `CATALYST_OUT` | Output directory (default `/tmp`) |
| `CATALYST_UPLOAD_URL` | Upload endpoint |
| `NO_COLOR` | Turn colors off |

## Version history

| Version | Changes |
|---|---|
| 2.5.4 | Summary report and full error log exported per share (plus an all-shares overview). `v` switches between the file list and a per-share dashboard (up to 5 shares). Outside the Anvil folder, at most 5 logs are scanned at a time and each finished log is renamed to `*-scanned` (`--no-rename` to skip). Replay plays at most 5 logs at a time. |
| 2.5.3 | Share ID (from each log's header) shown wherever results from several logs appear: FILES table, count by type, error guide, live feed, highlights, summaries, error log, CSV, unknown-entry file. |
| 2.5.2 | `e` opens an error guide while the scan keeps running: types found so far first (live counts, NEW tags, SID lookups), then the other known types. Arrow/Page/Home/End keys. |
| 2.5.1 | Completed logs shown in their dated folder: `<share>/assimilation-logs/<date-time stamp>/<log>`. |
| 2.5.0 | Notes that monitoring running assimilations requires Hammerspace support, and that end users examine completed logs in `<share>/assimilation-logs/`. Corrected where finished logs are moved to. |
| 2.4.9 | Windows support (console colors and fallback, safe file handling, no crashes on unsupported characters). Linux remains the primary platform. |
| 2.4.8 | `-O` / `--output-dir` (or `CATALYST_OUT`) sets where all output goes; default `/tmp`. Exports default to it. |
| 2.4.7 | Banner now spells CATALYST. Startup hint split over two lines. |
| 2.4.6 | Summary, report, and Markdown export explain each error type found, with next steps and pre-filled PowerShell AD lookups for unmapped SIDs. |
| 2.4.5 | On exit, offers to export a Markdown summary report and the full log of every error/issue (`-x DIR` to export without asking). Exports are included in the upload. |
| 2.4.4 | Log entries the tool doesn't recognise are kept with the lines of each entry. On exit you're offered to upload them (default No); otherwise you're asked to email them. |
| 2.4.3 | Watch items 15–16 for files skipped by SMB (not seen on the SMB side / existence denied), on by default, with counts by reason and highlights. |
| 2.4.2 | Live mode watches `/pd/assimilation-logs` by default. Accepts a folder, log file, or file name. Handles logs moved at completion (`MOVED`) or removed early (`VANISHED`). |
| 2.4.1 | Initial release |
