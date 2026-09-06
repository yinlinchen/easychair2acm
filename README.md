# easychair2acm

Convert EasyChair CSV exports into the **ACM enhanced CSV** that conference
proceedings chairs load into ACM's **e-Rights** system to start the rights /
copyright capture process.

Input: the **submission** and **author** tables exported from EasyChair.
Output: one row per author per accepted paper, **35 fields**, headerless, in the
order ACM's e-Rights loader expects.

Maintained rewrite of
[annaritz/easychair-to-acm-erights](https://github.com/annaritz/easychair-to-acm-erights)
(originally by Di Wu and Anna Ritz):

| original | easychair2acm |
| --- | --- |
| column positions hard-coded | columns located by header name |
| accepted paper ids typed by hand | detected from the `decision` column |
| Proceeding ID edited in the source | `--proceeding-id` option |
| input encoding hard-coded | expects UTF-8 (EasyChair's export); `--encoding` to override |
| `assert` tracebacks | plain errors + pre-upload warnings |
| multiple `corresponding?` authors upload as-is | `--single-contact` forces one (the presenter) |
| 31 output fields, `TRUE`/`FALSE` contact flag | current 35-field format, `yes`/`no`, `source` filled, paper-type validated |

**Requirements:** Python 3.8+. No third-party packages.

## Reference documents

Both are in [`docs/`](docs/) and are the authority for the output format:

- **`papertypes-csvfields-current.pdf`** — ACM's "Paper Types for ACM Sponsored
  and ICPS Conference Proceedings" + "The CSV File – A Definition of Terms".
  Lists the valid `paper_type` values and defines all 35 fields. This tool's
  output follows the 2025-11-12 revision.
- **`TAPS instructions for Organizers-Vendors.pdf`** — the *next* stage. After
  e-Rights, camera-ready PDFs/sources are processed through TAPS. Not used by
  this tool; kept here as the proceedings chair's reference.
- **`easychair-csv-export.png`** — the EasyChair export screen.

---

## Install

Copy `easychair2acm.py` anywhere. Optionally:

```bash
chmod +x easychair2acm.py
ln -s "$PWD/easychair2acm.py" ~/.local/bin/easychair2acm
```

Otherwise call it as `python easychair2acm.py ...`.

## 1. Export from EasyChair

On EasyChair's **CSV data export** page (under the **Premium** menu):

![EasyChair CSV Data Export Tables](docs/easychair-csv-export.png)

- tick **Submissions** and **Authors** (untick the rest)
- **"Include table headers"** must be checked (columns are matched by name)
- **Download Tables** → unzip → `submission.csv` and `author.csv`

Feed these files to the tool **exactly as exported**. Don't open them in a
spreadsheet and re-save — Excel/Numbers mangle the encoding (accented names,
dashes and quotes turn to `â€?`), and the tool will refuse a file it can't
decode cleanly rather than guess. The tool reads the raw export fine; if you
need to inspect it, use a plain-text editor.

## 2. Check how acceptances are recorded

```bash
python easychair2acm.py submission.csv --list-decisions
```

```
distinct values in the 'decision' column:
     39  'accept'
     35  'reject'
     18  'accept as short'
     52  'transfer to the poster track'
```

Note which decision text means "accepted" for each paper type.

## 3. Generate the enhanced CSV

**One run per paper type.** `--paper-type` is a single ACM value (see the list at
the bottom, or `easychair2acm -h`) stamped on **every** row of that run — so you
do one run per type and concatenate the outputs (step 4). `--proceeding-id`
comes from your ACM proceedings instruction email and is the same for every run
that feeds one proceedings volume.

You never edit the EasyChair CSVs. Which papers go into each run is selected one
of three ways, depending on where EasyChair recorded the paper type:

### A. The `decision` column names the type

The common case — different acceptance texts per type, as seen in step 2:

```bash
python easychair2acm.py submission.csv author.csv full.csv \
    --proceeding-id 12345 --paper-type "full paper" --decision-value "accept"

python easychair2acm.py submission.csv author.csv short.csv \
    --proceeding-id 12345 --paper-type "short paper" --decision-value "accept as short"

python easychair2acm.py submission.csv author.csv poster.csv \
    --proceeding-id 12345 --paper-type "poster" --decision-value "transfer to the poster track"
```

`--decision-value` is repeatable when several texts mean the same thing.

### B. The type is only in the submission form

When one `decision` covers several paper types, the type is usually the
submission's answer to a form question, which EasyChair puts in the `form fields`
column (as `(Question) N`, where `N` is the chosen option's *number*, not its
label — check the CfP for what each number means). Some tracks also export a
plain `Type` column.

The tool filters on `decision` only, so list the submission numbers for each
type and pass them with `--id`:

```bash
python easychair2acm.py submission.csv author.csv demo.csv \
    --proceeding-id 12345 --paper-type "demonstration" --id 15,23,88,104
```

Read those numbers straight off the `form fields` / `Type` column in a text
editor. A submission that left the question blank is in no `--id` list and is
**silently skipped** — decide where it belongs and add it.

### C. Nothing distinguishes them

Decide per paper and keep the `--id` lists yourself.

---

Useful options:

| option | effect |
| --- | --- |
| `--single-contact` | when EasyChair has several authors (or none) marked `corresponding?`, force exactly one contact author per paper: the presenter, else the first author. Prints each pick. See step 4 |
| `--source NAME` | value for the mandatory `source` field (default `EasyChair`) |
| `--include-abstract` | fill the optional abstract field from the submission export |
| `--html-entities` | encode non-ASCII in names/title/affiliation as `&#nnn;` — ACM's recommended handling for diacritics (e.g. `Chloé` → `Chlo&#233;`) |
| `--id N` | restrict to these submission numbers (repeatable / comma-separated) |
| `--encoding NAME` | force an input encoding (the export is UTF-8; only needed for an unusual or older file) |
| `--header` | write a header row (leave off for the file you upload) |

## 4. Combine and check

```bash
cat full.csv short.csv > acm-all.csv

# distinct papers in the file
cut -d, -f2 acm-all.csv | sort -u | wc -l
```

The tool prints the accepted count per run and **warnings** for things ACM will
reject or flag — missing affiliation/country, papers with no or multiple contact
authors, duplicate author emails.

**Multiple contact authors** is the usual one: EasyChair lets every co-author
tick `corresponding?` and doesn't stop them, but ACM allows exactly one. Rather
than chasing it in EasyChair, re-run with `--single-contact` — it keeps the
author who is the registered presenter (falling back to the first author) and
prints the choice it made for each paper. Check that list; if a paper needs a
different contact, set that person's `corresponding?`/`presenter?` in the author
export and re-run. Other warnings — missing affiliation/country, duplicate
emails — fix in EasyChair and re-run.

## 5. Upload to ACM e-Rights, then send notifications

Load `acm-all.csv` in the e-Rights grid, verify the paper/author counts and that
titles/names look right, then trigger the author rights-form notifications. City
and ORCID will warn as blank on every row — that's expected (not in the
EasyChair export; authors supply them). Section / page / sequence numbers stay
blank until the program is scheduled — re-upload with those later.

Camera-ready production after that happens in **TAPS** — see the TAPS doc in
`docs/`.

---

## Try it

```bash
python easychair2acm.py examples/submission.csv examples/author.csv /tmp/out.csv \
    --proceeding-id 12345 --paper-type "full paper" --header --include-abstract
```

5 rows for the 3 accepted papers (`#3` is rejected), 35 fields each, `Chloé` /
`Ekström` preserved.

## The 35 output fields

`proceeding_id`, `event_tracking_number`, `paper_type`, `title`, `prefix`,
`first_name`, `middle_name`, `last_name`, `suffix`, `author_sequence_no`,
`contact_author`, `acm_profile_id`, `acm_client_no`, `orcid`, `email`,
`department_school_lab`, `institution`, `city`, `state_province`, `country`,
`secondary_department_school_lab`, `secondary_institution`, `secondary_city`,
`secondary_state_province`, `secondary_country`, `section_title`,
`section_seq_no`, `published_article_number`, `start_page`, `end_page`,
`article_seq_no`, `art_submission_date`, `art_approval_date`, `source`,
`abstract`

Populated from EasyChair: `proceeding_id`, `event_tracking_number`,
`paper_type`, `title`, `first_name`, `last_name`, `author_sequence_no`,
`contact_author`, `email`, `institution`, `country`, `source`, and (with
`--include-abstract`) `abstract`.

Left blank — ACM keeps the column, don't delete it:

- `prefix` / `middle_name` / `suffix`, `orcid`, `acm_profile_id`, `acm_client_no`
  — authors add these in the grid
- `city` (required by ACM but **not in the EasyChair export** — it warns), plus
  `department_school_lab`, `state_province`, all `secondary_*`
- `section_*`, `published_article_number`, `start_page`, `end_page`,
  `article_seq_no`, the two `art_*` dates — filled after the program is scheduled

## Valid `paper_type` values

Exact strings ACM's e-Rights loader accepts (2025-11-12) — **no others**:

```
abstract           brief-report       course             demonstration
editorial          extended abstract  full paper         introduction
invited talk       invited talk abstract   keynote        obituary
oration            panel              plenary talk        poster
prefatory          short paper        technical note      tutorial
work-in-progress
```

`full paper` publishes in the ACM DL as *research-article*; `short paper` as
*short-paper*. The tool lowercases what you pass and rejects anything not on
this list.

## Troubleshooting

| message | cause / fix |
| --- | --- |
| `paper_type '...' is not an ACM value` | use an exact string from the list above |
| `no column matching (...)` | EasyChair changed a column name — add it to the alias list near the top of `easychair2acm.py` |
| `no accepted papers found` | wrong `--decision-value`; run `--list-decisions` |
| `these --id values are not accepted papers` | that submission was rejected/withdrawn, or a typo |
| `no author rows for accepted paper(s): N` | the author export doesn't match the submission export |
| `N contact authors marked (ACM allows one)` | several co-authors ticked `corresponding?`; re-run with `--single-contact` |
| `could not decode ... the export is damaged` | a spreadsheet round-trip (or a partial download) mangled the bytes. Re-export Submissions+Authors from EasyChair and don't open them in Excel/Numbers. `--encoding` forces one if you genuinely know it |
| `ORA-12899: value too large for ... PRIMARY_AUTHOR` | old versions wrote `TRUE`/`FALSE`; this version writes `yes`/`no` |
| accents wrong after ACM import | regenerate with `--html-entities` |

## Credits

Rewritten from `annaritz/easychair-to-acm-erights` by Di Wu (Texas A&M) and
Anna Ritz (Reed College).
