# Assumptions

These are the assumptions built into src/transform.py. They must carry over unchanged into the Apps Script port in phase 3, and into the dashboard copy in phase 5.

## Join and identity

The join key is unique_farmer_id, cleaned by trimming whitespace and converting to upper case. One id in the sample data only matched after this cleaning, so the rule is load bearing, not a precaution against a case that cannot occur.

Country and region are not join keys. They validate the join: farmer_master carries country_mismatch and region_mismatch flags, checked two ways, whether the two forms disagree on a linked farmer's country or region, and whether a farmer's own repeat crop health visits disagree with each other. Both checks found real cases in the sample data.

## Duplicate submissions

A farmer id repeated within distribution is treated as a resubmission. The most recent submission by SubmissionDate is kept and earlier ones are dropped. One case in the sample data had two submissions with different quantity_kg, so this rule changes the reported quantity for that farmer and is not a cosmetic cleanup.

Crop health is expected to carry more than one row per farmer, one row per growth stage visit. That is not treated as duplication. Only a repeated (farmer id, growth stage) pair is treated as an accidental resubmission and deduped the same way, most recent SubmissionDate wins. Two cases were found and deduped this way.

## Dates

SubmissionDate and CompletionDate carry no time zone marker in the API response. They are assumed to already represent East Africa Time and are localised to Africa/Nairobi rather than converted from another zone. If the SurveyCTO account or device settings are later confirmed to use a different zone, this assumption needs to change before the timestamps are trusted.

## Numeric and binary fields

quantity_kg and plant_height_cm are coerced to numeric with an explicit failure on any value that will not parse. A dirty value should stop the pipeline for review, not silently become a missing value.

seed_delivered and pest_disease_present are treated as strict binary fields, "0" or "1" only. Any other value raises rather than being read as false by default.

## Multi-select fields

distribution channel and symptoms observed arrive as one dummy column per option. An option that is not selected is coded false, not missing, since its absence is a real recorded answer, not an unanswered question. Channel and symptom totals will exceed the farmer count wherever a farmer selects more than one option, and that must be stated wherever those totals are shown.

distribution_challenges is a free text field that can hold more than one challenge separated by a semicolon. It is cleaned in this pass but not split into individual challenge flags.

seed_variety codes (a, b, c, other) are carried through as given. No lookup table maps them to real variety names.

## height_z_within_stage

Computed within each growth stage's own cohort in the cleaned crop health table, using that cohort's mean and standard deviation. Left blank when a stage has one observation or zero variance, since a z-score is undefined there. It is never defaulted to zero, a blank value is the correct representation of an unavailable statistic.

## farmer_master

One row per farmer id, a full outer join of the distinct ids in each form, so farmers with no match on either side survive rather than being dropped. It carries the farmer's distribution answers as submitted, plus a summary of their crop health visits: visit count, first and last visit date, and the most recent visit's growth stage, height, and height z-score. Full visit by visit detail stays in the crop_health table for anything that needs every visit, such as the growth stage distribution on page 3.

days_between_submissions is the number of days between a farmer's distribution submission and their first crop health submission. It is blank for a farmer missing either side, not zero.
