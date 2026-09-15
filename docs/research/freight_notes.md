# Freight & logistics research notes (Phase 0)

ACADEMIC SIMULATION — not actual trades. Owner: P0 freight/logistics. Code: `desk/data/fetch_freight.py`.
Parameters: `config/params/logistics.yaml`. Output: `data/processed/freight_weekly.csv` (CONTRACTS §4.3).
Raw evidence: `data/raw/freight/` (Wayback snapshots, cached articles). Derived point tables: `data/interim/freight/`
(`points_wci.csv`, `points_india_inbound_anchors.csv` — moved out of `data/raw/` after review because they are
regenerated on every run). Every URL below was actually downloaded; nothing here is from memory.

## 1. Bottom line

| week ending | JEA_NSA USD/t (20ft) | USEC_MUN USD/t (40ft) | Drewry WCI composite USD/FEU |
|---|---|---|---|
| 2022-03-04 | 24.00 | 106.41 | 9,279 |
| 2022-06-03 | 19.84 | 87.98 | 7,626 |
| 2022-08-26 | 15.78 | 69.96 | 5,986 |
| change 03-04 → 08-26 | −34.2 % | −34.3 % | −35.5 % |

- Ocean freight into India **fell** through the headline window. There was no freight spike on either desk lane
  between March and August 2022 in any source I could retrieve.
- USEC_MUN is tied to published USD/box rates for US East Coast → West India from Container News. The JEA_NSA level
  is a judgement (ASSUMPTION) because I could not find a 2022 Jebel Ali → Nhava Sheva quote I could cite.
- Coverage of the weekly shape index, 106 weeks (2020-12-25 … 2022-12-30): **82 reported (77 %)**, 17 derived
  from Drewry's own published week-on-week change (16 %), 7 interpolated (7 %). In the headline window
  (2022-03-04 … 2022-09-02, 27 weeks) there are 24 reported weeks, 3 derived and no interpolated ones.

### Look-ahead and flags (added after the Phase 0 review)

- **The levels are hindsight-calibrated.** Each anchor now carries `available_from` = the latest publication date of
  every article it depends on. The June-2022 USEC anchor (August level ÷ (1 − July's 12.5% drop)) is only knowable
  from 30-Aug-2022; the Mar/Apr-2022 SIBLING anchors use the USEC/Europe ratio from articles up to 30-Sep-2022. Every
  weekly `note` states when its level inputs became public (e.g. week ending 2022-03-04: 2022-09-30, +210 days).
  WCI_DERIVED weeks also use the next week's publication. No India-inbound quote published before 29-Apr-2022 was found,
  so no point-in-time level can be built for March–April 2022; P1/P2 must treat freight as a reconstruction.
- In the window, USEC level tags by panel day are SIBLING 60, EXTRAP_PRE 22, ANCHORED 44 (of 126, after the point-in-time
  alignment; 60 / 19 / 47 under the first build's containing-week mapping), and two of the four
  months behind the 0.790 USEC/Europe ratio (30 Jun, 27 Jul) are themselves DERIVED. So `freight_usec_mun_usd_t` is
  flagged **ASSUMPTION** (level) in `series_provenance.csv`, with the WCI shape described as PROXY; filter on
  `freight_src`, not on the column flag.
- The panel now aligns freight point-in-time (a day sees only Thursday assessments made on or before it); the first
  build used the containing Friday week, i.e. up to 3 days of look-ahead.

## 2. How the series is built

**Shape (PROXY).** The Drewry World Container Index (WCI) composite, in USD per 40ft box. Drewry's page only shows
the latest week, so I parsed the value and its date from 91 cached Internet Archive snapshots of that page (83
distinct assessment Thursdays). Most came from the main URL; a few came from newsletter and query-string versions
of the same page (CDX indexes are cached). Two
missing weeks were filled from AJOT, which republishes Drewry's weekly release word for word (5 May 2022 and
18 Aug 2022). If a week has no snapshot, its value is worked back from the next week's published change:
`value − $change`, or `value / (1 + pct)`. The note column says so, and marks it "approx." when Drewry rounded the
percentage. Weeks still missing after that are filled by linear interpolation, and the build stops if a gap is
longer than 4 weeks. A Thursday assessment belongs to the week ending the next day, a Friday.

**Flag legend.** `freight_src = <shape>|USEC:<level>|JEA:ASSUMPTION`. Shape is `WCI_REPORTED`, `WCI_DERIVED` or
`WCI_INTERPOLATED`. USEC level is `ANCHORED` (between anchors from the USEC leg itself), `SIBLING` (anchored to
the Europe→West India bridge), or `EXTRAP_PRE` / `EXTRAP_POST` (lane-to-index ratio held flat). Over 106 weeks the
USEC level flags are 27 ANCHORED, 13 SIBLING and 66 EXTRAP_PRE (all of 2021 up to 25 Mar 2022). In the headline
window: 10 ANCHORED, 13 SIBLING, 4 EXTRAP_PRE.

**USEC_MUN level (DIRECT anchors, PROXY series).** Container News publishes a monthly India rate analysis. It
reports average carrier rates for "USEC (New York) … into West India (Nhava Sheva/Mundra)":

| anchor date | USD/FEU | type | source sentence |
|---|---|---|---|
| 2022-03-31 | 1,974 | SIBLING | Europe→West India 2,500 × USEC/Europe ratio 0.790 |
| 2022-04-29 | 1,974 | SIBLING | same |
| 2022-06-30 | 1,657 | DERIVED | Jul-27 article: return leg "dropped by between 10% and 15%" vs June (midpoint) |
| 2022-07-27 | 1,450 | DERIVED | Aug-30 article: return leg "remained steady" vs last month |
| 2022-08-30 | 1,450 | REPORTED | Container News 30 Aug 2022 |
| 2022-09-30 | 1,434 | REPORTED | Container News 30 Sep 2022 |
| 2022-10-31 | 1,434 | DERIVED | Nov article: "not changed" vs last month |
| 2022-11-29 | 1,434 | REPORTED | Container News analysis republished by Maritime Gateway 29 Nov 2022 |
| 2022-12-30 | 1,125 | REPORTED | Container News 30 Jan 2023 ("from US$1,125") |
| 2023-01-30 | 1,100 | REPORTED | Container News 30 Jan 2023 |

`usec_box_t = WCI_t × k(t)`, where `k_i = anchor_i / WCI(anchor date)`. Between anchors, k is interpolated
log-linearly in calendar time; before the first anchor and after the last it is held flat.
`freight_usec_mun_usd_t = usec_box / 21 MT`.
The March and April 2022 anchors come from a sibling lane, because Container News did not report the USEC leg
before June. That lane is Felixstowe/Rotterdam → West India, also an India-inbound backhaul: 2,500 at end-March
and April, 2,050 in June, 1,950 in July, 1,900 in August and 1,700 in September 2022. It is multiplied by the
USEC/Europe ratio seen in the months where both lanes are known: Jun 0.81, Jul 0.74, Aug 0.76, Sep 0.84, mean
0.790. If only the two fully reported months (Aug and Sep) are used, the ratio is 0.803 and the March/April
anchor rises 1.7 %.

**Why not just scale the lane with the composite index?** The WCI composite is driven by China headhaul lanes.
India-inbound backhaul lanes did not collapse the same way. Scaling 1:1 from the August anchor would give USD 543
per FEU in December 2022, against the reported USD 1,125, and USD 1,028 in September against the reported 1,434.
Inside the Mar–Aug window the two methods happen to be close: naive scaling gives 2,377 / 1,953 / 1,533 per FEU at
the three dates, against 2,235 / 1,848 / 1,469 anchored. That is because India-inbound rates and the composite both
fell by roughly 25–35 % over those months.

**JEA_NSA level (ASSUMPTION).** USD 600 per 20ft box in the week ending 2022-03-04, so USD 24 per MT at 25 MT.
From there the lane moves in proportion to the USEC India-inbound series. Plausible range is USD 350–1,000 per box
(USD 14–40 per MT). The reasoning, all from cached sources:
1. Long-haul India-inbound rates in 2022 were USD 2,300/TEU Europe → West India (Mar–Apr) and USD 1,075/TEU
   USEC → West India (Aug). A ~1,050 nm Gulf feeder lane should sit well below both.
2. In 2021–22 India was short of empty boxes for exports, so carriers wanted to bring equipment into India.
   That pushes inbound short-sea rates down.
3. In later normal markets the reverse lane, West India → Jebel Ali, printed USD 75/TEU (Container News 28 Apr
   2023) and USD 550/TEU (27 Sep 2024, during the Red Sea disruption).

Assuming JEA_NSA moves with the India-inbound USEC shape is itself an assumption. The alternative, scaling with
the composite, gives almost the same numbers inside the window (see above) but a much lower 2022 Q4.

**Artefacts to avoid over-reading.** Because k is interpolated between monthly anchors, the anchored series shows a
few small weekly rises that are not market events: +1.2 % in the week ending 2022-08-05, and +0.1–0.4 % in mid-April
and mid-August. Nothing in the WCI shows them; every published WCI week from 3 Mar to 22 Dec 2022 was a decrease.
Weekly volatility of USEC_MUN inside the window is also smoothed. The log-return standard deviation is 1.7 % a week,
set mainly by the anchors, so P4 should not treat it as an observed spot-freight volatility.

## 3. Source register (retrieved)

| # | Source | What was used | Flag |
|---|---|---|---|
| S1 | Drewry WCI page via Wayback, e.g. https://web.archive.org/web/20220306133740/https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry (83 distinct weeks listed in `points_wci.csv`) | weekly composite, WoW change | DIRECT points → PROXY shape |
| S2 | AJOT republications: https://www.ajot.com/news/world-container-index-may-5th , https://www.ajot.com/news/drewry-world-container-index-18-aug | WCI 5 May 2022 = 7,727.84; 18 Aug 2022 = 6,223.82 ("the 25th consecutive weekly decrease") | DIRECT |
| S3 | https://container-news.com/freight-rate-analysis-for-indian-shippers-reflects-easing-signs-on-some-trades/ (29 Apr 2022) | Europe→West India 2,300/TEU, 2,500/FEU (end-Mar & Apr); West India→USEC spot 11,200 → 13,200/FEU; South China→West India 4,500 → 3,900/FEU | DIRECT |
| S4 | https://container-news.com/cn-freight-rate-analysis-for-indian-trades-reflects-easing-trends-but-for-intra-asia/ (27 Jul 2022) | Europe→WI 2,050 → 1,950/FEU; US→WI return leg −10 to −15 %; South China→WI 4,050 → 4,550/FEU; void calls at Nhava Sheva/Mundra; Chennai box shortage | DIRECT |
| S5 | https://container-news.com/cn-analysis-slowing-exports-send-freight-rates-on-major-trades-out-of-india-further-downwards/ (30 Aug 2022) | USEC→WI 1,075/TEU, 1,450/FEU "remained steady"; Europe→WI 1,900/FEU | DIRECT |
| S6 | https://container-news.com/cn-analysis-india-container-freight-rates-continue-to-slide-amid-weakening-demand/ (30 Sep 2022) | USEC→WI 1,434/FEU; Europe→WI 1,700/FEU | DIRECT |
| S7 | https://www.maritimegateway.com/freight-rates-on-indian-trades-hit-new-lows/ (29 Nov 2022, Container News analysis) | USEC→WI 1,434/FEU "not changed" | DIRECT |
| S8 | https://container-news.com/cn-analysis-freight-rates-on-indian-trades-continue-to-cool-amid-falling-export-volumes/ (30 Jan 2023) | USEC→WI 1,100/FEU "down from US$1,125" | DIRECT |
| S9 | https://container-news.com/cn-analysis-container-freight-rate-slide-on-larger-indian-trades-slows-amid-contract-negotiations/ (28 Apr 2023) | West India→Jebel Ali 75/TEU (Apr 2023), context only | DIRECT (context) |
| S10 | https://container-news.com/market-analysis-container-rates-on-trades-out-of-india-continue-to-soften-amid-weakening-demand/ (27 Sep 2024) | West India→Jebel Ali 550/TEU (Sep 2024), context only | DIRECT (context) |
| S11 | https://www.xeneta.com/blog/weekly-container-rate-update-week-43-2022 | West India→USEC spot peak USD 12,400/FEU end-May 2022 → 7,300 (late Oct); West India→N. Europe peak 9,100/FEU Mar 2022 → 4,400 | DIRECT |
| S12 | https://shipandbunker.com/news/world/134096-sb-analysis-latest-on-brent-vlsfo-hsfo-relationship-bunker-price-outlook-as-2022-sees-record-high-marine-fuel-prices | G20-VLSFO record USD 1,125.50/mt on 16 Jun 2022, more than double USD 543.5 a year earlier | DIRECT |

## 4. Attempts log (in the order tried)

| Attempt | Outcome |
|---|---|
| Google News RSS `"World Container Index" after:/before:` (Mar 2022 and six gap weeks) | Only 0–2 items per window for 2022, and no titles carried index values. Not usable. Raw XML kept in `data/raw/freight/news/`. |
| Drewry WCI live page | No history (latest week only). |
| Wayback CDX, main WCI URL (199 captures Dec 2020–Jan 2023) → one capture per Thursday window | **Success**: one capture per Thursday window, downloaded at ~11 s intervals, all parsed. |
| Wayback CDX, URL variants of the WCI page | Added weeks the main URL missed (e.g. 7 Jan 2021, 11 Feb 2021, 10 Feb 2022); other variant captures duplicated known weeks. Drewry's "coronavirus hub" chart page had no numbers (chart image only); discarded. |
| SCFI incl. Persian Gulf/Dubai route, en.sse.net.cn | `/currentIndex` JSON is public but current week only, with route values null. The history endpoint `/singleIndex/scfi?date=` returns HTTP 500 ("cannot be cast to SubscribeUser"), i.e. subscribers only. Chinese site: same login wall. **Failed.** |
| Freightos FBX | fbx.freightos.com redirects to the gated Freightos Terminal. FBX has no India or Middle East lane anyway. **Not usable.** |
| S&P Global Platts (West Coast India–Middle East container assessments since 1 Nov 2021; Dec-2020 scrap container freight article) | HTTP 403 for both WebFetch and curl. **Failed.** Platts' Dec-2020 UK→India/Pakistan scrap figure of USD 1,600–1,675/TEU was seen only in a search snippet, so it is **not used**. |
| Hellenic Shipping News WCI/Xeneta reprints | HTTP 403. **Failed.** |
| UNCTAD Review of Maritime Transport 2022 ch.3 PDF | HTTP 403. **Failed.** |
| AJOT slug guessing for 2021/2022 gap weeks (~24 weeks × 24 slug patterns) | No hits. Slugs are irregular and the probe may have been throttled; two AJOT pages found via web search were used (S2). |
| Carrier India THC/detention tariffs (MSC PDF) | HTTP 403, so port charges stay ASSUMPTION. |
| eCFR 23 CFR 658.17 (US 80,000 lb gross vehicle weight limit) | Redirected to a bot check. The payload reasoning cites the rule but verify stays PENDING. |
| Web search for a 2022 Jebel Ali→Nhava Sheva / Middle East→India container quote (forwarder calculators, BigMint, AlCircle, Business Standard, Loadstar) | Nothing citable for 2022. Calculators show current rates only. A Loadstar "India–Gulf rates plunge" result was not retrieved; its snippet (containers rerouted to Indian ports) does not describe 2022, so it is not used. **Failed**, so JEA_NSA level = ASSUMPTION. |

## 5. Adverse event #3 — what freight actually did (honesty section)

The spec's Table 5 row 3.6 describes adverse event #3 as a "container freight spike / buyer payment delay". The
evidence does **not** support a freight spike on the desk's lanes in Mar–Aug 2022:

1. **Global benchmark fell every week.** The WCI composite went from 9,279 (3 Mar) to 7,626 (2 Jun) to 5,986
   (25 Aug) USD/FEU, then 2,120 on 22 Dec 2022. The 2022 high was 9,698 on 20 Jan. Drewry itself called 18 Aug
   2022 "the 25th consecutive weekly decrease" (S2). That is an unbroken fall from early March.
2. **India-inbound lanes eased.** Europe→West India went 2,500 (Mar/Apr) → 2,050 (Jun) → 1,950 (Jul) → 1,900 (Aug)
   USD/FEU, −24 % (S3–S5). On US→West India the return leg fell 10–15 % in July (S4), then held at 1,450 → 1,434
   USD/FEU from Aug to Nov (S5–S7).
3. **Jebel Ali → India:** no 2022 data found. There is no basis to claim either a spike or a fall beyond the
   assumption that it tracked other India-inbound lanes.

Genuine short-lived up-moves did happen nearby, with dates and sources. Phase 3 may cite these, correctly labelled:

| Episode | Dates | Evidence | Relevance to desk |
|---|---|---|---|
| India **export** headhaul to US East Coast | spot 11,200 → 13,200/FEU Mar → Apr 2022 (+18 %); Xeneta spot peak 12,400/FEU end-May 2022 | S3, S11 | Opposite direction to our imports. It shows exporters' pain, not importers'. |
| West India → N. Europe spot peak | 9,100/FEU in Mar 2022 | S11 | Export direction |
| **Bunker fuel** record | G20-VLSFO USD 1,125.50/mt on 16 Jun 2022 | S12 | Cost push via bunker surcharges. The index data (WCI, India-inbound averages) still fell, so it did not show up as a rate spike. |
| South China → West India (India-inbound, intra-Asia) | 4,050 → 4,550/FEU Jun → Jul 2022 (+12 %), "China's post-lockdown recovery", fewer sailings | S4 | A real inbound India up-move, but not on our lanes |
| Void calls / blank sailings at Nhava Sheva & Mundra; Colombo crisis box shortage at Chennai | Jul 2022, void calls announced "up to November" | S4 | Schedule and equipment disruption means transit, demurrage and payment-timing risk, not a rate spike |

**Recommendation for Phase 3 (event #3):**
- Do **not** present a "real container freight spike" on JEA_NSA/USEC_MUN in Mar–Aug 2022. It did not happen in the
  data.
- The honest *real* freight story is the reverse. Freight was **fixed high and the market fell**. A cargo whose
  freight was locked in March (a CFR purchase priced off March freight, or a forward booking) carries an above-market
  freight cost by shipment in Jul–Aug. That is a negative "freight variation vs fixture" (attribution factor (d)),
  about −USD 36/t on USEC_MUN and −USD 8/t on JEA_NSA from 3 Mar to 26 Aug (106.4 → 70.0; 24.0 → 15.8). For a
  competitor buying later, the landed cost is lower, so the desk loses relative competitiveness.
- Make the event #3 headline the **buyer payment delay**, a simulated credit event (P2/P5), combined with the
  **real July 2022 logistics disruption** (void calls at Nhava Sheva/Mundra → longer transit and clearance →
  demurrage/detention accrual via `demurrage_usd_per_box_day` beyond `detention_free_days`, plus a later cash-in).
  Label the delay and the demurrage days ASSUMPTION/SIM.
- If a freight spike must be shown, use the spec's **hypothetical** stress `freight_stress_shock_frac` = +40 %
  (Table 6 row 4.2) and call it a stress scenario, not a historical event. For context, the WCI composite rose
  +99 % from 7 Jan to 16 Sep 2021, so +40 % is a moderate but plausible shock.

## 6. Parameters (logistics.yaml) — quick view

| key | value | flag | note |
|---|---|---|---|
| container_payload_mt_20ft / _40ft | 25 / 21 MT | ASSUMPTION | 40ft limited by US road GVW, not box size |
| transit_days_jea_nsa / _usec_mun | 5 / 40 d | ASSUMPTION | ranges 3–8 / 30–55 |
| clearance_delivery_days | 10 d | ASSUMPTION | range 7–21 |
| finance_days_jea_nsa / _usec_mun | 40 / 73 d | ASSUMPTION | supplier cash-out (sight LC) → buyer cash-in, **includes** 30d buyer credit |
| port_cf_charges_inr_t_nsa / _mun | 3,000 / 2,650 ₹/t | ASSUMPTION | THC, CFS, DO/docs, CHA, examination, inland haulage to Rajkot; NSA ~70 % haulage |
| insurance_rate × insured_value_uplift | 0.10 % × 1.10 | ASSUMPTION × DIRECT (UCP 600 Art. 28(f)(ii), PARTIAL verify) | |
| detention_free_days / demurrage_usd_per_box_day | 14 d / USD 35 | ASSUMPTION | |
| typical_laycan_days | 15 d | ASSUMPTION | container "shipment period" |
| freight_jea_nsa_usd_box_ref @ ref_date | USD 600 @ 2022-03-04 | ASSUMPTION | range 350–1,000 |
| freight_usec_west_india_usd_feu_reported | path | DIRECT | cross-checked against the article text on every build |
| freight_europe_west_india_usd_feu_reported | path | DIRECT | cross-checked against the article text on every build |
| freight_usec_jun2022_drop_frac | 0.125 | PROXY | midpoint of reported 10–15 % |
| freight_stress_shock_frac | 0.40 | ASSUMPTION | spec stress |

## 7. Open issues / next verification steps

1. **JEA_NSA level** is the weakest number. Next step: find a 2022 Wayback capture of a Jebel Ali→Nhava Sheva rate
   page (Freightos/SeaRates/iContainers), or a 2022 BigMint/Fastmarkets note giving a UAE-origin scrap CFR–FOB
   spread. Sensitivity: each ±USD 100/box moves JEA_NSA freight by ±USD 4/t.
2. **USEC Mar–Jun 2022** comes from a sibling-lane ratio (flag `USEC:SIBLING` from 31 Mar to the June anchor), and
   early March (before 31 Mar) is extrapolated with the WCI shape (flag `USEC:EXTRAP_PRE`). All of 2021 is also `EXTRAP_PRE`: a flat lane/composite ratio. Treat 2021
   levels as indicative only.
3. **Holiday weeks.** Drewry may skip publishing around Christmas/New Year. The derived values for 2021-01-01 and
   2021-12-31 assume the published change is week-on-week. The 2021-12-31 value is almost equal to 23 Dec either
   way. The 2021-01-01 value (4,358) could instead belong to 24 Dec 2020; this is pre-window and immaterial.
4. Port charges, detention and demurrage, insurance premium, transit days and payloads are ASSUMPTION with PENDING
   verify steps in the YAML.
5. The Container News figures are trade-press averages of carrier rates. They are not an exchange index, and the
   articles do not say whether surcharges are included.

## 8. What this does and doesn't tell you

It gives a source-traced size and direction for ocean freight per MT on each lane in each week. That is enough to
see that freight was a declining cost line through the 2022 window, and that the Gulf lane costs several times less
per tonne than the US lane. It is **not** a freight quote. Weekly wiggles are borrowed from a global index. The Gulf
lane's level is a judgement. The US lane's level is monthly trade-press averages with a sibling-lane bridge for
Mar–May 2022. Port, haulage and demurrage costs sit in separate parameters.
