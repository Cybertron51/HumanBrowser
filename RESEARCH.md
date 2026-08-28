# HumanBrowser — landscape research

Brief (formatted): https://claude.ai/code/artifact/03e3ea06-f1cf-4151-b36a-86e4c1540839
Researched 2026-08-26.

## Framing

Two separate industries are chasing the "browses like a human" idea and neither
talks to the other:

- **Lane A — what a human would notice.** Predicted eye-tracking / saliency
  heatmaps. Attention Insight, Neurons, Dragonfly AI, Expoze/alpha.one,
  Brainsight, EyeQuant, Feng-GUI. Mature, ~€25–450/mo self-serve.
- **Lane B — how a human would behave.** LLM agents with personas that navigate
  a site and report friction. UXAgent, AgentA/B, UXCascade; commercially Swarm,
  uxaudit.now, Uxia.

## Lane A findings

- **No vendor crawls a site.** All are static-bitmap saliency scorers. Six of
  seven score above the fold only. Only Brainsight produces a scrolling
  full-page heatmap. None handles a second page, hover, dropdown, modal, or any
  post-click state.
- **The "% accurate" claims are arithmetic.** They are AUC-Judd divided by the
  human inter-observer ceiling. alpha.one publishes the derivation: 0.87 / 0.92
  = "95% accurate". AUC's chance floor is 0.5, so a random model would
  advertise ~54%. EyeQuant is the most candid (0.82/0.90 ≈ "90% as accurate").
- **The benchmark contains no UI.** MIT300 = 300 natural photographs, 2s free
  viewing. Only Attention Insight (AUC-J 0.87 / NSS 2.17) and Feng-GUI (0.81 /
  1.25) actually appear on that leaderboard; the other five cite it without a
  row. Human ceiling 0.92 / 3.29; single-human baseline 0.80.
- **Measured domain gap.** WebSaliency: SAM-ResNet natural-image NSS 1.284 /
  CC 0.596 -> same arch retrained on web pages 1.532 / 0.718 -> purpose-built
  1.821 / 0.823 (+42% NSS just from in-domain training). Mobile UI is worse:
  SALICON-pretrained SAM NSS 0.537, in-domain retrain 0.84.
- **UIs are not natural scenes.** UEyes (CHI 2023, 62 participants, 1,980
  screenshots): top-left bias, not the center bias saliency models encode and
  AUC-Judd rewards. Text out-competes images regardless of image/text ratio.
- **All of it is free-viewing**, first 3–5 seconds. Real browsing is
  goal-driven. No independent peer-reviewed head-to-head of these commercial
  products vs ground-truth eye tracking on web pages exists.

## Lane B findings

UXAgent (github.com/neuhai/UXAgent, MIT) is the reference architecture:
persona generator (1,000 personas in ~2 min), memory stream (observations /
actions / reflections / thoughts, retrieved by importance x relevance x
recency), Fast Loop (perceive-plan-act), async Slow Loop (Reflect + Wonder),
Universal Browser Connector over Playwright. Best output is the agent
*interview* — researchers rated it 4.8/5, video replay 2.8/5.

**Its stated limitation is the key one:** it "only process[es] semantic or
textual information (i.e. HTML) ... visual elements such as images and visual
layout information are excluded." No scroll, read, or hover in the action
space. It is a user simulator that cannot see.

Validity evidence is consistently weak:

| Study | Result |
|---|---|
| AgentA/B (Amazon, 1k agents vs 2M users) | agents 6.05 actions/session vs humans 15.96; searched 4.5x less; filters 1.8x more. Outcomes directionally aligned. ~$2,925/run |
| UXCascade (UIST'26, seeded issues) | agents 9/17, human baseline 11/17, unassisted humans best. W=6, p=.813. "consistently struggles with visual perception" |
| Sim2Real Gap (451 humans, 31 simulators) | best simulator USI 76.0 vs human ceiling 92.9; success inflated +14.2pp |
| Lost in Simulation | ECE 15.1; SAE 50.6% vs AAVE 39.4%; blame inverted (sim blames system 48.9%, humans blame themselves 62.2%) |
| GPT-4o heuristic eval (INTERACT'25) | only 21.2% overlap with human experts' issues |
| UX-LLM (ICSE'25) | precision 0.61–0.66, recall 0.35–0.38 |

Market: User Interviews (May 2026, n=150) — only 8% actively use synthetic
users, 28% actively reject, ~64% skeptical-to-opposed. UserTesting has
publicly declined to ship them. NN/g: "user research needs real users."

## The gap

1. **The two lanes have never been wired together.** No system conditions an
   agent's next action on predicted attention. Lane A sees but has no user;
   Lane B has a user that can't see.
2. **Scroll is treated as capture, never as behavior.**
3. **Interactive states are invisible to both lanes.**
4. **Everything predicts free-viewing.** SeekUI (CHI 2026, MIT, weights on HF)
   just made task-conditioned GUI search scanpaths buildable.

## Build stack

**Capture:** Playwright directly — you need pixel-exact viewport control,
per-element bounding boxes, reproducibility. Stagehand only for semantic steps
(find pricing page, dismiss unfamiliar modal); it returns deterministic control
after each act().

**Never feed a fullPage screenshot to a saliency model.** Every model was
trained on a single fixed-size view at a known angular size (SUM 256x256,
TranSalNet 384x288, DeepGaze 1024x768 @ 35 px/dva). A 1440x9000 stitch
downscaled to 256x256 puts the learned center bias mid-*document* and shrinks
elements to ~6% of trained angular size. DeepGaze makes it explicit by
requiring pixel_per_dva.

Instead: set a real viewport (1440x900), scroll at 0.8–1.0x viewport height,
capture each view, run the model per view at native aspect, compose back into
document coordinates by adding scroll offset. Keep the stitched image as a
human-facing visualization only.

**Models:**
- SUM (github.com/Arhosseini77/SUM) — WACV'25, MIT, weights public, 57.5M
  params, one checkpoint trained across SALICON/MIT1003/CAT2000/e-commerce/
  **UEyes/FiWI**, with `--condition 3` = UI mode. The default choice.
- UMSI / Imp1k (predimportance.mit.edu) — predicts visual *importance* on
  designs (closer to what a UX report answers), 200 web pages in training set.
  TF1/Keras-era weights, **no stated license** — research-only until confirmed.
- UEyes dataset (zenodo.org/records/8010312) — 1,980 UIs, CC-BY-4.0, 12.9GB,
  ships 1s / 3s / 7s saliency maps. Use the **1s** map for first impression.
- SeekUI (github.com/YueJiang-nj/SeekUI-CHI2026) — task-conditioned GUI search
  scanpaths, Qwen2.5-VL base, MIT.
- EyeFormer, TranSalNet, DeepGaze — see brief. DeepGaze license unconfirmed.

**The output that makes it a product:** heatmap alone is not a finding. Pull
getBoundingClientRect() for every candidate element + the a11y tree, integrate
saliency mass inside each box, normalize by area, rank. Deliverable sentence:
"your primary CTA ranks 7th in predicted attention, behind the cookie banner."

**Gotchas:** cookie banners dominate every heatmap (Consent-O-Matic loads
unpacked into a Playwright persistent context; but a real first-time visitor
*does* see the banner, so consider both passes); lazy-loaded images read as
flat low-saliency grey; Chromium truncates fullPage above 16,384px; fullPage
resizes the window and re-evaluates vh/vw; position:fixed headers appear once
in a stitch but on every screen for a user; mobile is ~2x the px/dva of
desktop; carousels/hover/A-B variants mean a page has no canonical appearance.

**Data ceiling:** under 800 web pages with public gaze data exist in total —
UEyes (1,980 UIs across 4 types), Stony Brook WebSaliency (450 pages), FiWI
(149). That scarcity is the binding constraint on any accuracy claim.

## Positioning

Pattern across every validity study in both lanes: **correlation holds,
calibration fails.** rho ~ 0.6–0.95 on ratings and directional agreement on
A/B outcomes, but wrong absolute means, compressed variance, subgroup errors
that don't correct with a constant.

So: "this page scores 73/100" is not defensible. "Version B moves your CTA from
7th to 2nd in predicted attention and cuts the agent's steps to checkout from 9
to 5" is — a within-instrument comparison where calibration error cancels.

Pitch shape: **a regression detector for user experience**, run on every
deploy / on a competitor / across redesign variants. Nobody sells that because
Lane A can't crawl and Lane B can't see. Avoid the "% accurate" arms race
entirely.

## Open questions

- Who is it for? Agency/CRO buyer wants per-deploy regression reports and
  doesn't care about the model. Research buyer cares and is 64% skeptical.
- **Does the coupling work?** Testable in a weekend: does a saliency-fed agent
  catch a low-contrast CTA that a saliency-blind agent walks straight past?
  That is the core result.
- Validation without an eye tracker: in-domain metrics on held-out UEyes ->
  correlate with real behavioral heatmaps (Hotjar-style) -> webcam gaze.
  Brainsight's best evidence is outcome-based (ads scoring 65+ had 59.6% higher
  CTR), which is a cheaper template worth copying.
- Free-viewing or task-driven? SeekUI makes the latter possible for the first
  time; it's also the harder problem nobody in Lane A has attempted.
