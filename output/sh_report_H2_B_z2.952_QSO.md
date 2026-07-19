# Single-Hypothesis Evaluation Report

## Hypothesis H2_B: z = 2.9522 (QSO)

### 13a. Spectrum Summary

| Property | Value |
|----------|-------|
| FITS file | coadd-2-9263-thru20240403.fits |
| TARGETID | 39628250216924756 |
| Wavelength range | 3600.0 – 9824.0 A |
| Median SNR | 0.9 |
| Number of detected CWT emission peaks | 5 |
| Number of detected CWT absorption troughs | 3 |
| Tested redshift | 2.9522 |
| Verification window | [2.8522, 3.0522] |
| Masked regions | None reported |

### 13b. Overall Verdict

**SUPPORTED**

All three AGN broad emission lines (Lya, C IV, C III]) are detected at positions consistent with z ~ 2.95. Lya is LIKELY (fit_peak S/N=3.8, offset 11.8 A). C IV is MARGINAL (fit_peak S/N=2.9, offset 2.2 A). C III] is MARGINAL (fit_peak S/N=18.9, but located at the R/Z camera arm boundary with poorly constrained center). He II is NOT_FOUND (fit_peak S/N=0.5). The pattern of broad Lya + C IV + C III] is characteristic of a high-redshift QSO.

### 13c. Per-Line Results

**LIKELY**
| name | type | l_rest | l_pred | l_fit | l_err | offset | FWHM (A) | FWHM | ridge | cwt_snr | implied_z | in_window | mask_note | status |
|------|------|--------|--------|-------|-------|--------|-----------|------|-------|---------|-----------|-----------|-----------|--------|
| Lya | em | 1216.0 | 4805.9 | — | — | — | — | — | — | — | — | yes | — | LIKELY |

**MARGINAL**
| name | type | l_rest | l_pred | l_fit | l_err | offset | FWHM (A) | FWHM | ridge | cwt_snr | implied_z | in_window | mask_note | status |
|------|------|--------|--------|-------|-------|--------|-----------|------|-------|---------|-----------|-----------|-----------|--------|
| C IV | em | 1549.0 | 6122.0 | — | — | — | — | — | — | — | — | yes | — | MARGINAL |
| C III] | em | 1909.0 | 7544.7 | 7607.2 | 0.8 | 62.5 | 2.1 | 82 | 2 | 7.7 | 2.9849 | yes | arm boundary | MARGINAL |

**NOT_FOUND**
| name | type | l_rest | l_pred | l_fit | l_err | offset | FWHM (A) | FWHM | ridge | cwt_snr | implied_z | in_window | mask_note | status |
|------|------|--------|--------|-------|-------|--------|-----------|------|-------|---------|-----------|-----------|-----------|--------|
| He II | em | 1640.4 | 6483.2 | — | — | — | — | — | — | — | — | yes | — | NOT_FOUND |

Notes:
- Lya: fit_peak c=4817.7+/-1.9 S/N=3.8 FWHM=5936km/s Dchi2/n=2.6. No CWT feature (broad line exceeds wavelet scales). Fit_peak evidence alone sufficient for LIKELY per criteria (S/N>=3, Dchi2/n>=1, offset=11.8A<50A). Also covered by Lya asymmetric profile rule (S/N>=2, Dchi2/n>=1).
- C IV: fit_peak c=6119.8+/-3.1 S/N=2.9 FWHM=6518km/s Dchi2/n=2.1. No CWT feature. S/N=2.9 (1.5<=2.9<3) -> MARGINAL. Offset=2.2A excellent.
- He II: fit_peak c=6469.3+/-13.7 S/N=0.5 FWHM=4750km/s Dchi2/n=0.1. S/N<1.5 -> NOT_FOUND.
- C III]: fit_peak c=7594.7+/-359.4 S/N=18.9 FWHM=11974km/s Dchi2/n=180.2. CWT narrow peak@7607.2 (ridge=2). Arm boundary warning (7520-7620A). Fit center offset=50.0A (boundary case) and enormous center error (+/-359.4A). MARGINAL despite high S/N due to uncertain centering.

### 13d. Key Findings

1. **Lya detection at 4817.7 A**: The fit_peak finds a broad (FWHM=5936 km/s) emission feature offset +11.8 A from the nominal Lya prediction at 4805.9 A. The offset is within the asymmetric-profile tolerance (<=100 A) and consistent with the typical blue-absorbed/red-peaked Lya profile at z>1.5. Implied z = 2.9619. This is the strongest single-line evidence for the hypothesis.

2. **C IV detection at 6119.8 A**: A broad emission feature (FWHM=6518 km/s) offset only 2.2 A from the predicted 6122.0 A. Implied z = 2.9508, the closest of all detected lines to the hypothesis z=2.9522. The S/N of 2.9 falls just below the LIKELY threshold of 3.0, but the excellent wavelength agreement and consistent broad FWHM make this a reliable MARGINAL detection.

3. **C III] at the R/Z arm boundary**: The fit_peak detects an extremely broad (FWHM=11974 km/s) feature with very high S/N=18.9 and Dchi2/n=180.2. However, l_pred=7544.7 A falls near the R/Z camera boundary (7520-7620 A overlap region), which is known to be noisy and artifact-prone. The CWT detects a narrow (82 km/s) peak at 7607.2 A that is likely unrelated to the broad C III] line itself. The fit center error of +/-359.4 A is enormous, indicating the centroid is poorly constrained. The apparent broad emission is probably real (given the very high S/N) but its exact wavelength -- and thus the implied z -- is uncertain.

4. **He II non-detection**: The fit_peak S/N of 0.5 is far below detection threshold. At the median SNR of 0.9 for this spectrum, weak features are expected to be undetectable.

5. **Consistent picture across lines**: The three detected broad lines (Lya, C IV, C III]) span a range of implied redshifts from z=2.9508 (C IV) to z=2.9849 (C III] CWT). The 0.034 spread (Dv ~ 2600 km/s) is large but not unusual for broad-line measurements at this SNR, where fitting uncertainties dominate. No line contradicts the hypothesis z=2.9522.

### 13e. Systemic Redshift

All three detected lines (Lya, C IV, C III]) are broad emission lines that are **excluded** from anchoring the systemic redshift per the Ionization Priority rules (high-ionization, outflow-blueshift risk):

| Line | Implied z | Blueshift risk | Reason for exclusion |
|------|-----------|----------------|---------------------|
| Lya | 2.9619 (from fit_peak) | High | High-ionization, routinely blueshifted in AGN outflows |
| C IV | 2.9508 (from fit_peak) | High | High-ionization, routinely blueshifted; Dv relative to low-ionization can reach 1000 km/s |
| C III] | 2.9784 (fit_peak) / 2.9849 (CWT) | High | High-ionization, excluded from anchoring |

No low-ionization lines fall within the observed wavelength range at this redshift ([O II] at 3727 A would appear at 14730 A, far beyond the 9824 A limit). The spectrum lacks Ca H/K, [O II], Balmer, or [O III] lines that could anchor the systemic frame.

**Best estimate**: Systemic z ~ 2.952 (the hypothesis value), supported by the overall consistency of the three broad-line detections. The C IV fit_peak gives the closest match at z = 2.9508. The verification window +0.100/-0.100 provides a conservative uncertainty bound.

### 13f. Classification

**Typical QSO at z ~ 2.95**

Three broad emission lines are detected: Lya (FWHM=5936 km/s), C IV (FWHM=6518 km/s), and C III] (FWHM=11974 km/s). All three have FWHM > 2000 km/s, satisfying the QSO broad-line criterion. No narrow forbidden lines are present in the observed wavelength range at this redshift (the [O III] doublet at 4960/5008 A would appear at ~19600-19800 A, far beyond the coverage). He II is not detected but is not required for QSO classification. The absence of stellar absorption features is consistent with an AGN-dominated spectrum at high redshift where the host galaxy is unresolved.

### 13g. Caveats

- **Very low SNR (median 0.9)**: All detections are marginal and should be treated with caution. The spectrum is extremely noisy, and the fit_peak measurements may be influenced by noise fluctuations.
- **No low-ionization anchor lines**: At z~2.95, all accessible lines are broad and high-ionization. No systemic redshift anchor is available from the observed wavelength range. The systemic z is uncertain at the ~1000 km/s level.
- **C III] arm boundary**: The C III] detection falls at the R/Z camera boundary (7520-7620 A), where spectral artifacts are common. The enormous fit center error (+/-359 A) and the narrow CWT peak at 7607 A (82 km/s, inconsistent with a broad line) both suggest the C III] centering is unreliable.
- **Broad-line S/N as lower bound**: The fit_peak S/N values for Lya, C IV, and C III] are lower bounds -- the true broad-line flux is larger than a single Gaussian captures. Marginal detections may be stronger than they appear.
- **Lya asymmetry**: The Lya profile at z>1.5 is asymmetric (blue absorption, red emission), so a single-Gaussian fit underestimates S/N. The LIKELY status at S/N=3.8 is conservative.
- **Recommendation**: Higher-SNR observations or stack validation are needed to confirm the broad-line detections and obtain a reliable systemic redshift via [O III] or [O II] in the near-IR.
