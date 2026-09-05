#!/usr/bin/env python
"""easychair2acm - convert EasyChair CSV exports into ACM enhanced-CSV metadata.

Takes the ``submission`` and ``author`` tables exported from EasyChair and writes
the ACM enhanced CSV that conference proceedings chairs load into ACM's e-Rights
system (one row per author per accepted paper).

  * Columns are located by header name, not fixed positions.
  * Accepted papers are detected from the ``decision`` column.
  * The ACM Proceeding ID is a command-line option.
  * File encoding is auto-detected.

Output format follows "Paper Types for ACM Sponsored and ICPS Conference
Proceedings" / "The CSV File - A Definition of Terms"
(see docs/papertypes-csvfields-current.pdf; ACM revision 2025-11-12):
35 fields per row, headerless.

No third-party dependencies. Python 3.8+.

Derived from https://github.com/annaritz/easychair-to-acm-erights
(originally by Di Wu and Anna Ritz).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

__version__ = "1.1.0"

# ACM enhanced CSV: 35 fields, in this exact order (docs/papertypes-csvfields-current.pdf).
# Blank is fine for optional fields, but the field must still be present - "do
# not delete them".
ACM_COLUMNS = [
    "proceeding_id",             # mandatory - from your ACM instruction email
    "event_tracking_number",     # mandatory - EasyChair submission number
    "paper_type",                # mandatory - one of VALID_PAPER_TYPES
    "title",                     # mandatory - mixed case, English
    "prefix",
    "first_name",
    "middle_name",
    "last_name",                 # mandatory - single-name authors go here
    "suffix",
    "author_sequence_no",        # mandatory - 1, 2, 3, ...
    "contact_author",            # mandatory - "yes" / "no"
    "acm_profile_id",
    "acm_client_no",
    "orcid",                     # mandatory per ACM, usually filled by authors later
    "email",                     # mandatory - unique within a paper
    "department_school_lab",
    "institution",               # mandatory ("affiliation")
    "city",                      # mandatory - NOT in the EasyChair export
    "state_province",
    "country",                   # mandatory
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
    "art_submission_date",       # MM/DD/YYYY
    "art_approval_date",         # MM/DD/YYYY
    "source",                    # mandatory - CMS name, or the copyright contact person
    "abstract",
]

# Valid ACM e-Rights paper types (docs/papertypes-csvfields-current.pdf, ACM
# revision 2025-11-12). "no other paper types will be accepted".
VALID_PAPER_TYPES = [
    "abstract", "brief-report", "course", "demonstration", "editorial",
    "extended abstract", "full paper", "introduction", "invited talk",
    "invited talk abstract", "keynote", "obituary", "oration", "panel",
    "plenary talk", "poster", "prefatory", "short paper", "technical note",
    "tutorial", "work-in-progress",
]

# Encodings tried, in order, when reading an input file.
ENCODINGS_TO_TRY = ("utf-8-sig", "utf-8", "cp1252", "mac_roman", "latin-1")

# Values in EasyChair's "corresponding?" column that mark a contact author.
CONTACT_TRUE = {"yes", "y", "true", "1"}
CONTACT_AUTHOR_YES = "yes"
CONTACT_AUTHOR_NO = "no"

DEFAULT_SOURCE = "EasyChair"


def die(msg: str) -> "NoReturn":  # noqa: F821
    sys.exit(f"error: {msg}")


def warn(msg: str) -> None:
    print(f"warning: {msg}")


def intkey(s):
    """Sort submission numbers numerically when possible, else lexically."""
    try:
        return (0, int(s))
    except (TypeError, ValueError):
        return (1, str(s))


def to_html_entities(s: str) -> str:
    """Replace every non-ASCII character with its decimal HTML entity, as ACM
    recommends for names/titles/affiliations."""
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in s)


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


def load_papers(path: Path, id_filter, decision_values, forced_encoding):
    header, rows = read_csv_rows(path, forced_encoding)
    c_id = find_column(header, "#", "submission #", "submission number", "paper #",
                       context="submissions")
    c_title = find_column(header, "title", context="submissions")
    c_dec = find_column(header, "decision", context="submissions")
    c_abs = find_column(header, "abstract", required=False, context="submissions")
    c_del = find_column(header, "deleted?", "deleted", required=False, context="submissions")

    papers = {}
    for row in rows:
        pid = cell(row, c_id)
        if not pid:
            continue
        if c_del is not None and cell(row, c_del).lower() in ("yes", "y", "true", "1"):
            continue
        if id_filter is not None and pid not in id_filter:
            continue
        if not is_accepted(cell(row, c_dec), decision_values):
            continue
        papers[pid] = {"title": cell(row, c_title), "abstract": cell(row, c_abs)}

    if id_filter is not None:
        missing = id_filter - set(papers)
        if missing:
            die("these --id values are not accepted papers in the file: "
                + ", ".join(sorted(missing, key=intkey)))
    if not papers:
        die("no accepted papers found. Run with --list-decisions, then set "
            "--decision-value.")
    return papers


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
    c_pres = find_column(header, "presenter", "presenting", required=False, context="authors")

    authors = {pid: [] for pid in paper_ids}
    for row in rows:
        pid = cell(row, c_id)
        if pid not in authors:
            continue
        first, last = cell(row, c_first), cell(row, c_last)
        if not last and first:            # single-name author -> the one name is the last name
            first, last = "", first
        authors[pid].append({
            "first_name": first,
            "last_name": last,
            "email": cell(row, c_email),
            "country": cell(row, c_country),
            "institution": cell(row, c_affil),
            "contact_author": (CONTACT_AUTHOR_YES if cell(row, c_corr).lower() in CONTACT_TRUE
                               else CONTACT_AUTHOR_NO),
            "is_presenter": cell(row, c_pres).lower() in CONTACT_TRUE,
        })

    empty = sorted((pid for pid, a in authors.items() if not a), key=intkey)
    if empty:
        die("no author rows for accepted paper(s): " + ", ".join(empty)
            + "\n  (is this the authors export that matches these submissions?)")
    return authors


def enforce_single_contact(authors):
    """Reduce each paper to exactly one contact_author (ACM's hard rule).

    Preference order: an author already marked corresponding who is also the
    presenter, else the first author marked corresponding, else the presenter,
    else the first author. Prints the choice for every paper it changes.
    """
    for pid in sorted(authors, key=intkey):
        people = authors[pid]
        marked = [p for p in people if p["contact_author"] == CONTACT_AUTHOR_YES]
        if len(marked) == 1:
            continue
        presenters = [p for p in people if p["is_presenter"]]
        marked_presenters = [p for p in marked if p["is_presenter"]]
        choice = (marked_presenters or marked or presenters or people)[0]
        for p in people:
            p["contact_author"] = CONTACT_AUTHOR_YES if p is choice else CONTACT_AUTHOR_NO
        name = (f"{choice['first_name']} {choice['last_name']}").strip() or "?"
        basis = "also presenter" if choice["is_presenter"] else "no presenter flag - first author"
        print(f"  paper {pid}: {len(marked)} marked -> contact_author = {name} ({basis})")


def check_authors(pid, people):
    """Non-fatal checks against ACM's stated rules."""
    n_contact = sum(1 for p in people if p["contact_author"] == CONTACT_AUTHOR_YES)
    if n_contact == 0:
        warn(f"paper {pid}: no contact author marked (ACM needs exactly one)")
    elif n_contact > 1:
        warn(f"paper {pid}: {n_contact} contact authors marked (ACM allows one)")
    emails = [p["email"].lower() for p in people if p["email"]]
    dupes = {e for e in emails if emails.count(e) > 1}
    for e in sorted(dupes):
        warn(f"paper {pid}: duplicate email {e!r} (ACM rejects this)")
    for p in people:
        if not p["last_name"]:
            warn(f"paper {pid}: an author has no name")
        if not p["institution"]:
            warn(f"paper {pid}: {p['last_name'] or '?'} has no affiliation (ACM requires it)")
        if not p["country"]:
            warn(f"paper {pid}: {p['last_name'] or '?'} has no country (ACM requires it)")


def write_output(path, proceeding_id, paper_type, papers, authors, opts):
    enc = to_html_entities if opts["html_entities"] else (lambda s: s)
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        if opts["header"]:
            w.writerow(ACM_COLUMNS)
        for pid in sorted(papers, key=intkey):
            check_authors(pid, authors[pid])
            for seq, a in enumerate(authors[pid], start=1):
                rec = dict.fromkeys(ACM_COLUMNS, "")
                rec.update({
                    "proceeding_id": proceeding_id,
                    "event_tracking_number": pid,
                    "paper_type": paper_type,
                    "title": enc(papers[pid]["title"]),
                    "first_name": enc(a["first_name"]),
                    "last_name": enc(a["last_name"]),
                    "author_sequence_no": seq,
                    "contact_author": a["contact_author"],
                    "email": a["email"],
                    "institution": enc(a["institution"]),
                    "country": a["country"],
                    "source": opts["source"],
                })
                if opts["include_abstract"]:
                    rec["abstract"] = enc(papers[pid]["abstract"])
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
            "valid paper types (ACM, use exactly):\n  "
            + "\n  ".join(", ".join(VALID_PAPER_TYPES[i:i + 4])
                          for i in range(0, len(VALID_PAPER_TYPES), 4))
            + "\n\nexamples:\n"
            "  # inspect the decision column first\n"
            "  easychair2acm submission.csv --list-decisions\n\n"
            "  # generate the enhanced CSV for full papers\n"
            "  easychair2acm submission.csv author.csv full.csv \\\n"
            '      --proceeding-id 12345 --paper-type \"full paper\"\n\n'
            "  # when the decision text encodes the paper type\n"
            "  easychair2acm submission.csv author.csv short.csv \\\n"
            '      --proceeding-id 12345 --paper-type \"short paper\" \\\n'
            '      --decision-value \"accept as short\"\n'
        ),
    )
    p.add_argument("submissions_csv", type=Path, help="EasyChair submission table export")
    p.add_argument("authors_csv", nargs="?", type=Path, help="EasyChair author table export")
    p.add_argument("output_csv", nargs="?", type=Path, help="ACM enhanced CSV to write")
    p.add_argument("--proceeding-id", metavar="ID",
                   help="ACM Proceeding ID (from your ACM proceedings instruction email)")
    p.add_argument("--paper-type", metavar="TYPE",
                   help="ACM paper_type for every paper in this run (see list below)")
    p.add_argument("--decision-value", action="append", dest="decision_values", metavar="TEXT",
                   help="exact decision-column text meaning 'accepted' (repeatable); "
                        "default: any decision containing 'accept'")
    p.add_argument("--id", action="append", dest="ids", metavar="N",
                   help="restrict to these submission numbers (repeatable / comma-separated)")
    p.add_argument("--source", default=DEFAULT_SOURCE, metavar="NAME",
                   help=f"value for the mandatory 'source' field (default: {DEFAULT_SOURCE})")
    p.add_argument("--include-abstract", action="store_true",
                   help="fill the optional abstract field from the submission export")
    p.add_argument("--html-entities", action="store_true",
                   help="encode non-ASCII characters in names/title/affiliation/abstract "
                        "as decimal HTML entities (ACM-recommended for diacritics)")
    p.add_argument("--encoding", metavar="NAME",
                   help="force a specific input encoding instead of auto-detecting")
    p.add_argument("--single-contact", action="store_true",
                   help="force exactly one contact_author per paper when EasyChair "
                        "marked several (or none): keeps the presenter, else the first "
                        "author; prints each choice")
    p.add_argument("--header", action="store_true",
                   help="write a header row (default: no header row - ACM wants none)")
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
        die("missing required argument(s): " + ", ".join(missing) + "\n  run with -h for usage")
    if not args.authors_csv.is_file():
        die(f"file not found: {args.authors_csv}")

    paper_type = args.paper_type.strip().lower()
    if paper_type not in VALID_PAPER_TYPES:
        die(f"paper_type {args.paper_type!r} is not an ACM value. Use one of:\n  "
            + ", ".join(VALID_PAPER_TYPES))

    id_filter = None
    if args.ids:
        id_filter = {x.strip() for chunk in args.ids for x in chunk.split(",") if x.strip()}

    decision_values = ({v.strip().lower() for v in args.decision_values}
                       if args.decision_values else None)

    print("reading submissions...")
    papers = load_papers(args.submissions_csv, id_filter, decision_values, args.encoding)
    print(f"  {len(papers)} accepted paper(s): " + ", ".join(sorted(papers, key=intkey)))

    print("reading authors...")
    authors = load_authors(args.authors_csv, set(papers), args.encoding)
    print(f"  {sum(len(v) for v in authors.values())} author row(s)")

    if args.single_contact:
        print("normalizing to one contact author per paper...")
        enforce_single_contact(authors)

    opts = {
        "header": args.header,
        "source": args.source,
        "include_abstract": args.include_abstract,
        "html_entities": args.html_entities,
    }
    n = write_output(args.output_csv, args.proceeding_id, paper_type, papers, authors, opts)
    print(f"\nwrote {n} row(s) to {args.output_csv}  (paper_type={paper_type!r}, "
          f"source={args.source!r})")
    print("check: city is always blank (not in EasyChair) and orcid is blank - "
          "authors add both in the ACM grid.")


if __name__ == "__main__":
    main()
