# Privacy-first reader analytics

## Decision

Token by Token supports an optional Umami tracker. It is disabled unless both
`VITE_UMAMI_SCRIPT_URL` and `VITE_UMAMI_WEBSITE_ID` are supplied at build time.
`VITE_UMAMI_DOMAINS` restricts the tracker to approved production hostnames.

Umami is used because its tracker is cookie-free, supports anonymized
pageviews and named events, can respect Do Not Track, and can be self-hosted.
Those properties reduce collection; they do not by themselves make a
deployment legally compliant. The site owner remains responsible for lawful
basis, notices, data-processing terms, regional transfers, retention and data
subject procedures.

Official references:

- <https://docs.umami.is/docs/faq>
- <https://docs.umami.is/docs/tracker-configuration>
- <https://docs.umami.is/docs/track-events>
- <https://docs.umami.is/docs/guides/track-single-page-apps>

## Collection contract

The integration may send only these bounded values:

| Event | Properties | Purpose |
| --- | --- | --- |
| `section-view` | `page`, `section` | Aggregate readership by episode chapter |
| `scroll-depth` | `page`, `percent` (25, 50, 75, 100) | Coarse engagement map without pointer coordinates |
| `evidence-lab-toggle` | `episode`, `state` | Understand whether readers open detailed evidence |
| `study-control` | `page`, `control`, `value` | Understand use of recorded workload and comparison controls |
| `theme-change` | `theme` | Verify whether readers use the theme control |
| `brand-home` | no custom properties | Count navigation back to the episode index |

Do not add email addresses, account identifiers, IP addresses, free-form text,
request payloads, benchmark endpoints, serving profiles, exact pointer
coordinates or session replay. This implementation deliberately provides an
aggregate section/scroll engagement map rather than invasive visual heatmaps.

## Production checklist

1. Deploy Umami in the approved region or approve Umami Cloud and its DPA.
2. Create a dedicated Token by Token website ID with least-privilege access.
3. Set `VITE_UMAMI_DOMAINS` to the exact production hostnames.
4. Configure retention and deletion procedures; document the owner.
5. Update the public privacy notice with controller, purposes, lawful basis,
   retention, recipients/transfers and contact or rights procedures.
6. Build the static site and inspect the generated tracker attributes.
7. Verify Do Not Track, ad-blocked, offline and script-failure behavior. The
   reading experience must remain complete when analytics is unavailable.
8. Confirm events contain only the allowlisted bounded values above.

Local development and default static builds send no analytics because the
required environment variables are absent.
