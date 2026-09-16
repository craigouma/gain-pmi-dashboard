# Data profile

## Findings
- 48 farmer IDs are linked across both forms. 0 appear in distribution only and 2 appear in crop health only.
- Crop health carries 101 rows for 50 distinct farmers, one row per growth stage visit by design. 2 farmer and growth stage pairs are repeated, which looks like accidental resubmission rather than a second visit and needs a dedupe rule in phase 2.
- Distribution has 1 duplicated farmer ID(s), of which 1 carry conflicting values across the duplicate rows, for example a different quantity_kg on each submission. This must be resolved before the join, not silently summed.
- 4 linked farmers have a country value that disagrees between forms, and 0 disagree on region. Country and region validate the join, they do not drive it.
- 1 raw farmer ID value(s) needed strip and uppercase to match, confirming the cleaning rule is load bearing, not optional.

## Distribution
Shape: 49 rows, 20 columns

|                              | dtype   |   null_rate |   n_unique |
|:-----------------------------|:--------|------------:|-----------:|
| CompletionDate               | object  |      0      |         49 |
| SubmissionDate               | object  |      0      |         49 |
| country                      | object  |      0      |          4 |
| region                       | object  |      0      |         21 |
| unique_farmer_id             | object  |      0      |         48 |
| seed_delivered               | object  |      0      |          1 |
| seed_variety                 | object  |      0      |          4 |
| distribution_channel_ngo     | object  |      0.5918 |          1 |
| distribution_channel_direct  | object  |      0.8163 |          1 |
| quantity_kg                  | object  |      0      |         45 |
| distribution_challenges      | object  |      0      |         13 |
| instanceID                   | object  |      0      |         49 |
| formdef_version              | object  |      0      |          1 |
| review_quality               | object  |      0      |          1 |
| review_status                | object  |      0      |          1 |
| KEY                          | object  |      0      |         49 |
| variety_other                | object  |      0.8776 |          1 |
| distribution_channel_govt    | object  |      0.6327 |          1 |
| distribution_channel_coop    | object  |      0.7347 |          1 |
| distribution_channel_agrovet | object  |      0.6939 |          1 |

## Crop health
Shape: 101 rows, 20 columns

|                                 | dtype   |   null_rate |   n_unique |
|:--------------------------------|:--------|------------:|-----------:|
| CompletionDate                  | object  |      0      |        101 |
| SubmissionDate                  | object  |      0      |        101 |
| country                         | object  |      0      |          4 |
| region                          | object  |      0      |         21 |
| unique_farmer_id                | object  |      0      |         51 |
| pest_disease_present            | object  |      0      |          2 |
| growth_stage                    | object  |      0      |          5 |
| symptoms_observed_yellow        | object  |      0.901  |          1 |
| symptoms_observed_stunted       | object  |      0.9406 |          1 |
| symptoms_observed_wilting       | object  |      0.9109 |          1 |
| plant_height_cm                 | object  |      0      |         95 |
| additional_observations         | object  |      0      |         11 |
| instanceID                      | object  |      0      |        101 |
| formdef_version                 | object  |      0      |          1 |
| review_quality                  | object  |      0      |          1 |
| review_status                   | object  |      0      |          1 |
| KEY                             | object  |      0      |        101 |
| symptoms_observed_none          | object  |      0.2475 |          1 |
| symptoms_observed_discoloration | object  |      0.8713 |          1 |
| symptoms_observed_spots         | object  |      0.8416 |          1 |

## Submission date range
Distribution: 2026-09-13 13:31:19 to 2026-09-13 14:48:43
Crop health: 2026-09-13 15:05:13 to 2026-09-13 16:57:34
The two ranges do not overlap, the forms were submitted in separate batches.

## Join diagnostics, raw
distribution_rows: 49
distribution_distinct_ids: 48
distribution_duplicate_ids: {'FRM-IND-020': 2}
distribution_duplicate_conflicts: 1
crop_health_rows: 101
crop_health_distinct_ids: 50
crop_health_duplicate_ids: {'FRM-KEN-030': 3, 'FRM-NGA-040': 3, 'FRM-BGD-003': 2, 'FRM-BGD-002': 2, 'FRM-BGD-005': 2, 'FRM-BGD-006': 2, 'FRM-BGD-007': 2, 'FRM-BGD-004': 2, 'FRM-BGD-009': 2, 'FRM-BGD-010': 2, 'FRM-BGD-011': 2, 'FRM-BGD-012': 2, 'FRM-BGD-013': 2, 'FRM-IND-014': 2, 'FRM-IND-015': 2, 'FRM-BGD-008': 2, 'FRM-BGD-001': 2, 'FRM-IND-017': 2, 'FRM-IND-016': 2, 'FRM-IND-020': 2, 'FRM-IND-018': 2, 'FRM-IND-022': 2, 'FRM-IND-023': 2, 'FRM-IND-024': 2, 'FRM-IND-019': 2, 'FRM-IND-025': 2, 'FRM-KEN-027': 2, 'FRM-KEN-028': 2, 'FRM-KEN-029': 2, 'FRM-KEN-031': 2, 'FRM-KEN-032': 2, 'FRM-KEN-033': 2, 'FRM-IND-021': 2, 'FRM-KEN-034': 2, 'FRM-KEN-035': 2, 'FRM-KEN-037': 2, 'FRM-KEN-036': 2, 'FRM-KEN-038': 2, 'FRM-NGA-039': 2, 'FRM-NGA-041': 2, 'FRM-NGA-042': 2, 'FRM-NGA-043': 2, 'FRM-NGA-044': 2, 'FRM-NGA-045': 2, 'FRM-NGA-046': 2, 'FRM-NGA-047': 2, 'FRM-NGA-048': 2, 'FRM-NGA-049': 2, 'FRM-NGA-050': 2}
crop_health_same_stage_duplicate_pairs: 2
linked: 48
distribution_only: 0
crop_health_only: 2
id_whitespace_or_case_variants: 1
country_disagreements: 4
region_disagreements: 0
