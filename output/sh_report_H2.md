# SH Report: H2_B_z2.952_QSO

## 13a. Spectrum Summary

| Field | Value |
|-------|-------|
| File | coadd-2-9263-thru20240403.fits |
| TARGETID | 39628250216924756 |
| Wavelength range | 3600.0 – 9824.0 Å |
| Median SNR | 0.9 |
| Tested redshift | z = 2.9522 |
| Verification window | [2.8522, 3.0522] |
| Masked regions | None indicated |
| Lines predicted in range | 4 (Lyα, C IV, He II, C III]) |
| CWT features available | 5 peaks, 3 troughs |

## 13b. Overall Verdict

**NOT SUPPORTED**

Of the 4 predicted broad QSO lines at z=2.9522, 0 are LIKELY, 1 is MARGINAL (C III]), and 3 are NOT_FOUND (Lyα, C IV, He II). The sole candidate — peak@7607.2 attributed to C III] — has a 62.5 A wavelength offset, FWHM of only 82 km/s (vs >2000 km/s expected for a broad C III] emission line), and a tentative ridge length of 2. The three most critical QSO broad lines (Lyα, C IV, He II) lack any CWT detection whatsoever. At median SNR=0.9 the data are very shallow, but the CWT pipeline found no features at or near the predicted positions of these lines.

## 13c. Per-Line Results

### LIKELY

*None.*

---

### MARGINAL

| name | type | λ_rest | λ_pred | λ_fit | λ_err | offset | FWHM (Å) | FWHM | ridge_length | cwt_snr | implied_z | in_window | mask_note | status |
|------|------|--------|--------|-------|-------|--------|-----------|------|-------------|---------|-----------|-----------|-----------|--------|
| C III] | em | 1909.0 | 7544.7 | 7607.2 | 0.8 | 62.5 | 2.1 | 82 km/s | 2 | 7.7 | 2.9849 | yes | — | MARGINAL |

---

### NOT_FOUND

| name | type | λ_rest | λ_pred | λ_fit | λ_err | offset | FWHM (Å) | FWHM | ridge_length | cwt_snr | implied_z | in_window | mask_note | status |
|------|------|--------|--------|-------|-------|--------|-----------|------|-------------|---------|-----------|-----------|-----------|--------|
| Lyα | em | 1216.0 | 4805.9 | — | — | — | — | — | — | — | — | yes | — | NOT_FOUND |
| C IV | em | 1549.0 | 6122.0 | — | — | — | — | — | — | — | — | yes | — | NOT_FOUND |
| He II | em | 1640.4 | 6483.2 | — | — | — | — | — | — | — | — | yes | — | NOT_FOUND |

---

### MASKED

*None.*

## 13d. Key Findings

- **No CWT detection for three of four predicted lines**: Lyα (λ_pred 4805.9), C IV (λ_pred 6122.0), and He II (λ_pred 6483.2) all have zero CWT features within 80 Angstroms. The nearest CWT emission peak to any of these is peak@5761.6, which lies 360 A from C IV and 956 A from Lyα — far beyond the acceptable offset threshold.
- **C III] candidate is weak**: The sole MARGINAL detection is peak@7607.2 with 62.5 A offset from the C III] predicted position (7544.7 A). Its FWHM of 82 km/s is inconsistent with the broad-line FWHM > 2000 km/s expected for C III] in QSO spectra. The ridge length of 2 and moderate SNR of 7.7 further reduce confidence. An absorption trough at nearly the same wavelength (trough@7608.0) suggests the presence of a complex spectral structure possibly unrelated to C III].
- **Low SNR severely limits detection**: At median SNR = 0.9, the CWT pipeline's ability to detect real features is heavily constrained, but the pipeline did find 8 features (5 peaks, 3 troughs) across the full spectrum, none of which align with the predicted QSO line positions.
- **No low-ionization lines accessible**: At z=2.9522, all low-ionization lines (Ca H/K, [O II], Balmer series, etc.) fall beyond 9824 A and are entirely outside the observed wavelength range. The hypothesis rests entirely on high-ionization broad lines.

## 13e. Systemic Redshift

**Cannot be determined.** The only MARGINAL line is C III] (1909 A), which belongs to the excluded category (high-ionization, routinely blueshifted by AGN outflows per the Ionization Priority rules). No LIKELY lines exist at any priority level. No low-ionization lines (Ca H/K, [O II], [S II], [N II], Balmer) fall within the observed wavelength range at this redshift. No systemic anchor is available.

Excluded lines:
- **C III]** — excluded: high-ionization line in the excluded group (He II, C III], C IV, [Ne V], Lyα). Implied z = 2.9849 from peak@7607.2. Even if it were eligible, the 82 km/s FWHM is inconsistent with broad-line expectations.

## 13f. Classification

**Unknown** — insufficient confirmed lines for classification.

The tested hypothesis is a QSO at z = 2.9522. For QSO classification, broad emission lines (Lyα, C IV, C III], Mg II) with FWHM > 2000 km/s must be present. Of these, Lyα and C IV are both NOT_FOUND at their predicted positions within the observed range. Mg II (λ_rest 2800 A) falls at 11066 A, beyond the red edge of the spectrum. The sole MARGINAL line (C III]) has FWHM = 82 km/s — far below the 2000 km/s threshold expected for QSO broad lines — making it inconsistent with the QSO interpretation. The median SNR of 0.9 is extremely low, so the absence of detected features does not definitively rule out a QSO, but the CWT data provide no affirmative support for the hypothesis. No other classification (ELG, LRG/BGS, star) can be evaluated since all rest-frame optical lines are redshifted beyond the observed range.

## 13g. Caveats

- Median SNR of 0.9 is extremely low — CWT detection efficiency is severely limited. A deeper spectrum might reveal broad lines below the CWT detection threshold.
- The feature peak@7607.2 (and adjacent trough@7608.0) may be unrelated to C III] — possibilities include an OH sky line residual or a narrow emission line from a lower-redshift interloper.
- At z > 2.9, the rest-frame UV lines (Lyα, C IV, He II, C III]) are the only accessible diagnostics in DESI optical spectroscopy. No Balmer or forbidden lines are visible to provide independent redshift confirmation.
- The verification window of ±0.1 in z is relatively tight; a true QSO with slightly different redshift (e.g., z ≈ 2.985 matching the peak@7607.2 implied z) would still have the same problems (no Lyα, no C IV detections at their corresponding positions).
- C III] at 1909 A is a semi-forbidden line; in some QSOs it can be weak or absent. Its nondetection/weak detection alone does not disprove the QSO hypothesis but contributes to the overall lack of support.
