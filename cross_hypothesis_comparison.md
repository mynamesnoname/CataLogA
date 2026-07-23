# Cross-Hypothesis Comparison: TARGETID 39628250216924756

## Summary

Two redrock pipeline fits for the same source disagree catastrophically: H1 (z=0.2264, GALAXY) vs H2 (z=2.9522, QSO), both with ZWARN=0. After FeatureAuditor audit, **neither hypothesis has any surviving features** (0 KEEP + 0 FLAG for both). The spectrum has median SNR = 1.0 and shows no convincing astrophysical features at any of the predicted line positions.

## Key Findings

1. **FA removed all features from both hypotheses.** Every SH-detected feature was classified as noise/artifact by the FeatureAuditor. This is the single most important finding.

2. **Spectrum is dominated by noise.** With median SNR = 1.0, the spectrum shows only stochastic fluctuations. No emission or absorption features rise convincingly above the noise at any wavelength.

3. **Both ZWARN=0 fits are spurious.** The pipeline's "confidence" (ZWARN=0) is a product of the CWT-harness confirmation loop: at low SNR, CWT detects noise peaks, and the harness matches them to template lines. The dense galaxy template at low-z (H1) and the broad QSO template at high-z (H2) both find enough noise peaks to produce apparently "confident" but physically meaningless fits.

4. **Key diagnostic regions show nothing:**
   - ~4806 Å (predicted Lyα for H2): continuum-level flux (~3-5), no broad emission
   - ~4571 Å (predicted [O II] for H1): noise-level fluctuations (~0-2), no emission
   - ~6122 Å (predicted C IV for H2): continuum-level (~1.5-3), no broad feature
   - ~5962 Å (predicted Hβ for H1): noise-level (~0.5-2), no feature
   - ~7544 Å (predicted C III] for H2): R/Z boundary zone, noise-level
   - ~8049 Å (predicted Hα for H1): OH airglow zone, very low flux (~0.04-0.9)

5. **DELTACHI2 asymmetry is misleading.** H2 has DELTACHI2=2610 vs H1's 254, but this reflects the template flexibility (broad QSO lines can "fit" noise more easily) rather than physical reality.

## Directions Checked

- **Skyline contamination**: Searched KB for OH/OI positions. The predicted Hα for H1 (~8049 Å) falls in the dense OH forest (>7800 Å), making any narrow feature there inherently suspect. The predicted C III] for H2 (~7544 Å) is near the R/Z boundary.
- **R/Z arm boundary**: C III] at 7544 Å falls within 7520-7620 Å — position unconstrained, features here are unreliable.
- **Blue edge**: No features claimed below 4000 Å for either hypothesis.
- **Line width consistency**: Not applicable — no features survived FA audit to evaluate.

## Uncertainties

- The spectrum is so noisy that even genuine features could be buried. However, the complete absence of FA-KEEP features for either hypothesis means there is no positive evidence for either redshift.
- It is possible that deeper coadded data could reveal real features, but with the current spectrum quality, no decision can be made.

## Verdict

**INDETERMINATE.** Neither hypothesis has any credible supporting evidence after FA audit. The spectrum quality (median SNR = 1.0) is insufficient to distinguish between the two pipeline fits, both of which appear to be artifacts of the CWT-harness confirmation loop operating on pure noise.
