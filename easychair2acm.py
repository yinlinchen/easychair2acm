#!/usr/bin/env python3
"""easychair2acm - convert EasyChair CSV exports into ACM enhanced-CSV metadata.

Takes the ``submission`` and ``author`` tables exported from EasyChair and writes
the ACM "enhanced CSV" proceedings-metadata file used by the ACM eRights /
copyright grid (one row per author per accepted paper, 31 columns).

  * Columns are located by header name, not fixed positions.
  * Accepted papers are detected from the ``decision`` column.
  * The ACM Proceeding ID is a command-line option.
  * File encoding is auto-detected.

No third-party dependencies. Python 3.8+.

Derived from https://github.com/annaritz/easychair-to-acm-erights
(originally by Di Wu and Anna Ritz).
ACM enhanced CSV spec: https://www.acm.org/publications/gi-proceedings-current
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

__version__ = "1.0.0"

# ACM enhanced CSV: 31 columns, in this exact order. A blank value means the data
# is not available from EasyChair; some of these are completed later in the ACM
# grid (author profile ids) or once the program is scheduled (section / page
# numbers).
ACM_COLUMNS = [
    "proceeding_id",
    "event_tracking_number",
    "paper_type",
    "title",
    "prefix",
    "first_name",
    "middle_name",
    "last_name",
    "suffix",
    "author_sequence_no",
    "contact_author",
    "acm_profile_id",
    "acm_client_no",
    "orcid",
    "email",
    "department_school_lab",
    "institution",
    "city",
    "state_province",
    "country",
    "secondary_department_school_lab",
    "secondary_institution",
    "secondary_city",
    "secondary_state_province",
    "secondary_country",
    "section_title",
    "section_seq_no",
    "published_article_number",
    "start_page",
    "end_page",
    "article_seq_no",
]

# Encodings tried, in order, when reading an input file.
ENCODINGS_TO_TRY = ("utf-8-sig", "utf-8", "cp1252", "mac_roman", "latin-1")

# Values in EasyChair's "corresponding?" column that mark a contact author.
CONTACT_TRUE = {"yes", "y", "true", "1"}

# Common ACM paper_type values, shown in --help. Any string is accepted; check
# your proceedings' ACM instructions for the exact wording it expects.
COMMON_PAPER_TYPES = (
    "Full Paper", "Short Paper", "Poster", "Abstract",
    "Demonstration", "Workshop Paper", "Keynote", "Invited Paper",
)


def die(msg: str) -> "NoReturn":  # noqa: F821
    sys.exit(f"error: {msg}")


def intkey(s):
    """Sort submission numbers numerically when possible, else lexically."""
    try:
        return (0, int(s))
    except (TypeError, ValueError):
        return (1, str(s))


def read_csv_rows(path: Path, forced_encoding=None):
    """Read a CSV, trying several encodings. Returns (header_list, data_rows)."""
    encodings = (forced_encoding,) if forced_encoding else ENCODINGS_TO_TRY
    last_err = None
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as fh:
                rows = list(csv.reader(fh))
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except LookupError:
            die(f"unknown encoding: {enc}")
        if not rows:
            die(f"{path} is empty")
        print(f"  read {path.name} as {enc}  ({len(rows) - 1} data rows)")
        return [h.strip() for h in rows[0]], rows[1:]
    die(f"could not decode {path} with {list(encodings)}: {last_err}\n"
        f"  try --encoding <name>")


def find_column(header, *aliases, required=True, context=""):
    """Index of the first header cell matching any alias (case- and trailing
    '?'-insensitive)."""
    norm = {h.strip().lower().rstrip("?").strip(): i for i, h in enumerate(header)}
    for alias in aliases:
        key = alias.strip().lower().rstrip("?").strip()
        if key in norm:
            return norm[key]
    if required:
        die(f"no column matching {aliases} in the {context} file.\n"
            f"  header was: {header}\n"
            f"  add the real column name to the alias list in {Path(__file__).name}")
    return None


def cell(row, idx):
    return row[idx].strip() if (idx is not None and idx < len(row)) else ""


def is_accepted(decision, explicit_values):
    d = decision.strip().lower()
    if explicit_values is not None:
        return d in explicit_values
    return "accept" in d and "reject" not in d and "not accept" not in d


def summarize_decisions(path: Path, forced_encoding):
    header, rows = read_csv_rows(path, forced_encoding)
    c_dec = find_column(header, "decision", context="submissions")
    counts = Counter((r[c_dec].strip() or "(blank)") for r in rows if len(r) > c_dec)
    print("\ndistinct values in the 'decision' column:")
    for value, n in counts.most_common():
        print(f"  {n:5d}  {value!r}")
    print("\nIf the accepted value is not exactly 'accept', pass it with "
          "--decision-value, e.g.:\n  --decision-value \"accepted\"")


def load_titles(path: Path, id_filter, decision_values, forced_encoding):
    header, rows = read_csv_rows(path, forced_encoding)
    c_id = find_column(header, "#", "submission #", "submission number", "paper #",
                       context="submissions")
    c_title = find_column(header, "title", context="submissions")
    c_dec = find_column(header, "decision", context="submissions")

    titles = {}
    for row in rows:
        pid = cell(row, c_id)
        if not pid:
            continue
        if id_filter is not None and pid not in id_filter:
            continue
        if not is_accepted(cell(row, c_dec), decision_values):
            continue
        titles[pid] = cell(row, c_title)

    if id_filter is not None:
        missing = id_filter - set(titles)
        if missing:
            die("these --id values are not accepted papers in the file: "
                + ", ".join(sorted(missing, key=intkey)))
    if not titles:
        die("no accepted papers found. Run with --list-decisions, then set "
            "--decision-value.")
    return titles


def load_authors(path: Path, paper_ids, forced_encoding):
    header, rows = read_csv_rows(path, forced_encoding)
    c_id = find_column(header, "submission #", "submission number", "#", "paper #",
                       context="authors")
    c_first = find_column(header, "first name", "firstname", "given name", context="authors")
    c_last = find_column(header, "last name", "lastname", "family name", "surname",
                         context="authors")
    c_email = find_column(header, "email", "e-mail", context="authors")
    c_country = find_column(header, "country", "country/region", required=False, context="authors")
    c_affil = find_column(header, "affiliation", "organization", "organisation", context="authors")
    c_corr = find_column(header, "corresponding", "contact", required=False, context="authors")

    authors = {pid: [] for pid in paper_ids}
    for row in rows:
        pid = cell(row, c_id)
        if pid not in authors:
            continue
        authors[pid].append({
            "first_name": cell(row, c_first),
            "last_name": cell(row, c_last),
            "email": cell(row, c_email),
            "country": cell(row, c_country),
            "institution": cell(row, c_affil),
            "contact_author": "TRUE" if cell(row, c_corr).lower() in CONTACT_TRUE else "FALSE",
        })

    empty = sorted((pid for pid, a in authors.items() if not a), key=intkey)
    if empty:
        die("no author rows for accepted paper(s): " + ", ".join(empty)
            + "\n  (is this the authors export that matches these submissions?)")
    return authors


def write_output(path: Path, proceeding_id, paper_type, titles, authors, write_header):
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        if write_header:
            w.writerow(ACM_COLUMNS)
        for pid in sorted(titles, key=intkey):
            for seq, a in enumerate(authors[pid], start=1):
                rec = dict.fromkeys(ACM_COLUMNS, "")
                rec.update({
                    "proceeding_id": proceeding_id,
                    "event_tracking_number": pid,
                    "paper_type": paper_type,
                    "title": titles[pid],
                    "first_name": a["first_name"],
                    "last_name": a["last_name"],
                    "author_sequence_no": seq,
                    "contact_author": a["contact_author"],
                    "email": a["email"],
                    "institution": a["institution"],
                    "country": a["country"],
                })
                w.writerow([rec[c] for c in ACM_COLUMNS])
                n += 1
    return n


def build_parser():
    p = argparse.ArgumentParser(
        prog="easychair2acm",
        description="Convert EasyChair submission/author CSV exports into "
                    "ACM enhanced-CSV proceedings metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "common paper types: " + ", ".join(COMMON_PAPER_TYPES) + "\n\n"
            "examples:\n"
            "  # inspect the decision column first\n"
            "  easychair2acm submission.csv --list-decisions\n\n"
            "  # generate the enhanced CSV for full papers\n"
            "  easychair2acm submission.csv author.csv full.csv \\\n"
            '      --proceeding-id 12345 --paper-type \"Full Paper\"\n\n'
            "  # when the decision text encodes the paper type\n"
            "  easychair2acm submission.csv author.csv short.csv \\\n"
            '      --proceeding-id 12345 --paper-type \"Short Paper\" \\\n'
            '      --decision-value \"accept as short paper\"\n\n'
            "  # when full/short can only be split by an explicit id list\n"
            "  easychair2acm submission.csv author.csv short.csv \\\n"
            '      --proceeding-id 12345 --paper-type \"Short Paper\" --id 15,23,88\n'
        ),
    )
    p.add_argument("submissions_csv", type=Path, help="EasyChair submission table export")
    p.add_argument("authors_csv", nargs="?", type=Path, help="EasyChair author table export")
    p.add_argument("output_csv", nargs="?", type=Path, help="ACM enhanced CSV to write")
    p.add_argument("--proceeding-id", metavar="ID",
                   help="ACM Proceeding ID (from your ACM proceedings setup email); "
                        "written in column 1 of every row")
    p.add_argument("--paper-type", metavar="TYPE",
                   help="ACM paper_type applied to every paper in this run "
                        "(see 'common paper types' below)")
    p.add_argument("--decision-value", action="append", dest="decision_values", metavar="TEXT",
                   help="exact decision-column text meaning 'accepted' (repeatable); "
                        "default: any decision containing 'accept'")
    p.add_argument("--id", action="append", dest="ids", metavar="N",
                   help="restrict to these submission numbers (repeatable / comma-separated)")
    p.add_argument("--encoding", metavar="NAME",
                   help="force a specific input encoding instead of auto-detecting")
    p.add_argument("--header", action="store_true",
                   help="write a header row (default: no header row)")
    p.add_argument("--list-decisions", action="store_true",
                   help="print the distinct decision-column values and exit")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if not args.submissions_csv.is_file():
        die(f"file not found: {args.submissions_csv}")

    if args.list_decisions:
        summarize_decisions(args.submissions_csv, args.encoding)
        return

    missing = [name for name, val in (
        ("authors_csv", args.authors_csv),
        ("output_csv", args.output_csv),
        ("--proceeding-id", args.proceeding_id),
        ("--paper-type", args.paper_type),
    ) if not val]
    if missing:
        die("missing required argument(s): " + ", ".join(missing)
            + "\n  run with -h for usage")
    if not args.authors_csv.is_file():
        die(f"file not found: {args.authors_csv}")

    id_filter = None
    if args.ids:
        id_filter = {x.strip() for chunk in args.ids for x in chunk.split(",") if x.strip()}

    decision_values = ({v.strip().lower() for v in args.decision_values}
                       if args.decision_values else None)

    if args.paper_type not in COMMON_PAPER_TYPES:
        print(f"note: --paper-type {args.paper_type!r} is not one of the common "
              f"values; make sure it matches your ACM instructions.")

    print("reading submissions...")
    titles = load_titles(args.submissions_csv, id_filter, decision_values, args.encoding)
    print(f"  {len(titles)} accepted paper(s): " + ", ".join(sorted(titles, key=intkey)))

    print("reading authors...")
    authors = load_authors(args.authors_csv, set(titles), args.encoding)
    print(f"  {sum(len(v) for v in authors.values())} author row(s)")

    n = write_output(args.output_csv, args.proceeding_id, args.paper_type,
                     titles, authors, args.header)
    print(f"\nwrote {n} row(s) to {args.output_csv}")
    print("check: open it, verify accented names and the contact_author column.")


if __name__ == "__main__":
    main()
