# Single-Hypothesis Evaluation Report

## 13a. Spectrum Summary

| Property | Value |
|----------|-------|
| File | `.data/test_catas/spectro/loa/tiles/cumulative/7712/20240114/coadd-6-7712-thru20240114.fits` |
| TARGETID | 39628250216924756 |
| Wavelength coverage | 3600.0 – 9824.0 A |
| Median SNR | 0.9 |
| Tested redshift | z = 0.2264 |
| Verification window | z in [0.1264, 0.3264] |
| Masked regions | None reported |
| CWT features | 5 (2 emission peaks, 3 absorption troughs) all at 9380–9480 A |
| Prediction method | CWT (pre-detected) + fit_peak (pre-computed Gaussian+linear) |

## 13b. Overall Verdict

**UNSUPPORTED** — zero LIKELY lines and only 5 MARGINAL lines in a noise-dominated spectrum (median SNR = 0.9). All five MARGINAL detections come from fit_peak (pre-computed Gaussian+linear fits), not from CWT. Critically, zero CWT pre-detected features fall within 80 A of any predicted line position at this redshift. The only CWT features in the entire spectrum lie at 9380–9480 A, far from any predicted lambda_obs (max = 8257 A for [S II]b). The fit_peak results are unreliable at this noise level and likely represent noise fluctuations.

## 13c. Per-Line Results

**LIKELY** (0 lines)

None.

---

**MARGINAL** (5 lines)

| name | type | rest | pred | lambda_fit | lambda_err | offset(A) | FWHM(km/s) | fit_S/N | fit_dX2/n | in_window | status |
|------|------|------|------|------------|------------|-----------|-------------|---------|-----------|-----------|--------|
| Hepsilon | em | 3970.1 | 4868.9 | 4818.9 | 2.2 | -50.0 | 6814 | 3.5 | 2.6 | yes | MARGINAL |
| [O III]a | em | 4960.3 | 6083.3 | 6118.9 | 2.5 | +35.6 | 5454 | 2.9 | 1.8 | yes | MARGINAL |
| [O III]b | em | 5008.2 | 6142.1 | 6122.0 | 2.4 | -20.1 | 5378 | 3.2 | 2.2 | yes | MARGINAL |
| Mg I_abs | abs | 5176.7 | 6348.7 | 6298.7 | 29.9 | -50.0 | 13439 | 1.9 | 1.9 | yes | MARGINAL |
| Na D_abs | abs | 5895.6 | 7230.4 | 7242.0 | 0.3 | +11.6 | 98 | 3.3 | 0.1 | yes | MARGINAL |

All five MARGINAL lines lack CWT support. See caveats below for why each is unreliable.

**NOT_FOUND** (13 lines)

| name | type | rest | pred | lambda_fit | status |
|------|------|------|------|------------|--------|
| [Ne V] | em | 3426.0 | 4201.6 | — | NOT_FOUND |
| [O II] | em | 3727.0 | 4570.8 | — | NOT_FOUND |
| Ca K_abs | abs | 3934.8 | 4825.6 | — | NOT_FOUND |
| Ca H_abs | abs | 3969.6 | 4868.3 | — | NOT_FOUND |
| Hdelta | em | 4102.9 | 5031.8 | — | NOT_FOUND |
| G-band_abs | abs | 4305.6 | 5280.4 | — | NOT_FOUND |
| Hgamma | em | 4341.7 | 5324.7 | — | NOT_FOUND |
| Hbeta | em | 4862.7 | 5963.6 | — | NOT_FOUND |
| [N II]a | em | 6549.8 | 8032.7 | — | NOT_FOUND |
| Halpha | em | 6564.6 | 8050.8 | — | NOT_FOUND |
| [N II]b | em | 6585.3 | 8076.2 | — | NOT_FOUND |
| [S II]a | em | 6718.3 | 8239.3 | — | NOT_FOUND |
| [S II]b | em | 6732.7 | 8257.0 | — | NOT_FOUND |

All have no CWT feature within the verification window and fit_peak S/N < 1.5 (or S/N >= 1.5 but offset > 80 A or other disqualifying criteria — none meet even the marginal evidence threshold with CWT as primary).

**MASKED** (0 lines)

None.

---

## 13d. Key Findings

1. **CWT features do not match z = 0.2264**: All 5 CWT features cluster at 9380–9480 A. The farthest-red predicted line at this redshift is [S II]b at 8257 A — over 1100 A short. This is the strongest evidence against the hypothesis: the only real (CWT-detected) spectral structure in the data falls at wavelengths with no predicted counterpart.

2. **[O III] doublet is actually a single artifact**: The fit_peak results for [O III]a (6118.9) and [O III]b (6122.0) are separated by only 3.1 A, not the expected 58.7 A for the true [O III] doublet at z = 0.2264. Both fits have FWHM ~ 5400 km/s, wildly inconsistent with narrow-line class (< 2000 km/s). This is a single noise fluctuation fit twice with different initial parameters.

3. **Na D_abs candidate is tantalizing but weak**: The fit to Na D_abs gives lambda_fit = 7242.0 A, offset = +11.6 A from the predicted 7230.4 A — the best offset of all MARGINAL lines. FWHM = 98 km/s is consistent with narrow ISM absorption. However, the fit achieves only dX2/n = 0.1 (negligible improvement over a flat continuum), and there is zero CWT support. If real, z_implied = 0.2284 from this line.

4. **Hepsilon fit is offset by 50 A**: The Hepsilon fit-peak at 4818.9 A is 50 A blueward of the predicted 4868.9 A. At z = 0.2264, 50 A corresponds to ~3100 km/s — implausibly large for a Balmer line offset. Likely a noise fluctuation.

5. **Mg I_abs fit is clearly non-physical**: FWHM = 13439 km/s for an absorption line is physically absurd (~0.04c). This is a noise fit with no astrophysical meaning, retained as MARGINAL only because S/N = 1.9 formally meets the marginal threshold.

6. **Missing critical diagnostics**: Ca K/H absorption (the defining feature for LRG/BGS at this redshift) is absent. [O II] emission (the defining feature for ELG) is absent. Halpha and Hbeta are absent. The spectrum provides no positive evidence for any galaxy subtype.

## 13e. Systemic Redshift

**Cannot be reliably determined.** No LIKELY lines exist. Among MARGINAL lines, the lowest-ionization candidate is Na D_abs (Priority 1, neutral ISM absorption), giving z_implied = 7242.0 / 5895.6 - 1 = 0.2284. However, this is rejected as unreliable for the following reasons:

- Na D_abs: fit dX2/n = 0.1 (negligible), no CWT support. Insufficient to anchor systemic z.
- Mg I_abs: FWHM = 13439 km/s is non-physical for absorption. Excluded.
- Hepsilon: offset -50.0 A from prediction, no CWT. Excluded as unreliable.
- [O III]a/b: both fits are the same noise artifact at ~6120 A, not the doublet. FWHM ~ 5400 km/s inconsistent with narrow-line width. Excluded.
- Excluded high-ionization lines (not present at this z): none evaluated.

**Fallback**: No line meets the quality threshold for anchoring the systemic redshift.

## 13f. Classification

**Unknown** — insufficient confirmed lines for classification. The spectrum has median SNR = 0.9, making classification impossible. Key missing diagnostics include:

- **LRG/BGS**: Ca K/H absorption pair absent (fatal for LRG classification). G-band_abs, Mg I_abs, Na D_abs all NOT_FOUND or unreliable.
- **ELG**: [O II] 3727 absent (fatal). Hbeta, Halpha absent. [O III] detection is spurious.
- **QSO**: No broad lines (Ly-alpha, C IV, C III], Mg II) are within the observed wavelength range at z = 0.2264, so the QSO hypothesis is not testable at this redshift.

The tested classification (GALAXY) is neither confirmed nor refuted — the data are too poor to evaluate.

## 13g. Caveats

- **Very low SNR (median 0.9)**: The spectrum is noise-dominated. All fit_peak results with S/N < 5 in such conditions are suspect and likely represent noise fluctuations, not real spectral features.
- **No CWT support**: Zero CWT pre-detected features fall near any predicted line at this redshift. CWT is the higher-trust detection method. The fit_peak results, while formally meeting marginal-detection criteria for 5 lines, are unreliable as secondary evidence at this noise level.
- **[O III] doublet is spurious**: The fit_peak fits to [O III]a and [O III]b converged on the same noise feature (~6120 A), separated by only 3.1 A when 58.7 A is expected. This is a known risk of blind fitting in low-SNR data.
- **Unaccounted CWT features**: The 5 CWT features at 9380–9480 A have no predicted counterpart at z = 0.2264. They may be OH skyline residuals (common at lambda > 9000 A) or features at a substantially different redshift.
- **Hypothesis not falsified, only unsupported**: The absence of detected lines does not prove z = 0.2264 is wrong — it only means the data are insufficient to test it. A higher-SNR spectrum could validate or refute this redshift.
- **Known catastrophe object**: Based on external taxonomy (inspect_spectrum.py), TARGETID 39628250216924756 is labeled "QSO-Lya_failure" in the catastrophe spectra collection, suggesting the true redshift may be much higher (z > 2) with Ly-alpha misidentified by Redrock. This external information was not used in the evaluation but provides relevant context.
