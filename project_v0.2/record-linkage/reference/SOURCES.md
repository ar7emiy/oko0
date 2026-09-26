# Reference tables

Copied, not linked: a refresh inside `goko-v2-poc` cannot change this package's scores.
The notebook checks every file below against its SHA-256 at start-up and stamps the result
into the run manifest. `refresh_reference.py` re-copies the tables and rewrites this list.

| File | Source | License | Used for | SHA-256 |
|---|---|---|---|---|
| `surnames.csv.gz` | US Census 2010 surnames, <https://www2.census.gov/topics/genealogy/2010surnames/names.zip>, via `goko-v2-poc/corpus/reference/` (built 2026-09-23) | US Government work, public domain | chance two people share a surname | `e44a76a6ac0f65e626b729f2b4af5299d8759f9a5bf868349485c1dda93e0aaa` |
| `first_names.csv.gz` | SSA baby names 1930-2005, <https://www.ssa.gov/oact/babynames/names.zip>, via goko (built 2026-09-23) | US Government work, public domain | chance two people share a first name or an initial | `0db8745a9ecacf10055f63e0e7b6b34fd4b21b742d4bba068bbe8be1ddb00a99` |
| `org_tokens.csv.gz` | CMS NPPES organization names, September 2026 release, via goko (built 2026-09-23) | US Government work, public domain | how many organizations use a name word | `76889bbd492521ccec5c91ab67b3e190f11b0a0618c742fdf60fb59537574861` |
| `reference_meta.json` | goko build metadata (totals behind the three tables) | - | denominators | `488d87abc7094502e1ad9e93ba52b9ba421b78678067dbaad2dcab5023924ba0` |
| `nicknames.csv` | carltonnorthern/nicknames, <https://github.com/carltonnorthern/nicknames>, `names.csv` at commit `ed160b3af2d17e1af8ebd570f10a10e4dade4ff4` (fetched 2026-09-25) | Apache-2.0, see `nicknames_LICENSE.txt` | Bill meets William: nickname roots | `e6a4e5a55ca5b47a4146dbc118f26c71c63053d4b79ca9659de8e74efb65847e` |
| `nicknames_LICENSE.txt` | the same repository, `License.txt` at the same commit | Apache-2.0 | - | `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |

The nickname table is unchanged from upstream (2,827 `has_nickname` rows).
