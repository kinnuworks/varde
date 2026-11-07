# Hand-checked precision

A hand check, done on 7 November 2026, of how often each source type is right.

## Sample

1,000 organisation numbers drawn at random from the public universe (`eval/sample_1000.jsonl`, seed 2026). Varde ran on them with the commit before the sister-company rule. From the external facts it published, a stratified random sample of 141 was checked by hand against the live page and the register at data.brreg.no: 40 websites, 35 social profiles, 40 news items (at most three per company), 15 hiring pages, the one job ad and 10 group websites.

A fact counted as right only if it belongs to this exact organisation number. A parent's, sister's, agency's or theme author's site or profile counted as wrong, and so did a news item about another company, a recipe or a fixed page section, or a date that is not the publish date.

## Result

| Source type | Checked | Right | Wrong | Share right |
|---|---:|---:|---:|---:|
| Website | 40 | 39 | 1 | 98% |
| Social profile | 35 | 32 | 3 | 91% |
| News item | 40 | 34 | 6 | 85% |
| Hiring page | 15 | 14 | 1 | 93% |
| Job ad (NAV) | 1 | 1 | 0 | 100% |
| Group website (labelled as the group's, not the company's) | 10 | 10 | 0 | 100% |
| All | 141 | 130 | 11 | 92% |

## What was wrong and what changed

| Wrong facts | Cause | Change |
|---|---|---|
| 6 (1 website, 2 socials, 3 news) | Two companies whose site belongs to a sister company with a longer name: Sildakongen AS on the site of Sildakongen Produksjon AS, Steinde AS on the site of Steinde Environmental AS. The registry phone and the shared name passed the weak proof. | A site proven without our organisation number is now rejected when it presents a longer company name built on ours and never shows our own legal name. Both companies now get no website, socials or news. |
| 1 social | A Norwegian company's site links the Facebook page of a Danish company with a near-identical name. | Not fixed yet. |
| 2 news | Two short fixed "solution" sections that a WordPress site also publishes in its feed. | Not fixed yet. |
| 1 news | The date taken was the date of the event the post announces, not the date the post was published. | Not fixed yet. |
| 1 hiring | A shop's careers page is the chain's shared vacancy list. | Not fixed yet. |

After the change, the 135 checked facts still published hold 5 known errors: 96% right. On the same 1,000 companies the rule removed 7 websites. 2 of them were the sister-company sites above. 1 presents itself as Be Your Best Global AS, which is also correct to drop. The other 4 were lost to pages that came back near-empty on that run.

## Earlier feedback

Feedback on 1 November flagged news attached to the wrong company and sites belonging to parents or sisters. Since then:

- news on a site proven without our organisation number, or on the site of a company in a group, must name the company (its number or every distinctive word of its name) in the title or the text around it;
- menu and listing labels ("See more news", "Les mer", "Alle nyheter") are never news;
- only a publish date counts (`pubDate`, `published`, `dc:date`); feed `updated` and sitemap modification dates are no longer used;
- a subsidiary whose only proof is on its parent's site gets a `related_website` claim labelled as the group's site, its `official_website` is marked `ambiguous`, and nothing else is taken from that site;
- a social handle with several distinctive name words must match two of them, so a group handle does not pass for a member company;
- the NAV job index was rebuilt with its feed cursor, so each run reads new ads up to the live end of the feed (it had no cursor before, which is why the November run published no jobs).

## Refresh

Run with `--state-dir <dir>` and Varde keeps every run's envelopes in `<dir>/history/` and diffs against the latest one. The smoke test in `smoke/` was run against the run on record from 17 October and flags 4 changes: a new group company, a new board member, a changed registered activity and one new register event. A second run against it flags none (`smoke/rerun`).
